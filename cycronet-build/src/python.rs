use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;
use pyo3_async_runtimes::tokio::future_into_py;
use tokio::sync::Mutex as TokioMutex;

use crate::cronet::{SessionConfig, SessionManager, StreamChunk, CronetRequest, CronetWebSocket, WebSocketEvent};
use crate::cronet_pb::{Header, TargetRequest};

/// Python wrapper for SessionManager
#[pyclass]
pub struct PyCronetClient {
    manager: Arc<SessionManager>,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyCronetClient {
    #[new]
    fn new() -> PyResult<Self> {
        // Create a multi-threaded Tokio runtime for async operations
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                format!("Failed to create Tokio runtime: {}", e)
            ))?;

        Ok(PyCronetClient {
            manager: Arc::new(SessionManager::new()),
            runtime: Arc::new(runtime),
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

    /// Execute request using a session (true async with pyo3-asyncio)
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
    ///     Awaitable that resolves to Dict with keys: status_code, headers, body
    #[pyo3(signature = (session_id, url, method, headers=None, body=None, allow_redirects=true))]
    fn request<'py>(
        &self,
        py: Python<'py>,
        session_id: String,
        url: String,
        method: String,
        headers: Option<Vec<(String, String)>>,
        body: Option<Vec<u8>>,
        allow_redirects: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
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

        // Clone Arc for async task
        let manager = self.manager.clone();

        // Convert Rust async to Python awaitable (TRUE ASYNC!)
        future_into_py(py, async move {
            // Send request
            let (request, rx, timeout_ms) = manager
                .send_request(&session_id, &target, allow_redirects)
                .ok_or_else(|| {
                    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Failed to send request (session not found or concurrent limit reached)"
                    )
                })?;

            // Wait for response with timeout (TRUE ASYNC - no blocking!)
            let timeout_duration = Duration::from_millis(timeout_ms);
            let result = tokio::time::timeout(timeout_duration, rx).await;

            // Drop request handle
            drop(request);

            // Convert result to Python dict
            match result {
                Ok(Ok(Ok(response))) => {
                    Python::with_gil(|py| {
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

                        Ok::<PyObject, PyErr>(dict.into())
                    })
                }
                Ok(Ok(Err(e))) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("Request failed: {}", e)
                )),
                Ok(Err(_)) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    "Channel closed unexpectedly"
                )),
                Err(_) => Err(PyErr::new::<pyo3::exceptions::PyTimeoutError, _>(
                    format!("Request timeout after {}ms", timeout_ms)
                )),
            }
        })
    }

    /// Execute request using a session (blocking/sync version)
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
    fn request_sync(
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
                let timeout_duration = Duration::from_millis(timeout_ms);

                // Release GIL and block on async operation
                let response_result = py.allow_threads(|| {
                    self.runtime.block_on(async {
                        tokio::time::timeout(timeout_duration, rx).await
                    })
                });

                // Drop request handle
                drop(request);

                match response_result {
                    Ok(Ok(Ok(response))) => {
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

                        Ok(dict.into())
                    }
                    Ok(Ok(Err(e))) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        format!("Request failed: {}", e)
                    )),
                    Ok(Err(_)) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Channel closed unexpectedly"
                    )),
                    Err(_) => Err(PyErr::new::<pyo3::exceptions::PyTimeoutError, _>(
                        format!("Request timeout after {}ms", timeout_ms)
                    )),
                }
            }
            None => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Failed to send request (session not found or concurrent limit reached)"
            )),
        }
    }

    /// Execute streaming request using a session (blocking/sync version)
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
                let runtime = self.runtime.clone();

                // Wait for headers (first chunk), release GIL
                let first_chunk = py.allow_threads(|| {
                    runtime.block_on(async {
                        tokio::time::timeout(timeout_duration, rx.recv()).await
                    })
                });

                match first_chunk {
                    Ok(Some(StreamChunk::Headers { status_code, headers })) => {
                        let reader = PyStreamReader {
                            rx: Arc::new(TokioMutex::new(Some(rx))),
                            runtime: self.runtime.clone(),
                            _request: Arc::new(StdMutex::new(Some(request))),
                            status_code,
                            headers_list: headers,
                        };
                        Ok(Py::new(py, reader)?.into_py(py))
                    }
                    Ok(Some(StreamChunk::Error(e))) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            format!("Request failed: {}", e)
                        ))
                    }
                    Ok(Some(StreamChunk::Done)) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Stream completed without headers"
                        ))
                    }
                    Ok(Some(StreamChunk::Data(_))) => {
                        drop(request);
                        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                            "Unexpected data before headers"
                        ))
                    }
                    Ok(None) => {
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

    /// Execute streaming request using a session (true async version)
    ///
    /// Returns: Awaitable that resolves to PyStreamReader
    #[pyo3(signature = (session_id, url, method, headers=None, body=None, allow_redirects=true))]
    fn request_stream<'py>(
        &self,
        py: Python<'py>,
        session_id: String,
        url: String,
        method: String,
        headers: Option<Vec<(String, String)>>,
        body: Option<Vec<u8>>,
        allow_redirects: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
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

        let manager = self.manager.clone();
        let runtime = self.runtime.clone();

        future_into_py(py, async move {
            let (request, mut rx, timeout_ms) = manager
                .send_request_stream(&session_id, &target, allow_redirects)
                .ok_or_else(|| {
                    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Failed to send stream request (session not found or concurrent limit reached)"
                    )
                })?;

            let timeout_duration = Duration::from_millis(timeout_ms);
            let first_chunk = tokio::time::timeout(timeout_duration, rx.recv()).await;

            match first_chunk {
                Ok(Some(StreamChunk::Headers { status_code, headers })) => {
                    Python::with_gil(|py| {
                        let reader = PyStreamReader {
                            rx: Arc::new(TokioMutex::new(Some(rx))),
                            runtime,
                            _request: Arc::new(StdMutex::new(Some(request))),
                            status_code,
                            headers_list: headers,
                        };
                        Ok::<PyObject, PyErr>(Py::new(py, reader)?.into_py(py))
                    })
                }
                Ok(Some(StreamChunk::Error(e))) => {
                    drop(request);
                    Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        format!("Request failed: {}", e)
                    ))
                }
                Ok(Some(StreamChunk::Done)) => {
                    drop(request);
                    Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Stream completed without headers"
                    ))
                }
                Ok(Some(StreamChunk::Data(_))) => {
                    drop(request);
                    Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "Unexpected data before headers"
                    ))
                }
                Ok(None) => {
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
        })
    }

    /// Close a session
    fn close_session(&self, session_id: String) -> PyResult<bool> {
        Ok(self.manager.close_session(&session_id))
    }

    /// List all active sessions
    fn list_sessions(&self) -> PyResult<Vec<String>> {
        Ok(self.manager.list_sessions())
    }

    /// Create a WebSocket connection using a session
    ///
    /// Args:
    ///     session_id: Session ID
    ///     url: WebSocket URL (ws:// or wss://)
    ///
    /// Returns:
    ///     PyCronetWebSocket instance
    fn websocket_connect(&self, session_id: String, url: String) -> PyResult<PyCronetWebSocket> {
        let engine_ptr = self.manager.get_engine_ptr(&session_id)
            .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                format!("Session not found: {}", session_id)
            ))?;

        let ws = CronetWebSocket::new(engine_ptr)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;

        ws.connect(&url, None, None)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;

        Ok(PyCronetWebSocket {
            inner: Arc::new(StdMutex::new(Some(ws))),
        })
    }
}

