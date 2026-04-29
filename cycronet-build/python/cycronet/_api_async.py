"""
Asynchronous module-level API functions for cycronet.
"""

from typing import Optional, Dict, Any

from ._types import HeadersType, CookiesType, DataType
from ._response import Response, StreamResponse
from ._client import AsyncCronetClient


async def _async_send(method, url, *, stream=False, verify=True, timeout=None, **kwargs):
    """Internal helper: keeps session alive when stream=True."""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
    try:
        resp = await getattr(session, method)(url, stream=stream, **kwargs)
        if stream and isinstance(resp, StreamResponse):
            resp._session = session
            return resp
        await session.close()
        return resp
    except Exception:
        await session.close()
        raise


async def async_get(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async GET request"""
    return await _async_send('get', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_post(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async POST request"""
    return await _async_send('post', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_put(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async PUT request"""
    return await _async_send('put', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_delete(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async DELETE request"""
    return await _async_send('delete', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_patch(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async PATCH request"""
    return await _async_send('patch', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_head(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async HEAD request"""
    return await _async_send('head', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


async def async_options(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async OPTIONS request"""
    return await _async_send('options', url, stream=stream, verify=verify, timeout=timeout, **kwargs)


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
    """Async upload file"""
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
    """Async download file"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.download_file(
            url,
            save_path,
            chunk_size=chunk_size,
            **kwargs
        )
