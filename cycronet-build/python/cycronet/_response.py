"""
Response and exception classes for cycronet.
"""

import json as json_lib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from ._cookies import CookieJar


@dataclass
class Response:
    """HTTP response object - compatible with requests.Response"""
    status_code: int
    _headers: Dict[str, List[str]]
    content: bytes
    url: str = ""
    _cookies: CookieJar = field(default_factory=CookieJar)
    encoding: Optional[str] = None

    @property
    def headers(self) -> Dict[str, str]:
        """Return headers dictionary (take first value)"""
        return {k: v[0] if v else "" for k, v in self._headers.items()}

    @property
    def cookies(self) -> CookieJar:
        """Return response cookies (CookieJar object)"""
        return self._cookies

    def _get_encoding(self) -> str:
        """Get response encoding"""
        if self.encoding:
            return self.encoding

        # Try to get encoding from Content-Type header
        content_type = self.headers.get('content-type', '').lower()
        if 'charset=' in content_type:
            try:
                charset = content_type.split('charset=')[1].split(';')[0].strip()
                return charset
            except:
                pass

        # Default to utf-8
        return 'utf-8'

    @property
    def text(self) -> str:
        """Return response text"""
        encoding = self._get_encoding()
        return self.content.decode(encoding, errors='replace')

    def json(self) -> Any:
        """Parse JSON response"""
        return json_lib.loads(self.text)

    @property
    def ok(self) -> bool:
        """Check if status code indicates success"""
        return 200 <= self.status_code < 400

    def raise_for_status(self):
        """Raise exception if status code indicates error"""
        if self.status_code >= 400:
            raise HTTPStatusError(f"{self.status_code} Error", response=self)


class HTTPStatusError(Exception):
    """HTTP status code error"""
    def __init__(self, message: str, response: Response):
        super().__init__(message)
        self.response = response


class RequestError(Exception):
    """Request error"""
    pass


