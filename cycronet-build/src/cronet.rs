use crate::cronet_c::*;
use crate::cronet_pb::proxy_config::ProxyType;
use crate::VERBOSE_MODE;
use std::collections::HashMap;
use std::ffi::{c_void, CStr, CString};
use std::ptr;
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use tokio::sync::{mpsc, oneshot};

// SEH guard: Windows structured exception handling wrappers.
// Catches access violations (0xc0000005) inside cronet.dll so they become
// error codes instead of fatal crashes.
#[cfg(target_os = "windows")]
extern "C" {
    fn seh_safe_destroy(
        ptr: *mut std::ffi::c_void,
        destroy_fn: unsafe extern "C" fn(*mut std::ffi::c_void),
    ) -> u32;
    fn seh_safe_shutdown(
        ptr: *mut std::ffi::c_void,
        shutdown_fn: unsafe extern "C" fn(*mut std::ffi::c_void) -> i32,
    ) -> i32;
    fn seh_safe_call1(
        ptr: *mut std::ffi::c_void,
        call_fn: unsafe extern "C" fn(*mut std::ffi::c_void),
    ) -> u32;
}

/// Safely call a Cronet Destroy function, catching SEH exceptions on Windows.
/// All Cronet_*_Destroy functions have the ABI: `extern "C" fn(*mut T)`.
/// We transmute the function pointer to `extern "C" fn(*mut c_void)` which is
/// layout-compatible since all pointer types have the same ABI representation.
#[cfg(target_os = "windows")]
macro_rules! seh_destroy {
    ($ptr:expr, $destroy_fn:expr, $name:expr) => {
        if !$ptr.is_null() {
            let fn_ptr: unsafe extern "C" fn(*mut std::ffi::c_void) =
                std::mem::transmute($destroy_fn as *const () as usize);
            let code = seh_safe_destroy($ptr as *mut std::ffi::c_void, fn_ptr);
            if code != 0 {
                eprintln!(
                    "[cycronet/SEH] {} caught exception 0x{:08x}, ptr={:?}",
                    $name, code, $ptr
                );
            }
        }
    };
}

#[cfg(not(target_os = "windows"))]
macro_rules! seh_destroy {
    ($ptr:expr, $destroy_fn:expr, $name:expr) => {
        if !$ptr.is_null() {
            $destroy_fn($ptr);
        }
    };
}

/// Safely call Cronet_Engine_Shutdown (returns i32), catching SEH exceptions.
#[cfg(target_os = "windows")]
macro_rules! seh_shutdown {
    ($ptr:expr) => {
        if !$ptr.is_null() {
            let fn_ptr: unsafe extern "C" fn(*mut std::ffi::c_void) -> i32 =
                std::mem::transmute(Cronet_Engine_Shutdown as *const () as usize);
            let ret = seh_safe_shutdown($ptr as *mut std::ffi::c_void, fn_ptr);
            if ret == -1 {
                eprintln!(
                    "[cycronet/SEH] Engine_Shutdown caught exception, ptr={:?}",
                    $ptr
                );
            }
        }
    };
}

#[cfg(not(target_os = "windows"))]
macro_rules! seh_shutdown {
    ($ptr:expr) => {
        if !$ptr.is_null() {
            Cronet_Engine_Shutdown($ptr);
        }
    };
}

/// Safely call any Cronet void function with one pointer arg, catching SEH exceptions.
/// Use for Cancel, Start, Runnable_Run, etc.
#[cfg(target_os = "windows")]
macro_rules! seh_call {
    ($ptr:expr, $fn:expr, $name:expr) => {{
        if !$ptr.is_null() {
            let fn_ptr: unsafe extern "C" fn(*mut std::ffi::c_void) =
                std::mem::transmute($fn as *const () as usize);
            let code = seh_safe_call1($ptr as *mut std::ffi::c_void, fn_ptr);
            if code != 0 {
                eprintln!(
                    "[cycronet/SEH] {} caught exception 0x{:08x}, ptr={:?}",
                    $name, code, $ptr
                );
            }
        }
    }};
}

#[cfg(not(target_os = "windows"))]
macro_rules! seh_call {
    ($ptr:expr, $fn:expr, $name:expr) => {{
        if !$ptr.is_null() {
            $fn($ptr);
        }
    }};
}

// Macro for verbose logging
macro_rules! verbose_log {
    ($($arg:tt)*) => {
        if VERBOSE_MODE.load(Ordering::Relaxed) {
            eprintln!($($arg)*);
        }
    };
}

#[derive(Default)]
struct PendingRequests {
    inner: Mutex<Vec<usize>>,
}

impl PendingRequests {
    fn add(&self, request: Cronet_UrlRequestPtr) {
        if request.is_null() {
            return;
        }
        match self.inner.lock() {
            Ok(mut list) => list.push(request as usize),
            Err(poisoned) => {
                eprintln!("[WARN] PendingRequests::add: mutex poisoned, recovering");
                poisoned.into_inner().push(request as usize);
            }
        }
    }

    fn remove(&self, request: Cronet_UrlRequestPtr) {
        if request.is_null() {
            return;
        }
        let request_id = request as usize;
        match self.inner.lock() {
            Ok(mut list) => {
                if let Some(pos) = list.iter().position(|&p| p == request_id) {
                    list.swap_remove(pos);
                }
            }
            Err(poisoned) => {
                eprintln!("[WARN] PendingRequests::remove: mutex poisoned, recovering");
                let mut list = poisoned.into_inner();
                if let Some(pos) = list.iter().position(|&p| p == request_id) {
                    list.swap_remove(pos);
                }
            }
        }
    }

    fn snapshot(&self) -> Vec<Cronet_UrlRequestPtr> {
        let ids = match self.inner.lock() {
            Ok(list) => list.clone(),
            Err(poisoned) => {
                eprintln!("[WARN] PendingRequests::snapshot: mutex poisoned, recovering");
                poisoned.into_inner().clone()
            }
        };
        ids.into_iter()
            .map(|id| id as Cronet_UrlRequestPtr)
            .collect()
    }
}

