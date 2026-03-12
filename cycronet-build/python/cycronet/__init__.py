"""
Cycronet - Python Client for Cronet-Cloak

使用方式:
    import cycronet

    # 同步模式 - 模块级函数
    response = cycronet.get("https://example.com", verify=False)

    # 同步模式 - Session
    session = cycronet.CronetClient(verify=False)
    response = session.get("https://example.com")

    # 异步模式 - 模块级函数
    import asyncio
    response = await cycronet.async_get("https://example.com", verify=False)

    # 异步模式 - AsyncSession
    async with cycronet.AsyncCronetClient(verify=False) as session:
        response = await session.get("https://example.com")

    # 使用代理
    session = cycronet.CronetClient(
        verify=False,
        proxies={"https": "http://127.0.0.1:8080"}
    )

    # Response 对象
    print(response.status_code)
    print(response.text)
    print(response.json())
"""

import os
import sys
import json as json_lib
from typing import Optional, Union, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlencode

# macOS dylib 加载 - 预加载 libcronet.dylib
if sys.platform == "darwin":
    package_dir = os.path.dirname(__file__)
    # 查找 libcronet.*.dylib 文件
    import glob
    dylib_pattern = os.path.join(package_dir, "libcronet.*.dylib")
    dylib_files = glob.glob(dylib_pattern)

    if dylib_files:
        # 使用 ctypes 预加载 libcronet.dylib
        import ctypes
        try:
            # RTLD_GLOBAL 使库对后续加载的模块可见
            ctypes.CDLL(dylib_files[0], mode=ctypes.RTLD_GLOBAL)
        except Exception as e:
            # 如果失败，尝试设置 DYLD_LIBRARY_PATH（需要重启进程才生效）
            import warnings
            warnings.warn(
                f"Failed to preload libcronet.dylib: {e}. "
                f"You may need to set DYLD_LIBRARY_PATH={package_dir}",
                RuntimeWarning
            )

