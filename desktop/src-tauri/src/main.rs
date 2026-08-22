use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct DesktopState {
    child: Mutex<Option<CommandChild>>,
    _data_parent: tempfile::TempDir,
    port: u16,
    session: String,
}

#[derive(Deserialize)]
struct DesktopRequest {
    path: String,
    method: String,
    body: Option<String>,
}

#[derive(Serialize)]
struct DesktopResponse {
    status: u16,
    content_type: String,
    body: String,
}

fn session_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "Secure session generation failed.".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn health_ready(port: u16, session: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}")
            .parse()
            .expect("valid loopback address"),
        Duration::from_millis(250),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let request = format!(
        "GET /api/desktop/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Money-Map-Session: {session}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.starts_with("HTTP/1.1 200")
        && response.contains("\"ready\":true")
}

fn initialization_script() -> &'static str {
    r#"(() => {
          const nativeFetch = window.fetch.bind(window);
          const invoke = window.__TAURI_INTERNALS__.invoke;
          Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", { value: Object.freeze({
            mode: true,
            reload: () => invoke("desktop_reload"),
            print: () => invoke("desktop_print")
          }), configurable: false });
          window.print = () => { void invoke("desktop_print"); };
          window.fetch = async (input, init = {}) => {
            const url = typeof input === "string" ? input : input.url;
            if (!url.startsWith("/api/")) return nativeFetch(input, init);
            let result;
            try {
              result = await window.__TAURI_INTERNALS__.invoke("desktop_fetch", { request: {
                path: url,
                method: init.method || (typeof input === "string" ? "GET" : input.method),
                body: typeof init.body === "string" ? init.body : null
              }});
            } catch (reason) {
              throw new Error(String(reason));
            }
            return new Response(result.body, { status: result.status, headers: { "Content-Type": result.content_type } });
          };
        })();"#
}

#[tauri::command]
fn desktop_reload(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .reload()
        .map_err(|_| "The desktop window could not reload.".to_string())
}

#[tauri::command]
fn desktop_print(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .print()
        .map_err(|_| "The desktop print panel could not open.".to_string())
}

#[tauri::command]
fn desktop_fetch(
    state: tauri::State<'_, DesktopState>,
    request: DesktopRequest,
) -> Result<DesktopResponse, String> {
    if !request.path.starts_with("/api/") || request.path.contains(['\r', '\n']) {
        return Err("The desktop request path was rejected.".to_string());
    }
    let method = request.method.to_ascii_uppercase();
    if !matches!(method.as_str(), "GET" | "POST" | "PUT" | "DELETE") {
        return Err("The desktop request method was rejected.".to_string());
    }
    let body = request.body.unwrap_or_default();
    if body.len() > 1_048_576 {
        return Err("The desktop request was too large.".to_string());
    }
    let mut stream = TcpStream::connect_timeout(
        &format!("127.0.0.1:{}", state.port)
            .parse()
            .expect("valid loopback address"),
        Duration::from_secs(2),
    )
    .map_err(|_| "The local service is unavailable.".to_string())?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(15)));
    let wire = format!(
        "{method} {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nX-Money-Map-Session: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        request.path,
        state.port,
        state.session,
        body.len(),
        body
    );
    stream
        .write_all(wire.as_bytes())
        .map_err(|_| "The local service request failed.".to_string())?;
    let mut response = Vec::new();
    let mut buffer = [0_u8; 16_384];
    loop {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => response.extend_from_slice(&buffer[..count]),
            Err(error)
                if !response.is_empty()
                    && matches!(
                        error.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                    ) =>
            {
                break;
            }
            Err(_) => return Err("The local service response failed.".to_string()),
        }
    }
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "The local service response was invalid.".to_string())?;
    let header = String::from_utf8_lossy(&response[..separator]);
    let status = header
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| "The local service status was invalid.".to_string())?;
    let content_type = header
        .lines()
        .find_map(|line| line.strip_prefix("content-type: "))
        .unwrap_or("application/json")
        .to_string();
    let response_body = String::from_utf8(response[separator + 4..].to_vec())
        .map_err(|_| "The local service returned unsupported content.".to_string())?;
    Ok(DesktopResponse {
        status,
        content_type,
        body: response_body,
    })
}