fn wait_counter_zero(counter: &AtomicUsize, timeout: std::time::Duration, label: &str) -> bool {
    let start = std::time::Instant::now();
    while counter.load(Ordering::Acquire) > 0 {
        if start.elapsed() > timeout {
            eprintln!(
                "[WARN] Timeout waiting for {} to drain (remaining={})",
                label,
                counter.load(Ordering::Acquire)
            );
            return false;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    true
}

// 安全地创建 CString，过滤掉 null 字节
fn safe_cstring(s: &str, context: &str) -> Result<CString, String> {
    // 移除 null 字节
    let safe_str = s.replace('\0', "");
    CString::new(safe_str).map_err(|e| format!("Failed to create CString for {}: {}", context, e))
}

fn build_experimental_options(
    cipher_suites: Option<&[String]>,
    tls_curves: Option<&[String]>,
    tls_extensions: Option<&[String]>,
    signature_algorithms: Option<&[String]>,
) -> Result<CString, String> {
    let mut options = serde_json::Map::new();
    options.insert("enable_cookie_store".to_string(), serde_json::json!(true));

    if let Some(values) = cipher_suites {
        if !values.is_empty() {
            options.insert("tls_cipher_suites".to_string(), serde_json::json!(values));
        }
    }
    if let Some(values) = tls_curves {
        if !values.is_empty() {
            options.insert("tls_curves".to_string(), serde_json::json!(values));
        }
    }
    if let Some(values) = tls_extensions {
        if !values.is_empty() {
            options.insert("tls_extensions".to_string(), serde_json::json!(values));
        }
    }
    if let Some(values) = signature_algorithms {
        if !values.is_empty() {
            options.insert(
                "signature_algorithms".to_string(),
                serde_json::json!(values),
            );
        }
    }

    safe_cstring(
        &serde_json::Value::Object(options).to_string(),
        "experimental_options",
    )
}

// 验证 HTTP header name 是否合法 (RFC 7230 token)
// token = 1*tchar
// tchar = "!" / "#" / "$" / "%" / "&" / "'" / "*" / "+" / "-" / "." /
//         "^" / "_" / "`" / "|" / "~" / DIGIT / ALPHA
fn is_valid_header_name(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    name.bytes().all(|b| {
        matches!(b,
            b'!' | b'#' | b'$' | b'%' | b'&' | b'\'' | b'*' | b'+' | b'-' | b'.' |
            b'^' | b'_' | b'`' | b'|' | b'~' |
            b'0'..=b'9' | b'A'..=b'Z' | b'a'..=b'z'
        )
    })
}

// 验证 HTTP header value 是否合法（不含控制字符，除了水平制表符）
fn is_valid_header_value(value: &str) -> bool {
    value
        .bytes()
        .all(|b| b == b'\t' || (b >= 0x20 && b != 0x7f))
}

// -----------------------------------------------------------------------------
// Cronet Engine
// -----------------------------------------------------------------------------

// Engine configuration key for caching
#[derive(Hash, Eq, PartialEq, Clone, Debug)]
struct EngineConfig {
    proxy_rules: Option<String>,
    skip_cert_verify: bool,
}

// Cached engine wrapper
struct CachedEngine {
    ptr: Cronet_EnginePtr,
}

unsafe impl Send for CachedEngine {}
unsafe impl Sync for CachedEngine {}

pub struct CronetEngine {
    ptr: Cronet_EnginePtr,
    // Cache of engines with custom configurations
    engine_cache: Mutex<HashMap<EngineConfig, CachedEngine>>,
    live_requests: Arc<AtomicUsize>,
    in_flight_executors: Arc<AtomicUsize>,
    pending_requests: Arc<PendingRequests>,
    destroy_mutex: Arc<Mutex<()>>,
}

impl CronetEngine {
    pub fn new(user_agent: &str) -> Result<Self, String> {
        unsafe {
            let engine_ptr = Cronet_Engine_Create();
            let params_ptr = Cronet_EngineParams_Create();
            if engine_ptr.is_null() || params_ptr.is_null() {
                seh_destroy!(engine_ptr, Cronet_Engine_Destroy, "Engine_Create_cleanup");
                seh_destroy!(
                    params_ptr,
                    Cronet_EngineParams_Destroy,
                    "EngineParams_Create_cleanup"
                );
                return Err("Failed to allocate Cronet engine or params".to_string());
            }

            // 安全地创建 CString
            let c_ua = match safe_cstring(user_agent, "user_agent") {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("[ERROR] {}, using default", e);
                    CString::new("CronetClient/1.0").expect("literal has no nul bytes")
                }
            };
            Cronet_EngineParams_user_agent_set(params_ptr, c_ua.as_ptr());

            // Use true for params
            Cronet_EngineParams_enable_quic_set(params_ptr, true);
            Cronet_EngineParams_enable_http2_set(params_ptr, true);
            Cronet_EngineParams_enable_brotli_set(params_ptr, true);

            // Enable Cookie Store to handle Set-Cookie in 302 redirects
            let c_options = build_experimental_options(None, None, None, None)?;
            Cronet_EngineParams_experimental_options_set(params_ptr, c_options.as_ptr());

            // Start the engine
            let res = Cronet_Engine_StartWithParams(engine_ptr, params_ptr);
            seh_destroy!(
                params_ptr,
                Cronet_EngineParams_Destroy,
                "EngineParams_Destroy"
            );

            if res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                seh_destroy!(engine_ptr, Cronet_Engine_Destroy, "Engine_Start_cleanup");
                return Err(format!("Failed to start Cronet Engine: {:?}", res));
            }

            Ok(CronetEngine {
                ptr: engine_ptr,
                engine_cache: Mutex::new(HashMap::new()),
                live_requests: Arc::new(AtomicUsize::new(0)),
                in_flight_executors: Arc::new(AtomicUsize::new(0)),
                pending_requests: Arc::new(PendingRequests::default()),
                destroy_mutex: Arc::new(Mutex::new(())),
            })
        }
    }

    // Get or create a cached engine with custom configuration
    fn get_or_create_engine(&self, config_key: &EngineConfig) -> Result<Cronet_EnginePtr, String> {
        let mut cache = match self.engine_cache.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                eprintln!("[WARN] get_or_create_engine: cache mutex poisoned, recovering");
                poisoned.into_inner()
            }
        };

        if let Some(cached) = cache.get(config_key) {
            verbose_log!("[DEBUG] Reusing cached engine for config: {:?}", config_key);
            return Ok(cached.ptr);
        }

        verbose_log!("[DEBUG] Creating new engine for config: {:?}", config_key);
        unsafe {
            let engine = Cronet_Engine_Create();
            let params = Cronet_EngineParams_Create();
            if engine.is_null() || params.is_null() {
                seh_destroy!(engine, Cronet_Engine_Destroy, "CachedEngine_Create_cleanup");
                seh_destroy!(
                    params,
                    Cronet_EngineParams_Destroy,
                    "CachedEngineParams_Create_cleanup"
                );
                return Err("Failed to allocate cached Cronet engine or params".to_string());
            }

            // Configure proxy if present
            if let Some(ref proxy_rules) = config_key.proxy_rules {
                let c_rules = safe_cstring(proxy_rules, "proxy_rules")?;
                Cronet_EngineParams_proxy_rules_set(params, c_rules.as_ptr());
            }

            Cronet_EngineParams_enable_quic_set(params, true);
            Cronet_EngineParams_enable_http2_set(params, true);

            // Skip certificate verification if requested
            if config_key.skip_cert_verify {
                Cronet_EngineParams_skip_cert_verify_set(params, true);
            }

            // Enable Cookie Store to handle Set-Cookie in 302 redirects
            let c_options = build_experimental_options(None, None, None, None)?;
            Cronet_EngineParams_experimental_options_set(params, c_options.as_ptr());

            let res = Cronet_Engine_StartWithParams(engine, params);
            seh_destroy!(
                params,
                Cronet_EngineParams_Destroy,
                "CachedEngineParams_Destroy"
            );

            if res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                seh_destroy!(engine, Cronet_Engine_Destroy, "CachedEngine_Start_cleanup");
                return Err(format!("Failed to start cached Cronet Engine: {:?}", res));
            }

            cache.insert(config_key.clone(), CachedEngine { ptr: engine });
            Ok(engine)
        }
    }

    pub fn start_request(
        &self,
        target: &crate::cronet_pb::TargetRequest,
        config: &crate::cronet_pb::ExecutionConfig,
    ) -> (CronetRequest, RequestReceiver) {
        unsafe {
            verbose_log!("[DEBUG] start_request entered");
            // Determine Engine to use (Shared or Cached Engine with custom config)
            let needs_custom_engine = config.proxy.is_some() || config.skip_cert_verify;
            let engine_ptr = if needs_custom_engine {
                // Build proxy rules string if proxy is configured
                let proxy_rules = if let Some(proxy) = &config.proxy {
                    let scheme = match ProxyType::try_from(proxy.r#type).unwrap_or(ProxyType::Http)
                    {
                        ProxyType::Http => "http",
                        ProxyType::Https => "https",
                        ProxyType::Socks5 => "socks5",
                    };

                    let rules = if !proxy.username.is_empty() && !proxy.password.is_empty() {
                        format!(
                            "{}://{}:{}@{}:{}",
                            scheme, proxy.username, proxy.password, proxy.host, proxy.port
                        )
                    } else {
                        format!("{}://{}:{}", scheme, proxy.host, proxy.port)
                    };
                    Some(rules)
                } else {
                    None
                };

                let config_key = EngineConfig {
                    proxy_rules,
                    skip_cert_verify: config.skip_cert_verify,
                };

                // Use cached engine (session is preserved)
                match self.get_or_create_engine(&config_key) {
                    Ok(ptr) => ptr,
                    Err(e) => return CronetRequest::failed(e),
                }
            } else {
                self.ptr
            };
            // owned_engine_ptr is no longer needed since we cache engines
            let owned_engine_ptr: Option<Cronet_EnginePtr> = None;

            // Channel to receive the final result
            let (tx, rx) = oneshot::channel();

            // 创建完成标志，用于追踪请求是否已完成
            let completed = Arc::new(AtomicBool::new(false));
            let request_in_flight = Arc::new(AtomicUsize::new(0));

            // Create Context to hold state across callbacks
            let context = Box::new(RequestContext {
                tx: Mutex::new(Some(tx)),
                response_buffer: Mutex::new(Vec::new()),
                response_headers: Mutex::new(Vec::new()),
                status_code: AtomicI32::new(0),
                completed: completed.clone(),
                pending_requests: Some(self.pending_requests.clone()),
                redirect_response: Mutex::new(None),
                active_requests: None, // CronetEngine 不使用活跃请求计数
                allow_redirects: true, // 默认允许重定向（REST API）
                context_taken: AtomicBool::new(false),
                is_streaming: false,
                stream_tx: Mutex::new(None),
            });

            let context_ptr = Box::into_raw(context);

            // 复用引擎共享的 executor 线程（避免每个请求创建新线程）
            let executor_context = Box::new(ExecutorContext {
                request_in_flight: request_in_flight.clone(),
                aggregate_in_flight: Some(self.in_flight_executors.clone()),
            });
            let executor_context_ptr = Box::into_raw(executor_context);

            // Executor
            // We use the same executor for request and upload
            let executor_ptr = Cronet_Executor_CreateWith(Some(executor_execute));
            Cronet_Executor_SetClientContext(executor_ptr, executor_context_ptr as *mut c_void);

            // Callback
            let callback_ptr = Cronet_UrlRequestCallback_CreateWith(
                Some(on_redirect_received),
                Some(on_response_started),
                Some(on_read_completed),
                Some(on_succeeded),
                Some(on_failed),
                Some(on_canceled),
            );
            Cronet_UrlRequestCallback_SetClientContext(callback_ptr, context_ptr as *mut c_void);

            // Request & Params
            let request_ptr = Cronet_UrlRequest_Create();
            let params_ptr = Cronet_UrlRequestParams_Create();

            let c_method = safe_cstring(&target.method, "method").unwrap_or_else(|e| {
                eprintln!("[WARN] {}, using empty method", e);
                CString::new("").expect("literal has no nul bytes")
            });
            Cronet_UrlRequestParams_http_method_set(params_ptr, c_method.as_ptr());

            // Set highest priority to get HTTP/2 weight=256 (same as normal browsers)
            Cronet_UrlRequestParams_priority_set(
                params_ptr, 4, // REQUEST_PRIORITY_HIGHEST
            );

            let c_url = safe_cstring(&target.url, "url").unwrap_or_else(|e| {
                eprintln!("[WARN] {}, using empty url", e);
                CString::new("").expect("literal has no nul bytes")
            });

            // Headers - 按顺序添加（跳过无效的 header name/value）
            for header in &target.headers {
                if !is_valid_header_name(&header.name) {
                    eprintln!(
                        "[WARN] Skipping header with invalid name: {:?}",
                        header.name
                    );
                    continue;
                }
                if !is_valid_header_value(&header.value) {
                    eprintln!(
                        "[WARN] Skipping header with invalid value for key {:?}",
                        header.name
                    );
                    continue;
                }
                let c_key = safe_cstring(&header.name, "header_name").unwrap_or_else(|e| {
                    eprintln!("[WARN] {}, using empty header name", e);
                    CString::new("").expect("literal has no nul bytes")
                });
                let c_val = safe_cstring(&header.value, "header_value").unwrap_or_else(|e| {
                    eprintln!("[WARN] {}, using empty header value", e);
                    CString::new("").expect("literal has no nul bytes")
                });

                let header_ptr = Cronet_HttpHeader_Create();
                Cronet_HttpHeader_name_set(header_ptr, c_key.as_ptr());
                Cronet_HttpHeader_value_set(header_ptr, c_val.as_ptr());

                Cronet_UrlRequestParams_request_headers_add(params_ptr, header_ptr);

                seh_destroy!(header_ptr, Cronet_HttpHeader_Destroy, "HttpHeader_Destroy");
            }

            // Upload Data Provider (Body)
            let mut upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr> = None;
            let mut upload_context_ptr: *mut UploadContext = std::ptr::null_mut();

            // Keep body alive
            let upload_body_data = if !target.body.is_empty() {
                Some(target.body.clone())
            } else {
                None
            };

            if let Some(body) = &upload_body_data {
                eprintln!(
                    "[DEBUG] Creating Rust UploadDataProvider. Body len: {}",
                    body.len()
                );

                let upload_context = Box::new(UploadContext {
                    data: body.clone(),
                    position: 0,
                });
                upload_context_ptr = Box::into_raw(upload_context);

                let provider = Cronet_UploadDataProvider_CreateWith(
                    Some(upload_get_length),
                    Some(upload_read),
                    Some(upload_rewind),
                    Some(upload_close),
                );
                Cronet_UploadDataProvider_SetClientContext(
                    provider,
                    upload_context_ptr as *mut c_void,
                );

                Cronet_UrlRequestParams_upload_data_provider_set(params_ptr, provider);
                Cronet_UrlRequestParams_upload_data_provider_executor_set(params_ptr, executor_ptr);

                upload_data_provider_ptr = Some(provider);
            }

            self.live_requests.fetch_add(1, Ordering::Release);

            let init_res = Cronet_UrlRequest_InitWithParams(
                request_ptr,
                engine_ptr,
                c_url.as_ptr(),
                params_ptr,
                callback_ptr,
                executor_ptr,
            );

            seh_destroy!(
                params_ptr,
                Cronet_UrlRequestParams_Destroy,
                "UrlRequestParams_Destroy"
            );

            if init_res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                complete_request(
                    callback_ptr,
                    request_ptr,
                    Err(format!(
                        "Cronet_UrlRequest_InitWithParams failed: {:?}",
                        init_res
                    )),
                );
            } else {
                self.pending_requests.add(request_ptr);
                // Start
                verbose_log!("[DEBUG] Starting Cronet Request");
                let start_res = Cronet_UrlRequest_Start(request_ptr);

                if start_res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                    complete_request(
                        callback_ptr,
                        request_ptr,
                        Err(format!("Cronet_UrlRequest_Start failed: {:?}", start_res)),
                    );
                }
            }

            // Return Handle that owns the cleanup
            let request_handle = CronetRequest {
                ptr: request_ptr,
                callback_ptr,
                request_context_ptr: context_ptr,
                executor_ptr,
                executor_context_ptr,
                owned_engine_ptr,
                upload_data_provider_ptr,
                upload_context_ptr,
                upload_body_data,
                completed,
                request_in_flight,
                live_requests: Some(self.live_requests.clone()),
                pending_requests: Some(self.pending_requests.clone()),
                destroy_mutex: Some(self.destroy_mutex.clone()),
            };

            (request_handle, rx)
        }
    }
}

