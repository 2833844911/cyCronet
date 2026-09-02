//! C DLL export layer for cycronet.
//!
//! Provides `extern "C"` functions that wrap the Rust `SessionManager` / `CronetWebSocket`
//! APIs so that C/C++ callers can consume them through `cycronet.dll`.
//!
//! Build with: `cargo build --release --features cdll --no-default-features`

#![allow(clippy::missing_safety_doc)]

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use crate::cronet::{CronetWebSocket, SessionConfig, SessionManager, StreamChunk, WebSocketEvent};
use crate::cronet_pb::{Header, TargetRequest};

// ---------------------------------------------------------------------------
// Global runtime & session manager (lazy-initialized via cycronet_init)
// ---------------------------------------------------------------------------

struct Global {
    runtime: tokio::runtime::Runtime,
    manager: SessionManager,
}

static GLOBAL: OnceLock<Mutex<Option<Arc<Global>>>> = OnceLock::new();

fn global_cell() -> &'static Mutex<Option<Arc<Global>>> {
    GLOBAL.get_or_init(|| Mutex::new(None))
}

fn global() -> Option<Arc<Global>> {
    match global_cell().lock() {
        Ok(guard) => guard.clone(),
        Err(poisoned) => {
            eprintln!("[cycronet] global mutex poisoned, recovering");
            poisoned.into_inner().clone()
        }
    }
}

// ---------------------------------------------------------------------------
// Opaque handle types
// ---------------------------------------------------------------------------

/// Opaque response handle returned by synchronous request APIs.
pub struct CycronetResponse {
    status_code: i32,
    headers: Vec<(CString, CString)>,
    body: Vec<u8>,
}

/// Opaque stream handle for streaming reads.
pub struct CycronetStream {
    rx: tokio::sync::mpsc::UnboundedReceiver<StreamChunk>,
    _request: crate::cronet::CronetRequest,
    status_code: i32,
    headers: Vec<(CString, CString)>,
    headers_received: bool,
    done: bool,
}

/// Opaque WebSocket handle.
pub struct CycronetWebSocket {
    inner: Option<CronetWebSocket>,
    /// Handle for the callback reader thread (if set_callback was used).
    reader_thread: Option<std::thread::JoinHandle<()>>,
    callback_mode: bool,
    callback_stop: Arc<AtomicBool>,
}

// ---------------------------------------------------------------------------
// Helper: parse C header array  "name\0value\0name\0value\0..."
// ---------------------------------------------------------------------------

unsafe fn parse_headers(
    names: *const *const c_char,
    values: *const *const c_char,
    count: c_int,
) -> Vec<Header> {
    let mut out = Vec::new();
    if names.is_null() || values.is_null() || count <= 0 {
        return out;
    }
    for i in 0..count as usize {
        let n = CStr::from_ptr(*names.add(i)).to_string_lossy().into_owned();
        let v = CStr::from_ptr(*values.add(i))
            .to_string_lossy()
            .into_owned();
        out.push(Header { name: n, value: v });
    }
    out
}

unsafe fn c_str_opt(p: *const c_char) -> Option<String> {
    if p.is_null() {
        None
    } else {
        Some(CStr::from_ptr(p).to_string_lossy().into_owned())
    }
}

unsafe fn c_str(p: *const c_char) -> String {
    if p.is_null() {
        String::new()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}

/// Helper: convert a C array of C-strings to Vec<String>
unsafe fn c_str_array(arr: *const *const c_char, count: c_int) -> Option<Vec<String>> {
    if arr.is_null() || count <= 0 {
        return None;
    }
    let mut v = Vec::with_capacity(count as usize);
    for i in 0..count as usize {
        v.push(CStr::from_ptr(*arr.add(i)).to_string_lossy().into_owned());
    }
    Some(v)
}

// ---------------------------------------------------------------------------
// Send wrappers: convert raw pointers to usize for thread/async safety
// ---------------------------------------------------------------------------

/// Context for async HTTP request — all pointers stored as usize.
struct AsyncRequestCtx {
    callback: CycronetRequestCallback,
    user_data: usize, // *mut c_void as usize
}
unsafe impl Send for AsyncRequestCtx {}

/// Context for async stream read.
struct AsyncStreamCtx {
    stream: usize, // *mut CycronetStream as usize
    callback: CycronetStreamCallback,
    user_data: usize,
}
unsafe impl Send for AsyncStreamCtx {}

/// Context for WebSocket callback thread.
struct WsCallbackCtx {
    callback: CycronetWsCallback,
    user_data: usize,
}
unsafe impl Send for WsCallbackCtx {}

// =====================================================================
// 1. INIT / SHUTDOWN
// =====================================================================

/// Initialize the cycronet library. Must be called once before any other API.
/// Returns 0 on success, -1 if already initialized or on error.
#[no_mangle]
pub unsafe extern "C" fn cycronet_init() -> c_int {
    let mut guard = match global_cell().lock() {
        Ok(guard) => guard,
        Err(poisoned) => {
            eprintln!("[cycronet] global mutex poisoned during init, recovering");
            poisoned.into_inner()
        }
    };
    if guard.is_some() {
        return 0;
    }

    match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => {
            *guard = Some(Arc::new(Global {
                runtime: rt,
                manager: SessionManager::new(),
            }));
            0
        }
        Err(e) => {
            eprintln!("[cycronet] Failed to create runtime: {}", e);
            -1
        }
    }
}

