# Cycronet - 绕过 TLS/HTTP2 指纹检测的 Python HTTP 客户端

## 🎯 核心功能

Cycronet 是基于 Chromium Cronet 网络栈的 Python HTTP 客户端，**最大的特点是能够产生真实的 Chrome 浏览器 TLS/HTTP2 指纹**，从而绕过各种反爬虫和指纹检测系统。

**✨ 新特性：**

- 🚀 同时支持同步和异步 API
- ⚡ 异步并发请求，性能提升 5-10 倍
- 🔄 与 aiohttp/httpx 相同的使用体验
- 🎯 真实的 Chrome TLS/HTTP2 指纹（同步和异步均支持）
- 🔐 **自定义 TLS 指纹配置（NEW！）**
- 🔌 **SOCKS5 代理支持账号密码认证（NEW！）**
- 📡 **流式响应（Streaming）支持（NEW！）**
- 🔌 **WebSocket / WSS 支持，TLS 指纹与浏览器一致（NEW！）**

### 为什么需要 Cycronet？

传统的 Python HTTP 库（如 requests、httpx、aiohttp）使用的是 Python 的网络栈，它们的 TLS 握手和 HTTP/2 特征与真实浏览器不同，容易被检测和封禁。

**常见的检测方式：**

1. **TLS 指纹检测**
   - TLS ClientHello 消息中的加密套件顺序
   - 支持的 TLS 扩展及其顺序
   - 椭圆曲线算法的选择
   - ALPN 协议列表

2. **HTTP/2 指纹检测**
   - SETTINGS 帧的参数和顺序
   - WINDOW_UPDATE 的初始值
   - 伪头部（pseudo-headers）的顺序
   - 优先级（Priority）设置

3. **请求头指纹检测**
   - User-Agent 与实际行为不匹配
   - 请求头的顺序异常
   - 缺少浏览器特有的头部

**Cycronet 的解决方案：**

Cycronet 直接使用 Chromium 的 Cronet 网络库，产生的所有网络特征与真实 Chrome 浏览器**完全一致**，无法被检测出是爬虫。

## 🔐 TLS/HTTP2 指纹绕过

### 真实的 Chrome 指纹

**同步方式：**

```python
import cycronet

# Cycronet 自动使用 Chrome 的 TLS/HTTP2 指纹
response = cycronet.get('https://tls.peet.ws/api/all', verify=False)

# 查看 TLS 指纹信息
data = response.json()
print(f"TLS Version: {data['tls']['version']}")
print(f"Cipher Suite: {data['tls']['cipher_suite']}")
print(f"HTTP Version: {data['http']['version']}")  # HTTP/2
```

**异步方式：**

```python
import asyncio
import cycronet

async def check_fingerprint():
    # 异步请求，同样的 Chrome 指纹
    response = await cycronet.async_get('https://tls.peet.ws/api/all', verify=False)
    data = response.json()
    print(f"TLS Version: {data['tls']['version']}")
    print(f"HTTP Version: {data['http']['version']}")  # HTTP/2

asyncio.run(check_fingerprint())
```

### 与 requests 的对比

```python
# ❌ requests - 容易被检测
import requests
response = requests.get('https://example.com')
# TLS 指纹：Python/OpenSSL
# HTTP/2：不支持或特征异常

# ✅ cycronet 同步 - 真实 Chrome 指纹
import cycronet
response = cycronet.get('https://example.com', verify=False)
# TLS 指纹：Chrome 144.x
# HTTP/2：完全符合 Chrome 行为

# ✅ cycronet 异步 - 真实 Chrome 指纹 + 高性能
import asyncio
response = await cycronet.async_get('https://example.com', verify=False)
# TLS 指纹：Chrome 144.x
# HTTP/2：完全符合 Chrome 行为
# 性能：支持并发，速度提升 5-10 倍
```

### 绕过 Cloudflare、Akamai 等 CDN

```python
import cycronet

# Cloudflare 保护的网站
response = cycronet.get(
    'https://cloudflare-protected-site.com',
    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'sec-ch-ua': '"Chromium";v="144", "Not A(Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    },
    verify=False
)

print(f"Status: {response.status_code}")  # 200 - 成功绕过
```

