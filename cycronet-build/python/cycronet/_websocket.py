"""
WebSocketApp - High-level WebSocket client with callback interface.

Usage:
    from cycronet import CronetClient, WebSocketApp

    client = CronetClient(verify=False)
    session_id = client.create_session()

    def on_open(ws):
        ws.send("Hello")

    def on_message(ws, message):
        print(f"Received: {message}")

    def on_close(ws, code, reason):
        print(f"Closed: {code} {reason}")

    ws = WebSocketApp(
        client,
        session_id,
        "wss://echo.websocket.org",
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
    )
    ws.run_forever()
"""

import threading
from typing import Optional, Callable, Any


class WebSocketApp:
    """High-level WebSocket client with callback-based event handling.

    Wraps the native PyCronetWebSocket with a familiar callback interface
    similar to websocket-client's WebSocketApp.
    """

    def __init__(
        self,
        client,
        session_id: str,
        url: str,
        on_open: Optional[Callable] = None,
        on_message: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        sub_protocols: Optional[str] = None,
        origin: Optional[str] = None,
    ):
        """
        Args:
            client: CronetClient instance (must have a session created)
            session_id: Session ID from client.create_session()
            url: WebSocket URL (ws:// or wss://)
            on_open: Callback(ws) when connection opens
            on_message: Callback(ws, message) for text, Callback(ws, data) for binary
            on_close: Callback(ws, code, reason) when connection closes
            on_error: Callback(ws, error_message) on error
            sub_protocols: Optional comma-separated sub-protocols
            origin: Optional origin header
        """
        self._client = client
        self._session_id = session_id
        self._url = url
        self._on_open = on_open
        self._on_message = on_message
        self._on_close = on_close
        self._on_error = on_error
        self._sub_protocols = sub_protocols
        self._origin = origin
        self._ws = None
        self._running = False
        self._thread = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._running

    def send(self, message: str) -> None:
        """Send a text message."""
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._ws.send(message)

    def send_bytes(self, data: bytes) -> None:
        """Send binary data."""
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._ws.send_bytes(data)

    def close(self, code: int = 1000, reason: str = "") -> None:
        """Initiate graceful close."""
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close(code, reason)
            except Exception:
                pass

    def run_forever(self, blocking: bool = True) -> None:
        """Connect and start the event loop.

        Args:
            blocking: If True, blocks until connection closes.
                      If False, runs in a background thread.
        """
        if blocking:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        """Internal event loop."""
        try:
            # Connect
            self._ws = self._client._native.websocket_connect(
                self._session_id,
                self._url,
                self._sub_protocols,
                self._origin,
            )
            self._running = True

            # Event loop
            while self._running:
                try:
                    event = self._ws.recv_timeout(1000)
                except RuntimeError:
                    # Connection closed
                    break

                if event is None:
                    # Timeout, continue loop
                    continue

                event_type = event.get("type")

                if event_type == "open":
                    if self._on_open:
                        self._on_open(self)

                elif event_type == "message":
                    if self._on_message:
                        self._on_message(self, event.get("data"))

                elif event_type == "close":
                    self._running = False
                    if self._on_close:
                        self._on_close(
                            self,
                            event.get("code", 0),
                            event.get("reason", ""),
                        )

                elif event_type == "error":
                    self._running = False
                    if self._on_error:
                        self._on_error(self, event.get("message", "Unknown error"))

        except Exception as e:
            if self._on_error:
                self._on_error(self, str(e))
        finally:
            self._running = False
            self._ws = None