/// Python wrapper for streaming response reader
#[pyclass]
pub struct PyStreamReader {
    rx: Arc<TokioMutex<Option<tokio::sync::mpsc::UnboundedReceiver<StreamChunk>>>>,
    runtime: Arc<tokio::runtime::Runtime>,
    _request: Arc<StdMutex<Option<CronetRequest>>>,
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
        let runtime = self.runtime.clone();
        let rx = self.rx.clone();

        let chunk = py.allow_threads(|| {
            runtime.block_on(async {
                let mut guard = rx.lock().await;
                if let Some(ref mut recv) = *guard {
                    recv.recv().await
                } else {
                    None
                }
            })
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

    /// Read next chunk asynchronously
    /// Returns awaitable that resolves to bytes or None
    fn next_chunk<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let rx = self.rx.clone();

        future_into_py(py, async move {
            let mut guard = rx.lock().await;
            let chunk = if let Some(ref mut recv) = *guard {
                recv.recv().await
            } else {
                None
            };
            drop(guard);

            match chunk {
                Some(StreamChunk::Data(data)) => {
                    Python::with_gil(|py| {
                        Ok::<Option<PyObject>, PyErr>(Some(PyBytes::new_bound(py, &data).into()))
                    })
                }
                Some(StreamChunk::Done) | None => {
                    Ok(None::<PyObject>)
                }
                Some(StreamChunk::Error(e)) => {
                    Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        format!("Stream error: {}", e)
                    ))
                }
                Some(StreamChunk::Headers { .. }) => {
                    Ok(None::<PyObject>)
                }
            }
        })
    }

    /// Close the stream reader and release resources
    fn close(&self) -> PyResult<()> {
        // Drop receiver
        if let Ok(mut guard) = self.rx.try_lock() {
            *guard = None;
        }
        // Drop request handle (triggers cancel if still active)
        if let Ok(mut guard) = self._request.lock() {
            *guard = None;
        }
        Ok(())
    }
}

