"""请求/会话销毁路径的压力测试（只依赖标准库和已安装的 cycronet）。

脚本自带一个本地 HTTP 服务器，逐个场景压测会销毁 Cronet native 对象的路径：
正常完成、重定向（取消）、超时（drop 时取消）、连接失败、代理不可用、
流提前关闭、关闭会话时还有在途请求、会话频繁创建销毁、异步并发、
以及请求刚结束就退出进程。

每个场景在独立的子进程里运行，崩溃、非零退出码，或 stderr 里出现
泄漏 / SEH / panic 字样都算失败。

用法:
    python test_teardown_stress.py                 # 跑一轮（约 1 分钟）
    python test_teardown_stress.py --rounds 20     # 连续跑 20 轮
    python test_teardown_stress.py --only timeouts close_inflight
"""

import argparse
import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# stderr 里出现这些字样说明销毁流程走了泄漏或崩溃保护分支
BAD_STDERR = ("leaking", "[cycronet/SEH]", "panicked", "FATAL:", "Check failed")


# ---------------------------------------------------------------------------
# 本地测试服务器（父进程里运行）
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, body=b"", headers=()):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        try:
            if path == "/small":
                self._reply(200, b"ok")
            elif path == "/redirect":
                self._reply(302, headers=[("Location", "/small")])
            elif path == "/big":
                kb = int(query.split("=")[1]) if query else 64
                self.send_response(200)
                self.send_header("Content-Length", str(kb * 1024))
                self.end_headers()
                chunk = b"x" * 1024
                for _ in range(kb):
                    self.wfile.write(chunk)
            elif path == "/hang":
                # 一直不响应，直到客户端断开或服务器停止
                self.server.stop_event.wait(15)
                self.close_connection = True
            else:
                self._reply(404, b"not found")
        except (BrokenPipeError, ConnectionError, OSError):
            self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        remaining = length
        try:
            while remaining > 0:
                data = self.rfile.read(min(remaining, 65536))
                if not data:
                    break
                remaining -= len(data)
            self._reply(200, str(length - remaining).encode())
        except (BrokenPipeError, ConnectionError, OSError):
            self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512

    def handle_error(self, request, client_address):
        pass  # 客户端取消请求时连接被重置是预期行为


