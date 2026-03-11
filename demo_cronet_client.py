#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cronet HTTP 客户端 Demo
演示同步和异步请求，GET/POST，以及会话级Cookie自动保持
"""

import sys
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from cronet_client import CronetClient, AsyncCronetClient, Proxy

# ============================================================
# 代理配置 (可选)
# ============================================================
PROXY_HOST = "[IP_ADDRESS]"
PROXY_PORT = 3389
PROXY_USERNAME = "admin"
PROXY_PASSWORD = "[PASSWORD]"

USE_PROXY = True  # 设为 True 启用代理


def get_proxy():
    """获取代理配置"""
    if USE_PROXY:
        return Proxy(
            host=PROXY_HOST,
            port=PROXY_PORT,
            username=PROXY_USERNAME,
            password=PROXY_PASSWORD
        )
    return None


# ============================================================
# 同步请求 Demo
# ============================================================
def demo_sync():
    """同步请求演示"""
    print("\n" + "=" * 60)
    print("同步请求 Demo (CronetClient)")
    print("=" * 60)

    # 公共 headers - 使用列表保持顺序
    headers = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("Accept", "application/json"),
        ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    ]

    with CronetClient(proxy=get_proxy()) as client:
        # ----- GET 请求 -----
        print("\n[1] GET 请求")
        response = client.get(
            "https://httpbin.org/get",
            headers=headers,
            cookies={"init_cookie": "hello"}  # 初始 cookie
        )
        print(f"    状态码: {response.status_code}")
        print(f"    耗时: {response.duration_ms}ms")
        print(f"    当前会话 cookies: {client.cookies}")

        # ----- POST 请求 (使用 json 参数) -----
        print("\n[2] POST JSON 请求")
        response = client.post(
            "https://httpbin.org/post",
            headers=headers,
            json={"name": "张三", "age": 25}  # 自动设置 Content-Type
        )
        print(f"    状态码: {response.status_code}")
        print(f"    耗时: {response.duration_ms}ms")
        data = response.json()
        print(f"    服务器收到的 JSON: {data.get('json')}")

        # ----- GET 请求 (验证 cookie 保持) -----
        print("\n[3] GET 请求 - 验证 Cookie 保持")
        response = client.get(
            "https://httpbin.org/cookies",
            headers=headers,
            cookies={"new_cookie": "world"}  # 添加新 cookie，会合并到会话
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 cookies: {data.get('cookies')}")
        print(f"    当前会话 cookies: {client.cookies}")

        # ----- POST 请求 (使用 data 参数 - 字典格式) -----
        print("\n[4] POST 请求 - data 字典格式 (自动编码为 form-urlencoded)")
        response = client.post(
            "https://httpbin.org/post",
            headers=headers,
            data={"username": "admin", "password": "123456", "中文": "测试"}
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 form: {data.get('form')}")

        # ----- POST 请求 (使用 data 参数 - 字符串格式) -----
        print("\n[5] POST 请求 - data 字符串格式")
        response = client.post(
            "https://httpbin.org/post",
            headers=headers,
            data="raw_string_data=hello&foo=bar"
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 form: {data.get('form')}")


# ============================================================
# 异步请求 Demo
# ============================================================
async def demo_async():
    """异步请求演示"""
    print("\n" + "=" * 60)
    print("异步请求 Demo (AsyncCronetClient)")
    print("=" * 60)

    # 公共 headers
    headers = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("Accept", "application/json"),
        ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    ]

    async with AsyncCronetClient(proxy=get_proxy()) as client:
        # ----- GET 请求 -----
        print("\n[1] GET 请求")
        response = await client.get(
            "https://httpbin.org/get",
            headers=headers,
            cookies={"async_cookie": "async_value"}
        )
        print(f"    状态码: {response.status_code}")
        print(f"    耗时: {response.duration_ms}ms")
        print(f"    当前会话 cookies: {client.cookies}")

        # ----- POST 请求 -----
        print("\n[2] POST JSON 请求")
        response = await client.post(
            "https://httpbin.org/post",
            headers=headers,
            json={"message": "Hello from async!", "数据": "中文测试"}
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 JSON: {data.get('json')}")

        # ----- 并发请求 -----
        print("\n[3] 并发 GET 请求")
        urls = [
            "https://httpbin.org/get?id=1",
            "https://httpbin.org/get?id=2",
            "https://httpbin.org/get?id=3",
        ]
        tasks = [client.get(url, headers=headers) for url in urls]
        responses = await asyncio.gather(*tasks)

        for i, resp in enumerate(responses):
            data = resp.json()
            print(f"    请求 {i+1}: 状态={resp.status_code}, url={data.get('url')}")

        # ----- POST 请求 (使用 data 参数) -----
        print("\n[4] POST 请求 - data 字典格式")
        response = await client.post(
            "https://httpbin.org/post",
            headers=headers,
            data={"field1": "value1", "field2": "value2"}
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 form: {data.get('form')}")

        # ----- 验证 Cookie 保持 -----
        print("\n[5] 验证 Cookie 保持")
        response = await client.get(
            "https://httpbin.org/cookies",
            headers=headers,
            cookies={"another_cookie": "another_value"}
        )
        data = response.json()
        print(f"    服务器收到的 cookies: {data.get('cookies')}")
        print(f"    当前会话 cookies: {client.cookies}")

        # ----- POST 请求 (使用 data 字符串) -----
        print("\n[6] POST 请求 - data 字符串格式")
        response = await client.post(
            "https://httpbin.org/post",
            headers=headers,
            data="key1=async_value1&key2=async_value2"
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 form: {data.get('form')}")



# ============================================================
# 使用字典格式 headers 的 Demo
# ============================================================
def demo_dict_headers():
    """使用字典格式 headers"""
    print("\n" + "=" * 60)
    print("字典格式 Headers Demo")
    print("=" * 60)

    # 字典格式 headers (Python 3.7+ 保持插入顺序)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "X-Custom-Header": "custom-value"
    }

    with CronetClient(proxy=get_proxy()) as client:
        response = client.get(
            "https://httpbin.org/headers",
            headers=headers  # 使用字典格式
        )
        print(f"    状态码: {response.status_code}")
        data = response.json()
        print(f"    服务器收到的 Headers:")
        for name, value in data.get('headers', {}).items():
            print(f"      {name}: {value}")


# ============================================================
# Cookie 自动保持演示
# ============================================================
def demo_cookie_persistence():
    """Cookie 自动保持演示"""
    print("\n" + "=" * 60)
    print("Cookie 自动保持 Demo")
    print("=" * 60)

    headers = [
        ("User-Agent", "Mozilla/5.0"),
        ("Accept", "*/*"),
    ]

    with CronetClient(proxy=get_proxy()) as client:
        # 第一次请求设置 cookie
        print("\n[1] 第一次请求 - 设置初始 cookie")
        response = client.get(
            "https://httpbin.org/cookies/set/session_id/abc123",
            headers=headers
        )
        print(f"    状态码: {response.status_code}")
        print(f"    会话 cookies: {client.cookies}")

        # 第二次请求 - cookie 自动携带
        print("\n[2] 第二次请求 - Cookie 自动携带")
        response = client.get(
            "https://httpbin.org/cookies",
            headers=headers
        )
        data = response.json()
        print(f"    服务器收到的 cookies: {data.get('cookies')}")

        # 第三次请求 - 用户传递的 cookie 会合并
        print("\n[3] 第三次请求 - 用户 cookie 合并到会话")
        response = client.get(
            "https://httpbin.org/cookies",
            headers=headers,
            cookies={"user_token": "xyz789"}  # 新增 cookie
        )
        data = response.json()
        print(f"    服务器收到的 cookies: {data.get('cookies')}")
        print(f"    会话 cookies: {client.cookies}")

        # 第四次请求 - 用户 cookie 覆盖同名 cookie
        print("\n[4] 第四次请求 - 用户 cookie 覆盖同名 cookie")
        response = client.get(
            "https://httpbin.org/cookies",
            headers=headers,
            cookies={"session_id": "new_session_456"}  # 覆盖已有 cookie
        )
        data = response.json()
        print(f"    服务器收到的 cookies: {data.get('cookies')}")
        print(f"    会话 cookies: {client.cookies}")


# ============================================================
# 主函数
# ============================================================
def main():
    print("Cronet HTTP 客户端 Demo")
    print(f"使用代理: {USE_PROXY}")
    if USE_PROXY:
        print(f"代理地址: {PROXY_HOST}:{PROXY_PORT}")

    try:
        # 同步请求 demo
        demo_sync()

        # 异步请求 demo
        asyncio.run(demo_async())

        # 字典 headers demo
        demo_dict_headers()

        # Cookie 保持 demo
        demo_cookie_persistence()

        print("\n" + "=" * 60)
        print("所有 Demo 完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[-] 错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
