"""
Cookie management classes for cycronet.
"""

from typing import Dict, Optional, Union


class Cookie:
    """Single Cookie object - similar to http.cookiejar.Cookie"""

    def __init__(self, name: str, value: str, domain: str = "", path: str = "/"):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path

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
        if domain not in self._cookies:
            self._cookies[domain] = {}
        self._cookies[domain][name] = Cookie(name, value, domain, path)

    def get(self, name: str, domain: str = "") -> Optional[str]:
        """Get cookie value"""
        if domain in self._cookies and name in self._cookies[domain]:
            return self._cookies[domain][name].value
        # If no domain specified, search all domains
        if not domain:
            for domain_cookies in self._cookies.values():
                if name in domain_cookies:
                    return domain_cookies[name].value
        return None

    def get_dict(self, domain: str = "") -> Dict[str, str]:
        """Get cookies dictionary"""
        if domain:
            if domain in self._cookies:
                return {name: cookie.value for name, cookie in self._cookies[domain].items()}
            return {}
        # Return all cookies
        result = {}
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                result[name] = cookie.value
        return result

    def update(self, cookies: Union[Dict[str, str], 'CookieJar'], domain: str = ""):
        """Update cookies"""
        if isinstance(cookies, CookieJar):
            for d, domain_cookies in cookies._cookies.items():
                for name, cookie in domain_cookies.items():
                    self.set(name, cookie.value, cookie.domain, cookie.path)
        elif isinstance(cookies, dict):
            for name, value in cookies.items():
                self.set(name, value, domain)

    def clear(self, domain: str = ""):
        """Clear cookies"""
        if domain:
            if domain in self._cookies:
                del self._cookies[domain]
        else:
            self._cookies.clear()

    def items(self):
        """Return all (name, value) pairs"""
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                yield (name, cookie.value)

    def keys(self):
        """Return all cookie names"""
        for domain_cookies in self._cookies.values():
            for name in domain_cookies.keys():
                yield name

    def values(self):
        """Return all cookie values"""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie.value

    def __iter__(self):
        """Iterate all Cookie objects"""
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie

    def __len__(self):
        """Return total cookie count"""
        return sum(len(domain_cookies) for domain_cookies in self._cookies.values())

    def __repr__(self):
        """Return RequestsCookieJar-like representation"""
        cookies_list = list(self)
        if not cookies_list:
            return "<CookieJar[]>"
        cookies_repr = ", ".join(repr(cookie) for cookie in cookies_list)
        return f"<CookieJar[{cookies_repr}]>"

    def __str__(self):
        return self.__repr__()
