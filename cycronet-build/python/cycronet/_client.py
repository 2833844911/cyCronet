"""
Client factory functions for creating CronetClient and AsyncCronetClient.
"""

import os
import json as json_lib
from typing import Optional, Union, Dict, List
from urllib.parse import urlparse

from ._session import Session
from ._async_session import AsyncSession
from ._response import RequestError


# Module-level cache for TLS profiles (loaded once on first use)
# Users can directly set this to customize TLS profiles without modifying tls_profiles.json
_TLS_PROFILES_CACHE: Optional[Dict[str, Dict]] = None


def _load_tls_profiles() -> Dict[str, Dict]:
    """Load all TLS profiles from tls_profiles.json (cached)

    If _TLS_PROFILES_CACHE is already set (by user or previous load), return it directly.
    Otherwise, load from tls_profiles.json file.
    """
    global _TLS_PROFILES_CACHE

    # If user has set the cache directly, use it
    if _TLS_PROFILES_CACHE is not None:
        return _TLS_PROFILES_CACHE

    # Load from file
    config_path = os.path.join(os.path.dirname(__file__), "tls_profiles.json")
    if not os.path.exists(config_path):
        _TLS_PROFILES_CACHE = {}
        return _TLS_PROFILES_CACHE

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            _TLS_PROFILES_CACHE = json_lib.load(f)
            return _TLS_PROFILES_CACHE
    except Exception:
        _TLS_PROFILES_CACHE = {}
        return _TLS_PROFILES_CACHE


def set_tls_profiles(profiles: Dict[str, Dict]) -> None:
    """Set custom TLS profiles (replaces file-based profiles)

    Args:
        profiles: Dictionary of TLS profiles, e.g.:
            {
                "chrome_test": {
                    "version": "Chrome test",
                    "cipher_suites": ["TLS_AES_128_GCM_SHA256", ...],
                    "tls_curves": ["X25519", ...],
                    "tls_extensions": [...]
                }
            }

    Example:
        import cycronet
        cycronet.set_tls_profiles({
            "chrome_test": {
                "cipher_suites": ["TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA"],
                "tls_curves": ["X25519"],
                "tls_extensions": []
            }
        })
        session = cycronet.CronetClient(chrometls="chrome_test")
    """
    global _TLS_PROFILES_CACHE
    _TLS_PROFILES_CACHE = profiles


def add_tls_profile(name: str, profile: Dict) -> None:
    """Add or update a single TLS profile

    Args:
        name: Profile name (e.g., "chrome_test")
        profile: Profile configuration with cipher_suites, tls_curves, tls_extensions

    Example:
        import cycronet
        cycronet.add_tls_profile("chrome_test", {
            "cipher_suites": ["TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA"],
            "tls_curves": ["X25519"],
            "tls_extensions": []
        })
    """
    profiles = _load_tls_profiles()
    profiles[name] = profile


def get_tls_profiles() -> Dict[str, Dict]:
    """Get all loaded TLS profiles

    Returns:
        Dictionary of all TLS profiles
    """
    return _load_tls_profiles().copy()


def clear_tls_profiles_cache() -> None:
    """Clear TLS profiles cache, forcing reload from file on next use"""
    global _TLS_PROFILES_CACHE
    _TLS_PROFILES_CACHE = None


def _load_tls_profile(chrometls: Optional[str] = None) -> Optional[Dict[str, List[str]]]:
    """Get TLS fingerprint configuration for a specific profile"""
    if chrometls is None:
        return None

    profiles = _load_tls_profiles()
    if chrometls not in profiles:
        available = ', '.join(sorted(profiles.keys())) if profiles else 'none'
        raise RequestError(
            f"TLS profile '{chrometls}' not found. Available profiles: {available}"
        )

    profile = profiles[chrometls]
    return {
        "cipher_suites": profile.get('cipher_suites', []) or [],
        "tls_curves": profile.get('tls_curves', []) or [],
        "tls_extensions": profile.get('tls_extensions', []) or [],
    }


