use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::sync::Arc;
use std::time::Duration;

use crate::cronet::{SessionConfig, SessionManager, StreamChunk, CronetRequest, CronetWebSocket, WebSocketEvent};
use crate::cronet_pb::{Header, TargetRequest};
use std::sync::Mutex as StdMutex;

/// Python wrapper for SessionManager
#[pyclass]
pub struct PyCronetClient {
    manager: Arc<SessionManager>,
}

#[pymethods]
impl PyCronetClient {
    #[new]
    fn new() -> PyResult<Self> {
        Ok(PyCronetClient {
            manager: Arc::new(SessionManager::new()),
        })
    }

    /// Create a new session
    ///
    /// Args:
    ///     proxy_rules: Optional proxy rules string (e.g., "http://proxy.com:8080")
    ///     skip_cert_verify: Skip certificate verification
    ///     timeout_ms: Default timeout for requests
    ///     cipher_suites: Optional list of TLS cipher suite names (e.g., ["TLS_AES_128_GCM_SHA256", "TLS_RSA_WITH_AES_128_CBC_SHA"])
    ///     tls_curves: Optional list of TLS curve/group names (e.g., ["X25519MLKEM768", "X25519", "P-256"])
    ///     tls_extensions: Optional list of TLS extension control names (e.g., ["application_settings_old"])
    ///
    /// Returns:
    ///     Session ID string
    #[pyo3(signature = (proxy_rules=None, skip_cert_verify=None, timeout_ms=None, cipher_suites=None, tls_curves=None, tls_extensions=None))]
    fn create_session(
        &self,
        proxy_rules: Option<String>,
        skip_cert_verify: Option<bool>,
        timeout_ms: Option<u64>,
        cipher_suites: Option<Vec<String>>,
        tls_curves: Option<Vec<String>>,
        tls_extensions: Option<Vec<String>>,
    ) -> PyResult<String> {
        let config = SessionConfig {
            proxy_rules,
            skip_cert_verify: skip_cert_verify.unwrap_or(false),
            timeout_ms: timeout_ms.unwrap_or(30000),
            cipher_suites,
            tls_curves,
            tls_extensions,
            allow_redirects: true,  // 默认允许重定向
        };

        let session_id = self.manager.create_session(config);
        Ok(session_id)
    }

