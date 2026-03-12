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
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def parse_set_cookie(set_cookie_values: List[str]) -> List[Tuple[str, str, str]]:
    """Parse Set-Cookie header values.

    Returns:
        List of (name, value, domain) tuples
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
                for part in parts[1:]:
                    part = part.strip()
                    if part.lower().startswith('domain='):
                        domain = part.split('=', 1)[1].strip().lower()
                        if domain.startswith('.'):
                            domain = domain[1:]
                        break
                cookies.append((name, val, domain))
    return cookies


def domain_matches(cookie_domain: str, request_domain: str) -> bool:
    """Check if cookie domain matches request domain."""
    if not cookie_domain:
        return False
    request_domain = request_domain.lower()
    cookie_domain = cookie_domain.lower()
    if request_domain == cookie_domain:
        return True
    if request_domain.endswith('.' + cookie_domain):
        return True
    return False