def _validate_proxy_url(proxy_url: str) -> None:
    """Validate proxy URL format"""
    if not proxy_url or not isinstance(proxy_url, str):
        raise RequestError("Proxy URL must be a non-empty string")

    # Parse proxy URL
    try:
        parsed = urlparse(proxy_url)
    except ValueError as e:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': {e}")

    # Check scheme
    if not parsed.scheme:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': No schema supplied")

    # Supported proxy protocols
    supported_schemes = ('http', 'https', 'socks5', 'socks5h')
    if parsed.scheme not in supported_schemes:
        raise RequestError(
            f"Invalid proxy URL '{proxy_url}': Unsupported schema '{parsed.scheme}'. "
            f"Supported schemas: {', '.join(supported_schemes)}"
        )

    # Check host
    if not parsed.netloc:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': No host supplied")

    # Check port (if provided)
    try:
        if parsed.port is not None:
            if not (1 <= parsed.port <= 65535):
                raise RequestError(f"Invalid proxy URL '{proxy_url}': Port must be between 1 and 65535")
    except ValueError as e:
        raise RequestError(f"Invalid proxy URL '{proxy_url}': {e}")


def _extract_base_url_host(base_url: Optional[str]) -> Optional[str]:
    """Return the hostname of *base_url*, or None when it is unusable as a
    cookie default domain (missing, relative, or non-http scheme).
    """
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url if "://" in base_url else "http://" + base_url)
    except ValueError:
        return None
    host = parsed.hostname
    if not host:
        return None
    return host


def CronetClient(
    verify: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    timeout_ms: int = 30000,
    chrometls: Optional[str] = "chrome_144",
    headers: Optional[Dict[str, str]] = None,
    base_url: Optional[str] = None,
    default_domain: Optional[str] = None,
) -> Session:
    """
    Create Cronet Session - similar to requests.Session()

    Args:
        verify: Whether to verify SSL certificates (False to skip verification)
        proxies: Proxy configuration, supports dict format {"https": "http://127.0.0.1:8080"} or string
        timeout_ms: Timeout in milliseconds
        chrometls: TLS fingerprint configuration name (e.g. "chrome_144")
        headers: Default headers for all requests in this session
        base_url: Optional base URL whose hostname becomes the CookieJar's
            default domain (host-only, like a browser host cookie — only
            exact host matches). Use this for single-host sessions.
        default_domain: Optional explicit default cookie domain. Unlike
            ``base_url`` this is treated as a RFC 6265 domain attribute, so
            a value like ``"example.com"`` is also sent to
            ``sub.example.com``. Use this when the Akamai/SSO cookies need to
            follow a user across sibling subdomains (e.g. ``www.site.com``
            and ``booking.site.com`` both need cookies scoped to
            ``site.com``). Takes precedence over *base_url*.
            If neither is set, the host of the first outgoing request is
            used automatically (host-only).

    Returns:
        Session object

    Example:
        session = CronetClient(verify=False)
        session = CronetClient(proxies={"https": "http://127.0.0.1:8080"})
        session = CronetClient(verify=False, chrometls="chrome_144")
        session = CronetClient(headers={"User-Agent": "MyApp/1.0"})
        session = CronetClient(base_url="https://www.example.com")
        session = CronetClient(default_domain="example.com")  # cross-subdomain
        response = session.get("https://example.com")
    """
    # Import here to avoid circular dependency
    from .cronet_cloak import PyCronetClient

    # Handle proxies parameter
    proxy_rules = None
    if proxies:
        if isinstance(proxies, dict):
            # Extract proxy URL from dict (prefer https, then http)
            proxy_rules = proxies.get('https') or proxies.get('http') or proxies.get('all')
        else:
            proxy_rules = proxies

        # Validate proxy URL
        if proxy_rules:
            _validate_proxy_url(proxy_rules)
            # Normalize socks5h -> socks5 (Cronet SOCKS5 always uses remote DNS)
            if proxy_rules.startswith('socks5h://'):
                proxy_rules = 'socks5://' + proxy_rules[len('socks5h://'):]

    # Load TLS fingerprint configuration
    tls_profile = _load_tls_profile(chrometls)
    cipher_suites = tls_profile.get("cipher_suites", []) if tls_profile else None
    tls_curves = tls_profile.get("tls_curves", []) if tls_profile else None
    tls_extensions = tls_profile.get("tls_extensions", []) if tls_profile else None

    client = PyCronetClient()
    session_id = client.create_session(
        proxy_rules,
        not verify,  # skip_cert_verify = not verify
        timeout_ms,
        cipher_suites,
        tls_curves,
        tls_extensions
    )

    # Create a wrapped Session, save client reference
    class _ClientWrapper:
        def __init__(self, client):
            self._client = client

    wrapper = _ClientWrapper(client)
    effective_default = default_domain or _extract_base_url_host(base_url)
    session = Session(wrapper, session_id, verify, default_domain=effective_default)
    if headers:
        session.headers = headers
    return session


