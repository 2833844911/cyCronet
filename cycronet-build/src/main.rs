use axum::{routing::{delete, get, post}, Router};
use cronet_cloak::cronet::{self, SessionManager};
use cronet_cloak::service;
use cronet_cloak::service::AppState;
use cronet_cloak::{DEBUG_MODE, VERBOSE_MODE};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use clap::Parser;
use std::process;
use std::time::Duration;

/// Cronet-Cloak: Undetectable HTTP requests with authentic Chrome fingerprints
#[derive(Parser, Debug, Clone)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Server port to bind to
    #[arg(short, long, env = "CRONET_PORT", default_value = "3000")]
    port: u16,

    /// Server host to bind to
    #[arg(long, env = "CRONET_HOST", default_value = "0.0.0.0")]
    host: String,

    /// Enable debug mode (logs requests to req.txt)
    #[arg(short, long, env = "CRONET_DEBUG")]
    debug: bool,

    /// Enable verbose logging (shows detailed debug information)
    #[arg(short, long, env = "CRONET_VERBOSE")]
    verbose: bool,

    /// Enable auto-restart on crash (uses external wrapper)
    #[arg(short, long, env = "CRONET_AUTO_RESTART")]
    auto_restart: bool,

    /// Internal flag - do not use directly
    #[arg(long, hide = true)]
    internal_run: bool,
}

fn main() {
    // Parse arguments and handle errors
    let args = match Args::try_parse() {
        Ok(args) => args,
        Err(e) => {
            eprintln!("{}", e);
            eprintln!("\nFor more information, try '--help'");
            process::exit(1);
        }
    };

    if args.auto_restart && !args.internal_run {
        // Run with auto-restart wrapper
        run_with_auto_restart_wrapper(args);
    } else {
        // Run server directly
        run_server_sync(args);
    }
}

fn run_with_auto_restart_wrapper(args: Args) {
    let max_restarts = std::env::var("CRONET_MAX_RESTARTS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(0);

    let restart_delay = std::env::var("CRONET_RESTART_DELAY")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(3);

    let mut restart_count = 0u32;
    let exe_path = std::env::current_exe().expect("Failed to get executable path");

    loop {
        if args.verbose {
            println!("\n========================================");
            println!("Starting Cronet-Cloak server...");
            if restart_count > 0 {
                println!("Restart attempt: {}", restart_count);
            }
            println!("========================================\n");
        }

        let mut cmd = process::Command::new(&exe_path);
        cmd.arg("--internal-run")
            .arg("--port").arg(args.port.to_string())
            .arg("--host").arg(&args.host);

        if args.debug {
            cmd.arg("--debug");
        }

        if args.verbose {
            cmd.arg("--verbose");
        }

        // Inherit environment variables
        cmd.envs(std::env::vars());

        let status = cmd.status();

        match status {
            Ok(exit_status) => {
                if exit_status.success() {
                    if args.verbose {
                        println!("\n[INFO] Server stopped gracefully");
                    }
                    break;
                } else {
                    eprintln!("\n[ERROR] Server exited with status: {:?}", exit_status);
                    restart_count += 1;
                }
            }
            Err(e) => {
                eprintln!("\n[ERROR] Failed to start server: {}", e);
                restart_count += 1;
            }
        }

        if max_restarts > 0 && restart_count >= max_restarts {
            eprintln!("[ERROR] Maximum restart attempts ({}) reached. Exiting.", max_restarts);
            eprintln!("Tip: Use '--help' for more information");
            process::exit(1);
        }

        if args.verbose {
            eprintln!("[INFO] Restarting in {} seconds...", restart_delay);
        }
        std::thread::sleep(Duration::from_secs(restart_delay));
    }
}

#[tokio::main]
async fn run_server_sync(args: Args) {
    run_server(args).await;
}

async fn run_server(args: Args) {
    // Set verbose mode globally
    if args.verbose {
        VERBOSE_MODE.store(true, Ordering::SeqCst);
    }

    // Initialize logging based on verbose flag
    if args.verbose {
        tracing_subscriber::fmt()
            .with_max_level(tracing::Level::DEBUG)
            .init();
    } else {
        tracing_subscriber::fmt()
            .with_max_level(tracing::Level::WARN)
            .init();
    }

    if args.debug {
        DEBUG_MODE.store(true, Ordering::SeqCst);
        if args.verbose {
            println!("[DEBUG] Debug mode enabled - requests will be logged to req.txt");
        }
    }

    if args.verbose {
        println!("[INFO] Initializing Cronet Engine...");
    }

    // Initialize Cronet Engine
    let engine = Arc::new(cronet::CronetEngine::new("CronetCloak/1.0"));

    // Initialize Session Manager
    let session_manager = Arc::new(SessionManager::new());

    let state = AppState { engine, session_manager };

    // Build Router
    let app = Router::new()
        // Connect-RPC compatible path
        .route(
            "/cronet.engine.v1.EngineService/Execute",
            post(service::execute_request),
        )
        // Simple REST path alias
        .route("/api/execute", post(service::execute_request))
        .route("/api/v1/execute", post(service::execute_request))
        // Version endpoint
        .route("/version", get(service::get_version))
        .route("/api/version", get(service::get_version))
        // Session Management API
        .route("/api/v1/session", post(service::create_session))
        .route("/api/v1/session", get(service::list_sessions))
        .route("/api/v1/session/:session_id", delete(service::close_session))
        .route("/api/v1/session/:session_id/request", post(service::session_request))
        .with_state(state);

    let bind_addr = format!("{}:{}", args.host, args.port);

    if args.verbose {
        println!("[INFO] Binding to {}...", bind_addr);
    }

    let listener = tokio::net::TcpListener::bind(&bind_addr)
        .await
        .unwrap_or_else(|e| {
            eprintln!("[ERROR] Failed to bind to {}: {}", bind_addr, e);
            eprintln!("Tip: Use '--help' for more information");
            process::exit(1);
        });

    println!("\n========================================");
    println!("✓ Cronet-Cloak Server Started");
    println!("========================================");
    println!("Listening on: http://{}", listener.local_addr().unwrap());
    if args.verbose {
        println!("Debug mode: {}", if args.debug { "enabled" } else { "disabled" });
        println!("Verbose logging: enabled");
        println!("Auto-restart: {}", if args.auto_restart { "enabled" } else { "disabled" });
    }
    println!("========================================");
    println!("Press Ctrl+C to stop the server");
    println!("Use '--help' for more options\n");

    axum::serve(listener, app).await.unwrap();
}
