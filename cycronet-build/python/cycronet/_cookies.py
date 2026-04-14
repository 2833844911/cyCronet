"""
Cookie management classes for cycronet.
"""

from typing import Dict, Iterator, Optional, Tuple, Union

from ._utils import domain_matches as _domain_matches, normalize_cookie_domain


class Cookie:
    """Single Cookie object - similar to http.cookiejar.Cookie"""

    def __init__(self, name: str, value: str, domain: str = "", path: str = "/"):
        self.name = name
        self.value = value
        self.domain = Cookie._normalize_domain(domain)
        self.path = path

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return normalize_cookie_domain(domain)

    def __repr__(self):
        return f"<Cookie {self.name}={self.value} for {self.domain}{self.path}>"

    def __str__(self):
        return f"{self.name}={self.value}"


class CookieJar:
    """Cookie Jar manager - similar to requests.cookies.RequestsCookieJar"""

    def __init__(self):
        # Storage structure: {domain: {name: Cookie}}
        self._cookies: Dict[str, Dict[str, Cookie]] = {}

    def set(self, name: str, value: str, domain: str = "", path: str = "/"):
        """Set a cookie"""
        domain = Cookie._normalize_domain(domain)
        if domain not in self._cookies:
            self._cookies[domain] = {}
        self._cookies[domain][name] = Cookie(name, value, domain, path)

    def get(self, name: str, default: Optional[str] = None, domain: Optional[str] = None) -> Optional[str]:
        """Get cookie value by name.

        If domain is specified, only look in that domain (with domain matching).
        If domain is None, search all domains.

        :param name: cookie name
        :param default: default value if not found
        :param domain: optional domain filter
        :return: cookie value or default
        """
        if domain is not None:
            domain = Cookie._normalize_domain(domain)
            # Try exact match first
            if domain in self._cookies and name in self._cookies[domain]:
                return self._cookies[domain][name].value
            # Try domain matching (e.g., request "sub.example.com" matches cookie "example.com")
            for cookie_domain, domain_cookies in self._cookies.items():
                if name in domain_cookies and _domain_matches(cookie_domain, domain):
                    return domain_cookies[name].value
            return default
        # No domain: search all
        for domain_cookies in self._cookies.values():
            if name in domain_cookies:
                return domain_cookies[name].value
        return default

    def get_dict(self, domain: Optional[str] = None) -> Dict[str, str]:
        """Get cookies as {name: value} dict.

        If domain is specified, returns cookies that would be sent to that domain
        (using RFC 6265 domain matching). This means a cookie for "example.com"
        will be included when querying "sub.example.com".

        If domain is None, returns ALL cookies.

        :param domain: optional domain filter (the request domain to match against)
        :return: dict of {cookie_name: cookie_value}
        """
        result = {}
        if domain is not None:
            domain = Cookie._normalize_domain(domain)
            for cookie_domain, domain_cookies in self._cookies.items():
                if _domain_matches(cookie_domain, domain):
                    for name, cookie in domain_cookies.items():
                        result[name] = cookie.value
        else:
            for domain_cookies in self._cookies.values():
                for name, cookie in domain_cookies.items():
                    result[name] = cookie.value
        return result

    def update(self, cookies: Union[Dict[str, str], 'CookieJar'], domain: Optional[str] = None):
        """Update cookies from dict or another CookieJar.

        :param cookies: dict {name: value} or CookieJar
        :param domain: domain to use when updating from dict
        """
        if isinstance(cookies, CookieJar):
            for d, domain_cookies in cookies._cookies.items():
                for name, cookie in domain_cookies.items():
                    self.set(name, cookie.value, cookie.domain, cookie.path)
        elif isinstance(cookies, dict):
            for name, value in cookies.items():
                self.set(name, value, domain)

    def clear(self, domain: Optional[str] = None):
        """Clear cookies.

        :param domain: if specified, only clear cookies for that domain; otherwise clear all
        """
        if domain is not None:
            domain = Cookie._normalize_domain(domain)
            if domain in self._cookies:
                del self._cookies[domain]
        else:
            self._cookies.clear()

    def remove(self, name: str, domain: Optional[str] = None):
        """Remove a specific cookie.

        :param name: cookie name
        :param domain: if specified, only remove from that domain
        """
        if domain is not None:
            domain = Cookie._normalize_domain(domain)
            if domain in self._cookies and name in self._cookies[domain]:
                del self._cookies[domain][name]
                if not self._cookies[domain]:
                    del self._cookies[domain]
        else:
            for d in list(self._cookies.keys()):
                if name in self._cookies[d]:
                    del self._cookies[d][name]
                    if not self._cookies[d]:
                        del self._cookies[d]

    def copy(self) -> 'CookieJar':
        """Return a copy of this CookieJar."""
        new_jar = CookieJar()
        for domain, domain_cookies in self._cookies.items():
            for name, cookie in domain_cookies.items():
                new_jar.set(name, cookie.value, cookie.domain, cookie.path)
        return new_jar

    def items(self) -> Iterator[Tuple[str, str]]:
        """Yield all (name, value) pairs."""
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                yield (name, cookie.value)

    def keys(self) -> Iterator[str]:
        """Yield all cookie names."""
        for domain_cookies in self._cookies.values():
            for name in domain_cookies.keys():
                yield name

    def values(self) -> Iterator[str]:
        """Yield all cookie values."""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie.value

    def list_domains(self) -> list:
        """Return list of all domains that have cookies."""
        return list(self._cookies.keys())

    def items_for_domain(self, domain: str) -> Iterator[Tuple[str, str]]:
        """Yield (name, value) pairs for cookies matching a domain (with RFC 6265 matching).

        :param domain: the request domain to match against
        """
        domain = Cookie._normalize_domain(domain)
        for cookie_domain, domain_cookies in self._cookies.items():
            if _domain_matches(cookie_domain, domain):
                for name, cookie in domain_cookies.items():
                    yield (name, cookie.value)

    def __setitem__(self, name: str, value: str):
        """Allow jar[name] = value syntax (sets with empty domain)."""
        self.set(name, value)

    def __getitem__(self, name: str) -> str:
        """Allow jar[name] syntax."""
        val = self.get(name)
        if val is None:
            raise KeyError(name)
        return val

    def __contains__(self, name: str) -> bool:
        """Support 'name in jar' syntax."""
        return self.get(name) is not None

    def __bool__(self) -> bool:
        """Truthiness: True if jar has any cookies."""
        return len(self) > 0

    def __iter__(self) -> Iterator[Cookie]:
        """Iterate all Cookie objects."""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie

    def __len__(self) -> int:
        """Return total cookie count."""
        return sum(len(domain_cookies) for domain_cookies in self._cookies.values())

    def __repr__(self):
        cookies_list = list(self)
        if not cookies_list:
            return "<CookieJar[]>"
        cookies_repr = ", ".join(repr(cookie) for cookie in cookies_list)
        return f"<CookieJar[{cookies_repr}]>"

    def __str__(self):
        return self.__repr__()
