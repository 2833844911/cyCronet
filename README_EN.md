# Cycronet - Python HTTP Client Bypassing TLS/HTTP2 Fingerprint Detection

English | [简体中文](README.md)

## 🎯 Core Features

Cycronet is a Python HTTP client based on Chromium's Cronet network stack. **Its key feature is generating authentic Chrome browser TLS/HTTP2 fingerprints**, effectively bypassing various anti-bot and fingerprint detection systems.

**✨ New Features:**

- 🚀 Support for both synchronous and asynchronous APIs
- ⚡ Async concurrent requests with 5-10x performance boost
- 🔄 Same user experience as aiohttp/httpx
- 🎯 Authentic Chrome TLS/HTTP2 fingerprints (both sync and async)
- 🔐 **Custom TLS fingerprint configuration (NEW!)**

### Why Cycronet?

Traditional Python HTTP libraries (like requests, httpx, aiohttp) use Python's network stack, which has different TLS handshake and HTTP/2 characteristics from real browsers, making them easy to detect and block.

**Common Detection Methods:**

1. **TLS Fingerprint Detection**
   - Cipher suite order in TLS ClientHello message
   - Supported TLS extensions and their order
   - Elliptic curve algorithm selection
   - ALPN protocol list

2. **HTTP/2 Fingerprint Detection**
   - SETTINGS frame parameters and order
   - Initial WINDOW_UPDATE values
   - Pseudo-headers order
   - Priority settings

3. **Request Header Fingerprint Detection**
   - User-Agent mismatch with actual behavior
   - Abnormal header order
   - Missing browser-specific headers

**Cycronet's Solution:**

Cycronet directly uses Chromium's Cronet network library, producing network characteristics **completely identical** to real Chrome browsers, making it undetectable as a bot.

## Installation
```bash
pip install cycronet
```
- Currently supports macOS ARM64, Linux (glibc 2.18+), Windows 64-bit
- Proxy support: HTTP, HTTPS, SOCKS5 (without authentication)
- For SOCKS5 with authentication, use pproxy to convert to HTTP: `pip install pproxy` then `pproxy -l http://127.0.0.1:8118 -r socks5://user:pass@remote:1080`


## 🔐 TLS/HTTP2 Fingerprint Bypass

### Authentic Chrome Fingerprint

**Synchronous Method:**

```python
import cycronet

# Cycronet automatically uses Chrome's TLS/HTTP2 fingerprint
response = cycronet.get('https://tls.peet.ws/api/all', verify=False)

# View TLS fingerprint information
data = response.json()
print(f"TLS Version: {data['tls']['version']}")
print(f"Cipher Suite: {data['tls']['cipher_suite']}")
print(f"HTTP Version: {data['http']['version']}")  # HTTP/2
```

**Asynchronous Method:**

```python
import asyncio
import cycronet

async def check_fingerprint():
    # Async request with same Chrome fingerprint
    response = await cycronet.async_get('https://tls.peet.ws/api/all', verify=False)
    data = response.json()
    print(f"TLS Version: {data['tls']['version']}")
    print(f"HTTP Version: {data['http']['version']}")  # HTTP/2

asyncio.run(check_fingerprint())
```

### Comparison with requests

```python
# ❌ requests - Easily detected
import requests
response = requests.get('https://example.com')
# TLS fingerprint: Python/OpenSSL
# HTTP/2: Not supported or abnormal characteristics

# ✅ cycronet sync - Real Chrome fingerprint
import cycronet
response = cycronet.get('https://example.com', verify=False)
# TLS fingerprint: Chrome 144.x
# HTTP/2: Fully compliant with Chrome behavior

# ✅ cycronet async - Real Chrome fingerprint + High performance
import asyncio
response = await cycronet.async_get('https://example.com', verify=False)
# TLS fingerprint: Chrome 144.x
# HTTP/2: Fully compliant with Chrome behavior
# Performance: Concurrent support, 5-10x faster
```

### Bypassing Cloudflare, Akamai, and Other CDNs

```python
import cycronet

# Cloudflare-protected website
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

print(f"Status: {response.status_code}")  # 200 - Successfully bypassed
```

### Custom TLS Fingerprint Configuration

Cycronet supports custom TLS fingerprint configurations to simulate specific Chrome browser versions:

```python
import cycronet

# Use Chrome 144 TLS fingerprint configuration
session = cycronet.CronetClient(
    verify=False,
    chrometls="chrome_144"  # Specify TLS configuration
)

response = session.get('https://tls.peet.ws/api/all')
print(response.json())
session.close()

# Use proxy with TLS fingerprint
session = cycronet.CronetClient(
    verify=False,
    proxies={'https': 'http://127.0.0.1:21882'},
    chrometls="chrome_144"
)
```

