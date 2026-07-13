"""
Synchronous module-level API functions for cycronet.
"""

from typing import Optional, Dict, Any, Union

from ._types import HeadersType, CookiesType, DataType
from ._response import Response, StreamResponse
from ._client import CronetClient


def _send(method, url, *, stream=False, proxies=None, chrometls="chrome_150",
          timeout=None, verify=True, **kwargs):
    """Internal helper: keeps session alive when stream=True."""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    session = CronetClient(verify=verify, timeout_ms=timeout_ms, proxies=proxies, chrometls=chrometls)
    try:
        resp = getattr(session, method)(url, verify=verify, stream=stream, **kwargs)
        if stream and isinstance(resp, StreamResponse):
            resp._session = session
            return resp
        session.close()
        return resp
    except Exception:
        session.close()
        raise


def get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send GET request - similar to requests.get()"""
    return _send('get', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, allow_redirects=allow_redirects, **kwargs)


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
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send POST request - similar to requests.post()"""
    return _send('post', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, data=data, json=json,
                 allow_redirects=allow_redirects, **kwargs)


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
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send PUT request - similar to requests.put()"""
    return _send('put', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, data=data, json=json,
                 allow_redirects=allow_redirects, **kwargs)


def delete(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send DELETE request - similar to requests.delete()"""
    return _send('delete', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, allow_redirects=allow_redirects, **kwargs)


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
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send PATCH request - similar to requests.patch()"""
    return _send('patch', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, data=data, json=json,
                 allow_redirects=allow_redirects, **kwargs)


def head(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send HEAD request - similar to requests.head()"""
    return _send('head', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, allow_redirects=allow_redirects, **kwargs)


def options(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[HeadersType] = None,
    cookies: Optional[CookiesType] = None,
    timeout: Optional[float] = None,
    verify: bool = True,
    allow_redirects: bool = True,
    stream: bool = False,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    chrometls: Optional[str] = "chrome_150",
    **kwargs
):
    """Send OPTIONS request - similar to requests.options()"""
    return _send('options', url, stream=stream, proxies=proxies, chrometls=chrometls,
                 timeout=timeout, verify=verify, params=params, headers=headers,
                 cookies=cookies, allow_redirects=allow_redirects, **kwargs)


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