### 自定义 TLS 指纹配置

Cycronet 支持自定义 TLS 指纹配置，可以模拟特定版本的 Chrome 浏览器：

```python
import cycronet

# 使用 Chrome 144 的 TLS 指纹配置
session = cycronet.CronetClient(
    verify=False,
    chrometls="chrome_144"  # 指定 TLS 配置
)

response = session.get('https://tls.peet.ws/api/all')
print(response.json())
session.close()

# 同时使用代理和 TLS 指纹
session = cycronet.CronetClient(
    verify=False,
    proxies={'https': 'http://127.0.0.1:21882'},
    chrometls="chrome_144"
)
```

**支持的 TLS 配置：**
- `chrome_144`: Chrome 144 版本的 TLS 指纹（默认）

#### 添加自定义 TLS 配置

##### 使用 set_tls_profiles() 函数
```python
import cycronet

# 更友好的 API，功能相同
cycronet.set_tls_profiles({
    "chrome_test": {
        "cipher_suites": ["TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA"],
        "tls_curves": ["X25519"],
        "tls_extensions": []
    }
})

session = cycronet.CronetClient(chrometls="chrome_test")

```

##### 你可以通过编辑 `tls_profiles.json` 文件来添加自定义的 TLS 指纹配置。

**1. 找到配置文件位置**

配置文件会在以下位置查找（按优先级）：
- Python 包安装目录：`site-packages/cycronet/tls_profiles.json`
- 当前工作目录：`./tls_profiles.json`

**2. 编辑配置文件**

打开 `tls_profiles.json` 文件，添加新的配置：

```json
{
  "chrome_144": {
    "version": "Chrome 144",
    "cipher_suites": [
      "TLS_GREASE",
      "TLS_AES_128_GCM_SHA256",
      "TLS_AES_256_GCM_SHA384",
      "TLS_CHACHA20_POLY1305_SHA256",
      "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
      "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
      "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
      "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
      "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
      "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
      "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
      "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
      "TLS_RSA_WITH_AES_128_GCM_SHA256",
      "TLS_RSA_WITH_AES_256_GCM_SHA384",
      "TLS_RSA_WITH_AES_128_CBC_SHA",
      "TLS_RSA_WITH_AES_256_CBC_SHA"
    ],
    "hex_codes": []
  },
  "chrome_143": {
    "version": "Chrome 143",
    "cipher_suites": [
      "TLS_GREASE",
      "TLS_AES_128_GCM_SHA256",
      "TLS_AES_256_GCM_SHA384",
      "TLS_CHACHA20_POLY1305_SHA256"
    ],
    "hex_codes": []
  }
}
```

**3. 使用自定义配置**

```python
import cycronet

# 使用新添加的 Chrome 143 配置
session = cycronet.CronetClient(
    verify=False,
    chrometls="chrome_143"
)

response = session.get('https://example.com')
print(response.text)
session.close()
```

**配置说明：**

- `version`: 配置的描述名称
- `cipher_suites`: TLS Cipher Suites 列表（按顺序）
  - 必须使用标准的 TLS cipher suite 名称
  - 顺序很重要，会影响 TLS 指纹
  - `TLS_GREASE` 是 Chrome 的特殊值，用于防止协议僵化
- `hex_codes`: 对应的十六进制代码（可选，仅用于文档）

**常用 Cipher Suites：**

| 名称 | 十六进制 | 说明 |
|------|---------|------|
| TLS_GREASE | 0x6a6a | Chrome GREASE 值 |
| TLS_AES_128_GCM_SHA256 | 0x1301 | TLS 1.3 |
| TLS_AES_256_GCM_SHA384 | 0x1302 | TLS 1.3 |
| TLS_CHACHA20_POLY1305_SHA256 | 0x1303 | TLS 1.3 |
| TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256 | 0xc02b | TLS 1.2 |
| TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 | 0xc02f | TLS 1.2 |

**获取真实浏览器的 Cipher Suites：**

1. 访问 https://tls.peet.ws/api/all
2. 查看 `tls.ciphers` 字段
3. 复制 cipher suite 列表到配置文件

**示例：从浏览器获取配置**

