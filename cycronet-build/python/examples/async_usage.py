"""
异步使用示例 - Cycronet Async Support

展示如何使用 cycronet 的异步 API 进行并发请求
"""

import asyncio
import cycronet
import time


async def example_basic_async():
    """基本异步请求示例"""
    print("=== 基本异步请求 ===")

    # 使用模块级异步函数
    response = await cycronet.async_get('https://httpbin.org/get', verify=False)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")


async def example_async_session():
    """使用异步 Session"""
    print("\n=== 异步 Session ===")

    # 使用 async with 自动管理会话
    async with cycronet.AsyncCronetClient(verify=False) as session:
        # GET 请求
        response = await session.get('https://httpbin.org/get')
        print(f"GET Status: {response.status_code}")

        # POST 请求
        response = await session.post(
            'https://httpbin.org/post',
            json={'key': 'value'}
        )
        print(f"POST Status: {response.status_code}")


async def example_concurrent_requests():
    """并发请求示例 - 展示异步的性能优势"""
    print("\n=== 并发请求性能对比 ===")

    urls = [
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
    ]

    # 异步并发请求
    start = time.time()
    async with cycronet.AsyncCronetClient(verify=False) as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
    async_time = time.time() - start

    print(f"异步并发: {len(responses)} 个请求耗时 {async_time:.2f} 秒")
    print(f"平均每个请求: {async_time/len(responses):.2f} 秒")

    # 同步顺序请求（对比）
    start = time.time()
    with cycronet.CronetClient(verify=False) as session:
        for url in urls:
            response = session.get(url)
    sync_time = time.time() - start

    print(f"同步顺序: {len(urls)} 个请求耗时 {sync_time:.2f} 秒")
    print(f"性能提升: {sync_time/async_time:.2f}x")


async def example_async_with_proxy():
    """异步请求使用代理"""
    print("\n=== 异步代理请求 ===")

    async with cycronet.AsyncCronetClient(
        verify=False,
        proxies={"https": "http://127.0.0.1:8080"}
    ) as session:
        try:
            response = await session.get('https://httpbin.org/ip')
            print(f"IP: {response.json()}")
        except Exception as e:
            print(f"代理请求失败（可能代理未运行）: {e}")


async def example_async_headers():
    """异步请求自定义 Headers"""
    print("\n=== 异步自定义 Headers ===")

    headers = [
        ("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/144.0.0.0"),
        ("accept", "application/json"),
        ("accept-language", "zh-CN,zh;q=0.9"),
    ]

    response = await cycronet.async_get(
        'https://httpbin.org/headers',
        headers=headers,
        verify=False
    )

    print(f"Status: {response.status_code}")
    print(f"Headers sent: {response.json()['headers']}")


async def example_async_post_json():
    """异步 POST JSON 数据"""
    print("\n=== 异步 POST JSON ===")

    data = {
        "name": "Cycronet",
        "version": "144.0.3",
        "async": True
    }

    response = await cycronet.async_post(
        'https://httpbin.org/post',
        json=data,
        verify=False
    )

    print(f"Status: {response.status_code}")
    print(f"Echo: {response.json()['json']}")


async def example_async_file_upload():
    """异步文件上传"""
    print("\n=== 异步文件上传 ===")

    # 创建测试文件
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Hello from Cycronet Async!")
        temp_file = f.name

    try:
        async with cycronet.AsyncCronetClient(verify=False) as session:
            response = await session.upload_file(
                'https://httpbin.org/post',
                temp_file,
                field_name='file',
                additional_fields={'description': 'Test file'}
            )
            print(f"Upload Status: {response.status_code}")
            print(f"File uploaded: {response.json()['files']}")
    finally:
        os.unlink(temp_file)


async def example_async_file_download():
    """异步文件下载"""
    print("\n=== 异步文件下载 ===")

    import tempfile
    import os

    temp_dir = tempfile.gettempdir()
    save_path = os.path.join(temp_dir, 'cycronet_test.json')

    try:
        info = await cycronet.async_download_file(
            'https://httpbin.org/json',
            save_path,
            verify=False
        )
        print(f"Downloaded: {info['file_path']}")
        print(f"Size: {info['size']} bytes")
        print(f"Status: {info['status_code']}")
    finally:
        if os.path.exists(save_path):
            os.unlink(save_path)


async def example_error_handling():
    """异步错误处理"""
    print("\n=== 异步错误处理 ===")

    try:
        # 超时测试
        response = await cycronet.async_get(
            'https://httpbin.org/delay/10',
            timeout=2.0,
            verify=False
        )
    except Exception as e:
        print(f"捕获超时错误: {type(e).__name__}")

    try:
        # 404 错误
        response = await cycronet.async_get(
            'https://httpbin.org/status/404',
            verify=False
        )
        response.raise_for_status()
    except cycronet.HTTPStatusError as e:
        print(f"捕获 HTTP 错误: {e.response.status_code}")


async def main():
    """运行所有示例"""
    print("Cycronet 异步使用示例\n")

    await example_basic_async()
    await example_async_session()
    await example_concurrent_requests()
    await example_async_with_proxy()
    await example_async_headers()
    await example_async_post_json()
    await example_async_file_upload()
    await example_async_file_download()
    await example_error_handling()

    print("\n所有示例运行完成！")


if __name__ == '__main__':
    asyncio.run(main())