class StreamResponse:
    """Streaming HTTP response - compatible with requests stream=True style.

    Usage (sync):
        response = session.get(url, stream=True)
        for chunk in response.iter_content(8192):
            f.write(chunk)

    Usage (async):
        response = await session.get(url, stream=True)
        async for chunk in response.aiter_content(8192):
            f.write(chunk)
    """

    def __init__(self, reader, url: str = "", cookies: Optional['CookieJar'] = None,
                 encoding: Optional[str] = None, session=None):
        self._reader = reader
        self._status_code: int = reader.status_code
        self._raw_headers: List = list(reader.headers)
        self.url: str = url
        self._cookies: CookieJar = cookies or CookieJar()
        self.encoding: Optional[str] = encoding
        self._content: Optional[bytes] = None
        self._closed: bool = False
        self._session = session

        # Parse raw headers into dict
        self._headers: Dict[str, List[str]] = {}
        for name, value in self._raw_headers:
            lower_name = name.lower()
            if lower_name not in self._headers:
                self._headers[lower_name] = []
            self._headers[lower_name].append(value)

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def headers(self) -> Dict[str, str]:
        """Return headers dictionary (take first value)"""
        return {k: v[0] if v else "" for k, v in self._headers.items()}

    @property
    def cookies(self) -> 'CookieJar':
        return self._cookies

    @property
    def ok(self) -> bool:
        return 200 <= self._status_code < 400

    def _get_encoding(self) -> str:
        if self.encoding:
            return self.encoding
        content_type = self.headers.get('content-type', '').lower()
        if 'charset=' in content_type:
            try:
                charset = content_type.split('charset=')[1].split(';')[0].strip()
                return charset
            except Exception:
                pass
        return 'utf-8'

    def raise_for_status(self):
        if self._status_code >= 400:
            raise HTTPStatusError(f"{self._status_code} Error", response=self)

    # ---- Sync iteration ----

    def iter_content(self, chunk_size: Optional[int] = None):
        """Iterate over response data chunks (sync generator).

        Args:
            chunk_size: If set, re-chunk data into pieces of this size.
                        If None, yield raw chunks as received from network.
        """
        if self._closed:
            return

        buf = b""
        while True:
            chunk = self._reader.next_chunk_sync()
            if chunk is None:
                if buf:
                    yield buf
                break
            if chunk_size is None:
                yield chunk
            else:
                buf += chunk
                while len(buf) >= chunk_size:
                    yield buf[:chunk_size]
                    buf = buf[chunk_size:]

    def iter_lines(self, chunk_size: int = 512, delimiter: Optional[str] = None):
        """Iterate over response lines (sync generator).

        Args:
            chunk_size: Internal read buffer size.
            delimiter: Line delimiter. Default: None (auto-detect \\n or \\r\\n).
        """
        pending = b""
        delim_bytes = delimiter.encode(self._get_encoding()) if delimiter else None

        for chunk in self.iter_content(chunk_size=chunk_size):
            pending += chunk
            if delim_bytes:
                lines = pending.split(delim_bytes)
            else:
                lines = pending.splitlines(True)

            # All complete lines except the last (which may be incomplete)
            if lines:
                for line in lines[:-1]:
                    decoded = line.decode(self._get_encoding(), errors='replace')
                    yield decoded.rstrip('\r\n')
                pending = lines[-1] if not lines[-1].endswith((b'\n', b'\r')) else b""
                if lines[-1].endswith((b'\n', b'\r')):
                    decoded = lines[-1].decode(self._get_encoding(), errors='replace')
                    yield decoded.rstrip('\r\n')

        if pending:
            yield pending.decode(self._get_encoding(), errors='replace').rstrip('\r\n')

    # ---- Async iteration ----

    async def aiter_content(self, chunk_size: Optional[int] = None):
        """Iterate over response data chunks (async generator)."""
        if self._closed:
            return

        buf = b""
        while True:
            chunk = await self._reader.next_chunk()
            if chunk is None:
                if buf:
                    yield buf
                break
            if chunk_size is None:
                yield chunk
            else:
                buf += chunk
                while len(buf) >= chunk_size:
                    yield buf[:chunk_size]
                    buf = buf[chunk_size:]

    async def aiter_lines(self, chunk_size: int = 512, delimiter: Optional[str] = None):
        """Iterate over response lines (async generator)."""
        pending = b""
        delim_bytes = delimiter.encode(self._get_encoding()) if delimiter else None

        async for chunk in self.aiter_content(chunk_size=chunk_size):
            pending += chunk
            if delim_bytes:
                lines = pending.split(delim_bytes)
            else:
                lines = pending.splitlines(True)

            if lines:
                for line in lines[:-1]:
                    decoded = line.decode(self._get_encoding(), errors='replace')
                    yield decoded.rstrip('\r\n')
                pending = lines[-1] if not lines[-1].endswith((b'\n', b'\r')) else b""
                if lines[-1].endswith((b'\n', b'\r')):
                    decoded = lines[-1].decode(self._get_encoding(), errors='replace')
                    yield decoded.rstrip('\r\n')

        if pending:
            yield pending.decode(self._get_encoding(), errors='replace').rstrip('\r\n')

    # ---- Drain helpers ----

    @property
    def content(self) -> bytes:
        """Read entire remaining body. Drains the stream."""
        if self._content is None:
            chunks = []
            for chunk in self.iter_content():
                chunks.append(chunk)
            self._content = b"".join(chunks)
        return self._content

    @property
    def text(self) -> str:
        return self.content.decode(self._get_encoding(), errors='replace')

    def json(self) -> Any:
        return json_lib.loads(self.text)

    # ---- Resource management ----

    def close(self):
        if not self._closed:
            self._closed = True
            if self._reader is not None:
                self._reader.close()
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.close()

    def __del__(self):
        self.close()