```python
import cycronet
import json

# 使用默认配置访问 TLS 检测站点
response = cycronet.get('https://tls.peet.ws/api/all', verify=False)
data = response.json()

# 提取 cipher suites
ciphers = data['tls']['ciphers']
print("检测到的 Cipher Suites:")
for cipher in ciphers:
    print(f"  - {cipher}")

# 保存为新配置
new_config = {
    "my_custom": {
        "version": "My Custom Profile",
        "cipher_suites": ciphers
    }
}

# 写入配置文件
with open('tls_profiles.json', 'w') as f:
    json.dump(new_config, f, indent=2)
```

详细文档请参考：[TLS_PROFILES_GUIDE.md](TLS_PROFILES_GUIDE.md)

## ⚡ 异步支持（Async/Await）

Cycronet 提供完整的异步支持，让你可以使用 `async/await` 进行高性能并发请求。

### 基本异步使用

```python
import asyncio
import cycronet

async def main():
    # 方式 1：使用模块级异步函数
    response = await cycronet.async_get('https://httpbin.org/get', verify=False)
    print(response.json())

    # 方式 2：使用 AsyncSession
    async with cycronet.AsyncCronetClient(verify=False) as session:
        response = await session.get('https://httpbin.org/get')
        print(response.json())

asyncio.run(main())
```

### 异步并发请求 - 性能提升

异步的最大优势是可以并发执行多个请求，大幅提升性能：

```python
import asyncio
import cycronet

async def fetch_multiple():
    urls = [
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/1',
    ]

    # 并发执行 5 个请求
    async with cycronet.AsyncCronetClient(verify=False) as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)

    # 5 个请求只需要 ~1 秒（而不是 5 秒）
    for i, response in enumerate(responses):
        print(f"Request {i+1}: {response.status_code}")

asyncio.run(fetch_multiple())
```

**性能对比：**

| 场景 | 同步方式 | 异步方式 | 性能提升 |
|------|---------|---------|---------|
| 5 个请求（每个 1 秒） | ~5 秒 | ~1 秒 | **5x** |
| 10 个请求（每个 1 秒） | ~10 秒 | ~1 秒 | **10x** |
| 100 个请求 | 很慢 | 快速 | **10x+** |

### 异步 API 完整列表

所有同步 API 都有对应的异步版本：

```python
import cycronet

# 模块级异步函数
await cycronet.async_get(url, **kwargs)
await cycronet.async_post(url, **kwargs)
await cycronet.async_put(url, **kwargs)
await cycronet.async_delete(url, **kwargs)
await cycronet.async_patch(url, **kwargs)
await cycronet.async_head(url, **kwargs)
await cycronet.async_options(url, **kwargs)
await cycronet.async_upload_file(url, file_path, **kwargs)
await cycronet.async_download_file(url, save_path, **kwargs)

# AsyncSession 方法
async with cycronet.AsyncCronetClient(verify=False) as session:
    await session.get(url)
    await session.post(url, json=data)
    await session.put(url, data=data)
    await session.delete(url)
    await session.patch(url, json=data)
    await session.head(url)
    await session.options(url)
    await session.upload_file(url, file_path)
    await session.download_file(url, save_path)
```

### 异步使用代理

```python
import asyncio
import cycronet

async def main():
    # 异步 Session 支持代理
    async with cycronet.AsyncCronetClient(
        verify=False,
        proxies={"https": "http://127.0.0.1:8080"}
    ) as session:
        response = await session.get('https://httpbin.org/ip')
        print(response.json())

asyncio.run(main())
```

### 异步错误处理

```python
import asyncio
import cycronet

async def main():
    try:
        # 超时处理
        response = await cycronet.async_get(
            'https://httpbin.org/delay/10',
            timeout=2.0,
            verify=False
        )
    except asyncio.TimeoutError:
        print("请求超时")

    try:
        # HTTP 错误处理
        response = await cycronet.async_get(
            'https://httpbin.org/status/404',
            verify=False
        )
        response.raise_for_status()
    except cycronet.HTTPStatusError as e:
        print(f"HTTP 错误: {e.response.status_code}")

asyncio.run(main())
```

### 何时使用异步？

**推荐使用异步的场景：**