    /// Execute request using a session
    ///
    /// Args:
    ///     session_id: Session ID
    ///     url: Target URL
    ///     method: HTTP method (GET, POST, etc.)
    ///     headers: List of tuples [("name", "value"), ...]
    ///     body: Request body as bytes
    ///     allow_redirects: Whether to follow redirects (default: True)
    ///
    /// Returns:
    ///     Dict with keys: status_code, headers, body
    #[pyo3(signature = (session_id, url, method, headers=None, body=None, allow_redirects=true))]
    fn request(
        &self,
        py: Python,
        session_id: String,
        url: String,
        method: String,
        headers: Option<Vec<(String, String)>>,
        body: Option<Vec<u8>>,
        allow_redirects: bool,
    ) -> PyResult<PyObject> {
        let headers_vec = headers.unwrap_or_default();
        let body_vec = body.unwrap_or_default();

        // Build target request
        let target = TargetRequest {
            url,
            method,
            headers: headers_vec
                .into_iter()
                .map(|(name, value)| Header { name, value })
                .collect(),
            body: body_vec,
        };

        // Send request
        let result = self.manager.send_request(&session_id, &target, allow_redirects);

        match result {
            Some((request, rx, timeout_ms)) => {
                // Wait for response with timeout
                let timeout_duration = Duration::from_millis(timeout_ms);

                // Release GIL while waiting for response to allow concurrent requests
                let response_result = py.allow_threads(move || {
                    // Use a thread to implement timeout
                    let (timeout_tx, timeout_rx) = std::sync::mpsc::channel();
                    std::thread::spawn(move || {
                        match rx.blocking_recv() {
                            Ok(result) => {
                                let _ = timeout_tx.send(Some(result));
                            }
                            Err(_) => {
                                let _ = timeout_tx.send(None);
                            }
                        }
                    });

                    // Wait with timeout and keep request alive
                    let result = timeout_rx.recv_timeout(timeout_duration);
                    // Explicitly drop request here to ensure cleanup on timeout
                    drop(request);
                    result
                });

                match response_result {
                    Ok(Some(Ok(response))) => {
                        let dict = PyDict::new_bound(py);
                        dict.set_item("status_code", response.status_code)?;
                        dict.set_item("body", PyBytes::new_bound(py, &response.body))?;

                        // Convert headers
                        let headers_list = PyList::empty_bound(py);
                        for (name, value) in response.headers {
                            let tuple = (name, value);
                            headers_list.append(tuple)?;
                        }
                        dict.set_item("headers", headers_list)?;

                        Ok(dict.into_py(py))
                    }
                    Ok(Some(Err(e))) => {
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            format!("Request failed: {}", e)
                        ))
                    }
                    Ok(None) => {
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Channel closed unexpectedly"
                        ))
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                        // Request was already dropped in the closure above
                        Err(PyErr::new::<pyo3::exceptions::PyTimeoutError, _>(
                            format!("Request timeout after {}ms", timeout_ms)
                        ))
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Timeout channel disconnected"
                        ))
                    }
                }
            }
            None => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Failed to send request (session not found or concurrent limit reached)"
            )),
        }
    }

    /// Execute streaming request using a session (synchronous)
    ///
    /// Returns: PyStreamReader with status_code, headers, and next_chunk_sync() method
    #[pyo3(signature = (session_id, url, method, headers=None, body=None, allow_redirects=true))]
    fn request_stream_sync(
        &self,
        py: Python,
        session_id: String,
        url: String,
        method: String,
        headers: Option<Vec<(String, String)>>,
        body: Option<Vec<u8>>,
        allow_redirects: bool,
    ) -> PyResult<PyObject> {
        let headers_vec = headers.unwrap_or_default();
        let body_vec = body.unwrap_or_default();

        let target = TargetRequest {
            url,
            method,
            headers: headers_vec
                .into_iter()
                .map(|(name, value)| Header { name, value })
                .collect(),
            body: body_vec,
        };

        let result = self.manager.send_request_stream(&session_id, &target, allow_redirects);

        match result {
            Some((request, mut rx, timeout_ms)) => {
                let timeout_duration = Duration::from_millis(timeout_ms);

                // Wait for headers (first chunk), release GIL
                let first_chunk = py.allow_threads(|| {
                    let (tx, timeout_rx) = std::sync::mpsc::channel();
                    std::thread::spawn(move || {
                        let chunk = rx.blocking_recv();
                        let _ = tx.send((chunk, rx));
                    });
                    timeout_rx.recv_timeout(timeout_duration)
                });

                match first_chunk {
                    Ok((Some(StreamChunk::Headers { status_code, headers }), rx)) => {
                        let reader = PyStreamReader {
                            rx: StdMutex::new(Some(rx)),
                            _request: StdMutex::new(Some(request)),
                            status_code,
                            headers_list: headers,
                        };
                        Ok(Py::new(py, reader)?.into_py(py))
                    }
                    Ok((Some(StreamChunk::Error(e)), _)) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            format!("Request failed: {}", e)
                        ))
                    }
                    Ok((Some(StreamChunk::Done), _)) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Stream completed without headers"
                        ))
                    }
                    Ok((Some(StreamChunk::Data(_)), _)) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Unexpected data before headers"
                        ))
                    }
                    Ok((None, _)) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Stream closed unexpectedly"
                        ))
                    }
                    Err(_) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyTimeoutError, _>(
                            format!("Request timeout after {}ms", timeout_ms)
                        ))
                    }
                }
            }
            None => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Failed to send stream request (session not found or concurrent limit reached)"
            )),
        }
    }

    /// Close a session
    fn close_session(&self, session_id: String) -> PyResult<bool> {
        Ok(self.manager.close_session(&session_id))
    }

    /// List all active sessions
    fn list_sessions(&self) -> PyResult<Vec<String>> {
        Ok(self.manager.list_sessions())
    }

    /// Create a WebSocket connection
    ///
    /// Args:
    ///     session_id: Session ID (must be created first with create_session)
    ///     url: WebSocket URL (ws:// or wss://)
    ///     sub_protocols: Optional comma-separated sub-protocols
    ///     origin: Optional origin header
    ///
    /// Returns:
    ///     PyCronetWebSocket object
    #[pyo3(signature = (session_id, url, sub_protocols=None, origin=None))]
    fn websocket_connect(
        &self,
        session_id: String,
        url: String,
        sub_protocols: Option<String>,
        origin: Option<String>,
    ) -> PyResult<PyCronetWebSocket> {
        let engine_ptr = self.manager.get_engine_ptr(&session_id)
            .ok_or_else(|| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("Session '{}' not found", session_id)
                )
            })?;

        let ws = CronetWebSocket::new(engine_ptr).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)
        })?;

        ws.connect(
            &url,
            sub_protocols.as_deref(),
            origin.as_deref(),
        ).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)
        })?;

        Ok(PyCronetWebSocket {
            ws: Arc::new(StdMutex::new(Some(ws))),
        })
    }
}