impl Drop for CronetEngine {
    fn drop(&mut self) {
        unsafe {
            for request_ptr in self.pending_requests.snapshot() {
                verbose_log!(
                    "[DEBUG] CronetEngine::drop - Cancelling request {:?}",
                    request_ptr
                );
                seh_call!(request_ptr, Cronet_UrlRequest_Cancel, "Engine_Cancel");
            }

            let live_drained = wait_counter_zero(
                &self.live_requests,
                std::time::Duration::from_secs(5),
                "engine live request handles",
            );
            let executor_drained = wait_counter_zero(
                &self.in_flight_executors,
                std::time::Duration::from_secs(2),
                "engine executor callbacks",
            );

            if !live_drained || !executor_drained {
                eprintln!(
                    "[WARN] CronetEngine::drop - leaking engines to avoid parent-before-child destroy"
                );
                self.ptr = std::ptr::null_mut();
                if let Ok(mut cache) = self.engine_cache.lock() {
                    for cached in cache.values_mut() {
                        cached.ptr = std::ptr::null_mut();
                    }
                }
                return;
            }

            let _destroy_guard = self.destroy_mutex.lock().ok();
            match self.engine_cache.lock() {
                Ok(mut cache) => {
                    for cached in cache.values_mut() {
                        seh_shutdown!(cached.ptr);
                        seh_destroy!(cached.ptr, Cronet_Engine_Destroy, "CachedEngine_Destroy");
                        cached.ptr = std::ptr::null_mut();
                    }
                }
                Err(poisoned) => {
                    eprintln!("[WARN] CronetEngine::drop - cache mutex poisoned, recovering");
                    let mut cache = poisoned.into_inner();
                    for cached in cache.values_mut() {
                        seh_shutdown!(cached.ptr);
                        seh_destroy!(cached.ptr, Cronet_Engine_Destroy, "CachedEngine_Destroy");
                        cached.ptr = std::ptr::null_mut();
                    }
                }
            }

            seh_shutdown!(self.ptr);
            seh_destroy!(self.ptr, Cronet_Engine_Destroy, "Engine_Destroy");
            self.ptr = std::ptr::null_mut();
        }
    }
}

unsafe impl Send for CronetEngine {}
unsafe impl Sync for CronetEngine {}

// -----------------------------------------------------------------------------
// Request Infrastructure
// -----------------------------------------------------------------------------

#[derive(Debug)]
pub struct RequestResult {
    pub status_code: i32,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

type RequestReceiver = oneshot::Receiver<Result<RequestResult, String>>;
type SessionRequestStart = (CronetRequest, RequestReceiver, u64);

/// 流式响应数据块
#[derive(Debug)]
pub enum StreamChunk {
    /// 响应头（首个块）
    Headers {
        status_code: i32,
        headers: Vec<(String, String)>,
    },
    /// 响应体数据块
    Data(Vec<u8>),
    /// 请求完成
    Done,
    /// 错误
    Error(String),
}

#[allow(dead_code)]
pub struct CronetRequest {
    ptr: Cronet_UrlRequestPtr,
    callback_ptr: Cronet_UrlRequestCallbackPtr,
    request_context_ptr: *mut RequestContext,
    executor_ptr: Cronet_ExecutorPtr,
    executor_context_ptr: *mut ExecutorContext, // Executor 的独立 context
    owned_engine_ptr: Option<Cronet_EnginePtr>,
    upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr>,
    upload_context_ptr: *mut UploadContext,
    upload_body_data: Option<Vec<u8>>, // Owns the body data so pointers are valid
    completed: Arc<AtomicBool>,        // 标记请求是否完成，由回调设置
    request_in_flight: Arc<AtomicUsize>,
    live_requests: Option<Arc<AtomicUsize>>, // Rust request handles still alive
    pending_requests: Option<Arc<PendingRequests>>, // 用于在完成时从列表移除
    destroy_mutex: Option<Arc<Mutex<()>>>,   // 序列化销毁，避免并发 Destroy 导致 cronet.dll 崩溃
}

unsafe impl Send for CronetRequest {}

impl CronetRequest {
    fn failed(error: String) -> (Self, RequestReceiver) {
        let (tx, rx) = oneshot::channel();
        let _ = tx.send(Err(error));
        (
            CronetRequest {
                ptr: std::ptr::null_mut(),
                callback_ptr: std::ptr::null_mut(),
                request_context_ptr: std::ptr::null_mut(),
                executor_ptr: std::ptr::null_mut(),
                executor_context_ptr: std::ptr::null_mut(),
                owned_engine_ptr: None,
                upload_data_provider_ptr: None,
                upload_context_ptr: std::ptr::null_mut(),
                upload_body_data: None,
                completed: Arc::new(AtomicBool::new(true)),
                request_in_flight: Arc::new(AtomicUsize::new(0)),
                live_requests: None,
                pending_requests: None,
                destroy_mutex: None,
            },
            rx,
        )
    }