/// Shut down the cycronet library. All sessions are destroyed.
/// After this call, no other API may be used.
#[no_mangle]
pub unsafe extern "C" fn cycronet_shutdown() {
    // Drop global – this will drop SessionManager (which drops all Sessions/Engines)
    // and then drop the tokio Runtime.
    let mut guard = match global_cell().lock() {
        Ok(guard) => guard,
        Err(poisoned) => {
            eprintln!("[cycronet] global mutex poisoned during shutdown, recovering");
            poisoned.into_inner()
        }
    };
    *guard = None;
}

// =====================================================================
// 2. SESSION MANAGEMENT
// =====================================================================

/// Session configuration passed to `cycronet_session_create`.
#[repr(C)]
pub struct CycronetSessionConfig {
    /// Proxy rules string (e.g. "socks5://user:pass@host:port"), or null.
    pub proxy_rules: *const c_char,
    /// Skip TLS certificate verification (0 = false, 1 = true).
    pub skip_cert_verify: c_int,
    /// Default request timeout in milliseconds.
    pub timeout_ms: u64,
    /// Allow redirects by default (0 = false, 1 = true).
    pub allow_redirects: c_int,
    /// Custom TLS cipher suite names (array of C-strings), or null.
    pub cipher_suites: *const *const c_char,
    pub cipher_suites_count: c_int,
    /// Custom TLS curve/group names, or null.
    pub tls_curves: *const *const c_char,
    pub tls_curves_count: c_int,
    /// Custom TLS extension control names, or null.
    pub tls_extensions: *const *const c_char,
    pub tls_extensions_count: c_int,
}

/// Create a new session. Returns a session ID string that the caller must free
/// with `cycronet_free_string`. Returns null on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_session_create(
    config: *const CycronetSessionConfig,
) -> *mut c_char {
    let Some(g) = global() else {
        return ptr::null_mut();
    };
    let cfg = if config.is_null() {
        SessionConfig {
            proxy_rules: None,
            skip_cert_verify: false,
            timeout_ms: 30000,
            user_agent: None,
            accept_language: None,
            cipher_suites: None,
            tls_curves: None,
            tls_extensions: None,
            allow_redirects: true,
        }
    } else {
        let c = &*config;
        SessionConfig {
            proxy_rules: c_str_opt(c.proxy_rules),
            skip_cert_verify: c.skip_cert_verify != 0,
            timeout_ms: if c.timeout_ms == 0 {
                30000
            } else {
                c.timeout_ms
            },
            user_agent: None,
            accept_language: None,
            cipher_suites: c_str_array(c.cipher_suites, c.cipher_suites_count),
            tls_curves: c_str_array(c.tls_curves, c.tls_curves_count),
            tls_extensions: c_str_array(c.tls_extensions, c.tls_extensions_count),
            allow_redirects: c.allow_redirects != 0,
        }
    };

    let sid = g.manager.create_session(cfg);
    if sid.is_empty() {
        return ptr::null_mut();
    }
    CString::new(sid).map_or(ptr::null_mut(), |s| s.into_raw())
}

/// Destroy / close a session by ID.
/// Returns 1 on success, 0 if session not found.
#[no_mangle]
pub unsafe extern "C" fn cycronet_session_destroy(session_id: *const c_char) -> c_int {
    if session_id.is_null() {
        return 0;
    }
    let Some(g) = global() else {
        return 0;
    };
    let sid = c_str(session_id);
    if g.manager.close_session(&sid) {
        1
    } else {
        0
    }
}

