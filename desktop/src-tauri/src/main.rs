mod data_home;
mod lifecycle;
mod metadata;
mod proxy;
mod runtime;

use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use data_home::DataHomePaths;
use metadata::{about_info, native_about_metadata, AboutInfo};
use proxy::{forward, DesktopRequest, DesktopResponse};
use runtime::{RuntimeController, RuntimeStatus};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

fn initialization_script() -> &'static str {
    r#"(() => {
          const nativeFetch = window.fetch.bind(window);
          const invoke = window.__TAURI_INTERNALS__.invoke;
          Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", { value: Object.freeze({
            mode: true,
            reload: () => invoke("desktop_reload"),
            print: () => invoke("desktop_print"),
            runtimeStatus: () => invoke("desktop_runtime_status"),
            restart: () => invoke("desktop_restart"),
            about: () => invoke("desktop_about"),
            selectImport: () => invoke("desktop_select_import"),
            revealBackup: (backupId) => invoke("desktop_reveal_backup", { backupId })
          }), configurable: false });
          window.print = () => { void invoke("desktop_print"); };
          window.fetch = async (input, init = {}) => {
            const url = typeof input === "string" ? input : input.url;
            if (!url.startsWith("/api/")) return nativeFetch(input, init);
            let result;
            try {
              result = await invoke("desktop_fetch", { request: {
                path: url,
                method: init.method || (typeof input === "string" ? "GET" : input.method),
                body: typeof init.body === "string" ? init.body : null
              }});
            } catch (_) {
              throw new Error("Money Map's local service is unavailable.");
            }
            const headers = Object.fromEntries(result.headers.map((header) => [header.name, header.value]));
            headers["cache-control"] = "no-store";
            return new Response(result.body, { status: result.status, headers });
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
fn desktop_runtime_status(state: tauri::State<'_, Arc<RuntimeController>>) -> RuntimeStatus {
    state.status()
}

#[tauri::command]
async fn desktop_restart(
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<RuntimeStatus, String> {
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || controller.restart())
        .await
        .map_err(|_| "Money Map could not restart the local service.".to_string())?
}

#[tauri::command]
fn desktop_about() -> AboutInfo {
    about_info()
}

#[tauri::command]
async fn desktop_select_import(
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<Option<serde_json::Value>, String> {
    let selected = tauri::async_runtime::spawn_blocking(|| {
        rfd::FileDialog::new()
            .add_filter("Money Map database", &["sqlite3", "sqlite", "db"])
            .pick_file()
    })
    .await
    .map_err(|_| "The import chooser could not open.".to_string())?;
    let Some(selected) = selected else {
        return Ok(None);
    };
    let body = serde_json::to_string(&serde_json::json!({
        "selected_path": selected
    }))
    .map_err(|_| "The selected data could not be inspected.".to_string())?;
    let controller = Arc::clone(state.inner());
    let response = tauri::async_runtime::spawn_blocking(move || {
        let (port, session) = controller.target()?;
        forward(
            port,
            &session,
            DesktopRequest {
                path: "/api/desktop/data-home/candidate".to_string(),
                method: "POST".to_string(),
                body: Some(body),
            },
        )
    })
    .await
    .map_err(|_| "The selected data could not be inspected.".to_string())??;
    if response.status != 200 {
        return Err("The selected Money Map data was rejected safely.".to_string());
    }
    serde_json::from_str(&response.body)
        .map(Some)
        .map_err(|_| "The migration preview was unavailable.".to_string())
}

#[tauri::command]
async fn desktop_reveal_backup(
    state: tauri::State<'_, Arc<RuntimeController>>,
    backup_id: String,
) -> Result<(), String> {
    if backup_id.len() != 24 || !backup_id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("The selected backup was rejected.".to_string());
    }
    let controller = Arc::clone(state.inner());
    let backup_root = controller.backup_root();
    let response = tauri::async_runtime::spawn_blocking(move || {
        let (port, session) = controller.target()?;
        forward(
            port,
            &session,
            DesktopRequest {
                path: format!("/api/desktop/data-home/backups/{backup_id}/reveal"),
                method: "GET".to_string(),
                body: None,
            },
        )
    })
    .await
    .map_err(|_| "The backup location could not be revealed.".to_string())??;
    if response.status != 200 {
        return Err("The backup location was rejected.".to_string());
    }
    let payload: serde_json::Value = serde_json::from_str(&response.body)
        .map_err(|_| "The backup location could not be verified.".to_string())?;
    let filename = payload
        .get("filename")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "The backup location could not be verified.".to_string())?;
    if PathBuf::from(filename)
        .file_name()
        .and_then(|value| value.to_str())
        != Some(filename)
    {
        return Err("The backup location was rejected.".to_string());
    }
    let path = backup_root.join(filename);
    let metadata = std::fs::symlink_metadata(&path)
        .map_err(|_| "The backup location is unavailable.".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("The backup location was rejected.".to_string());
    }
    let approved = backup_root
        .canonicalize()
        .map_err(|_| "The backup location could not be verified.".to_string())?;
    let parent = path
        .parent()
        .and_then(|value| value.canonicalize().ok())
        .ok_or_else(|| "The backup location could not be verified.".to_string())?;
    if parent != approved {
        return Err("The backup location was rejected.".to_string());
    }
    let status = Command::new("/usr/bin/open")
        .arg("-R")
        .arg(&path)
        .status()
        .map_err(|_| "Finder could not reveal the verified backup.".to_string())?;
    if !status.success() {
        return Err("Finder could not reveal the verified backup.".to_string());
    }
    Ok(())
}