**Supported TLS Configurations:**
- `chrome_144`: Chrome 144 version TLS fingerprint (default)

#### Adding Custom TLS Configurations

You can add custom TLS fingerprint configurations by editing the `tls_profiles.json` file.

**1. Locate the Configuration File**

The configuration file is searched in the following locations (by priority):
- Python package installation directory: `site-packages/cycronet/tls_profiles.json`
- Current working directory: `./tls_profiles.json`

**2. Edit the Configuration File**

Open `tls_profiles.json` and add new configurations:

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

**3. Use Custom Configuration**

```python
import cycronet

# Use the newly added Chrome 143 configuration
session = cycronet.CronetClient(
    verify=False,
    chrometls="chrome_143"
)

response = session.get('https://example.com')
print(response.text)
session.close()
```

**Configuration Details:**

- `version`: Configuration description name
- `cipher_suites`: TLS Cipher Suites list (in order)
  - Must use standard TLS cipher suite names
  - Order matters and affects TLS fingerprint
  - `TLS_GREASE` is Chrome's special value to prevent protocol ossification
- `hex_codes`: Corresponding hexadecimal codes (optional, for documentation only)

**Common Cipher Suites:**

| Name | Hex | Description |
|------|-----|-------------|
| TLS_GREASE | 0x6a6a | Chrome GREASE value |
| TLS_AES_128_GCM_SHA256 | 0x1301 | TLS 1.3 |
| TLS_AES_256_GCM_SHA384 | 0x1302 | TLS 1.3 |
| TLS_CHACHA20_POLY1305_SHA256 | 0x1303 | TLS 1.3 |
| TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256 | 0xc02b | TLS 1.2 |
| TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 | 0xc02f | TLS 1.2 |

**Getting Real Browser Cipher Suites:**

1. Visit https://tls.peet.ws/api/all
2. Check the `tls.ciphers` field
3. Copy the cipher suite list to the configuration file

**Example: Getting Configuration from Browser**

```python
import cycronet
import json

# Access TLS detection site with default configuration
response = cycronet.get('https://tls.peet.ws/api/all', verify=False)
data = response.json()

# Extract cipher suites
ciphers = data['tls']['ciphers']
print("Detected Cipher Suites:")
for cipher in ciphers:
    print(f"  - {cipher}")

# Save as new configuration
new_config = {
    "my_custom": {
        "version": "My Custom Profile",
        "cipher_suites": ciphers
    }
}

# Write to configuration file
with open('tls_profiles.json', 'w') as f:
    json.dump(new_config, f, indent=2)
```

## ⚡ Async Support (Async/Await)

Cycronet provides full async support, allowing you to use `async/await` for high-performance concurrent requests.

### Basic Async Usage

```python
import asyncio
import cycronet

async def main():
    # Method 1: Use module-level async functions
    response = await cycronet.async_get('https://httpbin.org/get', verify=False)
    print(response.json())

    # Method 2: Use AsyncSession
    async with cycronet.AsyncCronetClient(verify=False) as session:
        response = await session.get('https://httpbin.org/get')
        print(response.json())

asyncio.run(main())
```

### Async Concurrent Requests - Performance Boost

The biggest advantage of async is concurrent execution of multiple requests, significantly improving performance:

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

    # Execute 5 requests concurrently
    async with cycronet.AsyncCronetClient(verify=False) as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)

    # 5 requests take only ~1 second (instead of 5 seconds)
    for i, response in enumerate(responses):
        print(f"Request {i+1}: {response.status_code}")

asyncio.run(fetch_multiple())
```

**Performance Comparison:**

| Scenario | Sync Method | Async Method | Performance Gain |
|----------|-------------|--------------|------------------|
| 5 requests (1 sec each) | ~5 sec | ~1 sec | **5x** |
| 10 requests (1 sec each) | ~10 sec | ~1 sec | **10x** |
| 100 requests | Very slow | Fast | **10x+** |

### Complete Async API List

All sync APIs have corresponding async versions:

```python
import cycronet

# Module-level async functions
await cycronet.async_get(url, **kwargs)
await cycronet.async_post(url, **kwargs)
await cycronet.async_put(url, **kwargs)
await cycronet.async_delete(url, **kwargs)
await cycronet.async_patch(url, **kwargs)
await cycronet.async_head(url, **kwargs)
await cycronet.async_options(url, **kwargs)
await cycronet.async_upload_file(url, file_path, **kwargs)
await cycronet.async_download_file(url, save_path, **kwargs)