    fn leak_to_avoid_crash(&mut self, live_requests: &Option<Arc<AtomicUsize>>) {
        self.ptr = std::ptr::null_mut();
        self.callback_ptr = std::ptr::null_mut();
        self.request_context_ptr = std::ptr::null_mut();
        self.executor_ptr = std::ptr::null_mut();
        self.executor_context_ptr = std::ptr::null_mut();
        self.upload_data_provider_ptr = None;
        self.upload_context_ptr = std::ptr::null_mut();
        self.owned_engine_ptr = None;
        if let Some(counter) = live_requests {
            counter.fetch_sub(1, Ordering::Release);
        }
    }
}

impl Drop for CronetRequest {
    fn drop(&mut self) {
        unsafe {
            let live_requests = self.live_requests.take();

            // 保存原始指针用于从 pending_requests 移除
            let original_ptr = self.ptr;

            // 检查请求是否已完成
            if !self.completed.load(Ordering::Acquire) {
                // 请求尚未完成，先取消它
                verbose_log!("[DEBUG] CronetRequest::drop - Request not completed, canceling...");
                seh_call!(self.ptr, Cronet_UrlRequest_Cancel, "UrlRequest_Cancel");
                // 等待请求完成（最多等待 5 秒）
                let start = std::time::Instant::now();
                while !self.completed.load(Ordering::Acquire) {
                    if start.elapsed() > std::time::Duration::from_secs(5) {
                        eprintln!("[WARN] CronetRequest::drop - Timeout waiting for cancel callback, leaking request to avoid use-after-free");
                        // 网络线程仍持有引用，不能销毁任何指针，否则会 DCHECK crash。
                        // 泄漏内存，但避免崩溃。
                        self.leak_to_avoid_crash(&live_requests);
                        return;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
            }

            // completed == true，等待 C++ 网络线程完成内部清理（MaybeReportMetrics 等）
            // 避免 Destroy 与仍在执行的回调产生竞态导致 DCHECK(!in_dtor_) crash
            // 高并发代理失败场景下需要更长的 grace period
            std::thread::sleep(std::time::Duration::from_millis(200));

            if !wait_counter_zero(
                &self.request_in_flight,
                std::time::Duration::from_secs(2),
                "request executor callbacks",
            ) {
                eprintln!(
                    "[WARN] CronetRequest::drop - executor callback still running, leaking request to avoid use-after-free"
                );
                self.leak_to_avoid_crash(&live_requests);
                return;
            }

            // 序列化销毁：防止多个请求同时调用 Destroy 导致 cronet.dll 内部竞态崩溃
            let _destroy_guard = self.destroy_mutex.as_ref().and_then(|m| m.lock().ok());

            if let Some(ref pending) = self.pending_requests {
                pending.remove(original_ptr);
                verbose_log!("[DEBUG] CronetRequest::drop - Removed from pending list");
            }

            if !self.callback_ptr.is_null() {
                Cronet_UrlRequestCallback_SetClientContext(self.callback_ptr, std::ptr::null_mut());
            }
            if !self.executor_ptr.is_null() {
                Cronet_Executor_SetClientContext(self.executor_ptr, std::ptr::null_mut());
            }
            if let Some(dp) = self.upload_data_provider_ptr {
                Cronet_UploadDataProvider_SetClientContext(dp, std::ptr::null_mut());
            }

            // completed == true，可以安全销毁（SEH 保护，防止崩溃）
            seh_destroy!(self.ptr, Cronet_UrlRequest_Destroy, "UrlRequest_Destroy");
            seh_destroy!(
                self.callback_ptr,
                Cronet_UrlRequestCallback_Destroy,
                "Callback_Destroy"
            );
            seh_destroy!(
                self.executor_ptr,
                Cronet_Executor_Destroy,
                "Executor_Destroy"
            );
            if !self.request_context_ptr.is_null() {
                let _ = Box::from_raw(self.request_context_ptr);
                self.request_context_ptr = std::ptr::null_mut();
            }
            // 释放 ExecutorContext
            if !self.executor_context_ptr.is_null() {
                let _ = Box::from_raw(self.executor_context_ptr);
                self.executor_context_ptr = std::ptr::null_mut();
            }
            if let Some(dp) = self.upload_data_provider_ptr.take() {
                seh_destroy!(
                    dp,
                    Cronet_UploadDataProvider_Destroy,
                    "UploadDataProvider_Destroy"
                );
            }
            if !self.upload_context_ptr.is_null() {
                let _ = Box::from_raw(self.upload_context_ptr);
                self.upload_context_ptr = std::ptr::null_mut();
            }
            // Finally destroy engine if we own it
            if let Some(engine_ptr) = self.owned_engine_ptr.take() {
                seh_shutdown!(engine_ptr);
                seh_destroy!(engine_ptr, Cronet_Engine_Destroy, "Engine_Destroy");
            }

            // 释放锁后稍微等待，让 Chromium 网络线程完全安定
            drop(_destroy_guard);
            std::thread::sleep(std::time::Duration::from_millis(10));

            if let Some(ref counter) = live_requests {
                counter.fetch_sub(1, Ordering::Release);
            }
        }
    }
}

// Context passed to C callbacks
struct RequestContext {
    tx: Mutex<Option<oneshot::Sender<Result<RequestResult, String>>>>,
    response_buffer: Mutex<Vec<u8>>,
    response_headers: Mutex<Vec<(String, String)>>,
    status_code: AtomicI32,
    completed: Arc<AtomicBool>,                      // 标记请求是否完成
    active_requests: Option<Arc<AtomicUsize>>,       // Session 的活跃请求计数器
    pending_requests: Option<Arc<PendingRequests>>,  // Session pending list
    allow_redirects: bool,                           // 是否允许重定向（只读，不需要锁）
    redirect_response: Mutex<Option<RequestResult>>, // 存储重定向响应（当 allow_redirects=false 时）
    context_taken: AtomicBool,                       // 防止双重释放：标记 context 是否已被取走
    // 流式响应
    is_streaming: bool,
    stream_tx: Mutex<Option<mpsc::UnboundedSender<StreamChunk>>>,
}

// Executor 专用 context - 独立于 RequestContext，避免 use-after-free
struct ExecutorContext {
    request_in_flight: Arc<AtomicUsize>,
    aggregate_in_flight: Option<Arc<AtomicUsize>>,
}

// -----------------------------------------------------------------------------
// C Callbacks (Extern "C")
// -----------------------------------------------------------------------------

struct ExecutorInFlightGuard {
    request: Arc<AtomicUsize>,
    aggregate: Option<Arc<AtomicUsize>>,
}

impl ExecutorInFlightGuard {
    fn new(context: &ExecutorContext) -> Self {
        context.request_in_flight.fetch_add(1, Ordering::AcqRel);
        if let Some(counter) = &context.aggregate_in_flight {
            counter.fetch_add(1, Ordering::AcqRel);
        }
        Self {
            request: context.request_in_flight.clone(),
            aggregate: context.aggregate_in_flight.clone(),
        }
    }
}

impl Drop for ExecutorInFlightGuard {
    fn drop(&mut self) {
        self.request.fetch_sub(1, Ordering::AcqRel);
        if let Some(counter) = &self.aggregate {
            counter.fetch_sub(1, Ordering::AcqRel);
        }
    }
}

unsafe extern "C" fn executor_execute(self_: Cronet_ExecutorPtr, command: Cronet_RunnablePtr) {
    // Cronet callbacks must be executed synchronously because:
    // 1. Cronet_Runnable pointers are not Send (cannot cross thread boundaries)
    // 2. Cronet expects immediate execution for proper state management
    //
    // The async improvement comes from:
    // - Using Tokio channels (oneshot) for result delivery
    // - Non-blocking wait in Python layer via async/await
    // - Tokio runtime managing concurrent requests efficiently

    let context_ptr = Cronet_Executor_GetClientContext(self_) as *mut ExecutorContext;
    let _guard = if context_ptr.is_null() {
        verbose_log!("[WARN] executor_execute: null ExecutorContext");
        None
    } else {
        Some(ExecutorInFlightGuard::new(&*context_ptr))
    };

    seh_call!(command, Cronet_Runnable_Run, "Runnable_Run");
    seh_call!(command, Cronet_Runnable_Destroy, "Runnable_Destroy");
}

// UrlRequest Callbacks
unsafe extern "C" fn on_redirect_received(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    info: Cronet_UrlResponseInfoPtr,
    _new_location_url: Cronet_String,
) {
    // 获取 RequestContext 检查是否允许重定向
    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] on_redirect_received: null RequestContext");
        return;
    }
    let context = &*context_ptr;

    // 获取响应头（无论是否允许重定向，都需要提取 Set-Cookie）
    let mut headers = Vec::new();
    let header_count = Cronet_UrlResponseInfo_all_headers_list_size(info);
    for i in 0..header_count {
        let header_ptr = Cronet_UrlResponseInfo_all_headers_list_at(info, i);
        if !header_ptr.is_null() {
            let name_ptr = Cronet_HttpHeader_name_get(header_ptr);
            let value_ptr = Cronet_HttpHeader_value_get(header_ptr);

            if !name_ptr.is_null() && !value_ptr.is_null() {
                let name = CStr::from_ptr(name_ptr).to_string_lossy().to_string();
                let value = CStr::from_ptr(value_ptr).to_string_lossy().to_string();
                headers.push((name, value));
            }
        }
    }

    if context.allow_redirects {
        // 允许重定向：将重定向响应头追加到 response_headers（用于提取 Set-Cookie）
        match context.response_headers.lock() {
            Ok(mut response_headers) => {
                response_headers.extend(headers);
            }
            Err(poisoned) => {
                eprintln!(
                    "[WARN] on_redirect_received: response_headers mutex poisoned, recovering"
                );
                let mut response_headers = poisoned.into_inner();
                response_headers.extend(headers);
            }
        }
        Cronet_UrlRequest_FollowRedirect(request);
    } else {
        // 不允许重定向，保存重定向响应信息然后取消请求
        let status_code = Cronet_UrlResponseInfo_http_status_code_get(info);

        // 保存重定向响应（使用锁保护，处理 poisoned）
        match context.redirect_response.lock() {
            Ok(mut redirect_response) => {
                *redirect_response = Some(RequestResult {
                    status_code,
                    headers,
                    body: Vec::new(), // 重定向响应通常没有 body
                });
            }
            Err(poisoned) => {
                eprintln!("[WARN] on_redirect_received: Mutex poisoned, recovering");
                let mut redirect_response = poisoned.into_inner();
                *redirect_response = Some(RequestResult {
                    status_code,
                    headers,
                    body: Vec::new(),
                });
            }
        }

        // 取消请求，on_canceled 会检查 redirect_response 并发送它
        seh_call!(request, Cronet_UrlRequest_Cancel, "Redirect_Cancel");
    }
}

unsafe extern "C" fn on_response_started(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_response_started");
    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] on_response_started: null RequestContext");
        return;
    }
    let context = &*context_ptr;

    let status_code = Cronet_UrlResponseInfo_http_status_code_get(info);
    context.status_code.store(status_code, Ordering::Release);

    // 提取响应 headers（使用锁保护，处理 poisoned）
    match context.response_headers.lock() {
        Ok(mut response_headers) => {
            let header_count = Cronet_UrlResponseInfo_all_headers_list_size(info);
            for i in 0..header_count {
                let header_ptr = Cronet_UrlResponseInfo_all_headers_list_at(info, i);
                if !header_ptr.is_null() {
                    let name_ptr = Cronet_HttpHeader_name_get(header_ptr);
                    let value_ptr = Cronet_HttpHeader_value_get(header_ptr);
                    if !name_ptr.is_null() && !value_ptr.is_null() {
                        let name = CStr::from_ptr(name_ptr).to_string_lossy().into_owned();
                        let value = CStr::from_ptr(value_ptr).to_string_lossy().into_owned();
                        response_headers.push((name, value));
                    }
                }
            }
        }
        Err(poisoned) => {
            eprintln!("[WARN] on_response_started: Mutex poisoned, recovering");
            let mut response_headers = poisoned.into_inner();
            let header_count = Cronet_UrlResponseInfo_all_headers_list_size(info);
            for i in 0..header_count {
                let header_ptr = Cronet_UrlResponseInfo_all_headers_list_at(info, i);
                if !header_ptr.is_null() {
                    let name_ptr = Cronet_HttpHeader_name_get(header_ptr);
                    let value_ptr = Cronet_HttpHeader_value_get(header_ptr);
                    if !name_ptr.is_null() && !value_ptr.is_null() {
                        let name = CStr::from_ptr(name_ptr).to_string_lossy().into_owned();
                        let value = CStr::from_ptr(value_ptr).to_string_lossy().into_owned();
                        response_headers.push((name, value));
                    }
                }
            }
        }
    }

    // 流式模式：发送 Headers 块
    if context.is_streaming {
        let status_code = context.status_code.load(Ordering::Acquire);
        let headers = match context.response_headers.lock() {
            Ok(guard) => guard.clone(),
            Err(poisoned) => {
                eprintln!(
                    "[WARN] on_response_started: response_headers mutex poisoned for streaming"
                );
                poisoned.into_inner().clone()
            }
        };
        if let Ok(guard) = context.stream_tx.lock() {
            if let Some(ref tx) = *guard {
                let _ = tx.send(StreamChunk::Headers {
                    status_code,
                    headers,
                });
            }
        }
    }

    let buffer_ptr = Cronet_Buffer_Create();
    Cronet_Buffer_InitWithAlloc(buffer_ptr, 32 * 1024);

    Cronet_UrlRequest_Read(request, buffer_ptr);
}