/// Free a string previously returned by cycronet (e.g. session ID).
#[no_mangle]
pub unsafe extern "C" fn cycronet_free_string(s: *mut c_char) {
    if !s.is_null() {
        let _ = CString::from_raw(s);
    }
}

// =====================================================================
// 3. SYNCHRONOUS HTTP REQUEST
// =====================================================================

/// Execute a synchronous HTTP request. Blocks until the response is complete.
///
/// Returns an opaque `CycronetResponse*` on success, or null on failure.
/// The caller must free the response with `cycronet_response_free`.
#[no_mangle]
pub unsafe extern "C" fn cycronet_request_sync(
    session_id: *const c_char,
    url: *const c_char,
    method: *const c_char,
    header_names: *const *const c_char,
    header_values: *const *const c_char,
    header_count: c_int,
    body: *const u8,
    body_len: usize,
    allow_redirects: c_int,
) -> *mut CycronetResponse {
    if session_id.is_null() || url.is_null() || method.is_null() {
        return ptr::null_mut();
    }
    let Some(g) = global() else {
        return ptr::null_mut();
    };
    let sid = c_str(session_id);
    let headers = parse_headers(header_names, header_values, header_count);

    let body_vec = if body.is_null() || body_len == 0 {
        Vec::new()
    } else {
        std::slice::from_raw_parts(body, body_len).to_vec()
    };

    let target = TargetRequest {
        url: c_str(url),
        method: c_str(method),
        headers,
        body: body_vec,
    };

    let result = g.manager.send_request(&sid, &target, allow_redirects != 0);
    let (request, rx, timeout_ms) = match result {
        Some(v) => v,
        None => return ptr::null_mut(),
    };

    // Block on the receiver
    let res = g.runtime.block_on(async {
        match tokio::time::timeout(Duration::from_millis(timeout_ms), rx).await {
            Ok(Ok(Ok(r))) => Some(r),
            Ok(Ok(Err(e))) => {
                eprintln!("[cycronet] request error: {}", e);
                None
            }
            Ok(Err(_)) => {
                eprintln!("[cycronet] request channel dropped");
                None
            }
            Err(_) => {
                eprintln!("[cycronet] request timed out");
                None
            }
        }
    });

    // Drop the request handle (cleanup Cronet resources)
    drop(request);

    match res {
        Some(r) => Box::into_raw(Box::new(CycronetResponse {
            status_code: r.status_code,
            headers: r
                .headers
                .into_iter()
                .map(|(n, v)| {
                    (
                        CString::new(n).unwrap_or_default(),
                        CString::new(v).unwrap_or_default(),
                    )
                })
                .collect(),
            body: r.body,
        })),
        None => ptr::null_mut(),
    }
}

/// Get the HTTP status code from a response.
#[no_mangle]
pub unsafe extern "C" fn cycronet_response_status(resp: *const CycronetResponse) -> c_int {
    if resp.is_null() {
        return 0;
    }
    (*resp).status_code
}

/// Get the number of response headers.
#[no_mangle]
pub unsafe extern "C" fn cycronet_response_header_count(resp: *const CycronetResponse) -> c_int {
    if resp.is_null() {
        return 0;
    }
    (*resp).headers.len() as c_int
}

/// Get a response header by index. Writes the name and value pointers.
/// The pointers are valid until the response is freed.
/// Returns 0 on success, -1 on invalid index.
#[no_mangle]
pub unsafe extern "C" fn cycronet_response_header_at(
    resp: *const CycronetResponse,
    index: c_int,
    out_name: *mut *const c_char,
    out_value: *mut *const c_char,
) -> c_int {
    if resp.is_null() {
        return -1;
    }
    let r = &*resp;
    let idx = index as usize;
    if idx >= r.headers.len() {
        return -1;
    }
    // Return pointers into CString buffers (null-terminated, valid while response lives)
    if !out_name.is_null() {
        *out_name = r.headers[idx].0.as_ptr();
    }
    if !out_value.is_null() {
        *out_value = r.headers[idx].1.as_ptr();
    }
    0
}

/// Get the response body pointer and length.
/// The pointer is valid until the response is freed.
#[no_mangle]
pub unsafe extern "C" fn cycronet_response_body(
    resp: *const CycronetResponse,
    out_data: *mut *const u8,
    out_len: *mut usize,
) -> c_int {
    if resp.is_null() {
        return -1;
    }
    let r = &*resp;
    if !out_data.is_null() {
        *out_data = r.body.as_ptr();
    }
    if !out_len.is_null() {
        *out_len = r.body.len();
    }
    0
}

