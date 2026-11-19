"""
Synchronous Session class for cycronet.
"""

import os
import json as json_lib
from typing import Optional, Dict, List, Tuple, Any
from urllib.parse import urlparse, urlencode

from ._types import HeadersType, CookiesType, DataType
from ._cookies import CookieJar
from ._response import Response, StreamResponse, HTTPStatusError, RequestError
from ._utils import extract_domain, parse_set_cookie, domain_matches, normalize_cookie_domain


class Session:
    """Session object - compatible with requests.Session"""

    MAX_REDIRECTS = 30  # Same default as requests

    def __init__(self, client: 'CronetClient', session_id: str, verify: bool = True,
                 headers: Optional[Dict[str, str]] = None,
                 default_domain: Optional[str] = None):
        self._client = client
        self._session_id = session_id
        self._closed = False
        self._verify = verify
        self._cookies = CookieJar(default_domain=default_domain)
        self._default_headers = dict(headers) if headers else {}  # Store default headers for session

    @property
    def cookies(self) -> CookieJar:
        """Get current session's CookieJar"""
        return self._cookies

    def _adjust_chrome_headers(self, headers: Dict[str, str], method: str, has_body: bool = False, is_json: bool = False) -> Dict[str, str]:
        """
        Adjust existing headers to match Chrome browser behavior.
        Only modifies headers that already exist in the dict.
        """
        # Create copy to avoid modifying original data
        adjusted = headers.copy()

        # Create lowercase key mapping for lookup
        headers_lower_map = {k.lower(): k for k in adjusted.keys()}

        method_upper = method.upper()

        # Adjust headers based on request type
        if method_upper in ('GET', 'HEAD'):
            # GET/HEAD request - navigation mode
            if 'accept' in headers_lower_map:
                original_key = headers_lower_map['accept']
                adjusted[original_key] = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7'

            if 'sec-fetch-dest' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-dest']
                adjusted[original_key] = 'document'

            if 'sec-fetch-mode' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-mode']
                adjusted[original_key] = 'navigate'

            if 'sec-fetch-site' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-site']
                adjusted[original_key] = 'none'

            if 'sec-fetch-user' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-user']
                adjusted[original_key] = '?1'

        elif method_upper in ('POST', 'PUT', 'PATCH', 'DELETE'):
            # POST/PUT/PATCH/DELETE request
            if is_json:
                # JSON request
                if 'accept' in headers_lower_map:
                    original_key = headers_lower_map['accept']
                    adjusted[original_key] = 'application/json, text/plain, */*'

            elif has_body:
                # Form request
                if 'accept' in headers_lower_map:
                    original_key = headers_lower_map['accept']
                    adjusted[original_key] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

            else:
                # No body POST/DELETE
                if 'accept' in headers_lower_map:
                    original_key = headers_lower_map['accept']
                    adjusted[original_key] = '*/*'

            # Modify sec-fetch-* headers (if they exist)
            if 'sec-fetch-dest' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-dest']
                adjusted[original_key] = 'empty'

            if 'sec-fetch-mode' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-mode']
                adjusted[original_key] = 'cors'

            if 'sec-fetch-site' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-site']
                adjusted[original_key] = 'same-origin'

            # POST requests usually don't have sec-fetch-user
            if 'sec-fetch-user' in headers_lower_map:
                original_key = headers_lower_map['sec-fetch-user']
                # Remove it for POST requests
                del adjusted[original_key]

        return adjusted

    def _prepare_headers(
        self,
        headers: Optional[HeadersType] = None,
        cookies: Optional[CookiesType] = None,
        domain: str = "",
        method: str = "GET",
        has_body: bool = False,
        is_json: bool = False,
        need_content_type: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """Prepare request headers with session defaults"""

        # Check if user provided headers
        user_provided = headers is not None

        # Decide which headers to use
        if user_provided:
            # User provided, use user's headers
            if isinstance(headers, dict):
                headers_dict = headers.copy()
            else:
                headers_dict = dict(headers)

            # Save to session (update default headers)
            self._default_headers = headers_dict.copy()

        elif self._default_headers:
            # User didn't provide, use saved headers
            headers_dict = self._default_headers.copy()

            # Adjust existing headers based on request type
            headers_dict = self._adjust_chrome_headers(
                headers_dict,
                method,
                has_body=has_body,
                is_json=is_json
            )

        else:
            # No headers at all
            headers_dict = {}

        # Add content-type if needed (and not already present)
        if need_content_type:
            headers_lower_map = {k.lower(): k for k in headers_dict.keys()}
            if 'content-type' not in headers_lower_map:
                headers_dict['content-type'] = need_content_type

        # Convert to list
        headers_list = list(headers_dict.items())

        # Process cookie, priority headers (keep original logic)
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

        # Get matching cookies from CookieJar (last-write-wins via seq)
        all_cookies = []
        for cookie in self._cookies.iter_cookies():
            if not cookie.domain or cookie.domain == domain or domain_matches(cookie.domain, domain):
                all_cookies.append(cookie)
        all_cookies.sort(key=lambda c: c.seq)
        merged_cookies = {c.name: c.value for c in all_cookies}

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
        """Extract Set-Cookie from response headers and update session cookies.

        Domain handling follows RFC 6265:
        - If Set-Cookie has Domain attribute, use it (normalized)
        - If no Domain attribute, use the request domain (host-only cookie)
        """
        request_domain = normalize_cookie_domain(request_domain)
        for name, values in headers.items():
            if name.lower() == 'set-cookie':
                parsed_cookies = parse_set_cookie(values)
                for cookie_name, cookie_value, cookie_domain, cookie_path in parsed_cookies:
                    store_domain = cookie_domain if cookie_domain else request_domain
                    self._cookies.set(cookie_name, cookie_value, store_domain, cookie_path)

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
        allow_redirects: bool = True,
        stream: bool = False,
        **kwargs
    ):
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

        # Auto-detect default domain from first request when none was
        # supplied at construction time (fulfils the documented behaviour).
        if not self._cookies.default_domain:
            self._cookies.set_default_domain(domain)

        # Per-request cookies are NOT merged into session (matching requests behavior).
        # They are only used for this single request via _prepare_headers.

        if headers is None:
            headers_to_prepare = None
        elif isinstance(headers, dict):
            headers_to_prepare = headers.copy()
        else:
            headers_to_prepare = list(headers)

        # Determine request type
        is_json_request = json is not None
        has_body = data is not None or json is not None
        need_content_type = None

        # Handle json parameter
        if json is not None:
            data = json
            need_content_type = 'application/json'

        # Handle data parameter
        elif data is not None:
            if isinstance(data, dict):
                data = urlencode(data)
                need_content_type = 'application/x-www-form-urlencoded'

        # Prepare request body
        if data is None:
            body = b""
        elif isinstance(data, dict):
            body = json_lib.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data

        # Prepare headers (pass request type information)
        prepared_headers = self._prepare_headers(
            headers_to_prepare,
            cookies,
            domain,
            method=method,
            has_body=has_body,
            is_json=is_json_request,
            need_content_type=need_content_type
        )

        # Always disable redirects at Rust layer, handle in Python
        # Use request_sync for synchronous blocking call
        # Streaming path
        if stream:
            reader = self._client._client.request_stream_sync(
                self._session_id,
                url,
                method.upper(),
                prepared_headers,
                body,
                False  # Always False - handle redirects in Python
            )

            status_code = reader.status_code
            resp_headers_list = list(reader.headers)

            resp_headers = {}
            for name, value in resp_headers_list:
                if name not in resp_headers:
                    resp_headers[name] = []
                resp_headers[name].append(value)

            # Update session cookies from response
            self._update_cookies_from_response(resp_headers, domain)

            # Create response CookieJar
            response_cookies = CookieJar()
            for header_name, values in resp_headers.items():
                if header_name.lower() == 'set-cookie':
                    for cookie_name, cookie_value, cookie_domain, cookie_path in parse_set_cookie(values):
                        store_domain = cookie_domain if cookie_domain else normalize_cookie_domain(domain)
                        response_cookies.set(cookie_name, cookie_value, store_domain, cookie_path)

            # Handle redirects for streaming
            if allow_redirects and status_code in (301, 302, 303, 307, 308):
                location = None
                for header_name, values in resp_headers.items():
                    if header_name.lower() == 'location':
                        location = values[0] if values else None
                        break
                if location:
                    reader.close()
                    redirects_remaining = kwargs.get('_redirects_remaining')
                    if redirects_remaining is None:
                        redirects_remaining = self.MAX_REDIRECTS
                    if redirects_remaining <= 0:
                        raise RequestError(f"Exceeded maximum redirects ({self.MAX_REDIRECTS})")
                    if not location.startswith(('http://', 'https://')):
                        from urllib.parse import urljoin
                        location = urljoin(url, location)
                    redirect_method = 'GET' if status_code == 303 else method
                    return self.request(
                        redirect_method, location,
                        params=None, headers=headers_to_prepare, cookies=cookies,
                        data=None if status_code == 303 else data, json=None,
                        timeout=timeout, verify=verify, allow_redirects=True,
                        stream=True, _redirects_remaining=redirects_remaining - 1
                    )

            return StreamResponse(
                reader, url=url, cookies=response_cookies
            )

        # Non-streaming path
        response_dict = self._client._client.request_sync(
            self._session_id,
            url,
            method.upper(),
            prepared_headers,
            body,
            False  # Always False - handle redirects in Python
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
                for cookie_name, cookie_value, cookie_domain, cookie_path in parse_set_cookie(values):
                    store_domain = cookie_domain if cookie_domain else normalize_cookie_domain(domain)
                    response_cookies.set(cookie_name, cookie_value, store_domain, cookie_path)

        # Update session cookies from response
        self._update_cookies_from_response(resp_headers, domain)

        # Handle redirects in Python layer
        if allow_redirects and status_code in (301, 302, 303, 307, 308):
            location = None
            for header_name, values in resp_headers.items():
                if header_name.lower() == 'location':
                    location = values[0] if values else None
                    break

            if location:
                # Enforce redirect depth limit
                redirects_remaining = kwargs.get('_redirects_remaining')
                if redirects_remaining is None:
                    redirects_remaining = self.MAX_REDIRECTS
                if redirects_remaining <= 0:
                    raise RequestError(
                        f"Exceeded maximum redirects ({self.MAX_REDIRECTS})"
                    )

                # Handle relative URLs
                if not location.startswith(('http://', 'https://')):
                    from urllib.parse import urljoin
                    location = urljoin(url, location)

                # Follow redirect with updated cookies and headers
                # For 303, change method to GET
                redirect_method = 'GET' if status_code == 303 else method

                # Recursively call request with updated URL
                # Pass original per-request cookies so they carry through redirects
                return self.request(
                    redirect_method,
                    location,
                    params=None,  # Don't carry params on redirect
                    headers=headers_to_prepare,  # Carry original headers
                    cookies=cookies,  # Carry per-request cookies through redirect
                    data=None if status_code == 303 else data,  # Drop body for 303
                    json=None,
                    timeout=timeout,
                    verify=verify,
                    allow_redirects=True,  # Continue following redirects
                    _redirects_remaining=redirects_remaining - 1
                )

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
        allow_redirects: bool = True,
        stream: bool = False
    ):
        """Send GET request"""
        return self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
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
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
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
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
        """Send DELETE request"""
        return self.request(
            "DELETE",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
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
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
        """Send HEAD request"""
        return self.request(
            "HEAD",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects,
            stream=stream
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
        allow_redirects: bool = True,
        stream: bool = False
    ):
        """Send OPTIONS request"""
        return self.request(
            "OPTIONS",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects,
            stream=stream
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

    def websocket(
        self,
        url: str,
        *,
        on_open=None,
        on_message=None,
        on_close=None,
        on_error=None,
        headers: Optional[HeadersType] = None,
        origin: Optional[str] = None,
        sub_protocols: Optional[str] = None,
    ):
        """Create a callback-based WebSocket connection.

        Args:
            url: WebSocket URL (ws:// or wss://)
            on_open: callback(ws) - called when connected
            on_message: callback(ws, message, is_text) - called on message
            on_close: callback(ws, code, reason, was_clean) - called on close
            on_error: callback(ws, error, net_error) - called on error
            headers: custom Upgrade headers. The session CookieJar is merged
                when this argument does not already include ``Cookie``.
            origin: explicit WebSocket Origin value. When omitted, an Origin
                entry in ``headers`` is used.
            sub_protocols: optional comma-separated WebSocket subprotocols

        Returns:
            WebSocketApp instance. Call .run_forever() or .run_in_background() to start.
        """
        if self._closed:
            raise RequestError("Session is closed")
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
            raise RequestError("WebSocket URL must use ws:// or wss:// and include a host")

        # A WebSocket Upgrade is HTTP/1.1 fingerprint-sensitive.  Do not pass
        # it through _prepare_headers(): that generic helper moves Cookie and
        # Priority fields, which changes the browser's Upgrade field order.
        if headers is None:
            prepared_headers = list(self._default_headers.items())
        elif isinstance(headers, dict):
            prepared_headers = list(headers.items())
        else:
            prepared_headers = list(headers)

        # Keep an explicit Cookie header exactly where the caller placed it.
        # Only append CookieJar state when no raw Cookie header was supplied.
        has_cookie = any(
            isinstance(name, str) and name.lower() == "cookie"
            for name, _ in prepared_headers
        )
        if not has_cookie:
            matching_cookies = []
            for cookie in self._cookies.iter_cookies():
                if (
                    not cookie.domain
                    or cookie.domain == parsed.hostname
                    or domain_matches(cookie.domain, parsed.hostname)
                ):
                    matching_cookies.append(cookie)
            matching_cookies.sort(key=lambda cookie: cookie.seq)
            if matching_cookies:
                prepared_headers.append((
                    "Cookie",
                    "; ".join(
                        f"{cookie.name}={cookie.value}"
                        for cookie in matching_cookies
                    ),
                ))

        from ._websocket import WebSocketApp
        return WebSocketApp(
            self,
            url,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
            on_error=on_error,
            headers=prepared_headers,
            origin=origin,
            sub_protocols=sub_protocols,
        )

    def close(self):
        """Close session"""
        if not self._closed:
            self._client._client.close_session(self._session_id)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