# AsyncSession methods
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

### Async with Proxy

```python
import asyncio
import cycronet

async def main():
    # Async Session supports proxy
    async with cycronet.AsyncCronetClient(
        verify=False,
        proxies={"https": "http://127.0.0.1:8080"}
    ) as session:
        response = await session.get('https://httpbin.org/ip')
        print(response.json())

asyncio.run(main())
```

### Async Error Handling

```python
import asyncio
import cycronet

async def main():
    try:
        # Timeout handling
        response = await cycronet.async_get(
            'https://httpbin.org/delay/10',
            timeout=2.0,
            verify=False
        )
    except asyncio.TimeoutError:
        print("Request timeout")

    try:
        # HTTP error handling
        response = await cycronet.async_get(
            'https://httpbin.org/status/404',
            verify=False
        )
        response.raise_for_status()
    except cycronet.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code}")

asyncio.run(main())
```

### When to Use Async?

**Recommended async scenarios:**

- ✅ Need to send multiple requests simultaneously (scraping, batch API calls)
- ✅ High concurrency scenarios (monitoring, data collection)
- ✅ Need to integrate with other async code (FastAPI, aiohttp, etc.)
- ✅ High performance requirements

**Use sync scenarios:**

- ✅ Simple single requests
- ✅ Script tools (no concurrency needed)
- ✅ Easier integration with sync code

## 🌐 Proxy Configuration

Cycronet supports multiple proxy types and can be combined with proxy pools and IP rotation solutions.

### Basic Proxy Configuration

```python
import cycronet

# HTTP proxy
session = cycronet.CronetClient(
    verify=False,
    proxies={"https": "http://127.0.0.1:8080"}
)


# Proxy with authentication
session = cycronet.CronetClient(
    verify=False,
    proxies={"https": "http://username:password@proxy.example.com:8080"}
)

response = session.get('https://httpbin.org/ip')
print(response.json())
session.close()
```


## 🔧 Advanced Configuration

### SSL Certificate Verification

```python
import cycronet

# Skip SSL verification (for testing or self-signed certificates)
session = cycronet.CronetClient(verify=False)

# Enable SSL verification (default, recommended for production)
session = cycronet.CronetClient(verify=True)
```

### Timeout Settings

```python
# Global timeout
session = cycronet.CronetClient(
    verify=False,
    timeout_ms=30000  # 30 seconds
)

# Per-request timeout
response = session.get('https://example.com', timeout=10.0)
```

### Cookie Management

Cycronet supports flexible cookie management. You can initialize cookies when creating a session or update them dynamically during requests.

#### Initialize Cookies

```python
import cycronet

def get_proxy():
    return "http://127.0.0.1:8080"

# Create Session and initialize cookies
session = cycronet.CronetClient(
    timeout_ms=10000,
    verify=False,
    proxies={"https": get_proxy()}
)

# Method 1: Use set_cookie to set cookies (recommended)
session.cookies.set_cookie('session_id', 'abc123', domain='example.com')
session.cookies.set_cookie('user_token', 'xyz789', domain='example.com')
session.cookies.set_cookie('preferences', 'dark_mode=1', domain='example.com')

# Method 2: Use update for batch setting (without domain)
session.cookies.update({
    'key1': 'value1',
    'key2': 'value2'
})

# Cookies are automatically sent with requests
response = session.get('https://example.com')
print(response.text)

session.close()
```

#### Set Cookies for Different Domains

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# Set different cookies for different domains
session.cookies.set_cookie('api_key', 'key123', domain='api.example.com')
session.cookies.set_cookie('user_token', 'token456', domain='www.example.com')
session.cookies.set_cookie('session', 'session789', domain='example.com', path='/admin')

# Automatically use corresponding cookies when accessing different domains
response1 = session.get('https://api.example.com/data')      # Carries api_key
response2 = session.get('https://www.example.com/page')      # Carries user_token
response3 = session.get('https://example.com/admin/panel')   # Carries session

session.close()
```

#### Dynamic Cookie Updates

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# First request
response = session.get('https://example.com/login')

# Get cookie from response and update
session.cookies.set_cookie('auth_token', 'new_token_from_response', domain='example.com')

# Subsequent requests carry updated cookies
response = session.get('https://example.com/dashboard')

session.close()
```

#### View and Manage Cookies