unsafe extern "C" fn on_read_completed(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
    buffer: Cronet_BufferPtr,
    bytes_read: u64,
) {
    verbose_log!("[DEBUG] on_read_completed: {} bytes", bytes_read);
    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] on_read_completed: null RequestContext");
        seh_destroy!(buffer, Cronet_Buffer_Destroy, "Buffer_Destroy");
        return;
    }
    let context = &*context_ptr;

    let data_ptr = Cronet_Buffer_GetData(buffer);
    let slice = std::slice::from_raw_parts(data_ptr as *const u8, bytes_read as usize);

    if context.is_streaming {
        // 流式模式：直接发送数据块
        if let Ok(guard) = context.stream_tx.lock() {
            if let Some(ref tx) = *guard {
                let _ = tx.send(StreamChunk::Data(slice.to_vec()));
            }
        }
    } else {
        // 非流式模式：缓冲数据
        match context.response_buffer.lock() {
            Ok(mut response_buffer) => {
                response_buffer.extend_from_slice(slice);
            }
            Err(poisoned) => {
                eprintln!("[WARN] on_read_completed: Mutex poisoned, recovering");
                let mut response_buffer = poisoned.into_inner();
                response_buffer.extend_from_slice(slice);
            }
        }
    }

    seh_destroy!(buffer, Cronet_Buffer_Destroy, "Buffer_Destroy");

    let new_buffer = Cronet_Buffer_Create();
    Cronet_Buffer_InitWithAlloc(new_buffer, 32 * 1024);

    Cronet_UrlRequest_Read(request, new_buffer);
}

unsafe extern "C" fn on_succeeded(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_succeeded");
    complete_request(self_, request, Ok(()));
}

unsafe extern "C" fn on_failed(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
    error: Cronet_ErrorPtr,
) {
    verbose_log!("[DEBUG] on_failed");
    let msg = CStr::from_ptr(Cronet_Error_message_get(error))
        .to_string_lossy()
        .into_owned();
    complete_request(self_, request, Err(msg));
}

unsafe extern "C" fn on_canceled(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_canceled");

    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] on_canceled: null RequestContext");
        return;
    }

    // 检查完成事件是否已发送，防止重复 final callback 重复递减/发送
    let context = &*context_ptr;
    if context.context_taken.swap(true, Ordering::AcqRel) {
        verbose_log!("[WARN] on_canceled: Context already taken, skipping");
        return;
    }

    // 标记请求已完成
    context.completed.store(true, Ordering::Release);

    remove_pending_request(context, request);

    // 减少活跃请求计数
    if let Some(ref active_requests) = context.active_requests {
        active_requests.fetch_sub(1, Ordering::Release);
    }

    // 流式模式：发送错误或重定向响应
    if context.is_streaming {
        let redirect_response = match context.redirect_response.lock() {
            Ok(mut guard) => guard.take(),
            Err(poisoned) => poisoned.into_inner().take(),
        };
        let stream_tx = match context.stream_tx.lock() {
            Ok(mut guard) => guard.take(),
            Err(poisoned) => poisoned.into_inner().take(),
        };
        if let Some(tx) = stream_tx {
            if let Some(redirect) = redirect_response {
                // 重定向响应：发送 Headers 然后 Done
                let _ = tx.send(StreamChunk::Headers {
                    status_code: redirect.status_code,
                    headers: redirect.headers,
                });
                let _ = tx.send(StreamChunk::Done);
            } else {
                let _ = tx.send(StreamChunk::Error("Canceled".to_string()));
            }
        }
        return;
    }

    // 检查是否有保存的重定向响应（allow_redirects=false 的情况）
    let redirect_response = match context.redirect_response.lock() {
        Ok(mut guard) => guard.take(),
        Err(poisoned) => {
            eprintln!("[WARN] on_canceled: redirect_response mutex poisoned, recovering");
            poisoned.into_inner().take()
        }
    };

    if let Some(redirect_response) = redirect_response {
        verbose_log!(
            "[DEBUG] on_canceled: Sending redirect response (status {})",
            redirect_response.status_code
        );
        let tx = match context.tx.lock() {
            Ok(mut guard) => guard.take(),
            Err(poisoned) => {
                eprintln!("[WARN] on_canceled: tx mutex poisoned, recovering");
                poisoned.into_inner().take()
            }
        };
        if let Some(tx) = tx {
            let _ = tx.send(Ok(redirect_response));
        }
    } else {
        // 正常的取消，发送错误
        let tx = match context.tx.lock() {
            Ok(mut guard) => guard.take(),
            Err(poisoned) => {
                eprintln!("[WARN] on_canceled: tx mutex poisoned, recovering");
                poisoned.into_inner().take()
            }
        };
        if let Some(tx) = tx {
            let _ = tx.send(Err("Canceled".to_string()));
        }
    }
}

unsafe fn remove_pending_request(context: &RequestContext, request: Cronet_UrlRequestPtr) {
    if request.is_null() {
        return;
    }
    if let Some(ref pending) = context.pending_requests {
        pending.remove(request);
        verbose_log!("[DEBUG] Removed request from pending list in final callback");
    }
}

unsafe fn complete_request(
    callback_ptr: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    result: Result<(), String>,
) {
    let context_ptr =
        Cronet_UrlRequestCallback_GetClientContext(callback_ptr) as *mut RequestContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] complete_request: null RequestContext");
        return;
    }

    // 检查完成事件是否已发送，防止重复 final callback 重复递减/发送
    let context = &*context_ptr;
    if context.context_taken.swap(true, Ordering::AcqRel) {
        verbose_log!("[WARN] complete_request: Context already taken, skipping");
        return;
    }

    // 标记请求已完成
    context.completed.store(true, Ordering::Release);

    remove_pending_request(context, request);

    // 递减活跃请求计数
    if let Some(ref counter) = context.active_requests {
        counter.fetch_sub(1, Ordering::Release);
    }

    verbose_log!("[DEBUG] complete_request: {:?}", result);

    // 流式模式：发送 Done 或 Error
    if context.is_streaming {
        let stream_tx = match context.stream_tx.lock() {
            Ok(mut guard) => guard.take(),
            Err(poisoned) => poisoned.into_inner().take(),
        };
        if let Some(tx) = stream_tx {
            match result {
                Ok(_) => {
                    let _ = tx.send(StreamChunk::Done);
                }
                Err(e) => {
                    let _ = tx.send(StreamChunk::Error(e));
                }
            }
        }
        return;
    }

    let tx = match context.tx.lock() {
        Ok(mut guard) => guard.take(),
        Err(poisoned) => {
            eprintln!("[WARN] complete_request: tx mutex poisoned, recovering");
            poisoned.into_inner().take()
        }
    };

    if let Some(tx) = tx {
        match result {
            Ok(_) => {
                let status_code = context.status_code.load(Ordering::Acquire);

                let headers = match context.response_headers.lock() {
                    Ok(guard) => guard.clone(),
                    Err(poisoned) => {
                        eprintln!(
                            "[WARN] complete_request: response_headers mutex poisoned, recovering"
                        );
                        poisoned.into_inner().clone()
                    }
                };

                let body = match context.response_buffer.lock() {
                    Ok(guard) => guard.clone(),
                    Err(poisoned) => {
                        eprintln!(
                            "[WARN] complete_request: response_buffer mutex poisoned, recovering"
                        );
                        poisoned.into_inner().clone()
                    }
                };

                let res = RequestResult {
                    status_code,
                    headers,
                    body,
                };
                let _ = tx.send(Ok(res));
            }
            Err(e) => {
                let _ = tx.send(Err(e));
            }
        }
    }
}

// -----------------------------------------------------------------------------
// Upload Data Provider Callbacks
// -----------------------------------------------------------------------------

struct UploadContext {
    data: Vec<u8>,
    position: u64,
}

unsafe extern "C" fn upload_get_length(self_: Cronet_UploadDataProviderPtr) -> i64 {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] upload_get_length: null UploadContext");
        return 0;
    }
    let context = &*context_ptr;
    context.data.len() as i64
}

unsafe extern "C" fn upload_read(
    self_: Cronet_UploadDataProviderPtr,
    sink: Cronet_UploadDataSinkPtr,
    buffer: Cronet_BufferPtr,
) {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] upload_read: null UploadContext");
        let msg = CString::new("Upload context is closed").expect("literal has no nul bytes");
        Cronet_UploadDataSink_OnReadError(sink, msg.as_ptr());
        return;
    }
    let context = &mut *context_ptr;

    let buffer_size = Cronet_Buffer_GetSize(buffer);
    let buffer_data = Cronet_Buffer_GetData(buffer) as *mut u8;

    let remaining = (context.data.len() as u64) - context.position;
    let to_read = std::cmp::min(buffer_size, remaining);

    if to_read > 0 {
        ptr::copy_nonoverlapping(
            context.data.as_ptr().add(context.position as usize),
            buffer_data,
            to_read as usize,
        );
        context.position += to_read;
    }

    Cronet_UploadDataSink_OnReadSucceeded(sink, to_read, false);
}

