"""
Type stubs for cycronet package
"""

from typing import Dict, List, Tuple, Optional, Union, Any, Iterator
from dataclasses import dataclass

HeadersType = Union[Dict[str, str], List[Tuple[str, str]]]
CookiesType = Dict[str, str]
DataType = Union[str, bytes, Dict[str, Any], None]

class Cookie:
    """单个 Cookie 对象"""
    name: str
    value: str
    domain: str
    path: str

    def __init__(self, name: str, value: str, domain: str = "", path: str = "/") -> None: ...
    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...

class CookieJar:
    """Cookie Jar 管理器 - 类似 requests.cookies.RequestsCookieJar"""

    def __init__(self) -> None: ...
    def set(self, name: str, value: str, domain: str = "", path: str = "/") -> None: ...
    def get(self, name: str, domain: str = "") -> Optional[str]: ...
    def get_dict(self, domain: str = "") -> Dict[str, str]: ...
    def update(self, cookies: Union[Dict[str, str], 'CookieJar'], domain: str = "") -> None: ...
    def clear(self, domain: str = "") -> None: ...
    def items(self) -> Iterator[Tuple[str, str]]: ...
    def keys(self) -> Iterator[str]: ...
    def values(self) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[Cookie]: ...
    def __len__(self) -> int: ...
    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...

@dataclass
class Response:
    """HTTP 响应对象"""
    status_code: int
    _headers: Dict[str, List[str]]
    content: bytes
    url: str = ""
    _cookies: CookieJar = ...
    encoding: Optional[str] = None

    @property
    def headers(self) -> Dict[str, str]: ...
    @property
    def cookies(self) -> CookieJar: ...
    def _get_encoding(self) -> str: ...
    @property
    def text(self) -> str: ...
    def json(self) -> Any: ...
    @property
    def ok(self) -> bool: ...
    def raise_for_status(self) -> None: ...

class HTTPStatusError(Exception):
    """HTTP 状态码错误"""
    response: Response
    def __init__(self, message: str, response: Response) -> None: ...

class RequestError(Exception):
    """请求错误"""
    pass

class Session:
    """Session 对象 - 兼容 requests.Session"""

    def __init__(self, client: Any, session_id: str, verify: bool = True) -> None: ...

    @property
    def cookies(self) -> CookieJar: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Dict[str, Any]: ...

    def close(self) -> None: ...
    def __enter__(self) -> Session: ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


class AsyncSession:
    """Async Session 对象 - 支持 async/await"""

    def __init__(self, client: Any, session_id: str, verify: bool = True) -> None: ...

    @property
    def cookies(self) -> CookieJar: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Response: ...

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
    ) -> Dict[str, Any]: ...

    async def close(self) -> None: ...
    async def __aenter__(self) -> AsyncSession: ...
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


def _load_tls_profile(chrometls: Optional[str] = None) -> Optional[Dict[str, List[str]]]: ...


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
    """
    ...


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
    """
    ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

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
    chrometls: Optional[str] = None
) -> Response: ...

def upload_file(
    url: str,
    file_path: str,
    *,
    field_name: str = "file",
    additional_fields: Optional[Dict[str, str]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True
) -> Response: ...

def download_file(
    url: str,
    save_path: str,
    *,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    chunk_size: int = 8192
) -> Dict[str, Any]: ...


# 异步模块级别函数
async def async_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_post(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_put(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_delete(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_patch(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    data: DataType = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_head(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_options(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True
) -> Response: ...

async def async_upload_file(
    url: str,
    file_path: str,
    *,
    field_name: str = "file",
    additional_fields: Optional[Dict[str, str]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True
) -> Response: ...

async def async_download_file(
    url: str,
    save_path: str,
    *,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    chunk_size: int = 8192
) -> Dict[str, Any]: ...


__all__: List[str]
