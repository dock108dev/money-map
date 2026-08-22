mod lifecycle;
mod metadata;
mod proxy;
mod runtime;

use std::path::PathBuf;
use std::sync::Arc;

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
            about: () => invoke("desktop_about")
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
            desktop_about
        ])
        .setup(|app| {
            install_native_menu(app.handle())?;
            let controller = RuntimeController::new(sidecar_path().map_err(std::io::Error::other)?)
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