/// Python wrapper for streaming response reader
#[pyclass]
pub struct PyStreamReader {
    rx: StdMutex<Option<tokio::sync::mpsc::UnboundedReceiver<StreamChunk>>>,
    _request: StdMutex<Option<CronetRequest>>,
    #[pyo3(get)]
    status_code: i32,
    headers_list: Vec<(String, String)>,
}

#[pymethods]
impl PyStreamReader {
    /// Get response headers as list of (name, value) tuples
    #[getter]
    fn headers(&self, py: Python) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for (name, value) in &self.headers_list {
            list.append((name.as_str(), value.as_str()))?;
        }
        Ok(list.into())
    }

    /// Read next chunk synchronously (releases GIL)
    /// Returns bytes or None when stream is complete
    fn next_chunk_sync(&self, py: Python) -> PyResult<Option<PyObject>> {
        let rx_mutex = &self.rx;

        let chunk = py.allow_threads(|| {
            let mut guard = rx_mutex.lock().unwrap();
            if let Some(ref mut recv) = *guard {
                recv.blocking_recv()
            } else {
                None
            }
        });

        match chunk {
            Some(StreamChunk::Data(data)) => {
                Ok(Some(PyBytes::new_bound(py, &data).into()))
            }
            Some(StreamChunk::Done) | None => {
                Ok(None)
            }
            Some(StreamChunk::Error(e)) => {
                Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("Stream error: {}", e)
                ))
            }
            Some(StreamChunk::Headers { .. }) => {
                // Unexpected headers in data stream, skip and try next
                self.next_chunk_sync(py)
            }
        }
    }

    /// Close the stream reader and release resources
    fn close(&self) -> PyResult<()> {
        // Drop receiver
        if let Ok(mut guard) = self.rx.lock() {
            *guard = None;
        }
        // Drop request handle (triggers cancel if still active)
        if let Ok(mut guard) = self._request.lock() {
            *guard = None;
        }
        Ok(())
    }
}

/// Python WebSocket wrapper
#[pyclass]
pub struct PyCronetWebSocket {
    ws: Arc<StdMutex<Option<CronetWebSocket>>>,
}