/// Free a response previously returned by `cycronet_request_sync`.
#[no_mangle]
pub unsafe extern "C" fn cycronet_response_free(resp: *mut CycronetResponse) {
    if !resp.is_null() {
        let _ = Box::from_raw(resp);
    }
}

// =====================================================================
// 4. ASYNCHRONOUS HTTP REQUEST (callback)
// =====================================================================

/// Callback signature for async HTTP request completion.
/// `user_data` is the opaque pointer passed by the caller.
/// `resp` is a `CycronetResponse*` on success, or null on failure.
/// The callee must free `resp` with `cycronet_response_free` if non-null.
pub type CycronetRequestCallback =
    Option<unsafe extern "C" fn(user_data: *mut c_void, resp: *mut CycronetResponse)>;

/// Execute an asynchronous HTTP request. Returns immediately.
/// The callback is invoked on a background thread when the request completes.
/// Returns 0 on success (request submitted), -1 on failure to submit.
#[no_mangle]
pub unsafe extern "C" fn cycronet_request_async(
    session_id: *const c_char,
    url: *const c_char,
    method: *const c_char,
    header_names: *const *const c_char,
    header_values: *const *const c_char,
    header_count: c_int,
    body: *const u8,
    body_len: usize,
    allow_redirects: c_int,
    callback: CycronetRequestCallback,
    user_data: *mut c_void,
) -> c_int {
    if session_id.is_null() || url.is_null() || method.is_null() || callback.is_none() {
        return -1;
    }
    let Some(g) = global() else {
        return -1;
    };
    let sid = c_str(session_id);
    let headers = parse_headers(header_names, header_values, header_count);

    let body_vec = if body.is_null() || body_len == 0 {
        Vec::new()
    } else {
        std::slice::from_raw_parts(body, body_len).to_vec()
    };

    let target = TargetRequest {
        url: c_str(url),
        method: c_str(method),
        headers,
        body: body_vec,
    };

    let result = g.manager.send_request(&sid, &target, allow_redirects != 0);
    let (request, rx, timeout_ms) = match result {
        Some(v) => v,
        None => return -1,
    };

    let ctx = AsyncRequestCtx {
        callback,
        user_data: user_data as usize,
    };

    g.runtime.spawn(async move {
        let res = match tokio::time::timeout(Duration::from_millis(timeout_ms), rx).await {
            Ok(Ok(Ok(r))) => Some(r),
            _ => None,
        };

        drop(request);

        let resp_ptr = match res {
            Some(r) => Box::into_raw(Box::new(CycronetResponse {
                status_code: r.status_code,
                headers: r
                    .headers
                    .into_iter()
                    .map(|(n, v)| {
                        (
                            CString::new(n).unwrap_or_default(),
                            CString::new(v).unwrap_or_default(),
                        )
                    })
                    .collect(),
                body: r.body,
            })),
            None => ptr::null_mut(),
        };

        if let Some(callback) = ctx.callback {
            callback(ctx.user_data as *mut c_void, resp_ptr);
        }
    });

    0
}

// =====================================================================
// 5. STREAMING HTTP REQUEST
// =====================================================================

/// Start a streaming HTTP request. Returns an opaque `CycronetStream*`.
/// Use `cycronet_stream_read` to consume data chunks.
/// Returns null on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_open(
    session_id: *const c_char,
    url: *const c_char,
    method: *const c_char,
    header_names: *const *const c_char,
    header_values: *const *const c_char,
    header_count: c_int,
    body: *const u8,
    body_len: usize,
    allow_redirects: c_int,
) -> *mut CycronetStream {
    if session_id.is_null() || url.is_null() || method.is_null() {
        return ptr::null_mut();
    }
    let Some(g) = global() else {
        return ptr::null_mut();
    };
    let sid = c_str(session_id);
    let headers = parse_headers(header_names, header_values, header_count);

    let body_vec = if body.is_null() || body_len == 0 {
        Vec::new()
    } else {
        std::slice::from_raw_parts(body, body_len).to_vec()
    };

    let target = TargetRequest {
        url: c_str(url),
        method: c_str(method),
        headers,
        body: body_vec,
    };

    let result = g
        .manager
        .send_request_stream(&sid, &target, allow_redirects != 0);
    let (request, rx, _timeout_ms) = match result {
        Some(v) => v,
        None => return ptr::null_mut(),
    };

    Box::into_raw(Box::new(CycronetStream {
        rx,
        _request: request,
        status_code: 0,
        headers: Vec::new(),
        headers_received: false,
        done: false,
    }))
}

