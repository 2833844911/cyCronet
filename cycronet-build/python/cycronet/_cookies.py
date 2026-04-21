"""
Cookie management classes for cycronet.
Designed to match requests.cookies.RequestsCookieJar behavior.
"""

from typing import Dict, Optional, Union, Iterator, Tuple


class Cookie:
    """Single Cookie object - similar to http.cookiejar.Cookie"""

    def __init__(self, name: str, value: str, domain: str = "", path: str = "/",
                 seq: int = 0):
        self.name = name
        self.value = value
        self.domain = self._normalize_domain(domain)
        self.path = path or "/"
        # Monotonic write sequence — used for last-write-wins dedup when
        # several cookies with the same name coexist across domain buckets
        # (matches requests / browser behaviour of "newest write wins").
        self.seq = seq

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Normalize domain: strip leading dot, lowercase, strip port."""
        if not domain:
            return ""
        domain = domain.lower().strip()
        if domain.startswith('.'):
            domain = domain[1:]
        if ':' in domain and not domain.startswith('['):
            domain = domain.rsplit(':', 1)[0]
        return domain

    def __repr__(self):
        return f"<Cookie {self.name}={self.value} for {self.domain}{self.path}>"

    def __str__(self):
        return f"{self.name}={self.value}"


def _domain_matches(cookie_domain: str, request_domain: str) -> bool:
    """Check if cookie domain matches request domain (RFC 6265).

    "example.com" matches: example.com, sub.example.com
    """
    if not cookie_domain or not request_domain:
        return not cookie_domain and not request_domain
    if request_domain == cookie_domain:
        return True
    if request_domain.endswith('.' + cookie_domain):
        return True
    return False


class CookieJar:
    """Cookie Jar manager - compatible with requests.cookies.RequestsCookieJar

    Storage: {domain: {name: Cookie}}
    Domain matching follows RFC 6265 rules.

    Supports an optional *default_domain* — when set, calls like
    ``set(name, value)`` or ``update(dict)`` that omit a domain will store
    cookies under the default domain instead of the empty (wildcard) bucket.
    The session wires this automatically from its ``base_url`` or the first
    outgoing request's host, so callers do not need to pass ``domain=`` every
    time for single-host clients.
    """

    def __init__(self, default_domain: Optional[str] = None):
        self._cookies: Dict[str, Dict[str, Cookie]] = {}
        self._default_domain: str = Cookie._normalize_domain(default_domain or "")
        self._seq_counter: int = 0

    def _next_seq(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    @property
    def default_domain(self) -> str:
        """Default domain used when a cookie is set/updated without an explicit domain."""
        return self._default_domain

    def set_default_domain(self, domain: Optional[str]) -> None:
        """Set (or clear, if falsy) the default domain used by subsequent writes."""
        self._default_domain = Cookie._normalize_domain(domain or "")

    def set(self, name: str, value: str, domain: Optional[str] = None, path: str = "/"):
        """Set a cookie.

        :param name: cookie name
        :param value: cookie value
        :param domain: cookie domain (auto-normalized). If ``None`` or empty,
            falls back to :attr:`default_domain`; if that is also empty the
            cookie is stored in the wildcard bucket (sent on every request).
        :param path: cookie path, defaults to "/"
        """
        effective = domain if domain else self._default_domain
        effective = Cookie._normalize_domain(effective or "")
        if effective not in self._cookies:
            self._cookies[effective] = {}
        self._cookies[effective][name] = Cookie(
            name, value, effective, path, seq=self._next_seq()
        )

    def get(self, name: str, default: Optional[str] = None, domain: Optional[str] = None) -> Optional[str]:
        """Get cookie value by name.

        If *domain* is specified, restricts the search to cookies whose
        domain matches (RFC 6265) — including wildcard cookies, which the
        request layer sends to every host.

        When multiple cookies with the same *name* match, the most recently
        written value wins (last-write-wins), so the result stays consistent
        with ``get_dict`` and with the Cookie header actually sent by the
        session.

        :param name: cookie name
        :param default: default value if not found
        :param domain: optional domain filter
        :return: cookie value or default
        """
        candidates = []
        if domain is not None:
            domain_norm = Cookie._normalize_domain(domain)
            for cookie_domain, domain_cookies in self._cookies.items():
                if name in domain_cookies and (
                    not cookie_domain or _domain_matches(cookie_domain, domain_norm)
                ):
                    candidates.append(domain_cookies[name])
        else:
            for domain_cookies in self._cookies.values():
                if name in domain_cookies:
                    candidates.append(domain_cookies[name])
        if not candidates:
            return default
        return max(candidates, key=lambda c: c.seq).value

    def get_dict(self, domain: Optional[str] = None) -> Dict[str, str]:
        """Get cookies as {name: value} dict.

        If *domain* is specified, returns cookies that would be sent to that
        domain using RFC 6265 matching. Wildcard (empty-domain) cookies —
        which the request layer treats as "send to every host" — are also
        included, so the result matches what actually goes on the wire.

        When several cookies share a name across different domain buckets
        (e.g. a wildcard ``_abck`` plus a host-scoped ``_abck`` written by a
        later Set-Cookie), **the most recently written value wins** — the
        same "last-write-wins" rule the request layer uses when building
        the Cookie header. This mirrors ``requests`` / browser behaviour and
        keeps ``session.cookies.update(fresh_ck)`` authoritative over stale
        response-scoped copies.

        If *domain* is None, returns ALL cookies (wildcard included), still
        deduped last-write-wins.

        :param domain: optional domain filter (the request domain to match against)
        :return: dict of {cookie_name: cookie_value}
        """
        matches = []  # list of Cookie objects that pass the domain filter
        if domain is not None:
            domain = Cookie._normalize_domain(domain)
            for cookie_domain, domain_cookies in self._cookies.items():
                if not cookie_domain or _domain_matches(cookie_domain, domain):
                    matches.extend(domain_cookies.values())
        else:
            for domain_cookies in self._cookies.values():
                matches.extend(domain_cookies.values())

        # Sort by write sequence ascending so dict-overwrite yields the
        # newest write for each name.
        matches.sort(key=lambda c: c.seq)
        return {c.name: c.value for c in matches}

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
        """Return a copy of this CookieJar, preserving *default_domain* and
        the relative write-ordering (seq) of every cookie so that
        last-write-wins results stay identical to the original.
        """
        new_jar = CookieJar(default_domain=self._default_domain or None)
        # Collect all cookies and replay them in original seq order so the
        # new jar's monotonic counter mirrors the relative ordering.
        all_cookies = sorted(self.iter_cookies(), key=lambda c: c.seq)
        for cookie in all_cookies:
            new_jar.set(cookie.name, cookie.value, cookie.domain, cookie.path)
        return new_jar

    def _deduped(self) -> Dict[str, 'Cookie']:
        """Return {name: Cookie} resolving same-name collisions via last-write-wins."""
        latest: Dict[str, 'Cookie'] = {}
        for domain_cookies in self._cookies.values():
            for name, cookie in domain_cookies.items():
                prev = latest.get(name)
                if prev is None or cookie.seq > prev.seq:
                    latest[name] = cookie
        return latest

    def items(self) -> Iterator[Tuple[str, str]]:
        """Yield (name, value) pairs, deduped by last-write-wins — matches
        ``requests.Session().cookies.items()`` so ``dict(jar)`` and
        ``get_dict()`` agree.
        """
        for name, cookie in self._deduped().items():
            yield (name, cookie.value)

    def keys(self) -> Iterator[str]:
        """Yield all cookie names (deduped)."""
        for name in self._deduped().keys():
            yield name

    def values(self) -> Iterator[str]:
        """Yield cookie values (deduped, last-write-wins)."""
        for cookie in self._deduped().values():
            yield cookie.value

    def list_domains(self) -> list:
        """Return list of all domains that have cookies."""
        return list(self._cookies.keys())

    def items_for_domain(self, domain: str) -> Iterator[Tuple[str, str]]:
        """Yield (name, value) pairs for cookies matching a domain.

        Uses the same matching rules as :meth:`get_dict`: RFC 6265 domain
        matching **plus** wildcard (empty-domain) cookies, deduped via
        last-write-wins so the result is consistent with what the session
        actually sends on the wire.

        :param domain: the request domain to match against
        """
        domain = Cookie._normalize_domain(domain)
        matches = []
        for cookie_domain, domain_cookies in self._cookies.items():
            if not cookie_domain or _domain_matches(cookie_domain, domain):
                matches.extend(domain_cookies.values())
        matches.sort(key=lambda c: c.seq)
        seen = {}
        for c in matches:
            seen[c.name] = c.value
        for name, value in seen.items():
            yield (name, value)

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

    def __iter__(self) -> Iterator[str]:
        """Iterate cookie **names** (deduped), so the jar behaves like a
        mapping — ``dict(jar)`` and ``{**jar}`` work the same way they do for
        ``requests.Session().cookies``. Use :meth:`iter_cookies` if you need
        the underlying :class:`Cookie` objects (including per-domain bucket
        duplicates).
        """
        return iter(self._deduped().keys())

    def iter_cookies(self) -> Iterator['Cookie']:
        """Yield every :class:`Cookie` object in the jar — including same-name
        entries in different domain/path buckets. Use this when you need the
        raw storage (e.g. for debugging or export).
        """
        for domain_cookies in self._cookies.values():
            for cookie in domain_cookies.values():
                yield cookie

    def __len__(self) -> int:
        """Number of distinct cookie names (after last-write-wins dedup), so
        ``len(jar)`` matches what ``dict(jar)`` produces.
        """
        return len(self._deduped())

    def __repr__(self):
        cookies_list = list(self.iter_cookies())
        if not cookies_list:
            return "<CookieJar[]>"
        cookies_repr = ", ".join(repr(cookie) for cookie in cookies_list)
        return f"<CookieJar[{cookies_repr}]>"

    def __str__(self):
        return self.__repr__()
