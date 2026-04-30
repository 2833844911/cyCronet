"""
Asynchronous module-level API functions for cycronet.
"""

from typing import Optional, Dict, Any

from ._types import HeadersType, CookiesType, DataType
from ._response import Response, StreamResponse
from ._client import AsyncCronetClient


async def _async_send(session, method, url, stream=False, **kwargs):
    """Helper to send async request, keeping session alive for streaming."""
    response = await session.request(method, url, stream=stream, **kwargs)
    if stream and isinstance(response, StreamResponse):
        response._session = session
    return response


async def async_get(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async GET request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "GET", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.get(url, **kwargs)


async def async_post(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async POST request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "POST", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.post(url, **kwargs)


async def async_put(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async PUT request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "PUT", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.put(url, **kwargs)


async def async_delete(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async DELETE request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "DELETE", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.delete(url, **kwargs)


async def async_patch(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async PATCH request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "PATCH", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.patch(url, **kwargs)


async def async_head(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async HEAD request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "HEAD", url, stream=True, **kwargs)
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.head(url, **kwargs)


async def async_options(url: str, *, verify: bool = True, timeout: Optional[float] = None, stream: bool = False, **kwargs):
    """Async OPTIONS request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    if stream:
        session = AsyncCronetClient(verify=verify, timeout_ms=timeout_ms)
        await session.__aenter__()
        return await _async_send(session, "OPTIONS", url, stream=True, **kwargs)
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