/// Read the next chunk from a stream (blocking).
///
/// Returns:
///   1  = data chunk written to `out_buf` (up to `buf_len` bytes), `out_read` set.
///   0  = stream finished (no more data).
///  -1  = error (stream handle invalid or error from server).
///   2  = headers received; use `cycronet_stream_status` / `cycronet_stream_header_*`
///         to inspect. No body data in this call.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_read(
    stream: *mut CycronetStream,
    out_buf: *mut u8,
    buf_len: usize,
    out_read: *mut usize,
) -> c_int {
    if stream.is_null() {
        return -1;
    }
    let s = &mut *stream;
    if s.done {
        return 0;
    }

    let Some(g) = global() else {
        return -1;
    };
    let chunk = g.runtime.block_on(async { s.rx.recv().await });

    match chunk {
        Some(StreamChunk::Headers {
            status_code,
            headers,
        }) => {
            s.status_code = status_code;
            s.headers = headers
                .into_iter()
                .map(|(n, v)| {
                    (
                        CString::new(n).unwrap_or_default(),
                        CString::new(v).unwrap_or_default(),
                    )
                })
                .collect();
            s.headers_received = true;
            2 // headers event
        }
        Some(StreamChunk::Data(data)) => {
            let copy_len = data.len().min(buf_len);
            if !out_buf.is_null() && copy_len > 0 {
                ptr::copy_nonoverlapping(data.as_ptr(), out_buf, copy_len);
            }
            if !out_read.is_null() {
                *out_read = copy_len;
            }
            1
        }
        Some(StreamChunk::Done) => {
            s.done = true;
            0
        }
        Some(StreamChunk::Error(e)) => {
            eprintln!("[cycronet] stream error: {}", e);
            s.done = true;
            -1
        }
        None => {
            s.done = true;
            0
        }
    }
}

/// Callback for async stream reads.
/// `chunk_type`: 2=headers, 1=data, 0=done, -1=error
pub type CycronetStreamCallback = Option<
    unsafe extern "C" fn(
        user_data: *mut c_void,
        chunk_type: c_int,
        data: *const u8,
        data_len: usize,
    ),
>;

/// Read the next chunk from a stream asynchronously.
/// The callback is invoked on a background thread.
/// Returns 0 on success, -1 if stream is invalid or already done.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_read_async(
    stream: *mut CycronetStream,
    callback: CycronetStreamCallback,
    user_data: *mut c_void,
) -> c_int {
    if stream.is_null() || callback.is_none() {
        return -1;
    }
    let s = &mut *stream;
    if s.done {
        return -1;
    }

    let ctx = AsyncStreamCtx {
        stream: stream as usize,
        callback,
        user_data: user_data as usize,
    };

    let Some(g) = global() else {
        return -1;
    };
    g.runtime.spawn(async move {
        let s = &mut *(ctx.stream as *mut CycronetStream);
        let chunk = s.rx.recv().await;
        let ud = ctx.user_data as *mut c_void;
        let Some(callback) = ctx.callback else {
            return;
        };
        match chunk {
            Some(StreamChunk::Headers {
                status_code,
                headers,
            }) => {
                s.status_code = status_code;
                s.headers = headers
                    .into_iter()
                    .map(|(n, v)| {
                        (
                            CString::new(n).unwrap_or_default(),
                            CString::new(v).unwrap_or_default(),
                        )
                    })
                    .collect();
                s.headers_received = true;
                callback(ud, 2, ptr::null(), 0);
            }
            Some(StreamChunk::Data(data)) => {
                callback(ud, 1, data.as_ptr(), data.len());
            }
            Some(StreamChunk::Done) => {
                s.done = true;
                callback(ud, 0, ptr::null(), 0);
            }
            Some(StreamChunk::Error(_)) => {
                s.done = true;
                callback(ud, -1, ptr::null(), 0);
            }
            None => {
                s.done = true;
                callback(ud, 0, ptr::null(), 0);
            }
        }
    });

    0
}

