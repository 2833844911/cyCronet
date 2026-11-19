"""Callback-based WebSocket support backed by the native Cronet handle."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ._types import HeadersType


# ``HttpRequestHeaders`` keeps the spelling and position used for the first
# insertion of a field.  Pin the browser spelling here instead of relying on
# callers to reproduce it, and put the WebSocket-generated fields in their
# Chrome HTTP/1.1 positions before Cronet fills in their values.
_CANONICAL_HEADER_NAMES: Dict[str, str] = {
    "pragma": "Pragma",
    "cache-control": "Cache-Control",
    "user-agent": "User-Agent",
    "upgrade": "Upgrade",
    "origin": "Origin",
    "sec-websocket-version": "Sec-WebSocket-Version",
    "accept-encoding": "Accept-Encoding",
    "accept-language": "Accept-Language",
    "cookie": "Cookie",
    "sec-websocket-protocol": "Sec-WebSocket-Protocol",
    "sec-websocket-key": "Sec-WebSocket-Key",
    "sec-websocket-extensions": "Sec-WebSocket-Extensions",
}

_BROWSER_WEBSOCKET_HEADER_ORDER = (
    "pragma",
    "cache-control",
    "user-agent",
    "upgrade",
    "origin",
    "sec-websocket-version",
    "accept-encoding",
    "accept-language",
    "cookie",
)

# Host and Connection are emitted by Chromium's HTTP transaction. Key and
# Extensions are regenerated for every upgrade by the WebSocket handshake.
_CHROMIUM_MANAGED_HEADERS = {
    "host",
    "connection",
    "sec-websocket-key",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
}


def _normalise_headers(
    headers: Optional[HeadersType], origin: Optional[str]
) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    items = [] if headers is None else (
        list(headers.items()) if isinstance(headers, dict) else list(headers)
    )
    fields: Dict[str, Tuple[str, str]] = {}
    unknown_order: List[str] = []
    selected_origin = origin
    for name, value in items:
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("WebSocket headers must be (str, str) pairs")
        lower_name = name.lower()
        if lower_name == "origin":
            if selected_origin is not None and selected_origin != value:
                raise ValueError("origin argument conflicts with the Origin header")
            selected_origin = value

        # Chromium adds these fields itself.  In particular, accepting a
        # caller-supplied key would make the response validation fail.
        if lower_name in _CHROMIUM_MANAGED_HEADERS:
            continue

        if lower_name in fields:
            raise ValueError(f"Duplicate WebSocket header: {name}")

        fields[lower_name] = (_CANONICAL_HEADER_NAMES.get(lower_name, name), value)
        if lower_name not in _BROWSER_WEBSOCKET_HEADER_ORDER:
            unknown_order.append(lower_name)

    # Pre-insertion fixes the on-the-wire position.  WebSocketStream then
    # replaces these values in place rather than appending them after Cookie.
    fields.setdefault("upgrade", ("Upgrade", "websocket"))
    fields.setdefault("sec-websocket-version", ("Sec-WebSocket-Version", "13"))
    if selected_origin is not None:
        fields["origin"] = ("Origin", selected_origin)

    result = [
        fields[name]
        for name in _BROWSER_WEBSOCKET_HEADER_ORDER
        if name in fields
    ]
    result.extend(fields[name] for name in unknown_order)
    return result, selected_origin


class WebSocketApp:
    """Run a native ``PyCronetWebSocket`` with websocket-client style callbacks."""

    def __init__(
        self,
        session: Any,
        url: str,
        *,
        on_open: Optional[Callable] = None,
        on_message: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        headers: Optional[HeadersType] = None,
        sub_protocols: Optional[str] = None,
        origin: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        # session_id is accepted for backward compatibility; the id of
        # ``session`` is always the one used.
        self._session = session
        self._url = url
        # Public so callers can also assign the callbacks after construction.
        self.on_open = on_open
        self.on_message = on_message
        self.on_close = on_close
        self.on_error = on_error
        self._headers, self._origin = _normalise_headers(headers, origin)
        self._sub_protocols = sub_protocols
        self._ws: Any = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._running

    def send(self, message: str) -> None:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._ws.send(message)

    def send_bytes(self, data: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._ws.send_bytes(data)

    def close(self, code: int = 1000, reason: str = "") -> None:
        """Start a graceful close and wait for the native close event."""
        if self._ws is not None:
            try:
                self._ws.close(code, reason)
            except Exception:
                # The native socket is already gone; stop the callback loop.
                self._running = False

    def stop(self) -> None:
        """Stop the callback loop after initiating a graceful close."""
        self.close()
        self._running = False

    def run_forever(self, blocking: bool = True, *, recv_timeout_ms: int = 500) -> None:
        """Run the callback loop.

        Args:
            blocking: run in the calling thread (default) or in a background thread.
            recv_timeout_ms: poll interval. Smaller reacts faster to ``stop()``.
        """
        if blocking:
            self._run(recv_timeout_ms)
        else:
            self.run_in_background(recv_timeout_ms=recv_timeout_ms)

    def run_in_background(self, *, daemon: bool = True,
                          recv_timeout_ms: int = 500) -> threading.Thread:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("WebSocket callback loop is already running")
        self._thread = threading.Thread(
            target=self._run, args=(recv_timeout_ms,), daemon=daemon
        )
        self._thread.start()
        return self._thread

    def wait(self, timeout: Optional[float] = None) -> bool:
        if self._thread is None:
            return not self._running
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _notify_error(self, message: str, net_error: int = -1) -> None:
        if self.on_error is not None:
            self.on_error(self, message, net_error)

    def _run(self, recv_timeout_ms: int = 500) -> None:
        try:
            native_client = self._session._client._client
            self._ws = native_client.websocket_connect(
                self._session._session_id,
                self._url,
                extra_headers=self._headers or None,
                origin=self._origin,
                sub_protocols=self._sub_protocols,
            )
            self._running = True
            while self._running:
                event = self._ws.recv_timeout(recv_timeout_ms)
                if event is None:
                    continue
                event_type = event.get("type")
                if event_type == "open":
                    if self.on_open is not None:
                        self.on_open(self)
                elif event_type == "message":
                    if self.on_message is not None:
                        self.on_message(self, event.get("data"), event.get("is_text", False))
                elif event_type == "close":
                    self._running = False
                    if self.on_close is not None:
                        self.on_close(
                            self,
                            event.get("code", 0),
                            event.get("reason", ""),
                            event.get("was_clean", False),
                        )
                elif event_type == "error":
                    self._running = False
                    self._notify_error(event.get("message", "Unknown error"), event.get("net_error", -1))
        except Exception as exc:
            # Without an on_error callback there is nowhere to report this,
            # so let it propagate instead of dropping it.
            if self.on_error is None:
                raise
            self._notify_error(str(exc))
        finally:
            self._running = False
            if self._ws is not None:
                self._ws = None
                # Let the network thread finish with the native socket before
                # the caller goes on to close the session.
                time.sleep(0.5)