- ✅ 需要同时发送多个请求（爬虫、批量 API 调用）
- ✅ 高并发场景（监控、数据采集）
- ✅ 需要与其他异步代码集成（FastAPI、aiohttp 等）
- ✅ 对性能有较高要求

**使用同步的场景：**

- ✅ 简单的单个请求
- ✅ 脚本工具（不需要并发）
- ✅ 与同步代码集成更方便

## 🌐 代理配置

Cycronet 支持多种代理类型，可以与代理池、IP 轮换等方案结合使用。

### 基本代理配置

```python
import cycronet

# HTTP 代理
session = cycronet.CronetClient(
    verify=False,
    proxies={"https": "http://127.0.0.1:8080"}
)

# 带认证的代理
session = cycronet.CronetClient(
    verify=False,
    proxies={"https": "http://username:password@proxy.example.com:8080"}
)

response = session.get('https://httpbin.org/ip')
print(response.json())
session.close()
```

### SOCKS5 代理（支持账号密码认证）

```python
import cycronet

# SOCKS5 代理（无认证）
response = cycronet.get('https://httpbin.org/ip', proxies='socks5://127.0.0.1:1080', verify=False)

# SOCKS5 代理（带账号密码）
response = cycronet.get(
    'https://httpbin.org/ip',
    proxies='socks5://username:password@127.0.0.1:1080',
    verify=False
)

# socks5h 模式 / 字典格式均支持
proxies = {
    'http': 'socks5://username:password@127.0.0.1:1080',
    'https': 'socks5://username:password@127.0.0.1:1080'
}
response = cycronet.get('https://httpbin.org/ip', proxies=proxies, verify=False)
```

详细用法请参考 [README.md](../README.md)

## � WebSocket 支持

Cycronet 支持 WebSocket (`ws://`) 和安全 WebSocket (`wss://`) 连接，使用 Chromium 原生 WebSocket 实现，**TLS 指纹与 Chrome 浏览器完全一致**。

### 基本用法

```python
import cycronet
import time

client = cycronet.PyCronetClient()
session_id = client.create_session(skip_cert_verify=True)

# 连接 WebSocket 服务器
ws = client.websocket_connect(session_id, "wss://ws.postman-echo.com/raw")

# 等待连接打开
evt = ws.recv_timeout(10000)  # 超时 10 秒，单位毫秒
if evt and evt["type"] == "open":
    print(f"已连接! 协议: {evt.get('protocol', '')}")

# 发送文本消息
ws.send("Hello WebSocket!")

# 接收消息
evt = ws.recv_timeout(5000)
if evt and evt["type"] == "message":
    print(f"收到: {evt['data']}")       # 消息内容
    print(f"文本: {evt['is_text']}")     # True=文本, False=二进制

# 发送二进制消息
ws.send_bytes(b"\x00\x01\x02\x03")

# 优雅关闭
ws.close(1000, "bye")
evt = ws.recv_timeout(5000)
if evt and evt["type"] == "close":
    print(f"关闭: code={evt['code']}, clean={evt['was_clean']}")

# 清理：先销毁 ws，再关闭 session
del ws
time.sleep(0.5)
client.close_session(session_id)
```

### 事件类型

`recv()` 和 `recv_timeout()` 返回一个字典，`type` 字段标识事件类型：

| type | 字段 | 说明 |
|------|------|------|
| `open` | `protocol` | 连接成功，返回协商的子协议 |
| `message` | `data`, `is_text` | 收到消息；`is_text=True` 时 `data` 为字符串，否则为 `bytes` |
| `close` | `was_clean`, `code`, `reason` | 连接关闭 |
| `error` | `net_error`, `message` | 连接错误 |

### API 参考

| 方法 | 说明 |
|------|------|
| `client.websocket_connect(session_id, url)` | 创建 WebSocket 连接，返回 `PyCronetWebSocket` |
| `ws.send(text)` | 发送文本消息 |
| `ws.send_bytes(data)` | 发送二进制消息 |
| `ws.recv()` | 阻塞接收下一个事件（释放 GIL） |
| `ws.recv_timeout(ms)` | 带超时接收，超时返回 `None` |
| `ws.close(code, reason)` | 发起关闭握手 |

### 快速收发多条消息