/// Get stream response status code (available after headers event).
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_status(stream: *const CycronetStream) -> c_int {
    if stream.is_null() {
        return 0;
    }
    (*stream).status_code
}

/// Get stream response header count.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_header_count(stream: *const CycronetStream) -> c_int {
    if stream.is_null() {
        return 0;
    }
    (*stream).headers.len() as c_int
}

/// Get stream response header by index.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_header_at(
    stream: *const CycronetStream,
    index: c_int,
    out_name: *mut *const c_char,
    out_value: *mut *const c_char,
) -> c_int {
    if stream.is_null() {
        return -1;
    }
    let s = &*stream;
    let idx = index as usize;
    if idx >= s.headers.len() {
        return -1;
    }
    if !out_name.is_null() {
        *out_name = s.headers[idx].0.as_ptr();
    }
    if !out_value.is_null() {
        *out_value = s.headers[idx].1.as_ptr();
    }
    0
}

/// Close and free a stream.
#[no_mangle]
pub unsafe extern "C" fn cycronet_stream_close(stream: *mut CycronetStream) {
    if !stream.is_null() {
        let _ = Box::from_raw(stream);
    }
}

// =====================================================================
// 6. WEBSOCKET
// =====================================================================

/// WebSocket event type constants.
pub const CYCRONET_WS_EVENT_OPEN: c_int = 0;
pub const CYCRONET_WS_EVENT_MESSAGE: c_int = 1;
pub const CYCRONET_WS_EVENT_CLOSE: c_int = 2;
pub const CYCRONET_WS_EVENT_ERROR: c_int = 3;

/// WebSocket event callback.
///
/// - `event_type`: one of `CYCRONET_WS_EVENT_*`
/// - For MESSAGE: `is_text`=1 if text, `data`/`data_len` contain the payload.
/// - For CLOSE: `code` is the close code, `data` is the reason string (UTF-8).
/// - For ERROR: `code` is the net error, `data` is the error message.
/// - For OPEN: `data` is the negotiated sub-protocol.
pub type CycronetWsCallback = Option<
    unsafe extern "C" fn(
        user_data: *mut c_void,
        event_type: c_int,
        is_text: c_int,
        code: c_int,
        data: *const u8,
        data_len: usize,
    ),
>;

/// Create a WebSocket on the given session.
/// Returns an opaque `CycronetWebSocket*`, or null on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_create(session_id: *const c_char) -> *mut CycronetWebSocket {
    if session_id.is_null() {
        return ptr::null_mut();
    }
    let Some(g) = global() else {
        return ptr::null_mut();
    };
    let sid = c_str(session_id);

    let (engine_ptr, session_live) = match g.manager.get_engine_handle(&sid) {
        Some(handle) => handle,
        None => return ptr::null_mut(),
    };

    // Safety: engine_ptr is owned by a live session in SessionManager. C callers
    // must destroy the websocket before destroying its session.
    match unsafe { CronetWebSocket::new_with_lifetime(engine_ptr, session_live) } {
        Ok(ws) => Box::into_raw(Box::new(CycronetWebSocket {
            inner: Some(ws),
            reader_thread: None,
            callback_mode: false,
            callback_stop: Arc::new(AtomicBool::new(false)),
        })),
        Err(e) => {
            eprintln!("[cycronet] ws_create error: {}", e);
            ptr::null_mut()
        }
    }
}

/// Connect the WebSocket to a URL.
/// `sub_protocols`, `origin`, `extra_headers` may be null.
/// Returns 0 on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_connect(
    ws: *mut CycronetWebSocket,
    url: *const c_char,
    sub_protocols: *const c_char,
    origin: *const c_char,
    extra_headers: *const c_char,
) -> c_int {
    if ws.is_null() || url.is_null() {
        return -1;
    }
    let w = &*ws;
    let url_s = c_str(url);
    let protos = if sub_protocols.is_null() {
        None
    } else {
        Some(c_str(sub_protocols))
    };
    let orig = if origin.is_null() {
        None
    } else {
        Some(c_str(origin))
    };
    let hdrs = if extra_headers.is_null() {
        None
    } else {
        Some(c_str(extra_headers))
    };

    match w
        .inner
        .as_ref()
        .ok_or_else(|| "WebSocket is closed".to_string())
        .and_then(|inner| {
            inner.connect(&url_s, protos.as_deref(), orig.as_deref(), hdrs.as_deref())
        }) {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("[cycronet] ws_connect error: {}", e);
            -1
        }
    }
}