fn create_error_window(app: &tauri::AppHandle) {
    let _ = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("desktop-error.html".into()))
        .title("Money Map — Safe startup error")
        .inner_size(680.0, 420.0)
        .build();
}

fn stop_child(mut child: CommandChild) {
    let _ = child.write(b"shutdown\n");
    std::thread::sleep(Duration::from_millis(1500));
    let _ = child.kill();
}

fn start_runtime(app: &tauri::AppHandle) -> Result<DesktopState, String> {
    if std::env::var_os("MONEY_MAP_SLICE0_FORCE_FAILURE").is_some() {
        return Err("Synthetic startup failure requested.".to_string());
    }
    let data_parent = tempfile::Builder::new()
        .prefix("money-map-slice0-parent-")
        .tempdir()
        .map_err(|_| "Disposable data setup failed.".to_string())?;
    let data_root = data_parent.path().join("money-map-slice0-data");
    let session = session_token()?;
    let executable = std::env::current_exe()
        .map_err(|_| "The signed application path is unavailable.".to_string())?;
    let sidecar_path = executable
        .parent()
        .ok_or_else(|| "The signed application layout is invalid.".to_string())?
        .join("money-map-sidecar");
    if !sidecar_path.is_file() {
        return Err("The bundled service is missing from the signed application.".to_string());
    }
    let sidecar = app
        .shell()
        .command(sidecar_path)
        .env_clear()
        .env("LC_ALL", "C")
        .env("PAYCHECK_MAP_DESKTOP_MODE", "true")
        .env("PAYCHECK_MAP_LOCAL_DIR", data_root.as_os_str())
        .env("PAYCHECK_MAP_DESKTOP_SESSION", &session);
    let (mut events, child) = sidecar
        .spawn()
        .map_err(|_| "Bundled service could not start.".to_string())?;
    let (sender, receiver) = mpsc::channel::<Result<u16, String>>();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    if let Some(value) = line.strip_prefix("MONEY_MAP_READY ") {
                        if let Ok(port) = value.trim().parse::<u16>() {
                            let _ = sender.send(Ok(port));
                            return;
                        }
                    }
                }
                CommandEvent::Terminated(_) | CommandEvent::Error(_) => {
                    let _ = sender.send(Err("Bundled service stopped during startup.".to_string()));
                    return;
                }
                _ => {}
            }
        }
    });
    let port = match receiver.recv_timeout(Duration::from_secs(30)) {
        Ok(Ok(port)) => port,
        Ok(Err(reason)) => {
            stop_child(child);
            return Err(reason);
        }
        Err(_) => {
            stop_child(child);
            return Err("Bundled service readiness timed out.".to_string());
        }
    };
    let deadline = Instant::now() + Duration::from_secs(45);
    while Instant::now() < deadline && !health_ready(port, &session) {
        std::thread::sleep(Duration::from_millis(75));
    }
    if !health_ready(port, &session) {
        stop_child(child);
        return Err("Bundled service did not become ready.".to_string());
    }
    Ok(DesktopState {
        child: Mutex::new(Some(child)),
        _data_parent: data_parent,
        port,
        session,
    })
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            desktop_fetch,
            desktop_reload,
            desktop_print
        ])
        .setup(|app| {
            match start_runtime(app.handle()) {
                Ok(state) => {
                    app.manage(state);
                    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                        .title("Money Map")
                        .inner_size(1280.0, 820.0)
                        .min_inner_size(900.0, 640.0)
                        .initialization_script(initialization_script())
                        .build()?;
                }
                Err(reason) => {
                    eprintln!("Money Map startup failed safely: {reason}");
                    create_error_window(app.handle());
                    app.manage(DesktopState {
                        child: Mutex::new(None),
                        _data_parent: tempfile::Builder::new()
                            .prefix("money-map-slice0-error-")
                            .tempdir()?,
                        port: 0,
                        session: String::new(),
                    });
                }
            };
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Money Map native shell could not initialize");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<DesktopState>() {
                if let Ok(mut guard) = state.child.lock() {
                    if let Some(child) = guard.take() {
                        stop_child(child);
                    }
                }
            }
        }
    });
}