#[tauri::command]
async fn desktop_fetch(
    state: tauri::State<'_, Arc<RuntimeController>>,
    request: DesktopRequest,
) -> Result<DesktopResponse, String> {
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let (port, session) = controller.target()?;
        forward(port, &session, request)
    })
    .await
    .map_err(|_| "The local service request failed.".to_string())?
}

fn sidecar_path() -> Result<PathBuf, String> {
    let executable = std::env::current_exe()
        .map_err(|_| "The signed application path is unavailable.".to_string())?;
    let path = executable
        .parent()
        .ok_or_else(|| "The signed application layout is invalid.".to_string())?
        .join("money-map-sidecar");
    Ok(path)
}

fn install_native_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    let about = PredefinedMenuItem::about(app, None, Some(native_about_metadata()))?;
    let restart = MenuItem::with_id(
        app,
        "restart-local-service",
        "Restart Local Service",
        true,
        None::<&str>,
    )?;
    let application = Submenu::with_items(
        app,
        "Money Map",
        true,
        &[
            &about,
            &PredefinedMenuItem::separator(app)?,
            &restart,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::services(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, None)?,
            &PredefinedMenuItem::hide_others(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::quit(app, None)?,
        ],
    )?;
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    app.set_menu(Menu::with_items(app, &[&application, &window])?)?;
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![
            desktop_fetch,
            desktop_reload,
            desktop_print,
            desktop_runtime_status,
            desktop_restart,
            desktop_about,
            desktop_select_import,
            desktop_reveal_backup
        ])
        .setup(|app| {
            install_native_menu(app.handle())?;
            let paths = DataHomePaths::resolve(app.handle()).map_err(std::io::Error::other)?;
            let controller =
                RuntimeController::new(sidecar_path().map_err(std::io::Error::other)?, paths)
                    .map_err(std::io::Error::other)?;
            app.manage(Arc::clone(&controller));
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Money Map")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 640.0)
                .initialization_script(initialization_script())
                .build()?;
            std::thread::spawn(move || {
                let _ = controller.start_initial();
            });
            Ok(())
        })
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "restart-local-service" {
                if let Some(controller) = app.try_state::<Arc<RuntimeController>>() {
                    let controller = Arc::clone(controller.inner());
                    std::thread::spawn(move || {
                        let _ = controller.restart();
                    });
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Money Map native shell could not initialize");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(controller) = handle.try_state::<Arc<RuntimeController>>() {
                controller.shutdown();
            }
        }
    });
}
