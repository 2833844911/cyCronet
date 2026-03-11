#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 cycronet 发送 TLS 验证请求
"""

import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from cycronet import CronetClient

# 代理配置
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 21882
PROXY_USERNAME = "admin"
PROXY_PASSWORD = "admin"

USE_PROXY = False  # 设为 False 禁用代理


def get_proxy():
    """获取代理配置"""
    if USE_PROXY:
        # cycronet 使用字典格式的代理配置
        proxy_url = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"
        return {"https": proxy_url, "http": proxy_url}
    return None


def main():
    print("=" * 60)
    print("CronetClient TLS 验证测试 (cycronet)")
    print("=" * 60)

    if USE_PROXY:
        print(f"[*] 使用代理: {PROXY_HOST}:{PROXY_PORT}")
    else:
        print("[*] 直连模式 (无代理)")

    print("-" * 60)

    # 公共 headers (使用列表格式保持顺序)
    headers = [
        ("user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"),
        ("sec-ch-ua-platform", '"macOS"'),
        ("sec-ch-ua", '"Google Chrome";v="144", "Chromium";v="144", "Not?A_Brand";v="24"'),
        ("sec-ch-ua-mobile", "?0"),
        ("origin", "https://tls.jsvmp.top:38080"),
        ("accept-language", "zh-CN,zh;q=0.9"),
        ("referer", "https://tls.jsvmp.top:38080/verify.htmdsadsadasdl"),
        ("accept-encoding", "gzip, deflate, br"),
        ("priority", "u=1, i"),
    ]

    cookies = None

    try:
        # 创建 cycronet session
        session = CronetClient(timeout_ms=100000,verify=False, proxies=get_proxy())

        print(f"[+] 会话已创建: {session._session_id}")

        # 请求 1: GET /verify.html
        print("\n[1] GET /verify.html")
        response = session.get(
            url="https://tls.jsvmp.top:38080/verify.html",
            headers=headers,
            cookies=cookies
        )
        print(f"    Status: {response.status_code}")
        print(f"    响应Headers:")
        for name, value in response.headers.items():
            print(f"      {name}: {value}")
        print(f"    Body (前200字符): {response.text[:200]}...")

        time.sleep(3)

        # 请求 2: GET /static/slider.css
        print("\n[2] GET /static/slider.css")
        response = session.get(
            url="https://tls.jsvmp.top:38080/static/slider.css",
            headers=headers,
            cookies=cookies
        )
        print(f"    Status: {response.status_code}")
        print(f"    响应Headers:")
        for name, value in response.headers.items():
            print(f"      {name}: {value}")
        print(f"    Body (前200字符): {response.text[:200]}...")

        time.sleep(3)

        # 请求 3: POST /api/verify_slider
        print("\n[3] POST /api/verify_slider")

        post_data = {
            "d": "GFEvXSEfMUhUU2QdYFYaAy4QRz9CURsFY0ALFjQSBz14AAYdLBZ_SRQFFA86XSMfRkN5VR0CUVscHzUVA1x6QSshTQIPUxVVJksWOU4-dgByb0JYFkIcb3FIBR0kLRVWCggWYAxUVF1rAmVDEiI6KxodYlwaBixVcipTUxpYYTkYRi4MB2AIU1BdaBp1RWlKPQcwUDBZXFh6Qht8BhpZUzYfElAzCBQqS0VZFTlYNg51SAIHOFY3URQIa08XNVgVNj9jVlJELQAWKVYVDlFiFggKOiMAEjNdYBxRGiAbUSBHaAceMQkzWzQPFm0DVVBLdBY2CCsPCwh0CzkSBAQtAV1tCgpAR3FWUlwkCAUnTUVZQmwAdUd7CQEKOUMGVQMZIVcPfQRFWVM1Ex1RGw4MKhtdQTIrXSRECgIPCDFZI1lRQWsbVDtZThA3NBQTdykEASQbXRcBLVE4R3sZCwUjQydvBwIiEFttChoWAhlONV8YCwwpb1YhQytZDB5sJV5eI0ADSgNZCBRXAAlfVww",
            "t": "csX4EkYjnfV1B0smIu5O08uqAzp4AabO9g"
        }

        # 发送3次POST请求
        for i in range(3):
            response = session.post(
                url="https://tls.jsvmp.top:38080/api/verify_slider",
                headers=headers,
                cookies=cookies,
                json=post_data
            )

        print(f"    Status: {response.status_code}")
        print(f"    响应Headers:")
        for name, value in response.headers.items():
            print(f"      {name}: {value}")
        print(f"    Response: {response.text[:500]}")

        if '"success"' in response.text:
            print("\n[+] tls验证成功")
        else:
            print("\n[-] tls验证失败")

        print(f"\n[+] 会话已关闭: {session._session_id}")
        session.close()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

    except Exception as e:
        print(f"[-] 错误: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