```python
# 批量发送
for i in range(10):
    ws.send(f"message-{i}")

# 按序接收
for i in range(10):
    evt = ws.recv_timeout(5000)
    assert evt["data"] == f"message-{i}"
```

### 回调模式（推荐）

类似 `websocket-client` 的 `WebSocketApp`，注册回调函数，自动在后台接收并分发事件：

```python
import cycronet

def on_open(ws):
    print("已连接!")
    ws.send("Hello!")

def on_message(ws, message, is_text):
    print(f"收到: {message}")
    ws.close(1000, "done")

def on_close(ws, code, reason, was_clean):
    print(f"已关闭: code={code}")

def on_error(ws, error, net_error):
    print(f"错误: {error}")

session = cycronet.CronetClient(verify=False)
ws = session.websocket(
    "wss://ws.postman-echo.com/raw",
    on_open=on_open,
    on_message=on_message,
    on_close=on_close,
    on_error=on_error,
)

# 方式 1：阻塞当前线程
ws.run_forever()

# 方式 2：在后台线程运行
ws.run_in_background()
# ... 做其他事情 ...
ws.wait()  # 等待结束
session.close()
```

**回调函数签名：**

| 回调 | 签名 | 说明 |
|------|------|------|
| `on_open` | `(ws)` | 连接建立 |
| `on_message` | `(ws, message, is_text)` | 收到消息，`is_text=True` 时 message 为 str |
| `on_close` | `(ws, code, reason, was_clean)` | 连接关闭 |
| `on_error` | `(ws, error, net_error)` | 发生错误 |

在回调中可直接调用 `ws.send()` / `ws.send_bytes()` / `ws.close()` 发送消息或关闭连接。

### 注意事项

- **TLS 指纹**：`wss://` 连接使用 Chromium 原生 BoringSSL，指纹与 Chrome 浏览器完全一致
- **线程安全**：`recv()` / `recv_timeout()` 会释放 Python GIL，不会阻塞其他线程
- **回调模式清理**：`session.close()` 前需确保 ws 已关闭（`ws.wait()` 等待完成）
- **轮询模式清理**：必须先 `del ws`，等待片刻后再 `session.close()`

## �� 流式响应（Streaming）

```python
import cycronet

# 流式读取
response = cycronet.get('https://httpbin.org/stream/5', stream=True, verify=False)
for line in response.iter_lines():
    print(line)
response.close()

# 按块下载
response = cycronet.get('https://example.com/file.zip', stream=True, verify=False)
with open('file.zip', 'wb') as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)
response.close()

# 异步流式
import asyncio
async def stream():
    r = await cycronet.async_get('https://httpbin.org/stream/5', stream=True, verify=False)
    async for line in r.aiter_lines():
        print(line)
    r.close()
asyncio.run(stream())
```

## 🔧 高级配置

### SSL 证书验证

```python
import cycronet

# 跳过 SSL 验证（用于测试或自签名证书）
session = cycronet.CronetClient(verify=False)

# 启用 SSL 验证（默认，推荐用于生产环境）
session = cycronet.CronetClient(verify=True)
```

### 超时设置

```python
# 全局超时
session = cycronet.CronetClient(
    verify=False,
    timeout_ms=30000  # 30 秒
)

# 单个请求超时
response = session.get('https://example.com', timeout=10.0)
```

### Cookie 管理

Cycronet 支持灵活的 Cookie 管理，可以在创建 Session 时初始化 Cookie，也可以在请求过程中动态更新。

#### 初始化 Cookie

```python
import cycronet

def get_proxy():
    return "http://127.0.0.1:8080"

# 创建 Session 并初始化 Cookie
session = cycronet.CronetClient(
    timeout_ms=10000,
    verify=False,
    proxies={"https": get_proxy()}
)

# 方法 1: 使用 set_cookie 设置 Cookie（推荐）
session.cookies.set_cookie('session_id', 'abc123', domain='example.com')
session.cookies.set_cookie('user_token', 'xyz789', domain='example.com')
session.cookies.set_cookie('preferences', 'dark_mode=1', domain='example.com')

# 方法 2: 使用 update 批量设置（不指定域名）
session.cookies.update({
    'key1': 'value1',
    'key2': 'value2'
})

# 发送请求时会自动携带这些 Cookie
response = session.get('https://example.com')
print(response.text)

session.close()
```

