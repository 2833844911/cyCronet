"""
Response and exception classes for cycronet.
"""

import json as json_lib
from typing import Dict, List, Any, Optional, Iterator, Generator
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
    """Streaming HTTP response object - compatible with requests streaming API.

    Usage:
        response = session.get("https://example.com", stream=True)
        for chunk in response.iter_content(chunk_size=1024):
            process(chunk)

        # Or with context manager:
        with session.get("https://example.com", stream=True) as response:
            for line in response.iter_lines():
                print(line)
    """

    def __init__(self, stream_reader, headers: Dict[str, List[str]],
                 url: str = "", cookies: Optional[CookieJar] = None):
        self._reader = stream_reader
        self.status_code: int = stream_reader.status_code
        self._headers = headers
        self.url = url
        self._cookies = cookies or CookieJar()
        self._closed = False
        self._session = None  # Will be set by module-level API to keep session alive
        self._content: Optional[bytes] = None  # Lazily consumed full body

    def _consume(self) -> bytes:
        """Read the entire stream into memory (idempotent)."""
        if self._content is None:
            self._content = b"".join(self.iter_content())
        return self._content

    @property
    def content(self) -> bytes:
        """Read the entire response body as bytes (consumes the stream)."""
        return self._consume()

    @property
    def text(self) -> str:
        """Read the entire response body as text (consumes the stream)."""
        body = self._consume()
        encoding = 'utf-8'
        ct = self._headers.get('content-type', [''])[0] if self._headers.get('content-type') else ''
        if 'charset=' in ct:
            encoding = ct.split('charset=')[-1].split(';')[0].strip()
        return body.decode(encoding, errors='replace')

    def json(self) -> Any:
        """Read the entire response body and parse as JSON (consumes the stream)."""
        import json as _json
        return _json.loads(self._consume())

    @property
    def headers(self) -> Dict[str, str]:
        """Return headers dictionary (take first value)"""
        return {k: v[0] if v else "" for k, v in self._headers.items()}

    @property
    def cookies(self) -> CookieJar:
        """Return response cookies (CookieJar object)"""
        return self._cookies

    @property
    def ok(self) -> bool:
        """Check if status code indicates success"""
        return 200 <= self.status_code < 400

    def raise_for_status(self):
        """Raise exception if status code indicates error"""
        if self.status_code >= 400:
            raise HTTPStatusError(f"{self.status_code} Error", response=self)

    def iter_content(self, chunk_size: Optional[int] = None) -> Generator[bytes, None, None]:
        """Iterate over response data in chunks.

        Args:
            chunk_size: Size of chunks to return. If None, return chunks as received.
        """
        if self._closed:
            return

        try:
            if chunk_size is None or chunk_size <= 0:
                # Return chunks as received from Cronet
                while True:
                    chunk = self._reader.next_chunk_sync()
                    if chunk is None:
                        break
                    if chunk:
                        yield chunk
            else:
                # Buffer and yield fixed-size chunks
                buffer = b""
                while True:
                    chunk = self._reader.next_chunk_sync()
                    if chunk is None:
                        if buffer:
                            yield buffer
                        break
                    buffer += chunk
                    while len(buffer) >= chunk_size:
                        yield buffer[:chunk_size]
                        buffer = buffer[chunk_size:]
        finally:
            self.close()

    def iter_lines(self, chunk_size: int = 512,
                   decode_unicode: bool = False,
                   delimiter: Optional[str] = None) -> Generator[str, None, None]:
        """Iterate over response data line by line.

        Args:
            chunk_size: Size of chunks to read.
            decode_unicode: Whether to decode bytes to string.
            delimiter: Line delimiter (default: newline).
        """
        pending = b""
        sep = delimiter.encode('utf-8') if delimiter else None

        for chunk in self.iter_content(chunk_size=chunk_size):
            pending += chunk
            if sep:
                lines = pending.split(sep)
            else:
                lines = pending.splitlines(True)

            # Yield all complete lines
            for line in lines[:-1]:
                line_clean = line.rstrip(b'\r\n') if not sep else line
                if line_clean:
                    if decode_unicode:
                        yield line_clean.decode('utf-8', errors='replace')
                    else:
                        yield line_clean

            # Keep incomplete last part
            last = lines[-1]
            if sep:
                pending = last
            else:
                if last.endswith((b'\n', b'\r', b'\r\n')):
                    line_clean = last.rstrip(b'\r\n')
                    if line_clean:
                        if decode_unicode:
                            yield line_clean.decode('utf-8', errors='replace')
                        else:
                            yield line_clean
                    pending = b""
                else:
                    pending = last

        # Yield remaining data
        if pending:
            pending_clean = pending.rstrip(b'\r\n')
            if pending_clean:
                if decode_unicode:
                    yield pending_clean.decode('utf-8', errors='replace')
                else:
                    yield pending_clean

    def close(self):
        """Close the stream and release resources."""
        if not self._closed:
            self._closed = True
            if self._reader is not None:
                try:
                    self._reader.close()
                except Exception:
                    pass
            # Release session reference (allows session cleanup)
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()
