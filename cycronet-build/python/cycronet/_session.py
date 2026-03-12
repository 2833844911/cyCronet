"""
Synchronous Session class for cycronet.
"""

import os
import json as json_lib
from typing import Optional, Dict, List, Tuple, Any
from urllib.parse import urlparse, urlencode

from ._types import HeadersType, CookiesType, DataType
from ._cookies import CookieJar
from ._response import Response, HTTPStatusError, RequestError
from ._utils import extract_domain, parse_set_cookie, domain_matches


class Session:
    """Session object - compatible with requests.Session"""

    def __init__(self, client: 'CronetClient', session_id: str, verify: bool = True):
        self._client = client
        self._session_id = session_id
        self._closed = False
        self._verify = verify
        self._cookies = CookieJar()

    @property
    def cookies(self) -> CookieJar:
        """Get current session's CookieJar"""
        return self._cookies

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = ""
    ) -> List[Tuple[str, str]]:
        """Prepare request headers"""
        if headers is None:
            headers_list = []
        elif isinstance(headers, dict):
            # Python 3.7+ dict maintains insertion order, convert directly to list
            headers_list = list(headers.items())
        else:
            # List maintains original order
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

        # Get matching cookies from CookieJar
        merged_cookies = {}
        for cookie in self._cookies:
            if not cookie.domain or cookie.domain == domain or domain_matches(cookie.domain, domain):
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
        """Extract Set-Cookie from response headers"""
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = parse_set_cookie(values)
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
        """Send HTTP request - compatible with requests.request()"""
        if self._closed:
            raise RequestError("Session is closed")

        # Validate URL
        if not url or not isinstance(url, str):
            raise RequestError("URL must be a non-empty string")

        # Validate URL format
        parsed = urlparse(url)
        if not parsed.scheme:
            raise RequestError(f"Invalid URL '{url}': No schema supplied. Perhaps you meant http://{url}?")
        if parsed.scheme not in ('http', 'https'):
            raise RequestError(f"Invalid URL '{url}': Unsupported schema '{parsed.scheme}'. Only http and https are supported.")
        if not parsed.netloc:
            raise RequestError(f"Invalid URL '{url}': No host supplied")

        # verify parameter is ignored here (decided at session creation)
        # but accept it for requests API compatibility

        if params:
            url = url + ('&' if '?' in url else '?') + urlencode(params)

        domain = extract_domain(url)

        if cookies:
            self._cookies.update(cookies, domain)

        if headers is None:
            headers_to_prepare = None
        elif isinstance(headers, dict):
            headers_to_prepare = headers.copy()
        else:
            headers_to_prepare = list(headers)

        # Handle json parameter
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

        # Handle data parameter
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

        # Prepare request body
        if data is None:
            body = b""
        elif isinstance(data, dict):
            body = json_lib.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data

        # Prepare headers
        prepared_headers = self._prepare_headers(headers_to_prepare, cookies, domain)

        # Call underlying Rust function
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

        # Create response CookieJar
        response_cookies = CookieJar()
        for header_name, values in resp_headers.items():
            if header_name.lower() == 'set-cookie':
                for cookie_name, cookie_value, cookie_domain in parse_set_cookie(values):
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
        """Send GET request"""
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
        """Send POST request"""
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
        """Send PUT request"""
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
        """Send DELETE request"""
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
        """Send PATCH request"""
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
        """Send HEAD request"""
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
        """Send OPTIONS request"""
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
        """Upload file"""
        import mimetypes

        # Read file
        if not os.path.exists(file_path):
            raise RequestError(f"File not found: {file_path}")

        with open(file_path, 'rb') as f:
            file_content = f.read()

        # Get filename and MIME type
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        # Build multipart/form-data
        boundary = f'----CycronetFormBoundary{os.urandom(16).hex()}'
        body_parts = []

        # Add additional fields
        if additional_fields:
            for key, value in additional_fields.items():
                body_parts.append(f'--{boundary}\r\n'.encode())
                body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body_parts.append(f'{value}\r\n'.encode())

        # Add file
        body_parts.append(f'--{boundary}\r\n'.encode())
        body_parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        body_parts.append(f'Content-Type: {mime_type}\r\n\r\n'.encode())
        body_parts.append(file_content)
        body_parts.append(b'\r\n')
        body_parts.append(f'--{boundary}--\r\n'.encode())

        # Merge body
        body = b''.join(body_parts)

        # Set Content-Type
        if headers is None:
            headers = {}
        elif isinstance(headers, list):
            headers = dict(headers)
        else:
            headers = dict(headers)

        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'

        # Send request
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
        """Download file"""
        # Send request
        response = self.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify
        )

        # Check status code
        if response.status_code >= 400:
            raise HTTPStatusError(
                f"Download failed with status {response.status_code}",
                response=response
            )

        # Create directory (if not exists)
        save_dir = os.path.dirname(save_path)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # Save file
        with open(save_path, 'wb') as f:
            f.write(response.content)

        return {
            'file_path': save_path,
            'size': len(response.content),
            'status_code': response.status_code,
            'headers': response.headers
        }

    def close(self):
        """Close session"""
        if not self._closed:
            self._client._client.close_session(self._session_id)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