unsafe extern "C" fn upload_rewind(
    self_: Cronet_UploadDataProviderPtr,
    sink: Cronet_UploadDataSinkPtr,
) {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] upload_rewind: null UploadContext");
        let msg = CString::new("Upload context is closed").expect("literal has no nul bytes");
        Cronet_UploadDataSink_OnRewindError(sink, msg.as_ptr());
        return;
    }
    let context = &mut *context_ptr;
    context.position = 0;
    Cronet_UploadDataSink_OnRewindSucceeded(sink);
}

unsafe extern "C" fn upload_close(self_: Cronet_UploadDataProviderPtr) {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
    if context_ptr.is_null() {
        verbose_log!("[WARN] upload_close: null UploadContext");
    }
}

// -----------------------------------------------------------------------------
// Session Management
// -----------------------------------------------------------------------------

use std::time::Instant;
use uuid::Uuid;

/// 会话配置
#[derive(Clone, Debug)]
pub struct SessionConfig {
    pub proxy_rules: Option<String>,
    pub skip_cert_verify: bool,
    pub timeout_ms: u64,
    pub cipher_suites: Option<Vec<String>>,
    pub tls_curves: Option<Vec<String>>,
    pub tls_extensions: Option<Vec<String>>,
    pub signature_algorithms: Option<Vec<String>>,
    pub allow_redirects: bool,
}

/// 单个会话 - 持有独立的 Cronet Engine
pub struct Session {
    pub id: String,
    engine_ptr: Cronet_EnginePtr,
    pub config: SessionConfig,
    pub created_at: Instant,
    active_requests: Arc<AtomicUsize>, // 追踪活跃请求数量（仅用于监控）
    live_requests: Arc<AtomicUsize>,   // 追踪仍持有 CronetRequest 的 Rust future/stream
    in_flight_executors: Arc<AtomicUsize>, // 追踪正在执行的 executor 回调数量
    is_closed: Arc<AtomicBool>,        // 标记 session 是否已关闭
    pending_requests: Arc<PendingRequests>, // 追踪所有进行中的请求指针
    destroy_mutex: Arc<Mutex<()>>,     // 序列化请求销毁，防止并发 Destroy 导致 cronet.dll 崩溃
}

unsafe impl Send for Session {}
unsafe impl Sync for Session {}

impl Drop for Session {
    fn drop(&mut self) {
        verbose_log!("[DEBUG] Session::drop - Starting for session {}", self.id);

        // 标记 session 已关闭
        self.is_closed.store(true, Ordering::Release);

        unsafe {
            if !self.engine_ptr.is_null() {
                let active = self.active_requests.load(Ordering::Acquire);
                verbose_log!("[DEBUG] Session::drop - active_requests={}", active);

                if active > 0 {
                    // 主动取消所有进行中的请求
                    verbose_log!(
                        "[DEBUG] Session::drop - Cancelling {} active requests",
                        active
                    );
                    let requests_to_cancel = self.pending_requests.snapshot();
                    for request_ptr in requests_to_cancel {
                        verbose_log!(
                            "[DEBUG] Session::drop - Cancelling request {:?}",
                            request_ptr
                        );
                        seh_call!(request_ptr, Cronet_UrlRequest_Cancel, "Session_Cancel");
                    }

                    // 等待请求完成取消（最多5秒）
                    let start = std::time::Instant::now();
                    while self.active_requests.load(Ordering::Acquire) > 0 {
                        if start.elapsed() > std::time::Duration::from_secs(5) {
                            eprintln!("[WARN] Session::drop - Timeout waiting for {} active requests after cancellation, leaking engine to avoid crash",
                                self.active_requests.load(Ordering::Acquire));
                            // 网络线程仍持有引用，不能销毁 Engine，否则会 use-after-free crash。
                            // 泄漏 Engine 内存，但避免崩溃。
                            self.engine_ptr = std::ptr::null_mut();
                            return;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(10));
                    }

                    // 额外等待，让 C++ 网络线程完成 MaybeReportMetrics 等内部清理
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }

                let start = std::time::Instant::now();
                while self.live_requests.load(Ordering::Acquire) > 0 {
                    if start.elapsed() > std::time::Duration::from_secs(2) {
                        eprintln!("[WARN] Session::drop - {} CronetRequest handles still alive, leaking engine to avoid parent-before-child destroy",
                            self.live_requests.load(Ordering::Acquire));
                        self.engine_ptr = std::ptr::null_mut();
                        return;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }

                if !wait_counter_zero(
                    &self.in_flight_executors,
                    std::time::Duration::from_secs(2),
                    "session executor callbacks",
                ) {
                    eprintln!(
                        "[WARN] Session::drop - leaking engine because executor callbacks are still running"
                    );
                    self.engine_ptr = std::ptr::null_mut();
                    return;
                }

                // 所有请求已完成，安全销毁 engine（SEH 保护）
                verbose_log!("[DEBUG] Session::drop - Calling Cronet_Engine_Shutdown");
                seh_shutdown!(self.engine_ptr);

                verbose_log!("[DEBUG] Session::drop - Calling Cronet_Engine_Destroy");
                seh_destroy!(
                    self.engine_ptr,
                    Cronet_Engine_Destroy,
                    "Session_Engine_Destroy"
                );
                verbose_log!("[DEBUG] Session::drop - Engine destroyed");
            }
        }
        verbose_log!("[DEBUG] Session::drop - Finished for session {}", self.id);
    }
}

/// 会话管理器 - 管理多个会话，支持并发访问
pub struct SessionManager {
    sessions: RwLock<HashMap<String, Session>>,
}

impl SessionManager {
    pub fn new() -> Self {
        SessionManager {
            sessions: RwLock::new(HashMap::new()),
        }
    }

    /// 创建新会话，返回会话ID
    pub fn create_session(&self, config: SessionConfig) -> String {
        let session_id = Uuid::new_v4().to_string();

        unsafe {
            let engine = Cronet_Engine_Create();
            let params = Cronet_EngineParams_Create();
            if engine.is_null() || params.is_null() {
                seh_destroy!(
                    engine,
                    Cronet_Engine_Destroy,
                    "SessionEngine_Create_cleanup"
                );
                seh_destroy!(
                    params,
                    Cronet_EngineParams_Destroy,
                    "SessionEngineParams_Create_cleanup"
                );
                return String::new();
            }

            if let Some(ref proxy_rules) = config.proxy_rules {
                let c_rules = match safe_cstring(proxy_rules, "proxy_rules") {
                    Ok(value) => value,
                    Err(e) => {
                        eprintln!("[ERROR] {}", e);
                        seh_destroy!(
                            params,
                            Cronet_EngineParams_Destroy,
                            "SessionEngineParams_Proxy_cleanup"
                        );
                        seh_destroy!(engine, Cronet_Engine_Destroy, "SessionEngine_Proxy_cleanup");
                        return String::new();
                    }
                };
                Cronet_EngineParams_proxy_rules_set(params, c_rules.as_ptr());
            }

            Cronet_EngineParams_enable_quic_set(params, true);
            Cronet_EngineParams_enable_http2_set(params, true);
            Cronet_EngineParams_enable_brotli_set(params, true);

            if config.skip_cert_verify {
                Cronet_EngineParams_skip_cert_verify_set(params, true);
            }

            let c_options = match build_experimental_options(
                config.cipher_suites.as_deref(),
                config.tls_curves.as_deref(),
                config.tls_extensions.as_deref(),
                config.signature_algorithms.as_deref(),
            ) {
                Ok(options) => options,
                Err(e) => {
                    eprintln!("[ERROR] Failed to build experimental options: {}", e);
                    seh_destroy!(
                        params,
                        Cronet_EngineParams_Destroy,
                        "SessionEngineParams_Options_cleanup"
                    );
                    seh_destroy!(
                        engine,
                        Cronet_Engine_Destroy,
                        "SessionEngine_Options_cleanup"
                    );
                    return String::new();
                }
            };
            verbose_log!(
                "[DEBUG] Setting experimental options: {}",
                c_options.to_string_lossy()
            );
            Cronet_EngineParams_experimental_options_set(params, c_options.as_ptr());

            let res = Cronet_Engine_StartWithParams(engine, params);
            seh_destroy!(
                params,
                Cronet_EngineParams_Destroy,
                "SessionEngineParams_Destroy"
            );

            if res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                eprintln!("[ERROR] Failed to create session engine: {:?}", res);
                seh_destroy!(engine, Cronet_Engine_Destroy, "SessionEngine_Start_cleanup");
                return String::new();
            }

            // 创建 in-flight 计数器用于监控
            let in_flight = Arc::new(AtomicUsize::new(0));

            let session = Session {
                id: session_id.clone(),
                engine_ptr: engine,
                config,
                created_at: Instant::now(),
                active_requests: Arc::new(AtomicUsize::new(0)),
                live_requests: Arc::new(AtomicUsize::new(0)),
                in_flight_executors: in_flight,
                is_closed: Arc::new(AtomicBool::new(false)),
                pending_requests: Arc::new(PendingRequests::default()),
                destroy_mutex: Arc::new(Mutex::new(())),
            };

            verbose_log!("[DEBUG] Created session: {}", session_id);
            match self.sessions.write() {
                Ok(mut sessions) => {
                    sessions.insert(session_id.clone(), session);
                }
                Err(poisoned) => {
                    eprintln!("[WARN] create_session: RwLock poisoned, recovering");
                    let mut sessions = poisoned.into_inner();
                    sessions.insert(session_id.clone(), session);
                }
            }
        }

        session_id
    }

