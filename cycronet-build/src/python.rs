use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::sync::Arc;
use std::time::Duration;
use pyo3_async_runtimes::tokio::future_into_py;

use crate::cronet::{SessionConfig, SessionManager};
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

    /// Close a session
    fn close_session(&self, session_id: String) -> PyResult<bool> {
        Ok(self.manager.close_session(&session_id))
    }

    /// List all active sessions
    fn list_sessions(&self) -> PyResult<Vec<String>> {
        Ok(self.manager.list_sessions())
    }
}

/// Python module
#[pymodule]
fn cronet_cloak(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCronetClient>()?;
    Ok(())
}

