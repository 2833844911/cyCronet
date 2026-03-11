#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cronet HTTP 客户端 - 类似 httpx 风格的 API
支持同步和异步请求，会话级Cookie自动保持
"""

import asyncio
import json
from typing import Optional, Union, Dict, List, Tuple, Any
from dataclasses import dataclass
from urllib.parse import urlparse
import aiohttp
BASE_URL =  "http://127.0.0.1:3000/api/v1"

def _extract_domain(url: str) -> str:
    """从 URL 中提取域名"""
    parsed = urlparse(url)
    return parsed.netloc.lower()


@dataclass
class Response: 
    """HTTP 响应对象"""
    status_code: int
    headers: Dict[str, List[str]]
    content: bytes
    duration_ms: float = 0

    @property
    def text(self) -> str:
        """返回响应文本"""
        return self.content.decode('utf-8', errors='replace')

    def json(self) -> Any:
        """解析 JSON 响应"""
        return json.loads(self.text)

    def raise_for_status(self):
        """如果状态码表示错误则抛出异常"""
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code}", response=self)


class HTTPStatusError(Exception):
    """HTTP 状态码错误"""
    def __init__(self, message: str, response: Response):
        super().__init__(message)
        self.response = response


class RequestError(Exception):
    """请求错误"""
    pass


@dataclass
class Proxy:
    """代理配置"""
    host: str
    port: int
    username: str = ""
    password: str = ""
    type: int = 0  # 0: HTTP, 1: SOCKS5


HeadersType = Union[Dict[str, str], List[Tuple[str, str]]]
CookiesType = Dict[str, str]
ContentType = Union[str, bytes, Dict[str, Any], None]


def _parse_set_cookie(set_cookie_values: List[str]) -> List[Tuple[str, str, str]]:
    """
    解析 Set-Cookie 响应头，提取 cookie 名值对和 Domain
    返回: [(cookie_name, cookie_value, domain), ...]
    domain 为空字符串表示没有指定 Domain 属性
    """
    cookies = []
    for value in set_cookie_values:
        # Set-Cookie: name=value; Domain=.example.com; Path=/; ...
        if '=' in value:
            parts = value.split(';')
            # 第一个部分是 name=value
            cookie_part = parts[0].strip()
            if '=' in cookie_part:
                name, val = cookie_part.split('=', 1)
                name = name.strip()
                val = val.strip()

                # 查找 Domain 属性
                domain = ""
                for part in parts[1:]:
                    part = part.strip()
                    if part.lower().startswith('domain='):
                        domain = part.split('=', 1)[1].strip().lower()
                        # 移除开头的点 (.) 以便统一处理
                        if domain.startswith('.'):
                            domain = domain[1:]
                        break

                cookies.append((name, val, domain))
    return cookies


def _domain_matches(cookie_domain: str, request_domain: str) -> bool:
    """
    检查 cookie 的 domain 是否匹配请求的 domain
    cookie_domain: cookie 指定的 domain (如 "cebupacificair.com")
    request_domain: 请求的 domain (如 "soar.cebupacificair.com")
    """
    if not cookie_domain:
        return False
    request_domain = request_domain.lower()
    cookie_domain = cookie_domain.lower()

    # 精确匹配
    if request_domain == cookie_domain:
        return True

    # 子域名匹配: request_domain 以 .cookie_domain 结尾
    if request_domain.endswith('.' + cookie_domain):
        return True

    return False


class AsyncCronetClient:
    """
    异步 Cronet HTTP 客户端

    特性:
    - 会话级 Cookie 自动保持
    - Priority 头始终在 headers 最后 (Cookie 之后)
    - Cookie 在倒数第二 (Priority 之前)
    - 用户传递的 cookies 会更新/覆盖会话 cookies
    - 支持并发控制和请求队列
    """

    def __init__(
        self,
        base_url: str =BASE_URL,
        proxy: Optional[Proxy] = None,
        timeout: float = 30.0,
        skip_cert_verify: bool = True,
        max_concurrent: int = 1  # 最大并发请求数
    ):
        self.base_url = base_url
        self.proxy = proxy
        self.timeout = timeout
        self.skip_cert_verify = skip_cert_verify
        self.max_concurrent = max_concurrent
        self.session_id: Optional[str] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        # 会话级 cookies 存储: {domain: {cookie_name: cookie_value}}
        self._cookies: Dict[str, Dict[str, str]] = {}
        # 并发控制
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_requests = 0
        self._is_closed = False

    @property
    def cookies(self) -> Dict[str, Dict[str, str]]:
        """获取当前会话的所有 cookies (按域名分组)"""
        return {domain: cookies.copy() for domain, cookies in self._cookies.items()}

    def get_cookies_for_domain(self, domain: str) -> Dict[str, str]:
        """获取指定域名的 cookies"""
        return self._cookies.get(domain.lower(), {}).copy()

    async def __aenter__(self):
        await self._create_session()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _create_session(self):
        """创建 Cronet 会话"""
        config = {
            "skip_cert_verify": self.skip_cert_verify,
            "timeout_ms": int(self.timeout * 1000)
        }

        if self.proxy:
            config["proxy"] = {
                "host": self.proxy.host,
                "port": self.proxy.port,
                "type": self.proxy.type,
                "username": self.proxy.username,
                "password": self.proxy.password
            }

        http_session = await self._get_http_session()
        async with http_session.post(f"{self.base_url}/session", json=config) as resp:
            data = await resp.json()

        if data.get("success"):
            self.session_id = data["session_id"]
        else:
            raise RequestError(f"创建会话失败: {data.get('error_message')}")

    async def close(self):
        """关闭会话"""
        self._is_closed = True

        # 等待所有活跃请求完成
        if self._active_requests > 0:
            print(f"[INFO] Waiting for {self._active_requests} active requests to complete...")
            for _ in range(100):  # 最多等待 10 秒
                if self._active_requests == 0:
                    break
                await asyncio.sleep(0.1)

            if self._active_requests > 0:
                print(f"[WARN] Timeout waiting for {self._active_requests} active requests")

        if self.session_id:
            try:
                http_session = await self._get_http_session()
                async with http_session.delete(f"{self.base_url}/session/{self.session_id}") as resp:
                    await resp.json()
            except Exception:
                pass
            self.session_id = None

        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = ""
    ) -> List[List[str]]:
        """
        准备请求头
        排序逻辑: [普通Headers] -> [Cookie] -> [Priority]
        """
        if headers is None:
            headers_list = []
        elif isinstance(headers, dict):
            headers_list = list(headers.items())
        else:
            headers_list = list(headers)

        # 1. 分离 headers: 普通的 / Priority / Cookie
        normal_headers = []
        priority_headers = []

        for k, v in headers_list:
            k_lower = k.lower()
            if k_lower == 'cookie':
                continue  # 稍后处理
            elif k_lower == 'priority':
                priority_headers.append([k, v])
            else:
                normal_headers.append([k, v])

        # 2. 合并 cookies: 匹配该域名的所有会话 cookies + 用户传递的 cookies
        merged_cookies = {}
        # 遍历所有存储的 cookie 域名，检查是否匹配当前请求域名
        for cookie_domain, domain_cookies in self._cookies.items():
            if cookie_domain == domain or _domain_matches(cookie_domain, domain):
                merged_cookies.update(domain_cookies)
        if cookies:
            merged_cookies.update(cookies)  # 用户的覆盖会话的

        # 3. 构建最终 result: 普通 -> Cookie -> Priority
        result = normal_headers

        # 添加 cookie (如果在 Priority 之前)
        if merged_cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in merged_cookies.items()])
            result.append(["cookie", cookie_str])

        # 最后添加 Priority
        result.extend(priority_headers)

        return result

    def _prepare_content(self, content: ContentType) -> str:
        """准备请求体，返回 hex 编码的字符串"""
        if content is None:
            return ""

        if isinstance(content, dict):
            body_bytes = json.dumps(content).encode('utf-8')
        elif isinstance(content, str):
            body_bytes = content.encode('utf-8')
        else:
            body_bytes = content

        return body_bytes.hex()

    def _update_cookies_from_response(self, headers: Dict[str, List[str]], request_domain: str):
        """从响应头中提取 Set-Cookie 并更新会话 cookies (按 cookie 声明的域名存储)"""
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = _parse_set_cookie(values)
                for cookie_name, cookie_value, cookie_domain in parsed_cookies:
                    # 如果 cookie 没有指定 Domain，则使用请求的域名
                    store_domain = cookie_domain if cookie_domain else request_domain
                    if store_domain not in self._cookies:
                        self._cookies[store_domain] = {}
                    self._cookies[store_domain][cookie_name] = cookie_value

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法 (GET, POST, etc.)
            url: 请求 URL
            headers: 请求头
            cookies: Cookies
            content: 请求体内容
            data: 表单数据或字符串
            json_data: JSON 数据
            timeout: 请求超时时间（秒），None 使用客户端默认值
        """
        if not self.session_id:
            raise RequestError("会话未创建，请使用 async with 或调用 _create_session()")

        if self._is_closed:
            raise RequestError("会话已关闭")

        # 使用信号量控制并发
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

        async with self._semaphore:
            self._active_requests += 1
            try:
                return await self._do_request(
                    method, url,
                    headers=headers,
                    cookies=cookies,
                    content=content,
                    data=data,
                    json_data=json_data,
                    timeout=timeout
                )
            finally:
                self._active_requests -= 1

    async def _do_request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """实际执行请求的内部方法"""
        # 提取域名
        domain = _extract_domain(url)

        # 更新会话 cookies (按域名存储)
        if cookies:
            if domain not in self._cookies:
                self._cookies[domain] = {}
            self._cookies[domain].update(cookies)

        # 确保 headers 是列表格式
        if headers is None:
            headers = []
        if isinstance(headers, dict):
            headers = list(headers.items())
        else:
            headers = list(headers)

        # 处理 json 参数
        if json_data is not None:
            content = json_data
            has_content_type = any(k.lower() == 'content-type' for k, v in headers)
            if not has_content_type:
                headers.append(("content-type", "application/json"))
        # 处理 data 参数
        elif data is not None:
            if isinstance(data, dict):
                # 字典转为 form-urlencoded
                from urllib.parse import urlencode
                content = urlencode(data)
                has_content_type = any(k.lower() == 'content-type' for k, v in headers)
                if not has_content_type:
                    headers.append(("content-type", "application/x-www-form-urlencoded"))
            else:
                # 字符串直接使用
                content = data
                has_content_type = any(k.lower() == 'content-type' for k, v in headers)
                if not has_content_type:
                    headers.append(("content-type", "application/x-www-form-urlencoded"))

        # 构建 payload
        request_timeout = timeout if timeout is not None else self.timeout

        # Ensure minimum timeout of 0.1 seconds (100ms)
        if request_timeout < 0.1:
            request_timeout = 0.1

        payload = {
            "url": url,
            "method": method.upper(),
            "headers": self._prepare_headers(headers, cookies, domain),
            "timeout_ms": int(request_timeout * 1000)
        }

        body_hex = self._prepare_content(content)
        if body_hex:
            payload["body"] = body_hex

        try:
            # Python HTTP timeout = Cronet timeout + 5 seconds buffer
            http_timeout = request_timeout + 5.0
            http_session = await self._get_http_session()
            async with http_session.post(
                f"{self.base_url}/session/{self.session_id}/request",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=http_timeout)
            ) as resp:
                data = await resp.json()

            if not data.get("success"):
                raise RequestError(f"请求失败: {data.get('error_message')}")

            response_data = data.get("response", {})
            status_code = response_data.get("status_code", 0)

            # 解析响应头
            raw_headers = response_data.get("headers", {})
            resp_headers = {}
            for name, value_info in raw_headers.items():
                resp_headers[name] = value_info.get("values", [])

            # 更新会话 cookies
            self._update_cookies_from_response(resp_headers, domain)

            # 解码响应体
            body_hex = response_data.get("body", "")
            if body_hex:
                content_bytes = bytes.fromhex(body_hex)
            else:
                content_bytes = b""

            return Response(
                status_code=status_code,
                headers=resp_headers,
                content=content_bytes,
                duration_ms=data.get("duration_ms", 0)
            )

        except aiohttp.ClientError as e:
            raise RequestError(f"连接错误: {e}")
        except Exception as e:
            if isinstance(e, RequestError):
                raise
            raise RequestError(f"{type(e).__name__}: {e}")

    async def get(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 GET 请求"""
        return await self.request("GET", url, headers=headers, cookies=cookies, timeout=timeout)

    async def post(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 POST 请求"""
        return await self.request("POST", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)

    async def put(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 PUT 请求"""
        return await self.request("PUT", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)

    async def delete(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 DELETE 请求"""
        return await self.request("DELETE", url, headers=headers, cookies=cookies, timeout=timeout)

    async def patch(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 PATCH 请求"""
        return await self.request("PATCH", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)


class CronetClient:
    """
    同步 Cronet HTTP 客户端

    特性:
    - 会话级 Cookie 自动保持
    - Priority 头始终在 headers 最后 (Cookie 之后)
    - Cookie 在倒数第二 (Priority 之前)
    - 用户传递的 cookies 会更新/覆盖会话 cookies
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        proxy: Optional[Proxy] = None,
        timeout: float = 30.0,
        skip_cert_verify: bool = True
    ):
        self.base_url = base_url
        self.proxy = proxy
        self.timeout = timeout
        self.skip_cert_verify = skip_cert_verify
        self.session_id: Optional[str] = None
        # 会话级 cookies 存储: {domain: {cookie_name: cookie_value}}
        self._cookies: Dict[str, Dict[str, str]] = {}

        # 导入 requests (同步版本使用)
        import requests as req_lib
        self._requests = req_lib

    @property
    def cookies(self) -> Dict[str, Dict[str, str]]:
        """获取当前会话的所有 cookies (按域名分组)"""
        return {domain: cookies.copy() for domain, cookies in self._cookies.items()}

    def get_cookies_for_domain(self, domain: str) -> Dict[str, str]:
        """获取指定域名的 cookies"""
        return self._cookies.get(domain.lower(), {}).copy()

    def __enter__(self):
        self._create_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _create_session(self):
        """创建 Cronet 会话"""
        config = {
            "skip_cert_verify": self.skip_cert_verify,
            "timeout_ms": int(self.timeout * 1000)
        }

        if self.proxy:
            config["proxy"] = {
                "host": self.proxy.host,
                "port": self.proxy.port,
                "type": self.proxy.type,
                "username": self.proxy.username,
                "password": self.proxy.password
            }

        resp = self._requests.post(f"{self.base_url}/session", json=config)
        data = resp.json()

        if data.get("success"):
            self.session_id = data["session_id"]
        else:
            raise RequestError(f"创建会话失败: {data.get('error_message')}")

    def close(self):
        """关闭会话"""
        if self.session_id:
            try:
                self._requests.delete(f"{self.base_url}/session/{self.session_id}")
            except Exception:
                pass
            self.session_id = None

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = ""
    ) -> List[List[str]]:
        """
        准备请求头
        排序逻辑: [普通Headers] -> [Cookie] -> [Priority]
        """
        if headers is None:
            headers_list = []
        elif isinstance(headers, dict):
            headers_list = list(headers.items())
        else:
            headers_list = list(headers)

        # 1. 分离 headers: 普通 / Priority / Cookie
        normal_headers = []
        priority_headers = []

        for k, v in headers_list:
            k_lower = k.lower()
            if k_lower == 'cookie':
                continue
            elif k_lower == 'priority':
                priority_headers.append([k, v])
            else:
                normal_headers.append([k, v])

        # 2. 合并 cookies: 匹配该域名的所有会话 cookies + 用户传递的 cookies
        merged_cookies = {}
        # 遍历所有存储的 cookie 域名，检查是否匹配当前请求域名
        for cookie_domain, domain_cookies in self._cookies.items():
            if cookie_domain == domain or _domain_matches(cookie_domain, domain):
                merged_cookies.update(domain_cookies)
        if cookies:
            merged_cookies.update(cookies)  # 用户的覆盖会话的

        # 3. 构建最终 result: 普通 -> Cookie -> Priority
        result = normal_headers

        # 添加 cookie
        if merged_cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in merged_cookies.items()])
            result.append(["cookie", cookie_str])

        # 最后添加 Priority
        result.extend(priority_headers)

        return result

    def _prepare_content(self, content: ContentType) -> str:
        """准备请求体"""
        if content is None:
            return ""

        if isinstance(content, dict):
            body_bytes = json.dumps(content).encode('utf-8')
        elif isinstance(content, str):
            body_bytes = content.encode('utf-8')
        else:
            body_bytes = content

        return body_bytes.hex()

    def _update_cookies_from_response(self, headers: Dict[str, List[str]], request_domain: str):
        """从响应头中提取 Set-Cookie 并更新会话 cookies (按 cookie 声明的域名存储)"""
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = _parse_set_cookie(values)
                for cookie_name, cookie_value, cookie_domain in parsed_cookies:
                    # 如果 cookie 没有指定 Domain，则使用请求的域名
                    store_domain = cookie_domain if cookie_domain else request_domain
                    if store_domain not in self._cookies:
                        self._cookies[store_domain] = {}
                    self._cookies[store_domain][cookie_name] = cookie_value

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法 (GET, POST, etc.)
            url: 请求 URL
            headers: 请求头
            cookies: Cookies
            content: 请求体内容
            data: 表单数据或字符串
            json_data: JSON 数据
            timeout: 请求超时时间（秒），None 使用客户端默认值
        """
        if not self.session_id:
            raise RequestError("会话未创建，请使用 with 语句或调用 _create_session()")

        # 提取域名
        domain = _extract_domain(url)

        # 更新会话 cookies (按域名存储)
        if cookies:
            if domain not in self._cookies:
                self._cookies[domain] = {}
            self._cookies[domain].update(cookies)

        # 确保 headers 是列表格式
        if headers is None:
            headers = []
        if isinstance(headers, dict):
            headers = list(headers.items())
        else:
            headers = list(headers)

        # 处理 json 参数
        if json_data is not None:
            content = json_data
            has_content_type = any(k.lower() == 'content-type' for k, v in headers)
            if not has_content_type:
                headers.append(("content-type", "application/json"))
        # 处理 data 参数
        elif data is not None:
            if isinstance(data, dict):
                # 字典转为 form-urlencoded
                from urllib.parse import urlencode
                content = urlencode(data)
                has_content_type = any(k.lower() == 'content-type' for k, v in headers)
                if not has_content_type:
                    headers.append(("content-type", "application/x-www-form-urlencoded"))
            else:
                # 字符串直接使用
                content = data
                has_content_type = any(k.lower() == 'content-type' for k, v in headers)
                if not has_content_type:
                    headers.append(("content-type", "application/x-www-form-urlencoded"))

        # 构建 payload
        request_timeout = timeout if timeout is not None else self.timeout

        # Ensure minimum timeout of 0.1 seconds (100ms)
        if request_timeout < 0.1:
            request_timeout = 0.1

        payload = {
            "url": url,
            "method": method.upper(),
            "headers": self._prepare_headers(headers, cookies, domain),
            "timeout_ms": int(request_timeout * 1000)
        }

        body_hex = self._prepare_content(content)
        if body_hex:
            payload["body"] = body_hex

        try:
            # Python HTTP timeout = Cronet timeout + 5 seconds buffer
            http_timeout = request_timeout + 5.0
            resp = self._requests.post(
                f"{self.base_url}/session/{self.session_id}/request",
                json=payload,
                timeout=http_timeout
            )
            data = resp.json()

            if not data.get("success"):
                raise RequestError(f"请求失败: {data.get('error_message')}")

            response_data = data.get("response", {})
            status_code = response_data.get("status_code", 0)

            # 解析响应头
            raw_headers = response_data.get("headers", {})
            resp_headers = {}
            for name, value_info in raw_headers.items():
                resp_headers[name] = value_info.get("values", [])

            # 更新会话 cookies
            self._update_cookies_from_response(resp_headers, domain)

            # 解码响应体
            body_hex = response_data.get("body", "")
            if body_hex:
                content_bytes = bytes.fromhex(body_hex)
            else:
                content_bytes = b""

            return Response(
                status_code=status_code,
                headers=resp_headers,
                content=content_bytes,
                duration_ms=data.get("duration_ms", 0)
            )

        except self._requests.exceptions.RequestException as e:
            raise RequestError(f"连接错误: {e}")
        except Exception as e:
            if isinstance(e, RequestError):
                raise
            raise RequestError(f"{type(e).__name__}: {e}")

    def get(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 GET 请求"""
        return self.request("GET", url, headers=headers, cookies=cookies, timeout=timeout)

    def post(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 POST 请求"""
        return self.request("POST", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)

    def put(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 PUT 请求"""
        return self.request("PUT", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)

    def delete(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 DELETE 请求"""
        return self.request("DELETE", url, headers=headers, cookies=cookies, timeout=timeout)

    def patch(
        self,
        url: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        content: ContentType = None,
        data: Union[str, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """发送 PATCH 请求"""
        return self.request("PATCH", url, headers=headers, cookies=cookies, content=content, data=data, json_data=json, timeout=timeout)