/// Send a text message on the WebSocket.
/// Returns 0 on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_send_text(
    ws: *mut CycronetWebSocket,
    text: *const c_char,
    len: usize,
) -> c_int {
    if ws.is_null() || text.is_null() {
        return -1;
    }
    let w = &*ws;
    let s = if len == 0 {
        c_str(text)
    } else {
        let slice = std::slice::from_raw_parts(text as *const u8, len);
        String::from_utf8_lossy(slice).into_owned()
    };
    let Some(inner) = w.inner.as_ref() else {
        return -1;
    };
    match inner.send_text(&s) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Send a binary message on the WebSocket.
/// Returns 0 on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_send_binary(
    ws: *mut CycronetWebSocket,
    data: *const u8,
    len: usize,
) -> c_int {
    if ws.is_null() || data.is_null() {
        return -1;
    }
    let w = &*ws;
    let slice = std::slice::from_raw_parts(data, len);
    let Some(inner) = w.inner.as_ref() else {
        return -1;
    };
    match inner.send_binary(slice) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Receive the next WebSocket event (blocking).
///
/// Returns the event type (CYCRONET_WS_EVENT_*), or -1 on error/channel closed.
///
/// For MESSAGE events:
///   - `out_is_text` is set to 1 for text, 0 for binary.
///   - `out_data` / `out_data_len` point to the payload (valid until next recv or ws_destroy).
///
/// For CLOSE events:
///   - `out_code` is the close code.
///
/// Returned data buffers must be released with `cycronet_free_bytes`.
unsafe fn set_ws_output(bytes: Vec<u8>, out_data: *mut *const u8, out_data_len: *mut usize) {
    let boxed = bytes.into_boxed_slice();
    let len = boxed.len();
    let ptr = if len == 0 {
        ptr::null()
    } else {
        boxed.as_ptr()
    };
    if !out_data.is_null() {
        *out_data = ptr;
    }
    if !out_data_len.is_null() {
        *out_data_len = len;
    }
    if len > 0 {
        std::mem::forget(boxed);
    }
}

#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_recv(
    ws: *mut CycronetWebSocket,
    out_is_text: *mut c_int,
    out_code: *mut c_int,
    out_data: *mut *const u8,
    out_data_len: *mut usize,
) -> c_int {
    if ws.is_null() {
        return -1;
    }
    let w = &mut *ws;
    if w.callback_mode {
        return -1;
    }
    let Some(inner) = w.inner.as_mut() else {
        return -1;
    };

    match inner.rx.recv() {
        Ok(event) => match event {
            WebSocketEvent::Open { protocol } => {
                // Store protocol temporarily – caller can read via out_data
                set_ws_output(protocol.into_bytes(), out_data, out_data_len);
                CYCRONET_WS_EVENT_OPEN
            }
            WebSocketEvent::Message { is_text, data } => {
                if !out_is_text.is_null() {
                    *out_is_text = if is_text { 1 } else { 0 };
                }
                set_ws_output(data, out_data, out_data_len);
                CYCRONET_WS_EVENT_MESSAGE
            }
            WebSocketEvent::Close {
                was_clean: _,
                code,
                reason,
            } => {
                if !out_code.is_null() {
                    *out_code = code as c_int;
                }
                set_ws_output(reason.into_bytes(), out_data, out_data_len);
                CYCRONET_WS_EVENT_CLOSE
            }
            WebSocketEvent::Error { net_error, message } => {
                if !out_code.is_null() {
                    *out_code = net_error;
                }
                set_ws_output(message.into_bytes(), out_data, out_data_len);
                CYCRONET_WS_EVENT_ERROR
            }
        },
        Err(_) => -1,
    }
}

