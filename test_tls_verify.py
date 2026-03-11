#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 CronetClient 发送 TLS 验证请求
"""

import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from cronet_client import CronetClient, Proxy
# 代理配置
PROXY_HOST = "xxx.xxx.xxx.xxx"
PROXY_PORT = 8080
PROXY_USERNAME = "admin"    
PROXY_PASSWORD = "admin"

USE_PROXY = False  # 设为 False 禁用代理


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


def main():
    print("=" * 60)
    print("CronetClient TLS 验证测试")
    print("=" * 60)

    if USE_PROXY:
        print(f"[*] 使用代理: {PROXY_HOST}:{PROXY_PORT}")
    else:
        print("[*] 直连模式 (无代理)")

    print("-" * 60)

    # 公共 headers
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
        with CronetClient(proxy=get_proxy()) as client:
            print(f"[+] 会话已创建: {client.session_id}")

            # 请求 1: GET /verify.html
            print("\n[1] GET /verify.html")
            response = client.get(
                url="https://tls.jsvmp.top:38080/verify.html",
                headers=headers,
                cookies=cookies
            )
            print(f"    Status: {response.status_code}")
            print(f"    耗时: {response.duration_ms}ms")
            print(f"    响应Headers:")
            for name, values in response.headers.items():
                for val in values:
                    print(f"      {name}: {val}")
            print(f"    Body (前200字符): {response.text[:200]}...")

            time.sleep(3)

            # 请求 2: GET /static/slider.css
            print("\n[2] GET /static/slider.css")
            response = client.get(
                url="https://tls.jsvmp.top:38080/static/slider.css",
                headers=headers,
                cookies=cookies
            )
            print(f"    Status: {response.status_code}")
            print(f"    耗时: {response.duration_ms}ms")
            print(f"    响应Headers:")
            for name, values in response.headers.items():
                for val in values:
                    print(f"      {name}: {val}")
            print(f"    Body (前200字符): {response.text[:200]}...")

            time.sleep(3)

            # 请求 3: POST /api/verify_slider
            print("\n[3] POST /api/verify_slider")

            post_data = {
                "d": "GFEvXSEfMUhUU2QdYFYaAy4QRz9CURsFY0ALFjQSBz14AAYdLBZ_SRQFFA86XSMfRkN5VR0CUVscHzUVA1x6QSshTQIPUxVVJksWOU4-dgByb0JYFkIcb3FIBR0kLRVWCggWYAxUVF1rAmVDEiI6KxodYlwaBixVcipTUxpYYTkYRi4MB2AIU1BdaBp1RWlKPQcwUDBZXFh6Qht8BhpZUzYfElAzCBQqS0VZFTlYNg51SAIHOFY3URQIa08XNVgVNj9jVlJELQAWKVYVDlFiFggKOiMAEjNdYBxRGiAbUSBHaAceMQkzWzQPFm0DVVBLdBY2CCsPCwh0CzkSBAQtAV1tCgpAR3FWUlwkCAUnTUVZQmwAdUd7CQEKOUMGVQMZIVcPfQRFWVM1Ex1RGw4MKhtdQTIrXSRECgIPCDFZI1lRQWsbVDtZThA3NBQTdykEASQbXRcBLVE4R3sZCwUjQydvBwIiEFttChoWAhlONV8YCwwpb1YhQytZDB5sJV5eI0ADSgNZCBRXAAlfVww",
                "t": "csX4EkYjnfV1B0smIu5O08uqAzp4AabO9g"
            }

            response = client.post(
                url="https://tls.jsvmp.top:38080/api/verify_slider",
                headers=headers,
                cookies=cookies,
                json=post_data
            )
            response = client.post(
                url="https://tls.jsvmp.top:38080/api/verify_slider",
                headers=headers,
                cookies=cookies,
                json=post_data
            )
            response = client.post(
                url="https://tls.jsvmp.top:38080/api/verify_slider",
                headers=headers,
                cookies=cookies,
                json=post_data
            )

            print(f"    Status: {response.status_code}")
            print(f"    耗时: {response.duration_ms}ms")
            print(f"    响应Headers:")
            for name, values in response.headers.items():
                for val in values:
                    print(f"      {name}: {val}")
            print(f"    Response: {response.text[:500]}")
            if '"success"' in response.text:
                print("\n[+] tls验证成功")
            else:
                print("\n[-] tls验证失败")
            print(f"\n[+] 会话已关闭: {client.session_id}")

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

    except Exception as e:
        print(f"[-] 错误: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
