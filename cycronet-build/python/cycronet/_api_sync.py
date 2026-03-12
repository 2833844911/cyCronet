"""
Synchronous module-level API functions for cycronet.
"""

from typing import Optional, Dict, Any, Union

from ._types import HeadersType, CookiesType, DataType
from ._response import Response
from ._client import CronetClient


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
    """Send GET request - similar to requests.get()"""
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
    """Send POST request - similar to requests.post()"""
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
    """Send PUT request - similar to requests.put()"""
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
    """Send DELETE request - similar to requests.delete()"""
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
    """Send PATCH request - similar to requests.patch()"""
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
    """Send HEAD request - similar to requests.head()"""
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
    """Send OPTIONS request - similar to requests.options()"""
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
    """Upload file - similar to requests file upload"""
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
    """Download file - similar to requests file download"""
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