/// Set a callback for WebSocket events (async mode).
/// The callback is invoked on a background thread for each event.
/// This function spawns a reader loop and returns immediately.
/// Returns 0 on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_set_callback(
    ws: *mut CycronetWebSocket,
    callback: CycronetWsCallback,
    user_data: *mut c_void,
) -> c_int {
    if ws.is_null() || callback.is_none() {
        return -1;
    }

    let w = &mut *ws;
    if w.callback_mode {
        return -1;
    }
    let Some(inner) = w.inner.as_mut() else {
        return -1;
    };

    let (_dummy_tx, dummy_rx) = std::sync::mpsc::channel();
    let rx = std::mem::replace(&mut inner.rx, dummy_rx);
    let stop = w.callback_stop.clone();
    stop.store(false, Ordering::Release);
    let ctx = WsCallbackCtx {
        callback,
        user_data: user_data as usize,
    };

    let handle = std::thread::spawn(move || {
        let ud = ctx.user_data as *mut c_void;
        let Some(callback) = ctx.callback else {
            return;
        };
        loop {
            if stop.load(Ordering::Acquire) {
                break;
            }
            match rx.recv_timeout(Duration::from_millis(100)) {
                Ok(event) => {
                    match event {
                        WebSocketEvent::Open { protocol } => {
                            callback(
                                ud,
                                CYCRONET_WS_EVENT_OPEN,
                                0,
                                0,
                                protocol.as_ptr(),
                                protocol.len(),
                            );
                        }
                        WebSocketEvent::Message { is_text, data } => {
                            callback(
                                ud,
                                CYCRONET_WS_EVENT_MESSAGE,
                                if is_text { 1 } else { 0 },
                                0,
                                data.as_ptr(),
                                data.len(),
                            );
                        }
                        WebSocketEvent::Close {
                            was_clean: _,
                            code,
                            reason,
                        } => {
                            callback(
                                ud,
                                CYCRONET_WS_EVENT_CLOSE,
                                0,
                                code as c_int,
                                reason.as_ptr(),
                                reason.len(),
                            );
                            break; // close → exit loop
                        }
                        WebSocketEvent::Error { net_error, message } => {
                            callback(
                                ud,
                                CYCRONET_WS_EVENT_ERROR,
                                0,
                                net_error,
                                message.as_ptr(),
                                message.len(),
                            );
                            break; // error → exit loop
                        }
                    }
                }
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => continue,
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
            }
        }
    });

    // Store thread handle so ws_destroy can join it.
    w.reader_thread = Some(handle);
    w.callback_mode = true;

    0
}

/// Close the WebSocket connection gracefully.
/// Returns 0 on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_close(
    ws: *mut CycronetWebSocket,
    code: u16,
    reason: *const c_char,
) -> c_int {
    if ws.is_null() {
        return -1;
    }
    let w = &*ws;
    let reason_owned = c_str(reason);
    let reason_s: &str = &reason_owned;
    let Some(inner) = w.inner.as_ref() else {
        return -1;
    };
    match inner.close(code, reason_s) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Destroy and free the WebSocket handle.
#[no_mangle]
pub unsafe extern "C" fn cycronet_ws_destroy(ws: *mut CycronetWebSocket) {
    if !ws.is_null() {
        let mut boxed = Box::from_raw(ws);
        boxed.callback_stop.store(true, Ordering::Release);
        // Drop inner first – this closes the mpsc channel, causing the
        // reader thread's recv() to return Err and exit the loop.
        if let Some(inner) = boxed.inner.take() {
            drop(inner);
        }
        // Now join the reader thread to ensure it has fully exited
        // before we free the CycronetWebSocket memory.
        if let Some(handle) = boxed.reader_thread.take() {
            let _ = handle.join();
        }
    }
}

// =====================================================================
// 7. UTILITY
// =====================================================================

/// Get the cycronet library version string.
/// The returned pointer is static and must NOT be freed.
#[no_mangle]
pub unsafe extern "C" fn cycronet_version() -> *const c_char {
    static VERSION_CSTR: OnceLock<CString> = OnceLock::new();
    VERSION_CSTR
        .get_or_init(|| {
            CString::new(env!("CARGO_PKG_VERSION")).expect("package version has no nul bytes")
        })
        .as_ptr()
}

/// Enable or disable verbose debug logging.
#[no_mangle]
pub unsafe extern "C" fn cycronet_set_verbose(enable: c_int) {
    crate::VERBOSE_MODE.store(enable != 0, std::sync::atomic::Ordering::Relaxed);
}

/// Enable or disable request file logging (req.txt).
#[no_mangle]
pub unsafe extern "C" fn cycronet_set_debug(enable: c_int) {
    crate::DEBUG_MODE.store(enable != 0, std::sync::atomic::Ordering::Relaxed);
}

/// Free a data buffer returned by ws_recv (protocol, message data, reason, etc.).
#[no_mangle]
pub unsafe extern "C" fn cycronet_free_bytes(data: *mut u8, len: usize) {
    if !data.is_null() && len > 0 {
        let slice = std::ptr::slice_from_raw_parts_mut(data, len);
        let _ = Box::from_raw(slice);
    }
}