```python
import cycronet

session = cycronet.CronetClient(verify=False)

# Set cookies
session.cookies.set_cookie('key1', 'value1', domain='example.com')
session.cookies.set_cookie('key2', 'value2', domain='example.com')

# View all cookies
print(session.cookies.get_dict())  # Get all cookies as dict
print(session.cookies.get_dict(domain='example.com'))  # Get cookies for specific domain

# Get specific cookie value
value = session.cookies.get('key1', domain='example.com')
print(f"key1 = {value}")

# Clear all cookies
session.cookies.clear()

session.close()
```

#### Cookie Management in Async Mode

```python
import asyncio
import cycronet

async def main():
    async with cycronet.AsyncCronetClient(verify=False) as session:
        # Initialize cookies
        session.cookies.set_cookie('session_id', 'async_session_123', domain='example.com')
        session.cookies.set_cookie('user_token', 'token_xyz', domain='example.com')

        # Send request
        response = await session.get('https://example.com')
        print(response.text)

asyncio.run(main())
```

### Headers Order Control (Dictionaries also maintain order)

**Use arrays (list of tuples) for precise header order control:**

Many anti-bot systems detect request header order. Using array format allows precise control of header sending order, which is key to bypassing fingerprint detection.

```python
import cycronet

# Use array (list of tuples) to control header order
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

**Why use arrays instead of dictionaries?**

- **Dictionary (dict)**: Python 3.7+ maintains insertion order, but may be reordered in some cases
- **Array (list of tuples)**: Strictly maintains defined order, ensuring headers are sent in your specified order
- Real browser header order is fixed; using arrays perfectly simulates this

## 📊 Performance Comparison

| Feature | requests | httpx | aiohttp | **cycronet (sync)** | **cycronet (async)** |
|---------|----------|-------|---------|---------------------|----------------------|
| TLS Fingerprint | Python/OpenSSL | Python/OpenSSL | Python/OpenSSL | **Chrome** ✅ | **Chrome** ✅ |
| HTTP/2 | ❌ | ✅ (abnormal) | ❌ | **✅ (authentic)** | **✅ (authentic)** |
| Async Support | ❌ | ✅ | ✅ | ❌ | **✅** |
| Concurrent Performance | Low | High | High | Low | **High** |
| Proxy Support | ✅ | ✅ | ✅ | ✅ | ✅ |
| Cookie Management | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bypass Detection | ❌ | ❌ | ❌ | **✅** | **✅** |

**Performance Test (10 concurrent requests):**

- requests (sync): ~10 seconds
- httpx (async): ~1 second (but abnormal TLS fingerprint)
- aiohttp (async): ~1 second (but abnormal TLS fingerprint)
- **cycronet (sync)**: ~10 seconds (authentic Chrome fingerprint)
- **cycronet (async)**: ~1 second (authentic Chrome fingerprint) ✅ **Best Choice**

## ⚠️ Important Notes

1. **Legal Use**: Only for legitimate data collection and testing, comply with website robots.txt and terms of service
2. **Request Rate**: Control request frequency to avoid stressing target servers
3. **Proxy Quality**: Use high-quality proxies to avoid blocked IPs
4. **Header Authenticity**: Use real browser headers consistent with User-Agent
5. **Behavior Simulation**: Add random delays to simulate real user behavior

## 🎯 Use Cases

- ✅ Bypass Cloudflare, Akamai, and other CDN fingerprint detection
- ✅ Scrape websites with anti-bot protection
- ✅ API testing and stress testing
- ✅ Data collection and monitoring
- ✅ SEO tool development
- ✅ Price monitoring and comparison systems
- ✅ Social media data collection
- ✅ **High-concurrency scraping (using async API)**
- ✅ **Large-scale data collection (async concurrency)**
- ✅ **Real-time monitoring systems (async polling)**

## 🚀 Quick Start

### Synchronous Method (Simple Scenarios)

```python
import cycronet

# Basic request
response = cycronet.get('https://example.com', verify=False)
print(response.text)

# Use Session
with cycronet.CronetClient(verify=False) as session:
    response = session.get('https://example.com')
    print(response.json())
```

### Asynchronous Method (High-Performance Scenarios)

```python
import asyncio
import cycronet

async def main():
    # Basic async request
    response = await cycronet.async_get('https://example.com', verify=False)
    print(response.text)

    # Concurrent requests
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

## 📚 Related Resources

- **TLS Fingerprint Detection Tool**: https://tls.peet.ws/
- **TLS Fingerprint Detection Site**: https://tls.tsvmp.com:38080/
- **HTTP/2 Fingerprint Detection**: https://http2.pro/
- **Cloudflare Detection Test**: https://check.torproject.org/

**Cycronet - Authentic Chrome Fingerprint, Bypass All Detection!** 🚀