/// Python-visible WebSocket handle
#[pyclass]
pub struct PyCronetWebSocket {
    inner: Arc<StdMutex<Option<CronetWebSocket>>>,
}

#[pymethods]
impl PyCronetWebSocket {
    /// Send a text message
    fn send(&self, message: String) -> PyResult<()> {
        let guard = self.inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
        let ws = guard.as_ref().ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed"))?;
        ws.send_text(&message).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))
    }

    /// Send binary data
    fn send_bytes(&self, data: Vec<u8>) -> PyResult<()> {
        let guard = self.inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
        let ws = guard.as_ref().ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed"))?;
        ws.send_binary(&data).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))
    }

    /// Initiate graceful close
    #[pyo3(signature = (code=1000, reason="".to_string()))]
    fn close(&self, code: u16, reason: String) -> PyResult<()> {
        let guard = self.inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
        let ws = guard.as_ref().ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed"))?;
        ws.close(code, &reason).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))
    }

    /// Blocking receive next event (releases GIL)
    fn recv(&self, py: Python) -> PyResult<PyObject> {
        let inner = self.inner.clone();
        py.allow_threads(|| {
            let guard = inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
            let ws = guard.as_ref().ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed"))?;
            ws.rx.recv().map_err(|_| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Channel closed"))
        }).and_then(|evt| Python::with_gil(|py| ws_event_to_dict(py, evt)))
    }

    /// Explicitly destroy the underlying WebSocket (releases socket back to pool).
    /// Must be called before close_session to avoid crashes.
    fn destroy(&self) -> PyResult<()> {
        let mut guard = self.inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
        // Take and drop the CronetWebSocket, which calls Cronet_WebSocket_Destroy
        let _ = guard.take();
        Ok(())
    }

    /// Receive with timeout in milliseconds (releases GIL). Returns None on timeout.
    fn recv_timeout(&self, py: Python, timeout_ms: u64) -> PyResult<Option<PyObject>> {
        let inner = self.inner.clone();
        let result = py.allow_threads(|| {
            let guard = inner.lock().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Lock error: {}", e)))?;
            let ws = guard.as_ref().ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("WebSocket is closed"))?;
            Ok::<Option<WebSocketEvent>, PyErr>(ws.rx.recv_timeout(Duration::from_millis(timeout_ms)).ok())
        })?;
        match result {
            Some(evt) => Python::with_gil(|py| ws_event_to_dict(py, evt).map(Some)),
            None => Ok(None),
        }
    }
}

fn ws_event_to_dict(py: Python, evt: WebSocketEvent) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    match evt {
        WebSocketEvent::Open { protocol } => {
            dict.set_item("type", "open")?;
            dict.set_item("protocol", protocol)?;
        }
        WebSocketEvent::Message { is_text, data } => {
            dict.set_item("type", "message")?;
            dict.set_item("is_text", is_text)?;
            if is_text {
                dict.set_item("data", String::from_utf8_lossy(&data).into_owned())?;
            } else {
                dict.set_item("data", PyBytes::new_bound(py, &data))?;
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
    Ok(dict.into())
}

/// Python module
#[pymodule]
fn cronet_cloak(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCronetClient>()?;
    m.add_class::<PyStreamReader>()?;
    m.add_class::<PyCronetWebSocket>()?;
    Ok(())
}