#[pymethods]
impl PyCronetWebSocket {
    /// Send a text message
    fn send(&self, message: &str) -> PyResult<()> {
        let guard = self.ws.lock().unwrap();
        let ws = guard.as_ref().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed")
        })?;
        ws.send_text(message).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)
        })
    }

    /// Send binary data
    fn send_bytes(&self, data: &[u8]) -> PyResult<()> {
        let guard = self.ws.lock().unwrap();
        let ws = guard.as_ref().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed")
        })?;
        ws.send_binary(data).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)
        })
    }

    /// Receive the next event (blocks, releases GIL).
    /// Returns a dict: {"type": "open"|"message"|"close"|"error", ...}
    fn recv(&self, py: Python) -> PyResult<PyObject> {
        let ws_arc = self.ws.clone();
        let event = py.allow_threads(move || {
            let guard = ws_arc.lock().unwrap();
            if let Some(ref ws) = *guard {
                ws.rx.recv().ok()
            } else {
                None
            }
        });

        match event {
            Some(WebSocketEvent::Open { protocol }) => {
                let dict = PyDict::new_bound(py);
                dict.set_item("type", "open")?;
                dict.set_item("protocol", protocol)?;
                Ok(dict.into())
            }
            Some(WebSocketEvent::Message { is_text, data }) => {
                let dict = PyDict::new_bound(py);
                dict.set_item("type", "message")?;
                if is_text {
                    let text = String::from_utf8_lossy(&data);
                    dict.set_item("data", text.as_ref())?;
                    dict.set_item("is_text", true)?;
                } else {
                    dict.set_item("data", PyBytes::new_bound(py, &data))?;
                    dict.set_item("is_text", false)?;
                }
                Ok(dict.into())
            }
            Some(WebSocketEvent::Close { was_clean, code, reason }) => {
                let dict = PyDict::new_bound(py);
                dict.set_item("type", "close")?;
                dict.set_item("was_clean", was_clean)?;
                dict.set_item("code", code)?;
                dict.set_item("reason", reason)?;
                Ok(dict.into())
            }
            Some(WebSocketEvent::Error { net_error, message }) => {
                let dict = PyDict::new_bound(py);
                dict.set_item("type", "error")?;
                dict.set_item("net_error", net_error)?;
                dict.set_item("message", message)?;
                Ok(dict.into())
            }
            None => {
                Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    "WebSocket connection closed"
                ))
            }
        }
    }

    /// Receive with timeout in milliseconds. Returns None on timeout.
    #[pyo3(signature = (timeout_ms=5000))]
    fn recv_timeout(&self, py: Python, timeout_ms: u64) -> PyResult<Option<PyObject>> {
        let ws_arc = self.ws.clone();
        let dur = Duration::from_millis(timeout_ms);
        let event = py.allow_threads(move || {
            let guard = ws_arc.lock().unwrap();
            if let Some(ref ws) = *guard {
                ws.rx.recv_timeout(dur).ok()
            } else {
                None
            }
        });

        match event {
            Some(evt) => {
                // Reuse recv logic by sending event back through a temp channel
                // Simpler: just inline the conversion
                let dict = PyDict::new_bound(py);
                match evt {
                    WebSocketEvent::Open { protocol } => {
                        dict.set_item("type", "open")?;
                        dict.set_item("protocol", protocol)?;
                    }
                    WebSocketEvent::Message { is_text, data } => {
                        dict.set_item("type", "message")?;
                        if is_text {
                            let text = String::from_utf8_lossy(&data);
                            dict.set_item("data", text.as_ref())?;
                            dict.set_item("is_text", true)?;
                        } else {
                            dict.set_item("data", PyBytes::new_bound(py, &data))?;
                            dict.set_item("is_text", false)?;
                        }
                    }
                    WebSocketEvent::Close { was_clean, code, reason } => {
                        dict.set_item("type", "close")?;
                        dict.set_item("was_clean", was_clean)?;
                        dict.set_item("code", code)?;
                        dict.set_item("reason", reason)?;
                    }
                    WebSocketEvent::Error { net_error, message } => {
                        dict.set_item("type", "error")?;
                        dict.set_item("net_error", net_error)?;
                        dict.set_item("message", message)?;
                    }
                }
                Ok(Some(dict.into()))
            }
            None => Ok(None),
        }
    }

    /// Initiate graceful close
    #[pyo3(signature = (code=1000, reason=""))]
    fn close(&self, code: u16, reason: &str) -> PyResult<()> {
        let guard = self.ws.lock().unwrap();
        if let Some(ref ws) = *guard {
            ws.close(code, reason).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)
            })
        } else {
            Ok(())
        }
    }
}

/// Python module
#[pymodule]
fn cronet_cloak(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCronetClient>()?;
    m.add_class::<PyStreamReader>()?;
    m.add_class::<PyCronetWebSocket>()?;
    Ok(())
}