# Linux SO 加载 - 预加载所有依赖 SO 文件
if sys.platform == "linux":
    package_dir = os.path.dirname(__file__)
    import glob
    import ctypes

    # 预加载顺序很重要：先加载基础依赖，再加载 NSS，最后加载 cronet
    # 1. 先加载 NSPR (NSS 的基础依赖)
    for lib_name in ['libnspr4.so', 'libplc4.so', 'libplds4.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 2. 加载 NSS 工具库
    for lib_name in ['libnssutil3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 3. 加载 NSS 加密库
    for lib_name in ['libfreebl3.so', 'libfreeblpriv3.so', 'libsoftokn3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 4. 加载 NSS 主库
    for lib_name in ['libnss3.so', 'libnssdbm3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 5. 最后加载 libcronet.so
    so_pattern = os.path.join(package_dir, "libcronet.*.so")
    so_files = glob.glob(so_pattern)
    if so_files:
        try:
            ctypes.CDLL(so_files[0], mode=ctypes.RTLD_GLOBAL)
        except Exception:
            pass

# Windows DLL 加载
if sys.platform == "win32":
    # 首先尝试从包目录加载 DLL
    package_dir = os.path.dirname(__file__)

    # 查找 cronet.*.dll 文件
    import glob
    dll_pattern = os.path.join(package_dir, "cronet.*.dll")
    dll_files = glob.glob(dll_pattern)

    if dll_files:
        # 使用版本化的 DLL（cronet.144.0.7506.0.dll）
        # 注意：PYD 文件直接依赖版本化的 DLL 名称
        versioned_dll = dll_files[0]

        # 添加包目录到 PATH（必须在 add_dll_directory 之前）
        os.environ['PATH'] = package_dir + os.pathsep + os.environ.get('PATH', '')

        # 添加包目录到 DLL 搜索路径
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(package_dir)

        # 预加载版本化的 DLL（Python 3.8+ 需要显式加载）
        import ctypes
        import ctypes.wintypes

        try:
            # 使用 LoadLibraryEx with LOAD_WITH_ALTERED_SEARCH_PATH
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

            # 加载版本化的 DLL（PYD 依赖这个名称）
            handle = kernel32.LoadLibraryExW(
                versioned_dll,
                None,
                LOAD_WITH_ALTERED_SEARCH_PATH
            )

            if not handle:
                # 如果 LoadLibraryExW 失败，尝试 ctypes.CDLL 作为备用
                ctypes.CDLL(versioned_dll)
        except Exception as e:
            import warnings
            warnings.warn(
                f"Failed to preload {os.path.basename(versioned_dll)}: {e}",
                RuntimeWarning
            )
    else:
        # 回退到旧的 cronet-bin 路径查找
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "cronet-bin"),  # 包内
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "cronet-bin"),  # site-packages/cronet-bin
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cronet-bin"),  # 上一级
            os.path.join(os.getcwd(), "cronet-bin"),  # 当前目录
        ]

        dll_loaded = False
        for path in possible_paths:
            dll_path = os.path.join(path, "cronet.dll")
            if os.path.exists(dll_path):
                if hasattr(os, 'add_dll_directory'):
                    os.add_dll_directory(path)
                else:
                    os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
                dll_loaded = False
                break

        if not dll_loaded:
            # 尝试从环境变量或系统路径加载
            pass

try:
    from .cronet_cloak import PyCronetClient
except ImportError as e:
    # 如果导入失败，提供简单的错误信息
    if sys.platform == "linux" and "libcronet" in str(e):
        package_dir = os.path.dirname(__file__)
        raise ImportError(
            f"Failed to load libcronet.so: {e}\n\n"
            f"Quick fix: Run this command before starting Python:\n"
            f"  export LD_LIBRARY_PATH={package_dir}:$LD_LIBRARY_PATH\n\n"
            f"See LINUX_INSTALL_GUIDE.md for more solutions."
        ) from e
    else:
        raise


# 浏览器默认 headers 顺序
BROWSER_HEADER_ORDER = [
    "host", "connection", "cache-control", "sec-ch-ua", "sec-ch-ua-mobile",
    "sec-ch-ua-platform", "upgrade-insecure-requests", "user-agent", "accept",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-user", "sec-fetch-dest",
    "referer", "accept-encoding", "accept-language", "cookie", "priority",
]


def _sort_headers_dict(headers_dict: Dict[str, str]) -> List[Tuple[str, str]]:
    """将字典 headers 按浏览器顺序排序"""
    header_dict_lower = {k.lower(): (k, v) for k, v in headers_dict.items()}
    sorted_headers = []

    for key in BROWSER_HEADER_ORDER:
        if key in header_dict_lower:
            sorted_headers.append(header_dict_lower[key])
            del header_dict_lower[key]

    for original_key, value in header_dict_lower.values():
        sorted_headers.append((original_key, value))

    return sorted_headers


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def _parse_set_cookie(set_cookie_values: List[str]) -> List[Tuple[str, str, str]]:
    cookies = []
    for value in set_cookie_values:
        if '=' in value:
            parts = value.split(';')
            cookie_part = parts[0].strip()
            if '=' in cookie_part:
                name, val = cookie_part.split('=', 1)
                name = name.strip()
                val = val.strip()
                domain = ""
                for part in parts[1:]:
                    part = part.strip()
                    if part.lower().startswith('domain='):
                        domain = part.split('=', 1)[1].strip().lower()
                        if domain.startswith('.'):
                            domain = domain[1:]
                        break
                cookies.append((name, val, domain))
    return cookies


def _domain_matches(cookie_domain: str, request_domain: str) -> bool:
    if not cookie_domain:
        return False
    request_domain = request_domain.lower()
    cookie_domain = cookie_domain.lower()
    if request_domain == cookie_domain:
        return True
    if request_domain.endswith('.' + cookie_domain):
        return True
    return False


class Cookie:
    """单个 Cookie 对象 - 类似 http.cookiejar.Cookie"""
    def __init__(self, name: str, value: str, domain: str = "", path: str = "/"):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path

    def __repr__(self):
        return f"<Cookie {self.name}={self.value} for {self.domain}{self.path}>"

    def __str__(self):
        return f"{self.name}={self.value}"


class CookieJar:
    """Cookie Jar 管理器 - 类似 requests.cookies.RequestsCookieJar"""
    def __init__(self):
        # 存储结构: {domain: {name: Cookie}}
        self._cookies: Dict[str, Dict[str, Cookie]] = {}

    def set(self, name: str, value: str, domain: str = "", path: str = "/"):
        """设置 cookie"""
        if domain not in self._cookies:
            self._cookies[domain] = {}
        self._cookies[domain][name] = Cookie(name, value, domain, path)

    def get(self, name: str, domain: str = "") -> Optional[str]:
        """获取 cookie 值"""
        if domain in self._cookies and name in self._cookies[domain]:
            return self._cookies[domain][name].value
        # 如果没有指定 domain，搜索所有 domain
        if not domain:
            for domain_cookies in self._cookies.values():
                if name in domain_cookies:
                    return domain_cookies[name].value
        return None

    def get_dict(self, domain: str = "") -> Dict[str, str]:
        """获取 cookies 字典"""
        if domain:
            if domain in self._cookies:
                return {name: cookie.value for name, cookie in self._cookies[domain].items()}
            return {}
        # 返回所有 cookies
        result = {}
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                result[name] = cookie.value
        return result

    def update(self, cookies: Union[Dict[str, str], 'CookieJar'], domain: str = ""):
        """更新 cookies"""
        if isinstance(cookies, CookieJar):
            for d, domain_cookies in cookies._cookies.items():
                for name, cookie in domain_cookies.items():
                    self.set(name, cookie.value, cookie.domain, cookie.path)
        elif isinstance(cookies, dict):
            for name, value in cookies.items():
                self.set(name, value, domain)

    def clear(self, domain: str = ""):
        """清除 cookies"""
        if domain:
            if domain in self._cookies:
                del self._cookies[domain]
        else:
            self._cookies.clear()

    def items(self):
        """返回所有 (name, value) 对"""
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                yield (name, cookie.value)

    def keys(self):
        """返回所有 cookie 名称"""
        for domain_cookies in self._cookies.values():
            for name in domain_cookies.keys():
                yield name

    def values(self):
        """返回所有 cookie 值"""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie.value

    def __iter__(self):
        """迭代所有 Cookie 对象"""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie

    def __len__(self):
        """返回 cookie 总数"""
        return sum(len(domain_cookies) for domain_cookies in self._cookies.values())

    def __repr__(self):
        """返回类似 RequestsCookieJar 的表示"""
        cookies_list = list(self)
        if not cookies_list:
            return "<CookieJar[]>"
        cookies_repr = ", ".join(repr(cookie) for cookie in cookies_list)
        return f"<CookieJar[{cookies_repr}]>"

    def __str__(self):
        return self.__repr__()


@dataclass
class Response:
    """HTTP 响应对象 - 兼容 requests.Response"""
    status_code: int
    _headers: Dict[str, List[str]]
    content: bytes
    url: str = ""
    _cookies: CookieJar = field(default_factory=CookieJar)
    encoding: Optional[str] = None

    @property
    def headers(self) -> Dict[str, str]:
        """返回 headers 字典（取第一个值）"""
        return {k: v[0] if v else "" for k, v in self._headers.items()}

    @property
    def cookies(self) -> CookieJar:
        """返回响应 cookies (CookieJar 对象)"""
        return self._cookies

    def _get_encoding(self) -> str:
        """获取响应编码"""
        if self.encoding:
            return self.encoding

        # 尝试从 Content-Type header 中获取编码
        content_type = self.headers.get('content-type', '').lower()
        if 'charset=' in content_type:
            try:
                charset = content_type.split('charset=')[1].split(';')[0].strip()
                return charset
            except:
                pass

        # 默认使用 utf-8
        return 'utf-8'

    @property
    def text(self) -> str:
        """返回响应文本"""
        encoding = self._get_encoding()
        return self.content.decode(encoding, errors='replace')

    def json(self) -> Any:
        """解析 JSON 响应"""
        return json_lib.loads(self.text)

    @property
    def ok(self) -> bool:
        """状态码是否表示成功"""
        return 200 <= self.status_code < 400

    def raise_for_status(self):
        """如果状态码表示错误则抛出异常"""
        if self.status_code >= 400:
            raise HTTPStatusError(f"{self.status_code} Error", response=self)


class HTTPStatusError(Exception):
    """HTTP 状态码错误"""
    def __init__(self, message: str, response: Response):
        super().__init__(message)
        self.response = response


class RequestError(Exception):
    """请求错误"""
    pass


HeadersType = Union[Dict[str, str], List[Tuple[str, str]]]
CookiesType = Dict[str, str]
DataType = Union[str, bytes, Dict[str, Any], None]


class Session:
    """Session 对象 - 兼容 requests.Session"""

    def __init__(self, client: 'CronetClient', session_id: str, verify: bool = True):
        self._client = client
        self._session_id = session_id
        self._closed = False
        self._verify = verify
        self._cookies = CookieJar()

    @property
    def cookies(self) -> CookieJar:
        """获取当前会话的 CookieJar"""
        return self._cookies

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = ""
    ) -> List[Tuple[str, str]]:
        """准备请求头"""
        if headers is None:
            headers_list = []
        elif isinstance(headers, dict):
            # Python 3.7+ 字典保持插入顺序，直接转换为列表
            headers_list = list(headers.items())
        else:
            # 列表保持原有顺序
            headers_list = list(headers)

        normal_headers = []
        priority_headers = []
        cookie_headers = []

        for k, v in headers_list:
            k_lower = k.lower()
            if k_lower == 'cookie':
                cookie_headers.append((k, v))
            elif k_lower == 'priority':
                priority_headers.append((k, v))
            else:
                normal_headers.append((k, v))

        # 从 CookieJar 中获取匹配的 cookies
        merged_cookies = {}
        for cookie in self._cookies:
            if not cookie.domain or cookie.domain == domain or _domain_matches(cookie.domain, domain):
                merged_cookies[cookie.name] = cookie.value

        if cookies:
            merged_cookies.update(cookies)

        result = normal_headers

        if not cookie_headers and merged_cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in merged_cookies.items()])
            result.append(("cookie", cookie_str))
        elif cookie_headers:
            result.extend(cookie_headers)

        result.extend(priority_headers)
        return result

    def _update_cookies_from_response(self, headers: Dict[str, List[str]], request_domain: str):
        """从响应头中提取 Set-Cookie"""
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = _parse_set_cookie(values)
                for cookie_name, cookie_value, cookie_domain in parsed_cookies:
                    store_domain = cookie_domain if cookie_domain else request_domain
                    self._cookies.set(cookie_name, cookie_value, store_domain)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 HTTP 请求 - 兼容 requests.request()"""
        if self._closed:
            raise RequestError("Session is closed")

        # 验证 URL
        if not url or not isinstance(url, str):
            raise RequestError("URL must be a non-empty string")

        # 验证 URL 格式
        parsed = urlparse(url)
        if not parsed.scheme:
            raise RequestError(f"Invalid URL '{url}': No schema supplied. Perhaps you meant http://{url}?")
        if parsed.scheme not in ('http', 'https'):
            raise RequestError(f"Invalid URL '{url}': Unsupported schema '{parsed.scheme}'. Only http and https are supported.")
        if not parsed.netloc:
            raise RequestError(f"Invalid URL '{url}': No host supplied")

        # verify 参数在这里被忽略（由 session 创建时决定）
        # 但接受它以兼容 requests API

        if params:
            url = url + ('&' if '?' in url else '?') + urlencode(params)

        domain = _extract_domain(url)

        if cookies:
            self._cookies.update(cookies, domain)

        if headers is None:
            headers_to_prepare = None
        elif isinstance(headers, dict):
            headers_to_prepare = headers.copy()
        else:
            headers_to_prepare = list(headers)

        # 处理 json 参数
        if json is not None:
            data = json
            if isinstance(headers_to_prepare, dict):
                if 'content-type' not in {k.lower() for k in headers_to_prepare.keys()}:
                    headers_to_prepare['content-type'] = 'application/json'
            elif isinstance(headers_to_prepare, list):
                if not any(k.lower() == 'content-type' for k, v in headers_to_prepare):
                    headers_to_prepare.append(('content-type', 'application/json'))
            else:
                headers_to_prepare = [('content-type', 'application/json')]

        # 处理 data 参数
        elif data is not None:
            if isinstance(data, dict):
                data = urlencode(data)
                if isinstance(headers_to_prepare, dict):
                    if 'content-type' not in {k.lower() for k in headers_to_prepare.keys()}:
                        headers_to_prepare['content-type'] = 'application/x-www-form-urlencoded'
                elif isinstance(headers_to_prepare, list):
                    if not any(k.lower() == 'content-type' for k, v in headers_to_prepare):
                        headers_to_prepare.append(('content-type', 'application/x-www-form-urlencoded'))
                else:
                    headers_to_prepare = [('content-type', 'application/x-www-form-urlencoded')]

        # 准备请求体
        if data is None:
            body = b""
        elif isinstance(data, dict):
            body = json_lib.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data

        # 准备 headers
        prepared_headers = self._prepare_headers(headers_to_prepare, cookies, domain)

        # 调用底层 Rust 函数
        response_dict = self._client._client.request(
            self._session_id,
            url,
            method.upper(),
            prepared_headers,
            body,
            allow_redirects
        )

        status_code = response_dict['status_code']
        resp_headers_list = response_dict['headers']
        body_bytes = response_dict['body']

        resp_headers = {}
        for name, value in resp_headers_list:
            if name not in resp_headers:
                resp_headers[name] = []
            resp_headers[name].append(value)

        # 创建响应的 CookieJar
        response_cookies = CookieJar()
        for header_name, values in resp_headers.items():
            if header_name.lower() == 'set-cookie':
                for cookie_name, cookie_value, cookie_domain in _parse_set_cookie(values):
                    store_domain = cookie_domain if cookie_domain else domain
                    response_cookies.set(cookie_name, cookie_value, store_domain)

        self._update_cookies_from_response(resp_headers, domain)

        return Response(
            status_code=status_code,
            _headers=resp_headers,
            content=body_bytes,
            url=url,
            _cookies=response_cookies
        )

    def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 GET 请求

        Args:
            url: 请求 URL
            params: URL 参数
            headers: 请求头
            cookies: Cookies
            timeout: 超时时间（秒）
            verify: 是否验证 SSL 证书（会被忽略，由 session 创建时决定）
            allow_redirects: 是否允许重定向
        """
        return self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def post(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 POST 请求

        Args:
            url: 请求 URL
            params: URL 参数
            headers: 请求头
            cookies: Cookies
            data: 请求体数据
            json: JSON 数据
            timeout: 超时时间（秒）
            verify: 是否验证 SSL 证书（会被忽略，由 session 创建时决定）
            allow_redirects: 是否允许重定向
        """
        return self.request(
            "POST",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def put(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 PUT 请求"""
        return self.request(
            "PUT",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def delete(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 DELETE 请求"""
        return self.request(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def patch(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 PATCH 请求"""
        return self.request(
            "PATCH",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def head(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 HEAD 请求"""
        return self.request(
            "HEAD",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def options(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送 OPTIONS 请求"""
        return self.request(
            "OPTIONS",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects
        )

    def upload_file(
        self,
        url: str,
        file_path: str,
        *,
        field_name: str = "file",
        additional_fields: Optional[Dict[str, str]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None
    ) -> Response:
        """上传文件

        Args:
            url: 上传 URL
            file_path: 文件路径
            field_name: 表单字段名（默认 "file"）
            additional_fields: 额外的表单字段
            headers: 请求头
            cookies: Cookies
            timeout: 超时时间
            verify: 是否验证 SSL 证书

        Returns:
            Response 对象

        Example:
            session.upload_file(
                'https://example.com/upload',
                '/path/to/file.txt',
                field_name='document',
                additional_fields={'description': 'My file'}
            )
        """
        import mimetypes

        # 读取文件
        if not os.path.exists(file_path):
            raise RequestError(f"File not found: {file_path}")

        with open(file_path, 'rb') as f:
            file_content = f.read()

        # 获取文件名和 MIME 类型
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        # 构建 multipart/form-data
        boundary = f'----CycronetFormBoundary{os.urandom(16).hex()}'
        body_parts = []

        # 添加额外字段
        if additional_fields:
            for key, value in additional_fields.items():
                body_parts.append(f'--{boundary}\r\n'.encode())
                body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body_parts.append(f'{value}\r\n'.encode())

        # 添加文件
        body_parts.append(f'--{boundary}\r\n'.encode())
        body_parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        body_parts.append(f'Content-Type: {mime_type}\r\n\r\n'.encode())
        body_parts.append(file_content)
        body_parts.append(b'\r\n')
        body_parts.append(f'--{boundary}--\r\n'.encode())

        # 合并 body
        body = b''.join(body_parts)

        # 设置 Content-Type
        if headers is None:
            headers = {}
        elif isinstance(headers, list):
            headers = dict(headers)
        else:
            headers = dict(headers)

        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'

        # 发送请求
        return self.request(
            "POST",
            url,
            headers=headers,
            cookies=cookies,
            data=body,
            timeout=timeout,
            verify=verify
        )

    def download_file(
        self,
        url: str,
        save_path: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        chunk_size: int = 8192
    ) -> Dict[str, Any]:
        """下载文件

        Args:
            url: 下载 URL
            save_path: 保存路径
            headers: 请求头
            cookies: Cookies
            timeout: 超时时间
            verify: 是否验证 SSL 证书
            chunk_size: 分块大小（字节）

        Returns:
            下载信息字典，包含：
            - file_path: 保存路径
            - size: 文件大小（字节）
            - status_code: HTTP 状态码

        Example:
            info = session.download_file(
                'https://example.com/file.zip',
                '/path/to/save/file.zip'
            )
            print(f"Downloaded {info['size']} bytes")
        """
        # 发送请求
        response = self.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify
        )

        # 检查状态码
        if response.status_code >= 400:
            raise HTTPStatusError(
                f"Download failed with status {response.status_code}",
                response=response
            )

        # 创建目录（如果不存在）
        save_dir = os.path.dirname(save_path)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 保存文件
        with open(save_path, 'wb') as f:
            f.write(response.content)

        return {
            'file_path': save_path,
            'size': len(response.content),
            'status_code': response.status_code,
            'headers': response.headers
        }

    def close(self):
        """关闭会话"""
        if not self._closed:
            self._client._client.close_session(self._session_id)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _load_tls_profile(chrometls: Optional[str] = None) -> Optional[Dict[str, List[str]]]:
    """加载 TLS 指纹配置（仅从包内 tls_profiles.json）"""
    if chrometls is None:
        return None

    config_path = os.path.join(os.path.dirname(__file__), "tls_profiles.json")
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            profiles = json_lib.load(f)
            if chrometls in profiles:
                profile = profiles[chrometls]
                return {
                    "cipher_suites": profile.get('cipher_suites', []) or [],
                    "tls_curves": profile.get('tls_curves', []) or [],
                    "tls_extensions": profile.get('tls_extensions', []) or [],
                }
    except Exception:
        pass

    return None


def _validate_proxy_url(proxy_url: str) -> None:
    """验证代理 URL 格式"""
    if not proxy_url or not isinstance(proxy_url, str):
        raise RequestError("Proxy URL must be a non-empty string")

    # 解析代理 URL
    try:
        parsed = urlparse(proxy_url)
    except ValueError as e:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': {e}")

    # 检查 scheme
    if not parsed.scheme:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': No schema supplied")

    # 支持的代理协议
    supported_schemes = ('http', 'https', 'socks5')
    if parsed.scheme not in supported_schemes:
        raise RequestError(
            f"Invalid proxy URL '{proxy_url}': Unsupported schema '{parsed.scheme}'. "
            f"Supported schemas: {', '.join(supported_schemes)}"
        )

    # 检查 host
    if not parsed.netloc:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': No host supplied")

    # 检查端口（如果提供了）
    try:
        if parsed.port is not None:
            if not (1 <= parsed.port <= 65535):
                raise RequestError(f"Invalid proxy URL '{proxy_url}': Port must be between 1 and 65535")
    except ValueError as e:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': {e}")



def CronetClient(
    verify: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    timeout_ms: int = 30000,
    chrometls: Optional[str] = "chrome_144"
) -> Session:
    """
    创建 Cronet Session - 类似 requests.Session()

    Args:
        verify: 是否验证 SSL 证书（False 跳过验证）
        proxies: 代理配置，支持字典格式 {"https": "http://127.0.0.1:8080"} 或字符串
        timeout_ms: 超时时间（毫秒）
        chrometls: TLS 指纹配置名称（如 "chrome_144"）

    Returns:
        Session 对象

    Example:
        session = CronetClient(verify=False)
        session = CronetClient(proxies={"https": "http://127.0.0.1:8080"})
        session = CronetClient(verify=False, chrometls="chrome_144")
        response = session.get("https://example.com")
    """
    # 处理 proxies 参数
    proxy_rules = None
    if proxies:
        if isinstance(proxies, dict):
            # 从字典中提取代理 URL (优先使用 https，然后 http)
            proxy_rules = proxies.get('https') or proxies.get('http') or proxies.get('all')
        else:
            proxy_rules = proxies

        # 验证代理 URL
        if proxy_rules:
            _validate_proxy_url(proxy_rules)

    # 加载 TLS 指纹配置
    tls_profile = _load_tls_profile(chrometls)
    cipher_suites = tls_profile.get("cipher_suites", []) if tls_profile else None
    tls_curves = tls_profile.get("tls_curves", []) if tls_profile else None
    tls_extensions = tls_profile.get("tls_extensions", []) if tls_profile else None

    client = PyCronetClient()
    session_id = client.create_session(
        proxy_rules,
        not verify,  # skip_cert_verify = not verify
        timeout_ms,
        cipher_suites,
        tls_curves,
        tls_extensions
    )

    # 创建一个包装的 Session，保存 client 引用
    class _ClientWrapper:
        def __init__(self, client):
            self._client = client

    wrapper = _ClientWrapper(client)
    return Session(wrapper, session_id, verify)


# 模块级别的便捷函数
def get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 GET 请求 - 类似 requests.get()

    Args:
        url: 请求 URL
        params: URL 参数
        headers: 请求头
        cookies: Cookies
        timeout: 超时时间（秒），会转换为 timeout_ms
        verify: 是否验证 SSL 证书
        allow_redirects: 是否允许重定向
        proxies: 代理设置
        chrometls: TLS 指纹配置名称（如 "chrome_144"）
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def post(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 POST 请求 - 类似 requests.post()

    Args:
        url: 请求 URL
        params: URL 参数
        headers: 请求头
        cookies: Cookies
        data: 请求体数据
        json: JSON 数据
        timeout: 超时时间（秒），会转换为 timeout_ms
        verify: 是否验证 SSL 证书
        allow_redirects: 是否允许重定向
        proxies: 代理设置
        chrometls: TLS 指纹配置名称（如 "chrome_144"）
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.post(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def put(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 PUT 请求 - 类似 requests.put()

    Args:
        timeout: 超时时间（秒），会转换为 timeout_ms
        proxies: 代理设置
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.put(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def delete(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 DELETE 请求 - 类似 requests.delete()

    Args:
        timeout: 超时时间（秒），会转换为 timeout_ms
        proxies: 代理设置
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.delete(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def patch(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 PATCH 请求 - 类似 requests.patch()

    Args:
        timeout: 超时时间（秒），会转换为 timeout_ms
        proxies: 代理设置
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.patch(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            data=data,
            json=json,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def head(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 HEAD 请求 - 类似 requests.head()

    Args:
        timeout: 超时时间（秒），会转换为 timeout_ms
        proxies: 代理设置
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.head(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def options(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_144",
    **kwargs
) -> Response:
    """发送 OPTIONS 请求 - 类似 requests.options()

    Args:
        timeout: 超时时间（秒），会转换为 timeout_ms
        proxies: 代理设置
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls) as session:
        return session.options(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            verify=verify,
            allow_redirects=allow_redirects,
            **kwargs
        )


def upload_file(
    url: str,
    file_path: str,
    *,
    field_name: str = "file",
    additional_fields: Optional[Dict[str, str]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    **kwargs: Any
) -> Response:
    """上传文件 - 类似 requests 的文件上传

    Args:
        url: 上传 URL
        file_path: 文件路径
        field_name: 表单字段名（默认 "file"）
        additional_fields: 额外的表单字段
        headers: 请求头
        cookies: Cookies
        timeout: 超时时间（秒），会转换为 timeout_ms
        verify: 是否验证 SSL 证书
        **kwargs: 其他参数

    Returns:
        Response 对象

    Example:
        response = cycronet.upload_file(
            'https://example.com/upload',
            '/path/to/file.txt',
            field_name='document',
            additional_fields={'description': 'My file'},
            verify=False
        )
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return session.upload_file(
            url,
            file_path,
            field_name=field_name,
            additional_fields=additional_fields,
            headers=headers,
            cookies=cookies,
            verify=verify
        )


def download_file(
    url: str,
    save_path: str,
    *,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    chunk_size: int = 8192,
    **kwargs: Any
) -> Dict[str, Any]:
    """下载文件 - 类似 requests 的文件下载

    Args:
        url: 下载 URL
        save_path: 保存路径
        headers: 请求头
        cookies: Cookies
        timeout: 超时时间（秒），会转换为 timeout_ms
        verify: 是否验证 SSL 证书
        chunk_size: 分块大小（字节）
        **kwargs: 其他参数

    Returns:
        下载信息字典，包含：
        - file_path: 保存路径
        - size: 文件大小（字节）
        - status_code: HTTP 状态码
        - headers: 响应头

    Example:
        info = cycronet.download_file(
            'https://example.com/file.zip',
            '/path/to/save/file.zip',
            verify=False
        )
        print(f"Downloaded {info['size']} bytes")
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    with CronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return session.download_file(
            url,
            save_path,
            headers=headers,
            cookies=cookies,
            verify=verify,
            chunk_size=chunk_size
        )


__all__ = ["CronetClient", "Session", "Response", "HTTPStatusError", "RequestError",
           "Cookie", "CookieJar",
           "get", "post", "put", "delete", "patch", "head", "options",
           "upload_file", "download_file",
           "AsyncCronetClient", "AsyncSession",
           "async_get", "async_post", "async_put", "async_delete", "async_patch",
           "async_head", "async_options", "async_upload_file", "async_download_file"]


# ============================================================================
# Async Support
# ============================================================================

class AsyncSession:
    """Async Session 对象 - 支持 async/await"""

    def __init__(self, client: 'AsyncCronetClient', session_id: str, verify: bool = True):
        self._client = client
        self._session_id = session_id
        self._closed = False
        self._verify = verify
        self._cookies = CookieJar()

    @property
    def cookies(self) -> CookieJar:
        """获取当前会话的 CookieJar"""
        return self._cookies

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = ""
    ) -> List[Tuple[str, str]]:
        """准备请求头"""
        if headers is None:
            headers_list = []
        elif isinstance(headers, dict):
            # Python 3.7+ 字典保持插入顺序，直接转换为列表
            headers_list = list(headers.items())
        else:
            headers_list = list(headers)

        normal_headers = []
        priority_headers = []
        cookie_headers = []

        for k, v in headers_list:
            k_lower = k.lower()
            if k_lower == 'cookie':
                cookie_headers.append((k, v))
            elif k_lower == 'priority':
                priority_headers.append((k, v))
            else:
                normal_headers.append((k, v))

        # 从 CookieJar 中获取匹配的 cookies
        merged_cookies = {}
        for cookie in self._cookies:
            if not cookie.domain or cookie.domain == domain or _domain_matches(cookie.domain, domain):
                merged_cookies[cookie.name] = cookie.value

        if cookies:
            merged_cookies.update(cookies)

        result = normal_headers

        if not cookie_headers and merged_cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in merged_cookies.items()])
            result.append(("cookie", cookie_str))
        elif cookie_headers:
            result.extend(cookie_headers)

        result.extend(priority_headers)
        return result

    def _update_cookies_from_response(self, headers: Dict[str, List[str]], request_domain: str):
        """从响应头中提取 Set-Cookie"""
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = _parse_set_cookie(values)
                for cookie_name, cookie_value, cookie_domain in parsed_cookies:
                    store_domain = cookie_domain if cookie_domain else request_domain
                    self._cookies.set(cookie_name, cookie_value, store_domain)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 HTTP 请求"""
        if self._closed:
            raise RequestError("Session is closed")

        # 验证 URL
        if not url or not isinstance(url, str):
            raise RequestError("URL must be a non-empty string")

        # 验证 URL 格式
        parsed = urlparse(url)
        if not parsed.scheme:
            raise RequestError(f"Invalid URL '{url}': No schema supplied. Perhaps you meant http://{url}?")
        if parsed.scheme not in ('http', 'https'):
            raise RequestError(f"Invalid URL '{url}': Unsupported schema '{parsed.scheme}'. Only http and https are supported.")
        if not parsed.netloc:
            raise RequestError(f"Invalid URL '{url}': No host supplied")

        if params:
            url = url + ('&' if '?' in url else '?') + urlencode(params)

        domain = _extract_domain(url)

        if cookies:
            self._cookies.update(cookies, domain)

        if headers is None:
            headers_to_prepare = None
        elif isinstance(headers, dict):
            headers_to_prepare = headers.copy()
        else:
            headers_to_prepare = list(headers)

        # 处理 json 参数
        if json is not None:
            data = json
            if isinstance(headers_to_prepare, dict):
                if 'content-type' not in {k.lower() for k in headers_to_prepare.keys()}:
                    headers_to_prepare['content-type'] = 'application/json'
            elif isinstance(headers_to_prepare, list):
                if not any(k.lower() == 'content-type' for k, v in headers_to_prepare):
                    headers_to_prepare.append(('content-type', 'application/json'))
            else:
                headers_to_prepare = [('content-type', 'application/json')]

        # 处理 data 参数
        elif data is not None:
            if isinstance(data, dict):
                data = urlencode(data)
                if isinstance(headers_to_prepare, dict):
                    if 'content-type' not in {k.lower() for k in headers_to_prepare.keys()}:
                        headers_to_prepare['content-type'] = 'application/x-www-form-urlencoded'
                elif isinstance(headers_to_prepare, list):
                    if not any(k.lower() == 'content-type' for k, v in headers_to_prepare):
                        headers_to_prepare.append(('content-type', 'application/x-www-form-urlencoded'))
                else:
                    headers_to_prepare = [('content-type', 'application/x-www-form-urlencoded')]

        # 准备请求体
        if data is None:
            body = b""
        elif isinstance(data, dict):
            body = json_lib.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data

        # 准备 headers
        prepared_headers = self._prepare_headers(headers_to_prepare, cookies, domain)

        # 使用 run_in_executor 在线程池中执行同步请求
        # 避免 pyo3-asyncio 的兼容性问题
        import asyncio
        loop = asyncio.get_event_loop()
        response_dict = await loop.run_in_executor(
            None,
            lambda: self._client._client.request(
                self._session_id,
                url,
                method.upper(),
                prepared_headers,
                body,
                allow_redirects
            )
        )

        status_code = response_dict['status_code']
        resp_headers_list = response_dict['headers']
        body_bytes = response_dict['body']

        resp_headers = {}
        for name, value in resp_headers_list:
            if name not in resp_headers:
                resp_headers[name] = []
            resp_headers[name].append(value)

        # 创建响应的 CookieJar
        response_cookies = CookieJar()
        for header_name, values in resp_headers.items():
            if header_name.lower() == 'set-cookie':
                for cookie_name, cookie_value, cookie_domain in _parse_set_cookie(values):
                    store_domain = cookie_domain if cookie_domain else domain
                    response_cookies.set(cookie_name, cookie_value, store_domain)

        self._update_cookies_from_response(resp_headers, domain)

        return Response(
            status_code=status_code,
            _headers=resp_headers,
            content=body_bytes,
            url=url,
            _cookies=response_cookies
        )

    async def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 GET 请求"""
        return await self.request(
            "GET", url, params=params, headers=headers, cookies=cookies,
            timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def post(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 POST 请求"""
        return await self.request(
            "POST", url, params=params, headers=headers, cookies=cookies,
            data=data, json=json, timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def put(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 PUT 请求"""
        return await self.request(
            "PUT", url, params=params, headers=headers, cookies=cookies,
            data=data, json=json, timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def delete(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 DELETE 请求"""
        return await self.request(
            "DELETE", url, params=params, headers=headers, cookies=cookies,
            timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def patch(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        data: DataType = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 PATCH 请求"""
        return await self.request(
            "PATCH", url, params=params, headers=headers, cookies=cookies,
            data=data, json=json, timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def head(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 HEAD 请求"""
        return await self.request(
            "HEAD", url, params=params, headers=headers, cookies=cookies,
            timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def options(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        allow_redirects: bool = True
    ) -> Response:
        """发送异步 OPTIONS 请求"""
        return await self.request(
            "OPTIONS", url, params=params, headers=headers, cookies=cookies,
            timeout=timeout, verify=verify, allow_redirects=allow_redirects
        )

    async def upload_file(
        self,
        url: str,
        file_path: str,
        *,
        field_name: str = "file",
        additional_fields: Optional[Dict[str, str]] = None,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None
    ) -> Response:
        """异步上传文件"""
        import mimetypes

        if not os.path.exists(file_path):
            raise RequestError(f"File not found: {file_path}")

        with open(file_path, 'rb') as f:
            file_content = f.read()

        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        boundary = f'----CycronetFormBoundary{os.urandom(16).hex()}'
        body_parts = []

        if additional_fields:
            for key, value in additional_fields.items():
                body_parts.append(f'--{boundary}\r\n'.encode())
                body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body_parts.append(f'{value}\r\n'.encode())

        body_parts.append(f'--{boundary}\r\n'.encode())
        body_parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        body_parts.append(f'Content-Type: {mime_type}\r\n\r\n'.encode())
        body_parts.append(file_content)
        body_parts.append(b'\r\n')
        body_parts.append(f'--{boundary}--\r\n'.encode())

        body = b''.join(body_parts)

        if headers is None:
            headers = {}
        elif isinstance(headers, list):
            headers = dict(headers)
        else:
            headers = dict(headers)

        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'

        return await self.request(
            "POST",
            url,
            headers=headers,
            cookies=cookies,
            data=body,
            timeout=timeout,
            verify=verify
        )

    async def download_file(
        self,
        url: str,
        save_path: str,
        *,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        timeout: Optional[float] = None,
        verify: Optional[bool] = None,
        chunk_size: int = 8192
    ) -> Dict[str, Any]:
        """异步下载文件"""
        response = await self.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify
        )

        if response.status_code >= 400:
            raise HTTPStatusError(
                f"Download failed with status {response.status_code}",
                response=response
            )

        save_dir = os.path.dirname(save_path)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        with open(save_path, 'wb') as f:
            f.write(response.content)

        return {
            'file_path': save_path,
            'size': len(response.content),
            'status_code': response.status_code,
            'headers': response.headers
        }

    async def close(self):
        """关闭会话"""
        if not self._closed:
            self._client._client.close_session(self._session_id)
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


def AsyncCronetClient(
    verify: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    timeout_ms: int = 30000,
    chrometls: Optional[str] = "chrome_144"
) -> AsyncSession:
    """
    创建异步 Cronet Session - 支持 async/await

    Args:
        verify: 是否验证 SSL 证书（False 跳过验证）
        proxies: 代理配置，支持字典格式 {"https": "http://127.0.0.1:8080"} 或字符串
        timeout_ms: 超时时间（毫秒）
        chrometls: TLS 指纹配置名称（如 "chrome_144"）

    Returns:
        AsyncSession 对象

    Example:
        async with AsyncCronetClient(verify=False) as session:
            response = await session.get("https://example.com")
        async with AsyncCronetClient(verify=False, chrometls="chrome_144") as session:
            response = await session.get("https://example.com")
    """
    proxy_rules = None
    if proxies:
        if isinstance(proxies, dict):
            proxy_rules = proxies.get('https') or proxies.get('http') or proxies.get('all')
        else:
            proxy_rules = proxies

        # 验证代理 URL
        if proxy_rules:
            _validate_proxy_url(proxy_rules)

    # 加载 TLS 指纹配置
    tls_profile = _load_tls_profile(chrometls)
    cipher_suites = tls_profile.get("cipher_suites", []) if tls_profile else None
    tls_curves = tls_profile.get("tls_curves", []) if tls_profile else None
    tls_extensions = tls_profile.get("tls_extensions", []) if tls_profile else None

    client = PyCronetClient()
    session_id = client.create_session(
        proxy_rules,
        not verify,
        timeout_ms,
        cipher_suites,
        tls_curves,
        tls_extensions
    )

    class _ClientWrapper:
        def __init__(self, client):
            self._client = client

    wrapper = _ClientWrapper(client)
    return AsyncSession(wrapper, session_id, verify)


# 异步模块级别函数
async def async_get(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 GET 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.get(url, **kwargs)


async def async_post(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 POST 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.post(url, **kwargs)


async def async_put(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 PUT 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.put(url, **kwargs)


async def async_delete(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 DELETE 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.delete(url, **kwargs)


async def async_patch(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 PATCH 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.patch(url, **kwargs)


async def async_head(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 HEAD 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.head(url, **kwargs)


async def async_options(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """异步 OPTIONS 请求

    Args:
        url: 请求 URL
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.options(url, **kwargs)


async def async_upload_file(
    url: str,
    file_path: str,
    *,
    field_name: str = "file",
    additional_fields: Optional[Dict[str, str]] = None,
    verify: bool = True,
    timeout: Optional[float] = None,
    **kwargs
) -> Response:
    """异步上传文件

    Args:
        url: 上传 URL
        file_path: 文件路径
        field_name: 表单字段名
        additional_fields: 额外的表单字段
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.upload_file(
            url,
            file_path,
            field_name=field_name,
            additional_fields=additional_fields,
            **kwargs
        )


async def async_download_file(
    url: str,
    save_path: str,
    *,
    verify: bool = True,
    timeout: Optional[float] = None,
    chunk_size: int = 8192,
    **kwargs
) -> Dict[str, Any]:
    """异步下载文件

    Args:
        url: 下载 URL
        save_path: 保存路径
        verify: 是否验证 SSL 证书
        timeout: 超时时间（秒），会转换为 timeout_ms
        chunk_size: 分块大小
        **kwargs: 其他参数
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.download_file(
            url,
            save_path,
            chunk_size=chunk_size,
            **kwargs
        )