def start_server():
    server = Server(("127.0.0.1", 0), Handler)
    server.stop_event = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def closed_port():
    """返回一个当前没有进程监听的端口。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# 场景（子进程里运行）
# ---------------------------------------------------------------------------

def _run_threads(n_threads, n_tasks, fn):
    with ThreadPoolExecutor(n_threads) as pool:
        return list(pool.map(fn, range(n_tasks)))


def _expect_error(fn):
    """调用 fn，返回它抛出的异常类型名；没抛异常返回 None。"""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 这里就是要统计各种网络错误
        return type(exc).__name__
    return None


def sc_sequential(cycronet, base, dead):
    """单会话顺序请求；每个请求都不应被销毁流程拖慢"""
    s = cycronet.CronetClient(verify=False)
    times = []
    for _ in range(300):
        t0 = time.perf_counter()
        assert s.get(base + "/small").status_code == 200
        times.append((time.perf_counter() - t0) * 1000)
    s.close()
    median = statistics.median(times)
    assert median < 100, f"median {median:.1f} ms per request (teardown is blocking the caller)"
    return {"median_ms": round(median, 2), "max_ms": round(max(times), 1)}


def sc_threads_shared_session(cycronet, base, dead):
    """16 个线程共用一个会话"""
    s = cycronet.CronetClient(verify=False)
    t0 = time.perf_counter()
    codes = _run_threads(16, 2400, lambda _: s.get(base + "/small").status_code)
    elapsed = time.perf_counter() - t0
    s.close()
    assert set(codes) == {200}, set(codes)
    return {"req_per_s": round(len(codes) / elapsed)}


def sc_redirects(cycronet, base, dead):
    """重定向：每一跳都走一次 native 取消路径"""
    s = cycronet.CronetClient(verify=False)
    texts = _run_threads(8, 400, lambda _: s.get(base + "/redirect").text)
    s.close()
    assert set(texts) == {"ok"}, set(texts)
    return {"requests": len(texts)}


def sc_timeouts(cycronet, base, dead):
    """超时：请求未完成就被 drop，由后台线程等取消回调"""
    s = cycronet.CronetClient(verify=False, timeout_ms=150)
    times = []

    def one(_):
        t0 = time.perf_counter()
        err = _expect_error(lambda: s.get(base + "/hang"))
        times.append(time.perf_counter() - t0)
        return err

    errors = _run_threads(8, 80, one)
    s.close()
    assert None not in errors, "a request to /hang returned without error"
    median = statistics.median(times)
    assert median < 0.4, f"timeout took {median:.2f} s for timeout_ms=150"
    return {"errors": sorted(set(errors)), "median_s": round(median, 3)}


def sc_refused(cycronet, base, dead):
    """连接被拒绝：高并发的失败回调"""
    s = cycronet.CronetClient(verify=False)
    errors = _run_threads(16, 1600, lambda _: _expect_error(lambda: s.get(dead + "/small")))
    s.close()
    assert None not in errors
    return {"errors": sorted(set(errors)), "requests": len(errors)}


def sc_dead_proxy(cycronet, base, dead):
    """代理不可用：高并发代理失败"""
    sessions = [cycronet.CronetClient(verify=False, proxies=dead) for _ in range(4)]
    target = "http://example.invalid/"
    errors = _run_threads(
        16, 800, lambda i: _expect_error(lambda: sessions[i % 4].get(target))
    )
    for s in sessions:
        s.close()
    assert None not in errors
    return {"errors": sorted(set(errors)), "requests": len(errors)}


def sc_upload(cycronet, base, dead):
    """带请求体的 POST（UploadDataProvider 的销毁）"""
    s = cycronet.CronetClient(verify=False)
    body = b"u" * (256 * 1024)
    texts = _run_threads(8, 200, lambda _: s.post(base + "/len", data=body).text)
    s.close()
    assert set(texts) == {str(len(body))}, set(texts)
    return {"requests": len(texts)}


def sc_stream_early_close(cycronet, base, dead):
    """流式响应读一块就关闭，以及完整读完"""
    s = cycronet.CronetClient(verify=False)

    def early(_):
        r = s.get(base + "/big?kb=2048", stream=True)
        chunk = next(iter(r.iter_content()))
        r.close()
        return len(chunk) > 0

    def full(_):
        r = s.get(base + "/big?kb=512", stream=True)
        total = sum(len(c) for c in r.iter_content())
        r.close()
        return total

    assert all(_run_threads(6, 150, early))
    totals = _run_threads(6, 30, full)
    s.close()
    assert set(totals) == {512 * 1024}, set(totals)
    return {"early_closed": 150, "full_reads": 30}


def sc_session_churn(cycronet, base, dead):
    """会话频繁创建/请求/关闭（engine 的延迟销毁）"""
    def one(_):
        s = cycronet.CronetClient(verify=False)
        code = s.get(base + "/small").status_code
        s.close()
        return code

    t0 = time.perf_counter()
    codes = _run_threads(8, 480, one)
    elapsed = time.perf_counter() - t0
    assert set(codes) == {200}, set(codes)
    return {"sessions": len(codes), "ms_per_session": round(elapsed * 1000 / len(codes) * 8, 1)}


def sc_module_level(cycronet, base, dead):
    """模块级一次性请求（每次新建并关闭会话）"""
    times = []
    for _ in range(60):
        t0 = time.perf_counter()
        assert cycronet.get(base + "/small", verify=False).status_code == 200
        times.append((time.perf_counter() - t0) * 1000)
    median = statistics.median(times)
    assert median < 150, f"cycronet.get() median {median:.1f} ms (session close is blocking)"
    return {"median_ms": round(median, 2)}


def sc_close_inflight(cycronet, base, dead):
    """关闭会话时还有在途请求：close() 应立即返回，在途请求被取消"""
    close_times = []
    for _ in range(25):
        s = cycronet.CronetClient(verify=False, timeout_ms=5000)
        results = []

        def worker():
            t0 = time.perf_counter()
            err = _expect_error(lambda: s.get(base + "/hang"))
            results.append((err, time.perf_counter() - t0))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.1)
        t0 = time.perf_counter()
        s.close()
        close_times.append(time.perf_counter() - t0)
        for t in threads:
            t.join(4)
        assert not any(t.is_alive() for t in threads), "in-flight request not released after close()"
        assert len(results) == 4 and all(err for err, _ in results), results
        assert max(el for _, el in results) < 3, results
    assert max(close_times) < 0.5, f"close() blocked for {max(close_times):.2f} s"
    return {"max_close_ms": round(max(close_times) * 1000, 1)}


def sc_async_fanout(cycronet, base, dead):
    """异步并发，夹杂超时"""
    async def main():
        async with cycronet.AsyncCronetClient(verify=False) as s:
            t0 = time.perf_counter()
            rs = await asyncio.gather(*[s.get(base + "/small") for _ in range(600)])
            elapsed = time.perf_counter() - t0
            assert {r.status_code for r in rs} == {200}
        async with cycronet.AsyncCronetClient(verify=False, timeout_ms=150) as s:
            outs = await asyncio.gather(
                *[s.get(base + "/hang") for _ in range(30)], return_exceptions=True
            )
            assert all(isinstance(o, Exception) for o in outs), outs
        return {"req_per_s": round(600 / elapsed)}

    return asyncio.run(main())


def sc_exit_pending(cycronet, base, dead):
    """请求刚结束、会话没关就退出进程（后台销毁还没做完）"""
    s = cycronet.CronetClient(verify=False)
    for _ in range(50):
        assert s.get(base + "/small").status_code == 200
    globals()["_keep_alive"] = s
    return {"requests": 50}


def sc_exit_after_close(cycronet, base, dead):
    """关闭会话后立刻退出进程（engine 销毁还在排队）"""
    for _ in range(5):
        s = cycronet.CronetClient(verify=False)
        assert s.get(base + "/small").status_code == 200
        s.close()
    return {"sessions": 5}


SCENARIOS = {
    "sequential": sc_sequential,
    "threads_shared_session": sc_threads_shared_session,
    "redirects": sc_redirects,
    "timeouts": sc_timeouts,
    "refused": sc_refused,
    "dead_proxy": sc_dead_proxy,
    "upload": sc_upload,
    "stream_early_close": sc_stream_early_close,
    "session_churn": sc_session_churn,
    "module_level": sc_module_level,
    "close_inflight": sc_close_inflight,
    "async_fanout": sc_async_fanout,
    "exit_pending": sc_exit_pending,
    "exit_after_close": sc_exit_after_close,
}

# 这两个场景要验证"销毁还没做完就退出"，所以结束前不等待
NO_SETTLE = {"exit_pending", "exit_after_close"}


def _native_threads():
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().num_threads()


def run_child(name, port, dead_port):
    import cycronet

    base = f"http://127.0.0.1:{port}"
    dead = f"http://127.0.0.1:{dead_port}"
    threads_before = _native_threads()
    stats = SCENARIOS[name](cycronet, base, dead)
    if name not in NO_SETTLE:
        # 给后台销毁留出时间，再看线程数有没有回落
        import gc

        gc.collect()
        time.sleep(1.5)
        threads_after = _native_threads()
        if threads_before is not None:
            stats["threads"] = f"{threads_before}->{threads_after}"
            assert threads_after <= threads_before + 40, (
                f"native threads grew from {threads_before} to {threads_after} (engines not destroyed?)"
            )
    print(json.dumps(stats), flush=True)


# ---------------------------------------------------------------------------
# 父进程：逐个场景起子进程并检查结果
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=1, help="整套场景重复的轮数")
    parser.add_argument("--only", nargs="+", choices=sorted(SCENARIOS), help="只跑指定场景")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--dead-port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        run_child(args.child, args.port, args.dead_port)
        return 0

    import cycronet

    print(f"cycronet from {os.path.dirname(cycronet.__file__)}")
    print(f"python {sys.version.split()[0]} on {sys.platform}, {os.cpu_count()} cpus")

    server = start_server()
    port = server.server_address[1]
    names = args.only or list(SCENARIOS)
    failures = 0
    started = time.perf_counter()
    for round_no in range(1, args.rounds + 1):
        for name in names:
            cmd = [sys.executable, os.path.abspath(__file__), "--child", name,
                   "--port", str(port), "--dead-port", str(closed_port())]
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                code, out, err = proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired as exc:
                code, out, err = "timeout", str(exc.stdout or ""), str(exc.stderr or "")
            elapsed = time.perf_counter() - t0
            bad_lines = [line for line in err.splitlines() if any(p in line for p in BAD_STDERR)]
            ok = code == 0 and not bad_lines
            failures += not ok
            stats = out.strip().splitlines()[-1] if out.strip() else ""
            print(f"[round {round_no}] {'PASS' if ok else 'FAIL'}  {name:24s} {elapsed:6.1f}s  {stats}")
            if not ok:
                print(f"    exit code: {code}")
                for line in (bad_lines or err.strip().splitlines())[-8:]:
                    print(f"    stderr: {line[:200]}")
    server.stop_event.set()
    total = args.rounds * len(names)
    print(f"\n{total - failures}/{total} passed in {time.perf_counter() - started:.0f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