    /// 使用会话发送请求
    /// 限制并发请求数量,避免资源泄漏
    /// 返回 (CronetRequest, Receiver, timeout_ms)
    pub fn send_request(
        &self,
        session_id: &str,
        target: &crate::cronet_pb::TargetRequest,
        allow_redirects: bool,
    ) -> Option<SessionRequestStart> {
        let sessions = match self.sessions.read() {
            Ok(guard) => guard,
            Err(poisoned) => {
                eprintln!("[WARN] send_request: RwLock poisoned, recovering");
                poisoned.into_inner()
            }
        };
        let session = sessions.get(session_id)?;

        // 检查 session 是否已关闭
        if session.is_closed.load(Ordering::Acquire) {
            eprintln!("[WARN] Session {} is closed, rejecting request", session_id);
            return None;
        }

        // 增加活跃请求计数
        session.active_requests.fetch_add(1, Ordering::Acquire);
        let current_active = session.active_requests.load(Ordering::Acquire);

        verbose_log!(
            "[DEBUG] Using session {} to send request to {} (active: {})",
            session_id,
            target.url,
            current_active
        );

        let (request, rx) = Self::start_request_with_engine(
            session.engine_ptr,
            target,
            Some(session.active_requests.clone()),
            Some(session.live_requests.clone()),
            Some(session.in_flight_executors.clone()),
            Some(session.pending_requests.clone()),
            allow_redirects,
            None,
            Some(session.destroy_mutex.clone()),
        );

        Some((request, rx, session.config.timeout_ms))
    }

    /// 使用会话发送流式请求
    /// 返回 (CronetRequest, mpsc::UnboundedReceiver<StreamChunk>, timeout_ms)
    pub fn send_request_stream(
        &self,
        session_id: &str,
        target: &crate::cronet_pb::TargetRequest,
        allow_redirects: bool,
    ) -> Option<(CronetRequest, mpsc::UnboundedReceiver<StreamChunk>, u64)> {
        let sessions = match self.sessions.read() {
            Ok(guard) => guard,
            Err(poisoned) => {
                eprintln!("[WARN] send_request_stream: RwLock poisoned, recovering");
                poisoned.into_inner()
            }
        };
        let session = sessions.get(session_id)?;

        if session.is_closed.load(Ordering::Acquire) {
            eprintln!(
                "[WARN] Session {} is closed, rejecting stream request",
                session_id
            );
            return None;
        }

        session.active_requests.fetch_add(1, Ordering::Acquire);

        let (stream_tx, stream_rx) = mpsc::unbounded_channel();

        let (request, _rx) = Self::start_request_with_engine(
            session.engine_ptr,
            target,
            Some(session.active_requests.clone()),
            Some(session.live_requests.clone()),
            Some(session.in_flight_executors.clone()),
            Some(session.pending_requests.clone()),
            allow_redirects,
            Some(stream_tx),
            Some(session.destroy_mutex.clone()),
        );

        Some((request, stream_rx, session.config.timeout_ms))
    }

    /// 使用指定的 engine 发送请求
    #[allow(clippy::too_many_arguments)]
    fn start_request_with_engine(
        engine_ptr: Cronet_EnginePtr,
        target: &crate::cronet_pb::TargetRequest,
        active_requests: Option<Arc<AtomicUsize>>,
        live_requests: Option<Arc<AtomicUsize>>,
        in_flight_executors: Option<Arc<AtomicUsize>>,
        pending_requests: Option<Arc<PendingRequests>>,
        allow_redirects: bool,
        stream_sender: Option<mpsc::UnboundedSender<StreamChunk>>,
        destroy_mutex: Option<Arc<Mutex<()>>>,
    ) -> (CronetRequest, RequestReceiver) {
        unsafe {
            let (tx, rx) = oneshot::channel();

            // 创建完成标志
            let completed = Arc::new(AtomicBool::new(false));
            let request_in_flight = Arc::new(AtomicUsize::new(0));

            let is_streaming = stream_sender.is_some();
            let context = Box::new(RequestContext {
                tx: Mutex::new(if is_streaming { None } else { Some(tx) }),
                response_buffer: Mutex::new(Vec::new()),
                response_headers: Mutex::new(Vec::new()),
                status_code: AtomicI32::new(0),
                completed: completed.clone(),
                active_requests,
                pending_requests: pending_requests.clone(),
                allow_redirects,
                redirect_response: Mutex::new(None),
                context_taken: AtomicBool::new(false),
                is_streaming,
                stream_tx: Mutex::new(stream_sender),
            });
            let context_ptr = Box::into_raw(context);

            // 创建独立的 ExecutorContext
            let executor_context = Box::new(ExecutorContext {
                request_in_flight: request_in_flight.clone(),
                aggregate_in_flight: in_flight_executors,
            });
            let executor_context_ptr = Box::into_raw(executor_context);

            // Executor - 使用独立的 ExecutorContext
            let executor_ptr = Cronet_Executor_CreateWith(Some(executor_execute));
            Cronet_Executor_SetClientContext(executor_ptr, executor_context_ptr as *mut c_void);

            // Callback - 使用 RequestContext
            let callback_ptr = Cronet_UrlRequestCallback_CreateWith(
                Some(on_redirect_received),
                Some(on_response_started),
                Some(on_read_completed),
                Some(on_succeeded),
                Some(on_failed),
                Some(on_canceled),
            );
            Cronet_UrlRequestCallback_SetClientContext(callback_ptr, context_ptr as *mut c_void);

            // Request & Params
            let request_ptr = Cronet_UrlRequest_Create();
            let params_ptr = Cronet_UrlRequestParams_Create();

            let c_method = safe_cstring(&target.method, "method").unwrap_or_else(|e| {
                eprintln!("[WARN] {}, using empty method", e);
                CString::new("").expect("literal has no nul bytes")
            });
            Cronet_UrlRequestParams_http_method_set(params_ptr, c_method.as_ptr());

            // Set highest priority to get HTTP/2 weight=256 (same as normal browsers)
            Cronet_UrlRequestParams_priority_set(
                params_ptr, 4, // REQUEST_PRIORITY_HIGHEST
            );

            let c_url = safe_cstring(&target.url, "url").unwrap_or_else(|e| {
                eprintln!("[WARN] {}, using empty url", e);
                CString::new("").expect("literal has no nul bytes")
            });

            // Headers - 按顺序添加（跳过无效的 header name/value）
            for header in &target.headers {
                if !is_valid_header_name(&header.name) {
                    eprintln!(
                        "[WARN] Skipping header with invalid name: {:?}",
                        header.name
                    );
                    continue;
                }
                if !is_valid_header_value(&header.value) {
                    eprintln!(
                        "[WARN] Skipping header with invalid value for key {:?}",
                        header.name
                    );
                    continue;
                }
                let c_key = safe_cstring(&header.name, "header_name").unwrap_or_else(|e| {
                    eprintln!("[WARN] {}, using empty header name", e);
                    CString::new("").expect("literal has no nul bytes")
                });
                let c_val = safe_cstring(&header.value, "header_value").unwrap_or_else(|e| {
                    eprintln!("[WARN] {}, using empty header value", e);
                    CString::new("").expect("literal has no nul bytes")
                });

                let header_ptr = Cronet_HttpHeader_Create();
                Cronet_HttpHeader_name_set(header_ptr, c_key.as_ptr());
                Cronet_HttpHeader_value_set(header_ptr, c_val.as_ptr());

                Cronet_UrlRequestParams_request_headers_add(params_ptr, header_ptr);
                seh_destroy!(header_ptr, Cronet_HttpHeader_Destroy, "HttpHeader_Destroy");
            }

            // Upload Data Provider (Body)
            let mut upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr> = None;
            let mut upload_context_ptr: *mut UploadContext = std::ptr::null_mut();
            let upload_body_data = if !target.body.is_empty() {
                Some(target.body.clone())
            } else {
                None
            };

            if let Some(body) = &upload_body_data {
                let upload_context = Box::new(UploadContext {
                    data: body.clone(),
                    position: 0,
                });
                upload_context_ptr = Box::into_raw(upload_context);

                let provider = Cronet_UploadDataProvider_CreateWith(
                    Some(upload_get_length),
                    Some(upload_read),
                    Some(upload_rewind),
                    Some(upload_close),
                );
                Cronet_UploadDataProvider_SetClientContext(
                    provider,
                    upload_context_ptr as *mut c_void,
                );

                Cronet_UrlRequestParams_upload_data_provider_set(params_ptr, provider);
                Cronet_UrlRequestParams_upload_data_provider_executor_set(params_ptr, executor_ptr);

                upload_data_provider_ptr = Some(provider);
            }

            if let Some(ref counter) = live_requests {
                counter.fetch_add(1, Ordering::Release);
            }

            let init_res = Cronet_UrlRequest_InitWithParams(
                request_ptr,
                engine_ptr,
                c_url.as_ptr(),
                params_ptr,
                callback_ptr,
                executor_ptr,
            );

            seh_destroy!(
                params_ptr,
                Cronet_UrlRequestParams_Destroy,
                "UrlRequestParams_Destroy"
            );

            if init_res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                complete_request(
                    callback_ptr,
                    request_ptr,
                    Err(format!(
                        "Cronet_UrlRequest_InitWithParams failed: {:?}",
                        init_res
                    )),
                );
            } else {
                // 将请求指针添加到 pending_requests 列表
                if let Some(ref pending) = pending_requests {
                    pending.add(request_ptr);
                }

                // Start
                let start_res = Cronet_UrlRequest_Start(request_ptr);

                if start_res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                    complete_request(
                        callback_ptr,
                        request_ptr,
                        Err(format!("Cronet_UrlRequest_Start failed: {:?}", start_res)),
                    );
                }
            }

            let request_handle = CronetRequest {
                ptr: request_ptr,
                callback_ptr,
                request_context_ptr: context_ptr,
                executor_ptr,
                executor_context_ptr,
                owned_engine_ptr: None, // Session owns the engine
                upload_data_provider_ptr,
                upload_context_ptr,
                upload_body_data,
                completed,
                request_in_flight,
                live_requests,
                pending_requests, // 保存引用以便在完成时移除
                destroy_mutex,    // 序列化销毁，防止并发 Destroy 崩溃
            };

