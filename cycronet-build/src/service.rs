use crate::cronet::{CronetEngine, SessionConfig, SessionManager};
use crate::cronet_pb::{ExecuteRequest, ExecuteResponse};
use crate::cronet_pb::proxy_config::ProxyType;
use axum::{
    extract::{Json, Path, State},
    response::IntoResponse,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::io::Write;
use std::sync::atomic::Ordering;

// Service State
#[derive(Clone)]
pub struct AppState {
    pub engine: Arc<CronetEngine>,
    pub session_manager: Arc<SessionManager>,
}

/// Log request details to req.txt when debug mode is enabled
fn log_request_debug(
    session_id: Option<&str>,
    url: &str,
    method: &str,
    headers: &[crate::cronet_pb::Header],
    body: &[u8],
) {
    let debug_enabled = crate::DEBUG_MODE.load(Ordering::SeqCst);
    if !debug_enabled {
        return;
    }

    // Build log entry
    let mut log_entry = String::new();
    log_entry.push_str(&format!("=== Request at {} ===\n", chrono_now()));
    if let Some(sid) = session_id {
        log_entry.push_str(&format!("Session: {}\n", sid));
    } else {
        log_entry.push_str("Session: <none>\n");
    }
    log_entry.push_str(&format!("URL: {}\n", url));
    log_entry.push_str(&format!("Method: {}\n", method));
    log_entry.push_str("Headers:\n");
    for header in headers {
        log_entry.push_str(&format!("  {}: {}\n", header.name, header.value));
    }
    if !body.is_empty() {
        // Try to display as UTF-8, fallback to hex
        match std::str::from_utf8(body) {
            Ok(s) => log_entry.push_str(&format!("Body (text): {}\n", s)),
            Err(_) => log_entry.push_str(&format!("Body (hex): {}\n", hex::encode(body))),
        }
    } else {
        log_entry.push_str("Body: <empty>\n");
    }
    log_entry.push_str("\n");

    // Append to req.txt
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("req.txt")
    {
        let _ = file.write_all(log_entry.as_bytes());
    }
}

/// Simple timestamp without external dependency
fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}", duration.as_secs())
}

// Handlers
pub async fn execute_request(
    State(state): State<AppState>,
    Json(request): Json<ExecuteRequest>,
) -> impl IntoResponse {
    eprintln!(
        "[DEBUG] execute_request handler entered. Request ID: {}",
        request.request_id
    );
    // Validate Target
    let target = match request.target {
        Some(t) => t,
        None => {
            return Json(ExecuteResponse {
                request_id: request.request_id,
                success: false,
                error_message: "Missing target configuration".to_string(),
                ..Default::default()
            })
        }
    };

    // Log request if debug mode is enabled
    log_request_debug(None, &target.url, &target.method, &target.headers, &target.body);

    // Start Timer
    let start_time = std::time::Instant::now();

    // Execute Request via Cronet
    // Note: We currently only support URL and Method. Headers/Body support pending.
    let config_default = crate::cronet_pb::ExecutionConfig::default();
    let config = request.config.as_ref().unwrap_or(&config_default);

    let (request_handle, rx) = state.engine.start_request(&target, config);

    // Wait for result
    let execution_result = rx.await;
    let duration_ms = start_time.elapsed().as_millis() as i64;

    // Drop the request handle after we are done
    drop(request_handle);

    match execution_result {
        Ok(Ok(res)) => {
            // Success - 构建响应 headers map
            let mut headers_map = std::collections::HashMap::new();
            for (name, value) in res.headers {
                headers_map
                    .entry(name)
                    .or_insert_with(|| crate::cronet_pb::HeaderValues { values: Vec::new() })
                    .values
                    .push(value);
            }

            Json(ExecuteResponse {
                request_id: request.request_id,
                success: true,
                error_message: "".to_string(),
                duration_ms,
                response: Some(crate::cronet_pb::TargetResponse {
                    status_code: res.status_code,
                    headers: headers_map,
                    body: res.body,
                }),
            })
        }
        Ok(Err(err_msg)) => {
            // Cronet Error (Failed/Canceled)
            Json(ExecuteResponse {
                request_id: request.request_id,
                success: false,
                error_message: err_msg,
                duration_ms,
                response: None,
            })
        }
        Err(_) => {
            // RecvError (Internal Panic)
            Json(ExecuteResponse {
                request_id: request.request_id,
                success: false,
                error_message: "Internal Executor Error".to_string(),
                duration_ms,
                response: None,
            })
        }
    }
}

#[derive(serde::Serialize)]
pub struct VersionResponse {
    pub version: String,
    pub service: String,
}

pub async fn get_version(State(_state): State<AppState>) -> Json<VersionResponse> {
    let version = env!("CRONET_VERSION").to_string();
    Json(VersionResponse {
        version,
        service: "cronet-cloak".to_string(),
    })
}

// -----------------------------------------------------------------------------
// Session Management API
// -----------------------------------------------------------------------------

/// 创建会话请求
#[derive(Debug, Deserialize)]
pub struct CreateSessionRequest {
    pub proxy: Option<ProxyConfig>,
    #[serde(default)]
    pub skip_cert_verify: bool,
    #[serde(default = "default_timeout")]
    pub timeout_ms: u64,
}

fn default_timeout() -> u64 {
    30000
}