#### 为不同域名设置 Cookie

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# 为不同域名设置不同的 Cookie
session.cookies.set_cookie('api_key', 'key123', domain='api.example.com')
session.cookies.set_cookie('user_token', 'token456', domain='www.example.com')
session.cookies.set_cookie('session', 'session789', domain='example.com', path='/admin')

# 访问不同域名时会自动使用对应的 Cookie
response1 = session.get('https://api.example.com/data')      # 携带 api_key
response2 = session.get('https://www.example.com/page')      # 携带 user_token
response3 = session.get('https://example.com/admin/panel')   # 携带 session

session.close()
```

#### 动态更新 Cookie

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# 第一次请求
response = session.get('https://example.com/login')

# 从响应中获取 Cookie 并更新
session.cookies.set_cookie('auth_token', 'new_token_from_response', domain='example.com')

# 后续请求会携带更新后的 Cookie
response = session.get('https://example.com/dashboard')

session.close()
```

#### 查看和管理 Cookie

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# 设置 Cookie
session.cookies.set_cookie('key1', 'value1', domain='example.com')
session.cookies.set_cookie('key2', 'value2', domain='example.com')

# 查看所有 Cookie
print(session.cookies.get_dict())  # 获取所有 Cookie 的字典
print(session.cookies.get_dict(domain='example.com'))  # 获取特定域名的 Cookie

# 获取特定 Cookie 的值
value = session.cookies.get('key1', domain='example.com')
print(f"key1 = {value}")

# 清空所有 Cookie
session.cookies.clear()

session.close()
```

#### 删除 Cookie

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# 设置一些 Cookie
session.cookies.set_cookie('token', 'abc', domain='example.com')
session.cookies.set_cookie('token', 'xyz', domain='api.example.com')
session.cookies.set_cookie('session_id', 'sess1', domain='example.com')
session.cookies.set_cookie('tracking', 'tr1', domain='example.com')

# 1. 删除指定域名下的指定 Cookie
session.cookies.delete(name='token', domain='example.com')
# 只删除 example.com 下的 token，api.example.com 的 token 不受影响

# 2. 删除所有域名下的同名 Cookie
session.cookies.delete(name='token')
# 所有域名下叫 token 的 Cookie 全部删除

# 3. 删除某个域名的所有 Cookie
session.cookies.delete(domain='example.com')
# example.com 下的所有 Cookie（session_id、tracking 等）全部删除

# 查看剩余 Cookie
print(session.cookies.get_dict())

session.close()
```

#### 异步模式下的 Cookie 管理

```python
import asyncio
import cycronet

async def main():
    async with cycronet.AsyncCronetClient(verify=False) as session:
        # 初始化 Cookie
        session.cookies.set_cookie('session_id', 'async_session_123', domain='example.com')
        session.cookies.set_cookie('user_token', 'token_xyz', domain='example.com')

        # 发送请求
        response = await session.get('https://example.com')
        print(response.text)

asyncio.run(main())
```

### Headers 顺序控制 （直接穿字典也是会按照字典顺序排列）

**使用数组（元组列表）精确控制 Headers 顺序：**

许多反爬虫系统会检测请求头的顺序。使用数组格式可以精确控制 Headers 的发送顺序，这是绕过指纹检测的关键。

```python
import cycronet

# 使用数组（元组列表）控制 Headers 顺序
headers = [
    ("user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"),
    ("sec-ch-ua-platform", '"macOS"'),
    ("sec-ch-ua", '"Google Chrome";v="144", "Chromium";v="144", "Not?A_Brand";v="24"'),
    ("sec-ch-ua-mobile", "?0"),
    ("origin", "https://example.com"),
    ("accept-language", "zh-CN,zh;q=0.9"),
    ("referer", "https://example.com/page"),
    ("accept-encoding", "gzip, deflate, br"),
    ("priority", "u=1, i"),
]

response = cycronet.get('https://example.com', headers=headers, verify=False)
```

**为什么使用数组而不是字典？**

- **字典（dict）**：Python 3.7+ 虽然保持插入顺序，但在某些情况下可能被重新排序
- **数组（list of tuples）**：严格保持定义的顺序，确保 Headers 按你指定的顺序发送
- 真实浏览器的 Headers 顺序是固定的，使用数组可以完美模拟