            (request_handle, rx)
        }
    }

    /// 关闭会话
    pub fn close_session(&self, session_id: &str) -> bool {
        let mut sessions = match self.sessions.write() {
            Ok(guard) => guard,
            Err(poisoned) => {
                eprintln!("[WARN] close_session: RwLock poisoned, recovering");
                poisoned.into_inner()
            }
        };
        if sessions.remove(session_id).is_some() {
            verbose_log!("[DEBUG] Closed session: {}", session_id);
            true
        } else {
            verbose_log!("[DEBUG] Session not found: {}", session_id);
            false
        }
    }

    /// 列出所有会话ID
    pub fn list_sessions(&self) -> Vec<String> {
        match self.sessions.read() {
            Ok(guard) => guard.keys().cloned().collect(),
            Err(poisoned) => poisoned.into_inner().keys().cloned().collect(),
        }
    }

    /// 获取会话数量
    pub fn session_count(&self) -> usize {
        match self.sessions.read() {
            Ok(guard) => guard.len(),
            Err(poisoned) => poisoned.into_inner().len(),
        }
    }

    /// 检查会话是否存在
    pub fn session_exists(&self, session_id: &str) -> bool {
        match self.sessions.read() {
            Ok(guard) => guard.contains_key(session_id),
            Err(poisoned) => poisoned.into_inner().contains_key(session_id),
        }
    }

    /// 获取 session 的 engine_ptr（供 WebSocket 使用）
    pub fn get_engine_ptr(&self, session_id: &str) -> Option<Cronet_EnginePtr> {
        self.get_engine_handle(session_id).map(|(ptr, _)| ptr)
    }

    pub(crate) fn get_engine_handle(
        &self,
        session_id: &str,
    ) -> Option<(Cronet_EnginePtr, Arc<AtomicUsize>)> {
        self.sessions.read().ok()?.get(session_id).and_then(|s| {
            if s.is_closed.load(Ordering::Acquire) {
                None
            } else {
                Some((s.engine_ptr, s.live_requests.clone()))
            }
        })
    }
}

impl Default for SessionManager {
    fn default() -> Self {
        Self::new()
    }
}

// -----------------------------------------------------------------------------
// WebSocket Support
// -----------------------------------------------------------------------------

/// WebSocket 事件
#[derive(Debug, Clone)]
pub enum WebSocketEvent {
    Open {
        protocol: String,
    },
    Message {
        is_text: bool,
        data: Vec<u8>,
    },
    Close {
        was_clean: bool,
        code: u16,
        reason: String,
    },
    Error {
        net_error: i32,
        message: String,
    },
}

/// 内部状态，通过 user_data 指针传递给 C 回调
struct WebSocketState {
    tx: std::sync::mpsc::Sender<WebSocketEvent>,
    closed: AtomicBool,
}

unsafe extern "C" fn ws_on_open(
    _ws: Cronet_WebSocketPtr,
    user_data: *mut c_void,
    protocol: *const std::os::raw::c_char,
) {
    if user_data.is_null() {
        return;
    }
    let state = &*(user_data as *const WebSocketState);
    let proto = if protocol.is_null() {
        String::new()
    } else {
        CStr::from_ptr(protocol).to_string_lossy().into_owned()
    };
    let _ = state.tx.send(WebSocketEvent::Open { protocol: proto });
}

unsafe extern "C" fn ws_on_message(
    _ws: Cronet_WebSocketPtr,
    user_data: *mut c_void,
    msg_type: Cronet_WebSocket_MessageType,
    data: *const c_void,
    len: u64,
) {
    if user_data.is_null() {
        return;
    }
    let state = &*(user_data as *const WebSocketState);
    let slice = std::slice::from_raw_parts(data as *const u8, len as usize);
    let _ = state.tx.send(WebSocketEvent::Message {
        is_text: msg_type == Cronet_WebSocket_MessageType_Cronet_WebSocket_MESSAGE_TEXT,
        data: slice.to_vec(),
    });
}

unsafe extern "C" fn ws_on_close(
    _ws: Cronet_WebSocketPtr,
    user_data: *mut c_void,
    was_clean: std::os::raw::c_int,
    code: u16,
    reason: *const std::os::raw::c_char,
) {
    if user_data.is_null() {
        return;
    }
    let state = &*(user_data as *const WebSocketState);
    state.closed.store(true, Ordering::Release);
    let reason_str = if reason.is_null() {
        String::new()
    } else {
        CStr::from_ptr(reason).to_string_lossy().into_owned()
    };
    let _ = state.tx.send(WebSocketEvent::Close {
        was_clean: was_clean != 0,
        code,
        reason: reason_str,
    });
}

unsafe extern "C" fn ws_on_error(
    _ws: Cronet_WebSocketPtr,
    user_data: *mut c_void,
    net_error: std::os::raw::c_int,
    message: *const std::os::raw::c_char,
) {
    if user_data.is_null() {
        return;
    }
    let state = &*(user_data as *const WebSocketState);
    state.closed.store(true, Ordering::Release);
    let msg = if message.is_null() {
        String::new()
    } else {
        CStr::from_ptr(message).to_string_lossy().into_owned()
    };
    let _ = state.tx.send(WebSocketEvent::Error {
        net_error,
        message: msg,
    });
}

/// Rust-safe WebSocket handle
pub struct CronetWebSocket {
    ws_ptr: Cronet_WebSocketPtr,
    // Box 保持 state 存活，C 回调通过 user_data 指针访问
    state: Option<Box<WebSocketState>>,
    pub rx: std::sync::mpsc::Receiver<WebSocketEvent>,
    session_live: Option<Arc<AtomicUsize>>,
}

unsafe impl Send for CronetWebSocket {}

impl CronetWebSocket {
    /// 用已有 engine 创建 WebSocket
    ///
    /// # Safety
    /// `engine_ptr` must point to a live Cronet engine that outlives the returned
    /// WebSocket handle. The caller must not destroy the engine before dropping
    /// this handle.
    pub unsafe fn new(engine_ptr: Cronet_EnginePtr) -> Result<Self, String> {
        Self::new_inner(engine_ptr, None)
    }

    pub(crate) unsafe fn new_with_lifetime(
        engine_ptr: Cronet_EnginePtr,
        session_live: Arc<AtomicUsize>,
    ) -> Result<Self, String> {
        session_live.fetch_add(1, Ordering::Release);
        match Self::new_inner(engine_ptr, Some(session_live.clone())) {
            Ok(ws) => Ok(ws),
            Err(e) => {
                session_live.fetch_sub(1, Ordering::Release);
                Err(e)
            }
        }
    }

    unsafe fn new_inner(
        engine_ptr: Cronet_EnginePtr,
        session_live: Option<Arc<AtomicUsize>>,
    ) -> Result<Self, String> {
        let (tx, rx) = std::sync::mpsc::channel();
        let state = Box::new(WebSocketState {
            tx,
            closed: AtomicBool::new(false),
        });
        let state_ptr = &*state as *const WebSocketState as *mut c_void;

        let callbacks = Cronet_WebSocket_Callbacks {
            on_open: Some(ws_on_open),
            on_message: Some(ws_on_message),
            on_close: Some(ws_on_close),
            on_error: Some(ws_on_error),
        };

        let ws_ptr = unsafe { Cronet_WebSocket_Create(engine_ptr, &callbacks, state_ptr) };
        if ws_ptr.is_null() {
            return Err("Failed to create WebSocket".to_string());
        }

        Ok(CronetWebSocket {
            ws_ptr,
            state: Some(state),
            rx,
            session_live,
        })
    }

    pub fn connect(
        &self,
        url: &str,
        sub_protocols: Option<&str>,
        origin: Option<&str>,
        extra_headers: Option<&str>,
    ) -> Result<(), String> {
        let c_url = safe_cstring(url, "ws_url")?;
        let c_protos = sub_protocols
            .map(|s| safe_cstring(s, "ws_sub_protocols"))
            .transpose()?;
        let c_origin = origin.map(|s| safe_cstring(s, "ws_origin")).transpose()?;
        let c_headers = extra_headers
            .map(|s| safe_cstring(s, "ws_extra_headers"))
            .transpose()?;

        let ret = unsafe {
            Cronet_WebSocket_Connect(
                self.ws_ptr,
                c_url.as_ptr(),
                c_protos.as_ref().map_or(ptr::null(), |s| s.as_ptr()),
                c_origin.as_ref().map_or(ptr::null(), |s| s.as_ptr()),
                c_headers.as_ref().map_or(ptr::null(), |s| s.as_ptr()),
            )
        };
        if ret != 0 {
            return Err(format!("WebSocket connect failed: {}", ret));
        }
        Ok(())
    }

    pub fn send_text(&self, text: &str) -> Result<(), String> {
        let ret = unsafe {
            Cronet_WebSocket_Send(
                self.ws_ptr,
                Cronet_WebSocket_MessageType_Cronet_WebSocket_MESSAGE_TEXT,
                text.as_ptr() as *const c_void,
                text.len() as u64,
            )
        };
        if ret != 0 {
            return Err(format!("WebSocket send failed: {}", ret));
        }
        Ok(())
    }

    pub fn send_binary(&self, data: &[u8]) -> Result<(), String> {
        let ret = unsafe {
            Cronet_WebSocket_Send(
                self.ws_ptr,
                Cronet_WebSocket_MessageType_Cronet_WebSocket_MESSAGE_BINARY,
                data.as_ptr() as *const c_void,
                data.len() as u64,
            )
        };
        if ret != 0 {
            return Err(format!("WebSocket send failed: {}", ret));
        }
        Ok(())
    }

    pub fn close(&self, code: u16, reason: &str) -> Result<(), String> {
        let c_reason = safe_cstring(reason, "ws_close_reason")?;
        let ret = unsafe { Cronet_WebSocket_Close(self.ws_ptr, code, c_reason.as_ptr()) };
        if ret != 0 {
            return Err(format!("WebSocket close failed: {}", ret));
        }
        Ok(())
    }
}

impl Drop for CronetWebSocket {
    fn drop(&mut self) {
        unsafe {
            if !self.ws_ptr.is_null() {
                seh_destroy!(self.ws_ptr, Cronet_WebSocket_Destroy, "WebSocket_Destroy");
            }
            if let Some(state) = self.state.take() {
                if !state.closed.load(Ordering::Acquire) {
                    eprintln!(
                        "[WARN] CronetWebSocket::drop - leaking callback state because websocket did not close cleanly"
                    );
                    Box::leak(state);
                }
            }
            if let Some(counter) = self.session_live.take() {
                counter.fetch_sub(1, Ordering::Release);
            }
        }
    }
}