#[derive(Debug, Deserialize)]
pub struct ProxyConfig {
    pub host: String,
    pub port: u32,
    #[serde(default)]
    pub r#type: i32,  // 0=HTTP, 1=HTTPS, 2=SOCKS5
    #[serde(default)]
    pub username: String,
    #[serde(default)]
    pub password: String,
}

/// 创建会话响应
#[derive(Debug, Serialize)]
pub struct CreateSessionResponse {
    pub success: bool,
    pub session_id: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub error_message: String,
}

/// 关闭会话响应
#[derive(Debug, Serialize)]
pub struct CloseSessionResponse {
    pub success: bool,
    pub message: String,
}

/// 列出会话响应
#[derive(Debug, Serialize)]
pub struct ListSessionsResponse {
    pub success: bool,
    pub sessions: Vec<String>,
    pub count: usize,
}

/// 会话请求
#[derive(Debug, Deserialize)]
pub struct SessionRequest {
    pub url: String,
    #[serde(default = "default_method")]
    pub method: String,
    /// Headers 数组，保持顺序
    /// 格式: [["Header-Name", "value1"], ["Header-Name", "value2"], ...]
    #[serde(default)]
    pub headers: Vec<(String, String)>,
    #[serde(default)]
    #[serde(with = "hex::serde")]
    pub body: Vec<u8>,
}

fn default_method() -> String {
    "GET".to_string()
}

/// 创建会话
pub async fn create_session(
    State(state): State<AppState>,
    Json(request): Json<CreateSessionRequest>,
) -> Json<CreateSessionResponse> {
    eprintln!("[DEBUG] create_session called");

    // 构建代理规则
    let proxy_rules = if let Some(proxy) = &request.proxy {
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

    let config = SessionConfig {
        proxy_rules,
        skip_cert_verify: request.skip_cert_verify,
        timeout_ms: request.timeout_ms,
    };

    let session_id = state.session_manager.create_session(config);

    if session_id.is_empty() {
        Json(CreateSessionResponse {
            success: false,
            session_id: String::new(),
            error_message: "Failed to create session".to_string(),
        })
    } else {
        Json(CreateSessionResponse {
            success: true,
            session_id,
            error_message: String::new(),
        })
    }
}

/// 使用会话发送请求
pub async fn session_request(
    State(state): State<AppState>,
    Path(session_id): Path<String>,
    Json(request): Json<SessionRequest>,
) -> impl IntoResponse {
    eprintln!("[DEBUG] session_request called for session: {}", session_id);

    // 检查会话是否存在
    if !state.session_manager.session_exists(&session_id) {
        return Json(ExecuteResponse {
            request_id: String::new(),
            success: false,
            error_message: format!("Session not found: {}", session_id),
            duration_ms: 0,
            response: None,
        });
    }

    // 构建 TargetRequest
    let target = crate::cronet_pb::TargetRequest {
        url: request.url,
        method: request.method,
        headers: request
            .headers
            .into_iter()
            .map(|(name, value)| crate::cronet_pb::Header { name, value })
            .collect(),
        body: request.body,
    };

    // Log request if debug mode is enabled
    log_request_debug(Some(&session_id), &target.url, &target.method, &target.headers, &target.body);

    let start_time = std::time::Instant::now();

    // 使用会话发送请求
    let result = state.session_manager.send_request(&session_id, &target);

    match result {
        Some((request_handle, rx)) => {
            let execution_result = rx.await;
            let duration_ms = start_time.elapsed().as_millis() as i64;

            drop(request_handle);

            match execution_result {
                Ok(Ok(res)) => {
                    // 构建响应 headers map
                    let mut headers_map = std::collections::HashMap::new();
                    for (name, value) in res.headers {
                        headers_map
                            .entry(name)
                            .or_insert_with(|| crate::cronet_pb::HeaderValues { values: Vec::new() })
                            .values
                            .push(value);
                    }

                    Json(ExecuteResponse {
                        request_id: String::new(),
                        success: true,
                        error_message: String::new(),
                        duration_ms,
                        response: Some(crate::cronet_pb::TargetResponse {
                            status_code: res.status_code,
                            headers: headers_map,
                            body: res.body,
                        }),
                    })
                },
                Ok(Err(err_msg)) => Json(ExecuteResponse {
                    request_id: String::new(),
                    success: false,
                    error_message: err_msg,
                    duration_ms,
                    response: None,
                }),
                Err(_) => Json(ExecuteResponse {
                    request_id: String::new(),
                    success: false,
                    error_message: "Internal Executor Error".to_string(),
                    duration_ms,
                    response: None,
                }),
            }
        }
        None => Json(ExecuteResponse {
            request_id: String::new(),
            success: false,
            error_message: format!("Session not found or invalid: {}", session_id),
            duration_ms: 0,
            response: None,
        }),
    }
}

/// 关闭会话
pub async fn close_session(
    State(state): State<AppState>,
    Path(session_id): Path<String>,
) -> Json<CloseSessionResponse> {
    eprintln!("[DEBUG] close_session called for session: {}", session_id);

    if state.session_manager.close_session(&session_id) {
        Json(CloseSessionResponse {
            success: true,
            message: format!("Session {} closed", session_id),
        })
    } else {
        Json(CloseSessionResponse {
            success: false,
            message: format!("Session {} not found", session_id),
        })
    }
}

/// 列出所有会话
pub async fn list_sessions(State(state): State<AppState>) -> Json<ListSessionsResponse> {
    let sessions = state.session_manager.list_sessions();
    let count = sessions.len();

    Json(ListSessionsResponse {
        success: true,
        sessions,
        count,
    })
}
