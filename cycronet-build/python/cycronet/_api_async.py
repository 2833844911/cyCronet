"""
Asynchronous module-level API functions for cycronet.
"""

from typing import Optional, Dict, Any

from ._types import HeadersType, CookiesType, DataType
from ._response import Response
from ._client import AsyncCronetClient


async def async_get(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async GET request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.get(url, **kwargs)


async def async_post(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async POST request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.post(url, **kwargs)


async def async_put(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async PUT request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.put(url, **kwargs)


async def async_delete(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async DELETE request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.delete(url, **kwargs)


async def async_patch(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async PATCH request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.patch(url, **kwargs)


async def async_head(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async HEAD request"""
    timeout_ms = int(timeout * 1000) if timeout else 30000
    async with AsyncCronetClient(verify=verify, timeout_ms=timeout_ms) as session:
        return await session.head(url, **kwargs)


async def async_options(url: str, *, verify: bool = True, timeout: Optional[float] = None, **kwargs) -> Response:
    """Async OPTIONS request"""
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
