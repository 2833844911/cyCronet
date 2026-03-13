use crate::cronet_c::*;
use crate::cronet_pb::proxy_config::ProxyType;
use crate::VERBOSE_MODE;
use std::collections::HashMap;
use std::ffi::{c_void, CStr, CString};
use std::ptr;
use std::sync::atomic::{AtomicBool, AtomicUsize, AtomicI32, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::oneshot;

// Macro for verbose logging
macro_rules! verbose_log {
    ($($arg:tt)*) => {
        if VERBOSE_MODE.load(Ordering::Relaxed) {
            eprintln!($($arg)*);
        }
    };
}

// 安全地创建 CString，过滤掉 null 字节
fn safe_cstring(s: &str, context: &str) -> Result<CString, String> {
    // 移除 null 字节
    let safe_str = s.replace('\0', "");
    CString::new(safe_str).map_err(|e| {
        format!("Failed to create CString for {}: {}", context, e)
    })
}

// 验证 HTTP header name 是否合法 (RFC 7230 token)
// token = 1*tchar
// tchar = "!" / "#" / "$" / "%" / "&" / "'" / "*" / "+" / "-" / "." /
//         "^" / "_" / "`" / "|" / "~" / DIGIT / ALPHA
fn is_valid_header_name(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    name.bytes().all(|b| matches!(b,
        b'!' | b'#' | b'$' | b'%' | b'&' | b'\'' | b'*' | b'+' | b'-' | b'.' |
        b'^' | b'_' | b'`' | b'|' | b'~' |
        b'0'..=b'9' | b'A'..=b'Z' | b'a'..=b'z'
    ))
}

// 验证 HTTP header value 是否合法（不含控制字符，除了水平制表符）
fn is_valid_header_value(value: &str) -> bool {
    value.bytes().all(|b| b == b'\t' || (b >= 0x20 && b != 0x7f))
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
}

impl CronetEngine {
    pub fn new(user_agent: &str) -> Self {
        unsafe {
            let engine_ptr = Cronet_Engine_Create();
            let params_ptr = Cronet_EngineParams_Create();

            // 安全地创建 CString
            let c_ua = match safe_cstring(user_agent, "user_agent") {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("[ERROR] {}, using default", e);
                    CString::new("CronetClient/1.0").unwrap()
                }
            };
            Cronet_EngineParams_user_agent_set(params_ptr, c_ua.as_ptr());

            // Use true for params
            Cronet_EngineParams_enable_quic_set(params_ptr, true);
            Cronet_EngineParams_enable_http2_set(params_ptr, true);
            Cronet_EngineParams_enable_brotli_set(params_ptr, true);

            // Enable Cookie Store to handle Set-Cookie in 302 redirects
            let experimental_options = r#"{"enable_cookie_store":true}"#;
            let c_options = CString::new(experimental_options).expect("Invalid experimental options");
            Cronet_EngineParams_experimental_options_set(params_ptr, c_options.as_ptr());

            // Start the engine
            let res = Cronet_Engine_StartWithParams(engine_ptr, params_ptr);
            Cronet_EngineParams_Destroy(params_ptr);

            if res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                panic!("Failed to start Cronet Engine: {:?}", res);
            }

            CronetEngine {
                ptr: engine_ptr,
                engine_cache: Mutex::new(HashMap::new()),
            }
        }
    }

    // Get or create a cached engine with custom configuration
    fn get_or_create_engine(&self, config_key: &EngineConfig) -> Cronet_EnginePtr {
        let mut cache = self.engine_cache.lock().unwrap();

        if let Some(cached) = cache.get(config_key) {
            verbose_log!("[DEBUG] Reusing cached engine for config: {:?}", config_key);
            return cached.ptr;
        }

        verbose_log!("[DEBUG] Creating new engine for config: {:?}", config_key);
        unsafe {
            let engine = Cronet_Engine_Create();
            let params = Cronet_EngineParams_Create();

            // Configure proxy if present
            if let Some(ref proxy_rules) = config_key.proxy_rules {
                let c_rules = CString::new(proxy_rules.as_str()).expect("Invalid proxy string");
                Cronet_EngineParams_proxy_rules_set(params, c_rules.as_ptr());
            }

            Cronet_EngineParams_enable_quic_set(params, true);
            Cronet_EngineParams_enable_http2_set(params, true);

            // Skip certificate verification if requested
            if config_key.skip_cert_verify {
                Cronet_EngineParams_skip_cert_verify_set(params, true);
            }

            // Enable Cookie Store to handle Set-Cookie in 302 redirects
            let experimental_options = r#"{"enable_cookie_store":true}"#;
            let c_options = CString::new(experimental_options).expect("Invalid experimental options");
            Cronet_EngineParams_experimental_options_set(params, c_options.as_ptr());

            Cronet_Engine_StartWithParams(engine, params);
            Cronet_EngineParams_Destroy(params);

            cache.insert(config_key.clone(), CachedEngine { ptr: engine });
            engine
        }
    }

    pub fn start_request(
        &self,
        target: &crate::cronet_pb::TargetRequest,
        config: &crate::cronet_pb::ExecutionConfig,
    ) -> (
        CronetRequest,
        oneshot::Receiver<Result<RequestResult, String>>,
    ) {
        unsafe {
            verbose_log!("[DEBUG] start_request entered");
            // Determine Engine to use (Shared or Cached Engine with custom config)
            let needs_custom_engine = config.proxy.is_some() || config.skip_cert_verify;
            let engine_ptr = if needs_custom_engine {
                // Build proxy rules string if proxy is configured
                let proxy_rules = if let Some(proxy) = &config.proxy {
                    let scheme = match ProxyType::try_from(proxy.r#type).unwrap_or(ProxyType::Http) {
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
                self.get_or_create_engine(&config_key)
            } else {
                self.ptr
            };
            // owned_engine_ptr is no longer needed since we cache engines
            let owned_engine_ptr: Option<Cronet_EnginePtr> = None;

            // Channel to receive the final result
            let (tx, rx) = oneshot::channel();

            // 创建完成标志，用于追踪请求是否已完成
            let completed = Arc::new(AtomicBool::new(false));

            // Create Context to hold state across callbacks
            let context = Box::new(RequestContext {
                tx: Mutex::new(Some(tx)),
                response_buffer: Mutex::new(Vec::new()),
                response_headers: Mutex::new(Vec::new()),
                status_code: AtomicI32::new(0),
                completed: completed.clone(),
                active_requests: None,  // CronetEngine 不使用活跃请求计数
                allow_redirects: true,  // 默认允许重定向（REST API）
                redirect_response: Mutex::new(None),
                context_taken: AtomicBool::new(false),
            });

            let context_ptr = Box::into_raw(context);

            // 复用引擎共享的 executor 线程（避免每个请求创建新线程）
            let executor_context = Box::new(ExecutorContext {
                in_flight_executors: None,  // CronetEngine 不使用 in-flight 计数
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

            let c_method = CString::new(target.method.as_str()).unwrap();
            Cronet_UrlRequestParams_http_method_set(params_ptr, c_method.as_ptr());

            // Set highest priority to get HTTP/2 weight=256 (same as normal browsers)
            Cronet_UrlRequestParams_priority_set(
                params_ptr,
                4  // REQUEST_PRIORITY_HIGHEST
            );

            let c_url = CString::new(target.url.as_str()).unwrap();

            // Headers - 按顺序添加（跳过无效的 header name/value）
            for header in &target.headers {
                if !is_valid_header_name(&header.name) {
                    eprintln!("[WARN] Skipping header with invalid name: {:?}", header.name);
                    continue;
                }
                if !is_valid_header_value(&header.value) {
                    eprintln!("[WARN] Skipping header with invalid value for key {:?}", header.name);
                    continue;
                }
                let c_key = CString::new(header.name.as_str()).unwrap();
                let c_val = CString::new(header.value.as_str()).unwrap();

                let header_ptr = Cronet_HttpHeader_Create();
                Cronet_HttpHeader_name_set(header_ptr, c_key.as_ptr());
                Cronet_HttpHeader_value_set(header_ptr, c_val.as_ptr());

                Cronet_UrlRequestParams_request_headers_add(params_ptr, header_ptr);

                Cronet_HttpHeader_Destroy(header_ptr);
            }

            // Upload Data Provider (Body)
            let mut upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr> = None;

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
                let upload_context_ptr = Box::into_raw(upload_context);

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

            Cronet_UrlRequest_InitWithParams(
                request_ptr,
                engine_ptr,
                c_url.as_ptr(),
                params_ptr,
                callback_ptr,
                executor_ptr,
            );

            Cronet_UrlRequestParams_Destroy(params_ptr);

            // Start
            verbose_log!("[DEBUG] Starting Cronet Request");
            Cronet_UrlRequest_Start(request_ptr);

            // Return Handle that owns the cleanup
            let request_handle = CronetRequest {
                ptr: request_ptr,
                callback_ptr,
                executor_ptr,
                executor_context_ptr,
                owned_engine_ptr,
                upload_data_provider_ptr,
                upload_body_data,
                completed,
            };

            (request_handle, rx)
        }
    }
}

impl Drop for CronetEngine {
    fn drop(&mut self) {
        unsafe {
            // Clean up cached engines
            let cache = self.engine_cache.lock().unwrap();
            for (_, cached) in cache.iter() {
                Cronet_Engine_Shutdown(cached.ptr);
                Cronet_Engine_Destroy(cached.ptr);
            }
            drop(cache);

            // Clean up main engine
            Cronet_Engine_Shutdown(self.ptr);
            Cronet_Engine_Destroy(self.ptr);
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

#[allow(dead_code)]
pub struct CronetRequest {
    ptr: Cronet_UrlRequestPtr,
    callback_ptr: Cronet_UrlRequestCallbackPtr,
    executor_ptr: Cronet_ExecutorPtr,
    executor_context_ptr: *mut ExecutorContext,  // Executor 的独立 context
    owned_engine_ptr: Option<Cronet_EnginePtr>,
    upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr>,
    upload_body_data: Option<Vec<u8>>, // Owns the body data so pointers are valid
    completed: Arc<AtomicBool>,  // 标记请求是否完成，由回调设置
}

unsafe impl Send for CronetRequest {}

impl Drop for CronetRequest {
    fn drop(&mut self) {
        unsafe {
            // 检查请求是否已完成
            if !self.completed.load(Ordering::Acquire) {
                // 请求尚未完成，先取消它
                verbose_log!("[DEBUG] CronetRequest::drop - Request not completed, canceling...");
                if !self.ptr.is_null() {
                    Cronet_UrlRequest_Cancel(self.ptr);
                }
                // 等待请求完成（最多等待 5 秒）
                let start = std::time::Instant::now();
                while !self.completed.load(Ordering::Acquire) {
                    if start.elapsed() > std::time::Duration::from_secs(5) {
                        eprintln!("[WARN] CronetRequest::drop - Timeout waiting for cancel callback");
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
            }

            // 现在可以安全销毁了（同步执行模式下不需要等待 executor）
            if !self.ptr.is_null() {
                Cronet_UrlRequest_Destroy(self.ptr);
            }
            if !self.callback_ptr.is_null() {
                Cronet_UrlRequestCallback_Destroy(self.callback_ptr);
            }
            if !self.executor_ptr.is_null() {
                Cronet_Executor_Destroy(self.executor_ptr);
            }
            // 释放 ExecutorContext
            if !self.executor_context_ptr.is_null() {
                let _ = Box::from_raw(self.executor_context_ptr);
            }
            if let Some(dp) = self.upload_data_provider_ptr {
                Cronet_UploadDataProvider_Destroy(dp);
            }
            // Finally destroy engine if we own it
            if let Some(engine_ptr) = self.owned_engine_ptr {
                Cronet_Engine_Shutdown(engine_ptr);
                Cronet_Engine_Destroy(engine_ptr);
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
    completed: Arc<AtomicBool>,  // 标记请求是否完成
    active_requests: Option<Arc<AtomicUsize>>,  // Session 的活跃请求计数器
    allow_redirects: bool,  // 是否允许重定向（只读，不需要锁）
    redirect_response: Mutex<Option<RequestResult>>,  // 存储重定向响应（当 allow_redirects=false 时）
    context_taken: AtomicBool,  // 防止双重释放：标记 context 是否已被取走
}

// Executor 专用 context - 独立于 RequestContext，避免 use-after-free
struct ExecutorContext {
    in_flight_executors: Option<Arc<AtomicUsize>>,
}

// -----------------------------------------------------------------------------
// C Callbacks (Extern "C")
// -----------------------------------------------------------------------------

unsafe extern "C" fn executor_execute(_self: Cronet_ExecutorPtr, command: Cronet_RunnablePtr) {
    // 同步执行，避免线程调度导致的竞态条件
    // 这会牺牲一些性能，但能保证线程安全
    Cronet_Runnable_Run(command);
    Cronet_Runnable_Destroy(command);
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
                eprintln!("[WARN] on_redirect_received: response_headers mutex poisoned, recovering");
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
        Cronet_UrlRequest_Cancel(request);
    }
}

unsafe extern "C" fn on_response_started(
    self_: Cronet_UrlRequestCallbackPtr,
    request: Cronet_UrlRequestPtr,
    info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_response_started");
    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;
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
    let context = &*context_ptr;

    let data_ptr = Cronet_Buffer_GetData(buffer);
    let slice = std::slice::from_raw_parts(data_ptr as *const u8, bytes_read as usize);

    // 使用锁保护 response_buffer，处理 poisoned
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

    Cronet_Buffer_Destroy(buffer);

    let new_buffer = Cronet_Buffer_Create();
    Cronet_Buffer_InitWithAlloc(new_buffer, 32 * 1024);

    Cronet_UrlRequest_Read(request, new_buffer);
}

unsafe extern "C" fn on_succeeded(
    self_: Cronet_UrlRequestCallbackPtr,
    _request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_succeeded");
    complete_request(self_, Ok(()));
}

unsafe extern "C" fn on_failed(
    self_: Cronet_UrlRequestCallbackPtr,
    _request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
    error: Cronet_ErrorPtr,
) {
    verbose_log!("[DEBUG] on_failed");
    let msg = CStr::from_ptr(Cronet_Error_message_get(error))
        .to_string_lossy()
        .into_owned();
    complete_request(self_, Err(msg));
}

unsafe extern "C" fn on_canceled(
    self_: Cronet_UrlRequestCallbackPtr,
    _request: Cronet_UrlRequestPtr,
    _info: Cronet_UrlResponseInfoPtr,
) {
    verbose_log!("[DEBUG] on_canceled");

    let context_ptr = Cronet_UrlRequestCallback_GetClientContext(self_) as *mut RequestContext;

    // 检查 context 是否已被取走，防止双重释放
    let context_ref = &*context_ptr;
    if context_ref.context_taken.swap(true, Ordering::AcqRel) {
        verbose_log!("[WARN] on_canceled: Context already taken, skipping");
        return;
    }

    let context = Box::from_raw(context_ptr);

    // 标记请求已完成
    context.completed.store(true, Ordering::Release);

    // 减少活跃请求计数
    if let Some(ref active_requests) = context.active_requests {
        active_requests.fetch_sub(1, Ordering::Release);
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
        verbose_log!("[DEBUG] on_canceled: Sending redirect response (status {})", redirect_response.status_code);
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

unsafe fn complete_request(callback_ptr: Cronet_UrlRequestCallbackPtr, result: Result<(), String>) {
    let context_ptr =
        Cronet_UrlRequestCallback_GetClientContext(callback_ptr) as *mut RequestContext;

    // 检查 context 是否已被取走，防止双重释放
    let context_ref = &*context_ptr;
    if context_ref.context_taken.swap(true, Ordering::AcqRel) {
        verbose_log!("[WARN] complete_request: Context already taken, skipping");
        return;
    }

    // Take ownership back to drop it.
    let context = Box::from_raw(context_ptr);

    // 标记请求已完成
    context.completed.store(true, Ordering::Release);

    // 递减活跃请求计数
    if let Some(ref counter) = context.active_requests {
        counter.fetch_sub(1, Ordering::Release);
    }

    verbose_log!("[DEBUG] complete_request: {:?}", result);

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
                        eprintln!("[WARN] complete_request: response_headers mutex poisoned, recovering");
                        poisoned.into_inner().clone()
                    }
                };

                let body = match context.response_buffer.lock() {
                    Ok(guard) => guard.clone(),
                    Err(poisoned) => {
                        eprintln!("[WARN] complete_request: response_buffer mutex poisoned, recovering");
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
    let context = &*context_ptr;
    context.data.len() as i64
}

unsafe extern "C" fn upload_read(
    self_: Cronet_UploadDataProviderPtr,
    sink: Cronet_UploadDataSinkPtr,
    buffer: Cronet_BufferPtr,
) {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
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
    let context = &mut *context_ptr;
    context.position = 0;
    Cronet_UploadDataSink_OnRewindSucceeded(sink);
}

unsafe extern "C" fn upload_close(self_: Cronet_UploadDataProviderPtr) {
    let context_ptr = Cronet_UploadDataProvider_GetClientContext(self_) as *mut UploadContext;
    // Take ownership to drop
    let _ = Box::from_raw(context_ptr);
}

// -----------------------------------------------------------------------------
// Session Management
// -----------------------------------------------------------------------------

use std::sync::RwLock;
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
    pub allow_redirects: bool,
}

/// 单个会话 - 持有独立的 Cronet Engine
pub struct Session {
    pub id: String,
    engine_ptr: Cronet_EnginePtr,
    pub config: SessionConfig,
    pub created_at: Instant,
    active_requests: Arc<AtomicUsize>,  // 追踪活跃请求数量（仅用于监控）
    in_flight_executors: Arc<AtomicUsize>,  // 追踪正在执行的 executor 回调数量
    is_closed: Arc<AtomicBool>,  // 标记 session 是否已关闭
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
                // 等待所有活跃请求完成
                let active = self.active_requests.load(Ordering::Acquire);
                verbose_log!("[DEBUG] Session::drop - active_requests={}", active);

                if active > 0 {
                    verbose_log!("[DEBUG] Session::drop - Waiting for {} active requests to complete", active);
                    let start = std::time::Instant::now();
                    while self.active_requests.load(Ordering::Acquire) > 0 {
                        if start.elapsed() > std::time::Duration::from_secs(30) {
                            eprintln!("[WARN] Session::drop - Timeout waiting for {} active requests",
                                self.active_requests.load(Ordering::Acquire));
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(50));
                    }
                }

                // 同步执行模式下不需要等待 executor 线程
                verbose_log!("[DEBUG] Session::drop - Calling Cronet_Engine_Shutdown");
                Cronet_Engine_Shutdown(self.engine_ptr);

                verbose_log!("[DEBUG] Session::drop - Calling Cronet_Engine_Destroy");
                Cronet_Engine_Destroy(self.engine_ptr);
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

            if let Some(ref proxy_rules) = config.proxy_rules {
                let c_rules = CString::new(proxy_rules.as_str()).expect("Invalid proxy string");
                Cronet_EngineParams_proxy_rules_set(params, c_rules.as_ptr());
            }

            Cronet_EngineParams_enable_quic_set(params, true);
            Cronet_EngineParams_enable_http2_set(params, true);
            Cronet_EngineParams_enable_brotli_set(params, true);

            if config.skip_cert_verify {
                Cronet_EngineParams_skip_cert_verify_set(params, true);
            }

            // Set custom TLS configuration and enable cookie store
            let mut options_parts = Vec::new();

            // Always enable Cookie Store to handle Set-Cookie in 302 redirects
            options_parts.push("\"enable_cookie_store\":true".to_string());

            if let Some(ref cipher_suites) = config.cipher_suites {
                if !cipher_suites.is_empty() {
                    let cipher_suites_json: Vec<String> = cipher_suites
                        .iter()
                        .map(|s| format!("\"{}\"", s))
                        .collect();
                    options_parts.push(format!(
                        "\"tls_cipher_suites\":[{}]",
                        cipher_suites_json.join(",")
                    ));
                }
            }

            if let Some(ref tls_curves) = config.tls_curves {
                if !tls_curves.is_empty() {
                    let tls_curves_json: Vec<String> = tls_curves
                        .iter()
                        .map(|s| format!("\"{}\"", s))
                        .collect();
                    options_parts.push(format!(
                        "\"tls_curves\":[{}]",
                        tls_curves_json.join(",")
                    ));
                }
            }

            if let Some(ref tls_extensions) = config.tls_extensions {
                if !tls_extensions.is_empty() {
                    let tls_extensions_json: Vec<String> = tls_extensions
                        .iter()
                        .map(|s| format!("\"{}\"", s))
                        .collect();
                    options_parts.push(format!(
                        "\"tls_extensions\":[{}]",
                        tls_extensions_json.join(",")
                    ));
                }
            }

            // Always set experimental_options (at least for enable_cookie_store)
            if !options_parts.is_empty() {
                let experimental_options = format!("{{{}}}", options_parts.join(","));
                verbose_log!("[DEBUG] Setting experimental options: {}", experimental_options);
                let c_options = CString::new(experimental_options).expect("Invalid experimental options");
                Cronet_EngineParams_experimental_options_set(params, c_options.as_ptr());
            }

            let res = Cronet_Engine_StartWithParams(engine, params);
            Cronet_EngineParams_Destroy(params);

            if res != Cronet_RESULT_Cronet_RESULT_SUCCESS {
                eprintln!("[ERROR] Failed to create session engine: {:?}", res);
                Cronet_Engine_Destroy(engine);
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
                in_flight_executors: in_flight,
                is_closed: Arc::new(AtomicBool::new(false)),
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
    ) -> Option<(CronetRequest, oneshot::Receiver<Result<RequestResult, String>>, u64)> {
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

        verbose_log!("[DEBUG] Using session {} to send request to {} (active: {})",
            session_id, target.url, current_active);

        let (request, rx) = Self::start_request_with_engine(
            session.engine_ptr,
            target,
            Some(session.active_requests.clone()),
            Some(session.in_flight_executors.clone()),
            allow_redirects,
        );

        Some((request, rx, session.config.timeout_ms))
    }

    /// 使用指定的 engine 发送请求
    fn start_request_with_engine(
        engine_ptr: Cronet_EnginePtr,
        target: &crate::cronet_pb::TargetRequest,
        active_requests: Option<Arc<AtomicUsize>>,
        in_flight_executors: Option<Arc<AtomicUsize>>,
        allow_redirects: bool,
    ) -> (CronetRequest, oneshot::Receiver<Result<RequestResult, String>>) {
        unsafe {
            let (tx, rx) = oneshot::channel();

            // 创建完成标志
            let completed = Arc::new(AtomicBool::new(false));

            let context = Box::new(RequestContext {
                tx: Mutex::new(Some(tx)),
                response_buffer: Mutex::new(Vec::new()),
                response_headers: Mutex::new(Vec::new()),
                status_code: AtomicI32::new(0),
                completed: completed.clone(),
                active_requests,
                allow_redirects,
                redirect_response: Mutex::new(None),
                context_taken: AtomicBool::new(false),
            });
            let context_ptr = Box::into_raw(context);

            // 创建独立的 ExecutorContext
            let executor_context = Box::new(ExecutorContext {
                in_flight_executors,
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

            let c_method = CString::new(target.method.as_str()).unwrap();
            Cronet_UrlRequestParams_http_method_set(params_ptr, c_method.as_ptr());

            // Set highest priority to get HTTP/2 weight=256 (same as normal browsers)
            Cronet_UrlRequestParams_priority_set(
                params_ptr,
                4  // REQUEST_PRIORITY_HIGHEST
            );

            let c_url = CString::new(target.url.as_str()).unwrap();

            // Headers - 按顺序添加（跳过无效的 header name/value）
            for header in &target.headers {
                if !is_valid_header_name(&header.name) {
                    eprintln!("[WARN] Skipping header with invalid name: {:?}", header.name);
                    continue;
                }
                if !is_valid_header_value(&header.value) {
                    eprintln!("[WARN] Skipping header with invalid value for key {:?}", header.name);
                    continue;
                }
                let c_key = CString::new(header.name.as_str()).unwrap();
                let c_val = CString::new(header.value.as_str()).unwrap();

                let header_ptr = Cronet_HttpHeader_Create();
                Cronet_HttpHeader_name_set(header_ptr, c_key.as_ptr());
                Cronet_HttpHeader_value_set(header_ptr, c_val.as_ptr());

                Cronet_UrlRequestParams_request_headers_add(params_ptr, header_ptr);
                Cronet_HttpHeader_Destroy(header_ptr);
            }

            // Upload Data Provider (Body)
            let mut upload_data_provider_ptr: Option<Cronet_UploadDataProviderPtr> = None;
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
                let upload_context_ptr = Box::into_raw(upload_context);

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

            Cronet_UrlRequest_InitWithParams(
                request_ptr,
                engine_ptr,
                c_url.as_ptr(),
                params_ptr,
                callback_ptr,
                executor_ptr,
            );

            Cronet_UrlRequestParams_Destroy(params_ptr);

            // Start
            Cronet_UrlRequest_Start(request_ptr);

            let request_handle = CronetRequest {
                ptr: request_ptr,
                callback_ptr,
                executor_ptr,
                executor_context_ptr,
                owned_engine_ptr: None, // Session owns the engine
                upload_data_provider_ptr,
                upload_body_data,
                completed,
            };

            (request_handle, rx)
        }
    }

    /// 关闭会话
    pub fn close_session(&self, session_id: &str) -> bool {
        let mut sessions = self.sessions.write().unwrap();
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
        self.sessions.read().unwrap().keys().cloned().collect()
    }

    /// 获取会话数量
    pub fn session_count(&self) -> usize {
        self.sessions.read().unwrap().len()
    }

    /// 检查会话是否存在
    pub fn session_exists(&self, session_id: &str) -> bool {
        self.sessions.read().unwrap().contains_key(session_id)
    }
}
