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
