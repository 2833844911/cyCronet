"""
Utility functions for cycronet.
"""

from typing import Dict, List, Tuple
from urllib.parse import urlparse


# Browser default header order
BROWSER_HEADER_ORDER = [
    "host", "connection", "cache-control", "sec-ch-ua", "sec-ch-ua-mobile",
    "sec-ch-ua-platform", "upgrade-insecure-requests", "user-agent", "accept",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-user", "sec-fetch-dest",
    "referer", "accept-encoding", "accept-language", "cookie", "priority",
]


def sort_headers_dict(headers_dict: Dict[str, str]) -> List[Tuple[str, str]]:
    """Sort dictionary headers in browser order."""
    header_dict_lower = {k.lower(): (k, v) for k, v in headers_dict.items()}
    sorted_headers = []

    for key in BROWSER_HEADER_ORDER:
        if key in header_dict_lower:
            sorted_headers.append(header_dict_lower[key])
            del header_dict_lower[key]

    for original_key, value in header_dict_lower.values():
        sorted_headers.append((original_key, value))

    return sorted_headers


def extract_domain(url: str) -> str:
    """Extract domain from URL (without port)."""
    parsed = urlparse(url)
    hostname = parsed.hostname or parsed.netloc
    return hostname.lower()


def extract_domain_with_port(url: str) -> str:
    """Extract domain with port from URL."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def parse_set_cookie(set_cookie_values: List[str]) -> List[Tuple[str, str, str, str]]:
    """Parse Set-Cookie header values.

    Returns:
        List of (name, value, domain, path) tuples
    """
    cookies = []
    for value in set_cookie_values:
        if '=' in value:
            parts = value.split(';')
            cookie_part = parts[0].strip()
            if '=' in cookie_part:
                name, val = cookie_part.split('=', 1)
                name = name.strip()
                val = val.strip()
                domain = ""
                path = "/"
                for part in parts[1:]:
                    part = part.strip()
                    part_lower = part.lower()
                    if part_lower.startswith('domain='):
                        domain = normalize_cookie_domain(part.split('=', 1)[1])
                    elif part_lower.startswith('path='):
                        path = part.split('=', 1)[1].strip() or "/"
                cookies.append((name, val, domain, path))
    return cookies


# RFC 7230 tchar characters allowed in HTTP header field-names
_TCHAR = frozenset(
    '!#$%&\'*+-.^_`|~'
    '0123456789'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'abcdefghijklmnopqrstuvwxyz'
)


def validate_header_name(name: str) -> None:
    """Validate HTTP header name per RFC 7230.

    Raises:
        ValueError: If the header name contains invalid characters.
    """
    if not name:
        raise ValueError("Header name must not be empty")
    for ch in name:
        if ch not in _TCHAR:
            raise ValueError(
                f"Invalid character {ch!r} in header name {name!r}. "
                f"Header names may only contain letters, digits, and !#$%&'*+-.^_`|~ characters."
            )


def validate_header_value(value: str) -> None:
    """Validate HTTP header value (no control characters except HTAB).

    Raises:
        ValueError: If the header value contains invalid characters.
    """
    for ch in value:
        code = ord(ch)
        if code == 0x09:  # HTAB is allowed
            continue
        if code < 0x20 or code == 0x7f:
            raise ValueError(
                f"Invalid control character (0x{code:02x}) in header value for: {value!r}"
            )


def normalize_cookie_domain(domain: str) -> str:
    """Normalize cookie domain: strip leading dot, lowercase, strip port."""
    if not domain:
        return ""
    domain = domain.lower().strip()
    if domain.startswith('.'):
        domain = domain[1:]
    # Strip port if present
    if ':' in domain and not domain.startswith('['):
        domain = domain.rsplit(':', 1)[0]
    return domain


def domain_matches(cookie_domain: str, request_domain: str) -> bool:
    """Check if cookie domain matches request domain (RFC 6265 style).

    A cookie with domain "example.com" should be sent to:
    - example.com (exact match)
    - sub.example.com (subdomain match)
    - any.sub.example.com (deep subdomain match)
    """
    if not cookie_domain:
        return False
    request_domain = normalize_cookie_domain(request_domain)
    cookie_domain = normalize_cookie_domain(cookie_domain)
    if request_domain == cookie_domain:
        return True
    if request_domain.endswith('.' + cookie_domain):
        return True
    return False
