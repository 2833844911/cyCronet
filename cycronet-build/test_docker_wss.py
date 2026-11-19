#!/usr/bin/env python3
"""Test WSS with custom headers inside Docker, using host proxy."""
import sys
import time
import threading

import cycronet

PROXY = "http://host.docker.internal:9000"
WSS_URL = "wss://ws.postman-echo.com/raw"

def test_wss_basic():
    """Test 1: Basic WSS echo without headers"""
    print("=== Test 1: WSS basic echo ===")
    result = {"ok": False}

    def on_open(ws):
        print("  [open] connected")
        ws.send("hello from docker")

    def on_message(ws, data, is_text):
        print(f"  [msg] {data}")
        if data == "hello from docker":
            result["ok"] = True
        ws.close()

    def on_close(ws, code, reason, was_clean):
        print(f"  [close] code={code} clean={was_clean}")

    def on_error(ws, msg, err):
        print(f"  [error] {msg} ({err})")

    session = cycronet.CronetClient(verify=False, proxies={"https": PROXY})
    ws = session.websocket(
        WSS_URL,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_in_background()
    ws.wait(timeout=15)
    session.close()
    print(f"  Result: {'PASS' if result['ok'] else 'FAIL'}")
    return result["ok"]


def test_wss_with_headers():
    """Test 2: WSS with custom headers"""
    print("\n=== Test 2: WSS with custom headers ===")
    result = {"ok": False}

    custom_headers = [
        ("User-Agent", "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"),
        ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
        ("Accept-Encoding", "gzip, deflate, br, zstd"),
        ("Cache-Control", "no-cache"),
        ("Pragma", "no-cache"),
    ]

    def on_open(ws):
        print("  [open] connected with custom headers")
        ws.send("headers-test")

    def on_message(ws, data, is_text):
        print(f"  [msg] {data}")
        if data == "headers-test":
            result["ok"] = True
        ws.close()

    def on_close(ws, code, reason, was_clean):
        print(f"  [close] code={code} clean={was_clean}")

    def on_error(ws, msg, err):
        print(f"  [error] {msg} ({err})")

    session = cycronet.CronetClient(verify=False, proxies={"https": PROXY})
    ws = session.websocket(
        WSS_URL,
        headers=custom_headers,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_in_background()
    ws.wait(timeout=15)
    session.close()
    print(f"  Result: {'PASS' if result['ok'] else 'FAIL'}")
    return result["ok"]


def test_wss_no_proxy():
    """Test 3: WSS without proxy (direct)"""
    print("\n=== Test 3: WSS direct (no proxy) ===")
    result = {"ok": False}

    def on_open(ws):
        print("  [open] connected directly")
        ws.send("direct-test")

    def on_message(ws, data, is_text):
        print(f"  [msg] {data}")
        if data == "direct-test":
            result["ok"] = True
        ws.close()

    def on_close(ws, code, reason, was_clean):
        print(f"  [close] code={code} clean={was_clean}")

    def on_error(ws, msg, err):
        print(f"  [error] {msg} ({err})")

    session = cycronet.CronetClient(verify=False)
    ws = session.websocket(
        WSS_URL,
        headers=[("User-Agent", "cycronet-docker-test/1.0")],
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_in_background()
    ws.wait(timeout=15)
    session.close()
    print(f"  Result: {'PASS' if result['ok'] else 'FAIL'}")
    return result["ok"]


if __name__ == "__main__":
    print(f"cycronet version: {getattr(cycronet, '__version__', 'unknown')}")
    print(f"Python: {sys.version}")
    print(f"Proxy: {PROXY}")
    print()

    results = []
    results.append(("WSS basic echo", test_wss_basic()))
    results.append(("WSS custom headers", test_wss_with_headers()))
    results.append(("WSS direct (no proxy)", test_wss_no_proxy()))

    print("\n" + "=" * 40)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