def AsyncCronetClient(
    verify: bool = True,
    proxies: Optional[Union[str, Dict[str, str]]] = None,
    timeout_ms: int = 30000,
    chrometls: Optional[str] = "chrome_144",
    headers: Optional[Dict[str, str]] = None,
    base_url: Optional[str] = None,
    default_domain: Optional[str] = None,
) -> AsyncSession:
    """
    Create async Cronet Session - supports async/await

    Args:
        verify: Whether to verify SSL certificates (False to skip verification)
        proxies: Proxy configuration, supports dict format {"https": "http://127.0.0.1:8080"} or string
        timeout_ms: Timeout in milliseconds
        chrometls: TLS fingerprint configuration name (e.g. "chrome_144")
        headers: Default headers for all requests in this session
        base_url: Optional base URL whose hostname becomes the CookieJar's
            default domain (host-only, like a browser host cookie — only
            exact host matches). Use this for single-host sessions.
        default_domain: Optional explicit default cookie domain (RFC 6265
            domain attribute). A value like ``"example.com"`` is also sent
            to ``sub.example.com``, so use this when cookies need to follow
            a user across sibling subdomains. Takes precedence over
            *base_url*. If neither is set, the host of the first outgoing
            request is used automatically (host-only).

    Returns:
        AsyncSession object

    Example:
        async with AsyncCronetClient(verify=False) as session:
            response = await session.get("https://example.com")
        async with AsyncCronetClient(headers={"User-Agent": "MyApp/1.0"}) as session:
            response = await session.get("https://example.com")
        async with AsyncCronetClient(default_domain="example.com") as session:
            session.cookies.update({"token": "abc"})
            await session.get("https://api.example.com/x")  # cookie sent
    """
    # Import here to avoid circular dependency
    from .cronet_cloak import PyCronetClient

    proxy_rules = None
    if proxies:
        if isinstance(proxies, dict):
            proxy_rules = proxies.get('https') or proxies.get('http') or proxies.get('all')
        else:
            proxy_rules = proxies

        # Validate proxy URL
        if proxy_rules:
            _validate_proxy_url(proxy_rules)
            # Normalize socks5h -> socks5 (Cronet SOCKS5 always uses remote DNS)
            if proxy_rules.startswith('socks5h://'):
                proxy_rules = 'socks5://' + proxy_rules[len('socks5h://'):]

    # Load TLS fingerprint configuration
    tls_profile = _load_tls_profile(chrometls)
    cipher_suites = tls_profile.get("cipher_suites", []) if tls_profile else None
    tls_curves = tls_profile.get("tls_curves", []) if tls_profile else None
    tls_extensions = tls_profile.get("tls_extensions", []) if tls_profile else None

    client = PyCronetClient()
    session_id = client.create_session(
        proxy_rules,
        not verify,
        timeout_ms,
        cipher_suites,
        tls_curves,
        tls_extensions
    )

    class _ClientWrapper:
        def __init__(self, client):
            self._client = client

    wrapper = _ClientWrapper(client)
    effective_default = default_domain or _extract_base_url_host(base_url)
    session = AsyncSession(wrapper, session_id, verify, default_domain=effective_default)
    if headers:
        session.headers = headers
    return session
