"""
Callback-based WebSocket client, similar to websocket-client's WebSocketApp.

Usage:
    import cycronet

    def on_open(ws):
        print("Connected!")
        ws.send("Hello")

    def on_message(ws, message, is_text):
        print(f"Received: {message}")

    def on_close(ws, code, reason, was_clean):
        print(f"Closed: {code}")

    def on_error(ws, error, net_error):
        print(f"Error: {error}")

    client = cycronet.CronetClient(verify=False)
    ws = client.websocket(
        "wss://example.com/ws",
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_forever()      # blocks current thread
    # or
    ws.run_in_background() # runs in a background thread
"""

import threading
import time
from typing import Optional, Callable, Any


class WebSocketApp:
    """Callback-based WebSocket wrapper over PyCronetWebSocket.

    Callbacks:
        on_open(ws)
        on_message(ws, message, is_text)
        on_close(ws, code, reason, was_clean)
        on_error(ws, error, net_error)
    """

    def __init__(
        self,
        client,          # CronetClient instance
        url: str,
        *,
        on_open: Optional[Callable] = None,
        on_message: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        headers: Optional[list] = None,
        session_id: Optional[str] = None,
    ):
        self._client = client
        self._url = url
        self.on_open = on_open
        self.on_message = on_message
        self.on_close = on_close
        self.on_error = on_error
        self._headers = headers  # list of (name, value) tuples

        self._session_id = session_id
        self._own_session = session_id is None
        self._raw_ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._closed = False

    # --- public API ---

    def send(self, message: str):
        """Send a text message."""
        if self._raw_ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._raw_ws.send(message)

    def send_bytes(self, data: bytes):
        """Send a binary message."""
        if self._raw_ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._raw_ws.send_bytes(data)

    def close(self, code: int = 1000, reason: str = ""):
        """Initiate graceful close. The event loop will stop after
        receiving the close/error event from the server."""
        if self._raw_ws is not None:
            try:
                self._raw_ws.close(code, reason)
            except Exception:
                # If close fails, force-stop the loop
                self._running = False

    def stop(self):
        """Force-stop the event loop immediately (no graceful close)."""
        self._running = False

    def run_forever(self, *, recv_timeout_ms: int = 500):
        """Block the current thread, dispatching events to callbacks.

        Args:
            recv_timeout_ms: Poll interval in ms. Smaller = more responsive
                             to close(), larger = less CPU.
        """
        self._connect()
        self._running = True
        try:
            self._event_loop(recv_timeout_ms)
        finally:
            self._cleanup()

    def run_in_background(self, *, daemon: bool = True,
                          recv_timeout_ms: int = 500) -> threading.Thread:
        """Start the event loop in a background thread.

        Returns the thread object.
        """
        self._thread = threading.Thread(
            target=self.run_forever,
            kwargs={"recv_timeout_ms": recv_timeout_ms},
            daemon=daemon,
        )
        self._thread.start()
        return self._thread

    def wait(self, timeout: Optional[float] = None):
        """Wait for the background thread to finish."""
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def connected(self) -> bool:
        return self._running and self._raw_ws is not None

    # --- internal ---

    def _connect(self):
        # _client is a Session object; _client._client._client is the PyCronetClient
        session = self._client
        self._session_id = session._session_id
        raw_client = session._client._client
        self._raw_ws = raw_client.websocket_connect(
            self._session_id, self._url, self._headers
        )

    def _event_loop(self, recv_timeout_ms: int):
        while self._running:
            evt = self._raw_ws.recv_timeout(recv_timeout_ms)
            if evt is None:
                continue

            evt_type = evt.get("type")

            if evt_type == "open":
                if self.on_open:
                    self.on_open(self)

            elif evt_type == "message":
                if self.on_message:
                    self.on_message(
                        self,
                        evt.get("data"),
                        evt.get("is_text", True),
                    )

            elif evt_type == "close":
                if self.on_close:
                    self.on_close(
                        self,
                        evt.get("code", 0),
                        evt.get("reason", ""),
                        evt.get("was_clean", False),
                    )
                self._running = False

            elif evt_type == "error":
                if self.on_error:
                    self.on_error(
                        self,
                        evt.get("message", ""),
                        evt.get("net_error", 0),
                    )
                self._running = False

    def _cleanup(self):
        if self._closed:
            return
        self._closed = True
        self._running = False
        if self._raw_ws is not None:
            try:
                del self._raw_ws
            except Exception:
                pass
            self._raw_ws = None
            time.sleep(0.5)