## 📊 性能对比

| 特性 | requests | httpx | aiohttp | **cycronet (同步)** | **cycronet (异步)** |
|------|----------|-------|---------|---------------------|---------------------|
| TLS 指纹 | Python/OpenSSL | Python/OpenSSL | Python/OpenSSL | **Chrome** ✅ | **Chrome** ✅ |
| HTTP/2 | ❌ | ✅ (异常) | ❌ | **✅ (真实)** | **✅ (真实)** |
| 异步支持 | ❌ | ✅ | ✅ | ❌ | **✅** |
| 并发性能 | 低 | 高 | 高 | 低 | **高** |
| 代理支持 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Cookie 管理 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 绕过检测 | ❌ | ❌ | ❌ | **✅** | **✅** |

**性能测试（10 个并发请求）：**

- requests（同步）：~10 秒
- httpx（异步）：~1 秒（但 TLS 指纹异常）
- aiohttp（异步）：~1 秒（但 TLS 指纹异常）
- **cycronet（同步）**：~10 秒（真实 Chrome 指纹）
- **cycronet（异步）**：~1 秒（真实 Chrome 指纹）✅ **最佳选择**

## ⚠️ 注意事项

1. **合法使用**：仅用于合法的数据采集和测试，遵守网站的 robots.txt 和服务条款
2. **请求频率**：控制请求频率，避免对目标服务器造成压力
3. **代理质量**：使用高质量的代理，避免被封禁的 IP
4. **Headers 真实性**：使用真实的浏览器 Headers，与 User-Agent 保持一致
5. **行为模拟**：添加随机延迟，模拟真实用户行为

## 🎯 使用场景

- ✅ 绕过 Cloudflare、Akamai 等 CDN 的指纹检测
- ✅ 爬取有反爬虫保护的网站
- ✅ API 测试和压力测试
- ✅ 数据采集和监控
- ✅ SEO 工具开发
- ✅ 价格监控和比价系统
- ✅ 社交媒体数据采集
- ✅ **高并发爬虫（使用异步 API）**
- ✅ **大规模数据采集（异步并发）**
- ✅ **实时监控系统（异步轮询）**
- ✅ **WebSocket 实时通信（聊天、推送、行情）**
- ✅ **WSS 连接绕过 WebSocket 指纹检测**

## 📦 安装

```bash
pip install cycronet
```

### Linux 注意事项

**✅ 最新版本已自动修复库加载问题！**

从源码编译时，构建系统会自动设置 RPATH，使得 Python 扩展能够在同目录找到 `libcronet.so`，无需手动配置。

如果仍然遇到 `libcronet.so` 找不到的错误（旧版本或特殊环境），请参考 [LINUX_INSTALL_GUIDE.md](LINUX_INSTALL_GUIDE.md)。

## 🚀 快速开始

### 同步方式（简单场景）

```python
import cycronet

# 基本请求
response = cycronet.get('https://example.com', verify=False)
print(response.text)

# 使用 Session
with cycronet.CronetClient(verify=False) as session:
    response = session.get('https://example.com')
    print(response.json())
```

### 异步方式（高性能场景）

```python
import asyncio
import cycronet

async def main():
    # 基本异步请求
    response = await cycronet.async_get('https://example.com', verify=False)
    print(response.text)

    # 并发请求
    async with cycronet.AsyncCronetClient(verify=False) as session:
        tasks = [
            session.get('https://example.com/page1'),
            session.get('https://example.com/page2'),
            session.get('https://example.com/page3'),
        ]
        responses = await asyncio.gather(*tasks)
        for resp in responses:
            print(resp.status_code)

asyncio.run(main())
```

## 📚 相关资源

- **TLS 指纹检测工具**：https://tls.peet.ws/
- **TLS 指纹检测站**：https://tls.jsvmp.top:38080/ 使用tls_verify.py检测
- **HTTP/2 指纹检测**：https://http2.pro/
- **Cloudflare 检测测试**：https://check.torproject.org/

**Cycronet - 真实的 Chrome 指纹，绕过一切检测！** 🚀
