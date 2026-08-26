mod data_home;
mod lifecycle;
mod metadata;
mod proxy;
mod qualification;
mod runtime;

use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::Arc;
use std::{fs, os::unix::fs::PermissionsExt};

use data_home::DataHomePaths;
use metadata::{about_info_for_mode, native_about_metadata, AboutInfo, BUILD_COMMIT};
use proxy::{forward, validate_frontend_request, DesktopRequest, DesktopResponse};
use qualification::{
    MatrixApiObservation, MatrixObserverFailure, MatrixUiObservation, QualificationContract,
};
use runtime::{RuntimeController, RuntimeStatus};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::webview::{NewWindowResponse, PageLoadEvent};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const OPERATION_MENU_IDS: &[&str] = &[
    "import-private-inbox",
    "import-existing-data",
    "create-backup",
    "restore-backup",
    "generate-report",
    "export-diagnostics",
];

static EXIT_CLEANUP_STARTED: AtomicBool = AtomicBool::new(false);

const MENU_ACTION_IDS: &[&str] = &[
    "import-private-inbox",
    "import-existing-data",
    "create-backup",
    "restore-backup",
    "generate-report",
    "print-current-view",
    "reload-safe",
    "export-diagnostics",
    "view-cash-flow",
    "view-goals",
    "view-overview",
    "view-activity",
    "view-accounts",
    "view-income",
    "view-wealth",
    "view-retirement",
    "view-lab",
    "view-connections",
    "view-review",
];

static WEBVIEW_ZOOM: AtomicU64 = AtomicU64::new(1.0_f64.to_bits());

fn planned_qualification_hash(contract: Option<&QualificationContract>) -> Option<String> {
    let (_, route) = contract?.matrix_plan()?;
    let view = match route {
        "add-account" => "connections",
        "cash-flow" | "goals" | "activity" | "overview" | "accounts" | "income" | "wealth"
        | "retirement" | "lab" => route,
        _ => return None,
    };
    Some(format!("#view={view}"))
}

fn initialization_script(contract: Option<&QualificationContract>) -> String {
    let planned_hash = serde_json::to_string(&planned_qualification_hash(contract))
        .unwrap_or_else(|_| "null".to_string());
    let script = r#"(() => {
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
            revealBackup: (backupId) => invoke("desktop_reveal_backup", { backupId }),
            reportAction: (reportId, action) => invoke("desktop_report_action", { reportId, action }),
            diagnosticsPreview: () => invoke("desktop_diagnostics_preview"),
            exportDiagnostics: () => invoke("desktop_export_diagnostics"),
            openExternal: (url) => invoke("desktop_open_external", { url }),
            setOperationsEnabled: (enabled) => invoke("desktop_set_operations_enabled", { enabled })
          }), configurable: false });
          window.print = () => { void invoke("desktop_print"); };
          document.addEventListener("click", (event) => {
            const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
            if (!target) return;
            const href = target.getAttribute("href") || "";
            if (!href.startsWith("https://")) return;
            event.preventDefault();
            event.stopPropagation();
            void invoke("desktop_open_external", { url: href });
          }, true);
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
        })();"#;
    script.replacen(
        "(() => {",
        &format!(
            "(() => {{ const plannedHash = {planned_hash}; if (plannedHash) window.history.replaceState(null, \"\", plannedHash);"
        ),
        1,
    )
}

fn safe_error_initialization_script() -> &'static str {
    r#"Object.defineProperty(window, "__MONEY_MAP_SAFE_ERROR__", { value: Object.freeze({
          restart: () => window.__TAURI_INTERNALS__.invoke("desktop_restart"),
          about: () => window.__TAURI_INTERNALS__.invoke("desktop_about")
        }), configurable: false });"#
}

fn show_safe_error(app: &tauri::AppHandle) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.hide();
    }
    if let Some(error) = app.get_webview_window("safe-error") {
        let _ = error.show();
        let _ = error.set_focus();
    }
}

fn build_main_window<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    qualification: Option<&QualificationContract>,
) -> tauri::Result<tauri::WebviewWindow<R>> {
    let observer_contract = qualification.cloned();
    let observer_sequence = Arc::new(AtomicU8::new(0));
    let page_sequence = Arc::clone(&observer_sequence);
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Money Map")
        .inner_size(1280.0, 820.0)
        .min_inner_size(900.0, 640.0)
        .zoom_hotkeys_enabled(false)
        .initialization_script(initialization_script(qualification))
        .on_page_load(move |window, payload| {
            if !matches!(payload.event(), PageLoadEvent::Finished) {
                return;
            }
            let sequence = page_sequence.fetch_add(1, Ordering::SeqCst) + 1;
            if sequence > 2 {
                return;
            }
            if let Some(script) = observer_contract
                .as_ref()
                .and_then(|contract| qualification_observer_script(contract, sequence))
            {
                let _ = window.eval(&script);
            }
        })
        .on_navigation(internal_navigation_allowed)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .build()?;
    let close_window = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = close_window.hide();
        }
    });
    Ok(window)
}

fn build_safe_error_window<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
) -> tauri::Result<tauri::WebviewWindow<R>> {
    WebviewWindowBuilder::new(
        app,
        "safe-error",
        WebviewUrl::App("desktop-error.html".into()),
    )
    .title("Money Map recovery")
    .inner_size(640.0, 440.0)
    .min_inner_size(560.0, 400.0)
    .zoom_hotkeys_enabled(false)
    .initialization_script(safe_error_initialization_script())
    .on_navigation(internal_navigation_allowed)
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .build()
}

#[tauri::command]
fn desktop_reload(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<(), String> {
    state.rearm_qualification_gate()?;
    window
        .reload()
        .map_err(|_| "The desktop window could not reload.".to_string())?;
    Ok(())
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

fn fetch_json(controller: &RuntimeController, path: String) -> Result<serde_json::Value, String> {
    let (port, session) = controller.target()?;
    let response = forward(
        port,
        &session,
        DesktopRequest {
            path,
            method: "GET".to_string(),
            body: None,
        },
    )?;
    if response.status != 200 {
        return Err("The requested local artifact was rejected safely.".to_string());
    }
    serde_json::from_str(&response.body)
        .map_err(|_| "The requested local artifact could not be verified.".to_string())
}

#[tauri::command]
async fn desktop_restart(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<RuntimeStatus, String> {
    let controller = Arc::clone(state.inner());
    let status = tauri::async_runtime::spawn_blocking(move || controller.restart())
        .await
        .map_err(|_| "Money Map could not restart the local service.".to_string())??;
    if window.label() == "safe-error" {
        let _ = window.hide();
        let main = match window.app_handle().get_webview_window("main") {
            Some(main) => main,
            None => build_main_window(window.app_handle(), state.qualification().as_ref())
                .map_err(|_| "Money Map could not create its verified window.".to_string())?,
        };
        let _ = main.show();
        let _ = main.set_focus();
    }
    Ok(status)
}

#[tauri::command]
fn desktop_about(state: tauri::State<'_, Arc<RuntimeController>>) -> AboutInfo {
    about_info_for_mode(state.data_mode())
}

const APPROVED_EXTERNAL_LINKS: &[&str] = &[
    "https://dashboard.plaid.com/",
    "https://www.irs.gov/retirement-plans/retirement-plans-faqs-regarding-loans",
];

fn approved_external_link(value: &str) -> bool {
    APPROVED_EXTERNAL_LINKS.contains(&value)
}

fn internal_navigation_allowed(url: &tauri::Url) -> bool {
    let approved_origin = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
        || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"));
    approved_origin
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.query().is_none()
        && matches!(url.path(), "" | "/" | "/index.html")
}

#[tauri::command]
fn desktop_open_external(url: String) -> Result<(), String> {
    if url.len() > 256 || !url.is_ascii() || !approved_external_link(&url) {
        return Err("The external link was rejected.".to_string());
    }
    let status = Command::new("/usr/bin/open")
        .arg("--")
        .arg(url)
        .status()
        .map_err(|_| "The approved external link could not open.".to_string())?;
    if !status.success() {
        return Err("The approved external link could not open.".to_string());
    }
    Ok(())
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

fn approved_child(root: &std::path::Path, filename: &str) -> Result<PathBuf, String> {
    if PathBuf::from(filename)
        .file_name()
        .and_then(|value| value.to_str())
        != Some(filename)
    {
        return Err("The selected local artifact was rejected.".to_string());
    }
    let path = root.join(filename);
    let metadata = fs::symlink_metadata(&path)
        .map_err(|_| "The selected local artifact is unavailable.".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("The selected local artifact was rejected.".to_string());
    }
    let approved = root
        .canonicalize()
        .map_err(|_| "The local artifact location could not be verified.".to_string())?;
    let parent = path
        .parent()
        .and_then(|value| value.canonicalize().ok())
        .ok_or_else(|| "The local artifact location could not be verified.".to_string())?;
    if parent != approved {
        return Err("The selected local artifact was rejected.".to_string());
    }
    Ok(path)
}

#[tauri::command]
async fn desktop_report_action(
    state: tauri::State<'_, Arc<RuntimeController>>,
    report_id: String,
    action: String,
) -> Result<(), String> {
    if report_id != "trailing-12-month" || !matches!(action.as_str(), "open" | "reveal") {
        return Err("The selected report action was rejected.".to_string());
    }
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let payload = fetch_json(&controller, format!("/api/reports/{report_id}/approved"))?;
        let filename = payload
            .get("filename")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| "The selected report could not be verified.".to_string())?;
        let path = approved_child(&controller.report_root(), filename)?;
        if action == "reveal" {
            if !Command::new("/usr/bin/open")
                .arg("-R")
                .arg(path)
                .status()
                .map_err(|_| "The report could not be revealed.".to_string())?
                .success()
            {
                return Err("The report could not be revealed.".to_string());
            }
        } else {
            Command::new("/usr/bin/qlmanage")
                .arg("-p")
                .arg(path)
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .map_err(|_| "The report preview could not be opened.".to_string())?;
        }
        Ok(())
    })
    .await
    .map_err(|_| "The report could not be opened.".to_string())?
}

fn diagnostic_backup_verification(backend: &serde_json::Value) -> serde_json::Value {
    backend
        .get("backup_verification")
        .cloned()
        .unwrap_or(serde_json::json!({
            "count": 0,
            "all_verified": false,
            "status": "unavailable"
        }))
}

fn diagnostic_payload(controller: &RuntimeController) -> Result<serde_json::Value, String> {
    let backend = fetch_json(controller, "/api/desktop/data-home/diagnostics".to_string())?;
    let status = controller.status();
    let about = about_info_for_mode(controller.data_mode());
    let macos = Command::new("/usr/bin/sw_vers")
        .arg("-productVersion")
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|value| value.trim().to_string())
        .unwrap_or_else(|| "unavailable".to_string());
    Ok(serde_json::json!({
        "contract": "money-map-sanitized-diagnostics-v1",
        "product_version": about.runtime_version,
        "release_state": about.release_state,
        "schema_revision": backend.get("schema_revision").cloned().unwrap_or(serde_json::json!("unavailable")),
        "desktop_build": about.desktop_build,
        "source_commit": about.source_commit,
        "target_architecture": about.target,
        "macos_version": macos,
        "data_mode": about.data_mode,
        "runtime": { "state": status.state, "generation": status.generation },
        "data_home_phase": backend.get("data_home_phase").cloned().unwrap_or(serde_json::json!("unavailable")),
        "backup_verification": diagnostic_backup_verification(&backend),
        "database_checks": backend.get("database_checks").cloned().unwrap_or(serde_json::json!({"integrity": "unavailable", "foreign_keys": "unavailable"})),
        "network_mode": "local_data; connected updates are explicit",
        "artifact_identity": { "build": about.desktop_build, "source": about.source_commit }
    }))
}

#[tauri::command]
async fn desktop_diagnostics_preview(
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<serde_json::Value, String> {
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || diagnostic_payload(&controller))
        .await
        .map_err(|_| "Sanitized diagnostics are unavailable.".to_string())?
}

#[tauri::command]
async fn desktop_export_diagnostics(
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<bool, String> {
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let payload = diagnostic_payload(&controller)?;
        let selected = rfd::FileDialog::new()
            .set_file_name("Money-Map-Sanitized-Diagnostics.json")
            .add_filter("JSON", &["json"])
            .save_file();
        let Some(selected) = selected else {
            return Ok(false);
        };
        if fs::symlink_metadata(&selected)
            .map(|metadata| metadata.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err("The diagnostics destination was rejected.".to_string());
        }
        let bytes = serde_json::to_vec_pretty(&payload)
            .map_err(|_| "Sanitized diagnostics could not be prepared.".to_string())?;
        fs::write(&selected, bytes)
            .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?;
        fs::set_permissions(&selected, fs::Permissions::from_mode(0o600))
            .map_err(|_| "Sanitized diagnostics permissions could not be secured.".to_string())?;
        Ok(true)
    })
    .await
    .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?
}

#[tauri::command]
fn desktop_set_operations_enabled(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    let menu = app
        .menu()
        .ok_or_else(|| "The application menu is unavailable.".to_string())?;
    for id in OPERATION_MENU_IDS {
        if let Some(item) = menu.get(*id).and_then(|item| item.as_menuitem().cloned()) {
            item.set_enabled(enabled)
                .map_err(|_| "The application menu could not be updated.".to_string())?;
        }
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
        validate_frontend_request(&request)?;
        controller.record_qualification_request(&request.method, &request.path);
        if request.method == "GET" {
            controller.hold_qualification_dashboard_request(&request.path)?;
        }
        let (port, session) = controller.target()?;
        forward(port, &session, request)
    })
    .await
    .map_err(|_| "The local service request failed.".to_string())?
}

fn matrix_api_endpoints(route: &str) -> &'static [(&'static str, &'static str)] {
    match route {
        "cash-flow" => &[
            (
                "cash-flow-period",
                "/api/v2/cash-flow?period_kind=all_imported_history",
            ),
            (
                "recurring-outflow-candidates",
                "/api/v2/cash-flow/recurring-outflow-candidates",
            ),
        ],
        "goals" => &[
            ("primary-goal", "/api/v2/goals/primary"),
            ("goal-position", "/api/v2/goals/position"),
            ("goal-comparison", "/api/v2/goals/comparison"),
            ("goal-milestone", "/api/v2/goals/milestone"),
        ],
        "activity" | "accounts" => &[("accounts-dashboard", "/api/accounts")],
        "income" => &[("payroll-history", "/api/payroll")],
        "wealth" => &[("wealth-dashboard", "/api/wealth")],
        "retirement" => &[
            ("retirement-profile", "/api/v2/retirement/profile"),
            (
                "retirement-starting-point",
                "/api/v2/retirement/starting-point",
            ),
            (
                "retirement-operational-goals",
                "/api/v2/retirement/operational-goals",
            ),
        ],
        "lab" => &[
            ("life-profile", "/api/life-plan/profile"),
            ("life-starting-point", "/api/life-plan/starting-point"),
            ("life-goals", "/api/life-plan/goals"),
            ("life-scenarios", "/api/life-plan/scenarios"),
        ],
        "overview" => &[
            ("overview", "/api/overview"),
            ("accounts-dashboard", "/api/accounts"),
        ],
        "add-account" => &[
            ("provider-status", "/api/plaid/status"),
            ("import-history", "/api/imports"),
        ],
        "data-home" => &[("data-home-status", "/api/desktop/data-home/status")],
        "diagnostics" => &[(
            "sanitized-data-home-diagnostics",
            "/api/desktop/data-home/diagnostics",
        )],
        "reports" => &[],
        _ => &[],
    }
}

fn matrix_response_class(status: u16) -> String {
    match status {
        200..=299 => "success",
        409 => "unavailable",
        400..=499 => "client-error",
        _ => "service-error",
    }
    .to_string()
}

#[tauri::command]
fn desktop_qualification_observe(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<RuntimeController>>,
    observation: MatrixUiObservation,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Synthetic qualification matrix observation was rejected.".to_string());
    }
    let qualification = state
        .qualification()
        .ok_or_else(|| "Synthetic qualification matrix observation was rejected.".to_string())?;
    let (_, route) = qualification
        .matrix_plan()
        .ok_or_else(|| "Synthetic qualification matrix observation was rejected.".to_string())?;
    let native_failure = |classification: &str, stage: &str| MatrixObserverFailure {
        sequence: observation.sequence,
        requested_route: route.to_string(),
        expected_phase: observation.phase.clone(),
        last_completed_stage: stage.to_string(),
        failure_classification: classification.to_string(),
        hash_matched: observation.location_hash
            == planned_qualification_hash(Some(&qualification)).unwrap_or_default(),
        global_loading_present: observation.loading_visible,
        route_local_loading_present: false,
        native_invocation_accepted: true,
        timeout_classification: false,
    };
    if !qualification.valid_matrix_ui_observation(&observation) {
        let _ = qualification.write_matrix_failure(&native_failure(
            "native-validation-rejected",
            "pending-observed",
        ));
        return Err("Synthetic qualification matrix observation was rejected.".to_string());
    }
    let (port, session) = state.target().map_err(|_| {
        let _ = qualification.write_matrix_failure(&native_failure(
            "native-api-probe-failed",
            "native-api-probe",
        ));
        "Synthetic qualification matrix API probe failed safely.".to_string()
    })?;
    let mut api = Vec::new();
    for (endpoint_class, path) in matrix_api_endpoints(route) {
        let response = forward(
            port,
            &session,
            DesktopRequest {
                path: (*path).to_string(),
                method: "GET".to_string(),
                body: None,
            },
        )
        .map_err(|_| {
            let _ = qualification.write_matrix_failure(&native_failure(
                "native-api-probe-failed",
                "native-api-probe",
            ));
            "Synthetic qualification matrix API probe failed safely.".to_string()
        })?;
        api.push(MatrixApiObservation {
            endpoint_class,
            status: response.status,
            response_class: matrix_response_class(response.status),
        });
    }
    let request_inventory = state.qualification_request_inventory();
    if !qualification.valid_matrix_observation(&observation, &request_inventory) {
        let _ = qualification.write_matrix_failure(&native_failure(
            "native-validation-rejected",
            "native-api-probe",
        ));
        return Err("Synthetic qualification matrix observation was rejected.".to_string());
    }
    qualification
        .write_matrix_result(&observation, &api, &request_inventory)
        .map_err(|_| {
            let _ = qualification
                .write_matrix_failure(&native_failure("evidence-write-failed", "evidence-write"));
            "Synthetic qualification matrix evidence write failed safely.".to_string()
        })
}

#[tauri::command]
fn desktop_qualification_observer_failure(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<RuntimeController>>,
    failure: MatrixObserverFailure,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("Synthetic qualification matrix failure was rejected.".to_string());
    }
    state
        .qualification()
        .ok_or_else(|| "Synthetic qualification matrix failure was rejected.".to_string())?
        .write_matrix_failure(&failure)
}

fn qualification_observer_script(contract: &QualificationContract, sequence: u8) -> Option<String> {
    let (state, route) = contract.matrix_plan()?;
    let route_json = serde_json::to_string(route).ok()?;
    let loading = state == "loading";
    Some(format!(
        r##"(() => {{
          const requestedRoute = {route_json};
          const boundedLoading = {loading};
          let consoleErrors = 0;
          const originalConsoleError = console.error.bind(console);
          console.error = (...args) => {{ consoleErrors += 1; originalConsoleError(...args); }};
          const routeLabels = {{
            "cash-flow": "Cash Flow", "goals": "Goals", "activity": "Activity",
            "accounts": "Accounts", "income": "Income", "wealth": "Wealth",
            "retirement": "Retirement", "lab": "Lab", "overview": "Overview",
            "add-account": "Add account"
          }};
          const expectedHashes = {{
            "cash-flow": "#view=cash-flow", "goals": "#view=goals",
            "activity": "#view=activity", "accounts": "#view=accounts",
            "income": "#view=income", "wealth": "#view=wealth",
            "retirement": "#view=retirement", "lab": "#view=lab",
            "overview": "#view=overview", "add-account": "#view=connections"
          }};
          const expectedHeadings = {{
            "cash-flow": "Cash Flow", "goals": "Goals", "activity": "Activity",
            "accounts": "Accounts", "income": "Income", "wealth": "Wealth",
            "retirement": "Retirement", "lab": "Life Lab", "overview": "Overview",
            "add-account": "Add account", "data-home": "Data safety"
          }};
          const globalSelector = '[data-qualification-loading="global-dashboard"]';
          let stage = boundedLoading ? "awaiting-global-loading" : "route-requested";
          let expectedPhase = boundedLoading ? "pending" : "settled";
          let routeRequested = false;
          let finished = false;
          let inFlight = false;
          let scheduled = false;
          let routeControlUnavailable = false;
          const text = (element) => (element?.textContent || "").replace(/\s+/g, " ").trim();
          const values = (selector, limit) => Array.from(document.querySelectorAll(selector))
            .map(text).filter(Boolean).slice(0, limit);
          const buttonLabel = (button) => (button.getAttribute("aria-label") || text(button))
            .replace(/, \d+ issues$/u, "");
          const routeButton = () => {{
            const label = routeLabels[requestedRoute]
              || (requestedRoute === "data-home" ? "Data safety" : null)
              || (requestedRoute === "diagnostics" ? "Diagnostics" : null);
            return label ? Array.from(document.querySelectorAll("button"))
              .find((button) => buttonLabel(button) === label) : null;
          }};
          const globalLoading = () => document.querySelector(globalSelector);
          const routeLocalLoading = () => Array.from(document.querySelectorAll(
            ".loading-state,.goals-loading,.retirement-loading,.cash-flow-busy"
          ))
            .some((element) => !element.matches(globalSelector));
          const hashMatched = () => !expectedHashes[requestedRoute]
            || window.location.hash === expectedHashes[requestedRoute];
          const routeObservable = () => {{
            const heading = expectedHeadings[requestedRoute];
            if (heading && !Array.from(document.querySelectorAll("h1"))
              .some((element) => text(element) === heading
                || text(element).startsWith(heading + " "))) return false;
            if (requestedRoute === "diagnostics"
              && !document.querySelector('[role="dialog"],[role="alertdialog"]')) return false;
            if (requestedRoute === "reports" && !Array.from(document.querySelectorAll("button"))
              .some((button) => buttonLabel(button) === "Generate report")) return false;
            return Boolean(heading || requestedRoute === "diagnostics" || requestedRoute === "reports");
          }};
          const failureFacts = (classification, timeout) => ({{ failure: {{
            sequence: {sequence}, requested_route: requestedRoute,
            expected_phase: expectedPhase, last_completed_stage: stage,
            failure_classification: classification, hash_matched: hashMatched(),
            global_loading_present: Boolean(globalLoading()),
            route_local_loading_present: routeLocalLoading(),
            native_invocation_accepted: classification !== "native-observation-rejected",
            timeout_classification: timeout
          }} }});
          const fail = (classification, timeout = false) => {{
            if (finished) return;
            finished = true;
            observer.disconnect();
            window.clearTimeout(deadline);
            void window.__TAURI_INTERNALS__.invoke(
              "desktop_qualification_observer_failure", failureFacts(classification, timeout)
            );
          }};
          const observe = async (phase) => window.__TAURI_INTERNALS__.invoke(
            "desktop_qualification_observe", {{ observation: {{
              sequence: {sequence}, phase, route: requestedRoute,
              location_hash: window.location.hash,
              headings: values("h1,h2", 16),
              statuses: values('[role="status"]', 16),
              alerts: values('[role="alert"],[role="alertdialog"]', 16),
              buttons: values("button", 64),
              disabled_buttons: Array.from(document.querySelectorAll("button:disabled"))
                .map(text).filter(Boolean).slice(0, 64),
              messages: values("main p,main small,main dt,main dd,main strong,.simple-empty", 64),
              loading_visible: Boolean(globalLoading()),
              loading_busy: globalLoading()?.getAttribute("aria-busy") === "true",
              loading_live: globalLoading()?.getAttribute("aria-live") || "",
              dialog_count: document.querySelectorAll('[role="dialog"],[role="alertdialog"]').length,
              progress_count: document.querySelectorAll('[role="progressbar"],progress').length,
              unsafe_console_errors: consoleErrors
            }} }}
          );
          const evaluate = async () => {{
            scheduled = false;
            if (finished || inFlight) return;
            const global = globalLoading();
            if (boundedLoading && stage === "awaiting-global-loading") {{
              const exactPending = global
                && global.getAttribute("aria-busy") === "true"
                && global.getAttribute("aria-live") === "polite"
                && values("h1", 16).length === 1
                && values("h1", 16)[0] === "Loading accounts…"
                && values("button", 64).length === 0
                && hashMatched();
              if (!exactPending) return;
              inFlight = true;
              try {{
                await observe("pending");
                stage = "pending-observed";
                expectedPhase = "settled";
              }} catch (_) {{ fail("native-observation-rejected"); }}
              finally {{ inFlight = false; }}
              schedule();
              return;
            }}
            if (boundedLoading && global) {{
              stage = "awaiting-global-release";
              return;
            }}
            if (!boundedLoading && !routeRequested && (global || routeLocalLoading())) {{
              stage = "awaiting-route";
              return;
            }}
            if (!routeRequested) {{
              const button = routeButton();
              if (button) {{
                routeControlUnavailable = false;
                button.click();
              }} else if (!["reports"].includes(requestedRoute)) {{
                routeControlUnavailable = true;
                return;
              }}
              routeRequested = true;
              stage = "route-requested";
              schedule();
              return;
            }}
            stage = "awaiting-route";
            if (!hashMatched() || routeLocalLoading() || !routeObservable()) return;
            inFlight = true;
            try {{
              await observe("settled");
              finished = true;
              observer.disconnect();
              window.clearTimeout(deadline);
            }} catch (_) {{ fail("native-observation-rejected"); }}
            finally {{ inFlight = false; }}
          }};
          const schedule = () => {{
            if (scheduled || finished) return;
            scheduled = true;
            window.requestAnimationFrame(() => {{ void evaluate(); }});
          }};
          const observer = new MutationObserver(schedule);
          observer.observe(document.documentElement, {{ childList: true, subtree: true, attributes: true }});
          const deadline = window.setTimeout(
            () => fail(routeControlUnavailable ? "route-control-unavailable" : "observer-timeout", true),
            15_000
          );
          schedule();
        }})();"##
    ))
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

fn install_native_menu(app: &tauri::AppHandle, data_mode: &str) -> tauri::Result<()> {
    let about = PredefinedMenuItem::about(app, None, Some(native_about_metadata(data_mode)))?;
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
            &PredefinedMenuItem::show_all(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::quit(app, None)?,
        ],
    )?;
    let file = Submenu::with_items(
        app,
        "File",
        true,
        &[
            &MenuItem::with_id(
                app,
                "import-private-inbox",
                "Import Private Inbox",
                true,
                Some("Cmd+I"),
            )?,
            &MenuItem::with_id(
                app,
                "import-existing-data",
                "Import Existing Money Map Data",
                true,
                Some("Cmd+Shift+I"),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(
                app,
                "create-backup",
                "Create Verified Backup",
                true,
                Some("Cmd+Shift+B"),
            )?,
            &MenuItem::with_id(
                app,
                "restore-backup",
                "Restore from Backup",
                true,
                None::<&str>,
            )?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(
                app,
                "generate-report",
                "Generate Report",
                true,
                Some("Cmd+Shift+R"),
            )?,
            &MenuItem::with_id(
                app,
                "export-diagnostics",
                "Export Diagnostics…",
                true,
                None::<&str>,
            )?,
            &MenuItem::with_id(app, "print-current-view", "Print…", true, Some("Cmd+P"))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        "View",
        true,
        &[
            &MenuItem::with_id(app, "view-cash-flow", "Cash Flow", true, Some("Cmd+1"))?,
            &MenuItem::with_id(app, "view-goals", "Goals", true, Some("Cmd+2"))?,
            &MenuItem::with_id(app, "view-overview", "Overview", true, None::<&str>)?,
            &MenuItem::with_id(app, "view-activity", "Activity", true, Some("Cmd+3"))?,
            &MenuItem::with_id(app, "view-accounts", "Accounts", true, Some("Cmd+4"))?,
            &MenuItem::with_id(app, "view-income", "Income", true, Some("Cmd+5"))?,
            &MenuItem::with_id(app, "view-wealth", "Wealth", true, Some("Cmd+6"))?,
            &MenuItem::with_id(app, "view-retirement", "Retirement", true, Some("Cmd+7"))?,
            &MenuItem::with_id(app, "view-lab", "Life Lab", true, Some("Cmd+8"))?,
            &MenuItem::with_id(app, "view-connections", "Add Account", true, Some("Cmd+9"))?,
            &MenuItem::with_id(app, "view-review", "Review", true, Some("Cmd+Shift+9"))?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, "reload-safe", "Reload", true, Some("Cmd+R"))?,
            &MenuItem::with_id(app, "zoom-reset", "Actual Size", true, Some("Cmd+0"))?,
            &MenuItem::with_id(app, "zoom-in", "Zoom In", true, Some("Cmd+Plus"))?,
            &MenuItem::with_id(app, "zoom-out", "Zoom Out", true, Some("Cmd+-"))?,
        ],
    )?;
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::bring_all_to_front(app, None)?,
        ],
    )?;
    app.set_menu(Menu::with_items(
        app,
        &[&application, &file, &view, &window],
    )?)?;
    Ok(())
}

fn dispatch_menu_action(app: &tauri::AppHandle, id: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(menu_action_script(id));
    }
}

fn menu_action_script(id: &str) -> String {
    format!("window.dispatchEvent(new CustomEvent('money-map-menu', {{ detail: '{id}' }}));")
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
            desktop_reveal_backup,
            desktop_report_action,
            desktop_diagnostics_preview,
            desktop_export_diagnostics,
            desktop_set_operations_enabled,
            desktop_open_external,
            desktop_qualification_observe,
            desktop_qualification_observer_failure
        ])
        .setup(|app| {
            let qualification =
                QualificationContract::from_environment().map_err(std::io::Error::other)?;
            if let Some(contract) = qualification.as_ref().filter(|contract| {
                BUILD_COMMIT != "development" && contract.source_commit != BUILD_COMMIT
            }) {
                let _ = contract.write_result(false, Some("qualification-source-identity"));
                return Err(std::io::Error::other(
                    "Synthetic qualification source identity was rejected.",
                )
                .into());
            }
            let paths = DataHomePaths::resolve(app.handle(), qualification.as_ref())
                .map_err(std::io::Error::other)?;
            install_native_menu(app.handle(), paths.mode)?;
            let controller = RuntimeController::new(
                sidecar_path().map_err(std::io::Error::other)?,
                paths,
                qualification,
            )
            .map_err(std::io::Error::other)?;
            app.manage(Arc::clone(&controller));
            if controller.start_initial().is_ok() {
                let active_qualification = controller.qualification();
                build_main_window(app.handle(), active_qualification.as_ref())?;
            } else {
                build_safe_error_window(app.handle())?;
            }
            Ok(())
        })
        .on_menu_event(|app, event| {
            let id = event.id().as_ref();
            if id == "restart-local-service" {
                if let Some(controller) = app.try_state::<Arc<RuntimeController>>() {
                    let controller = Arc::clone(controller.inner());
                    std::thread::spawn(move || {
                        let _ = controller.restart();
                    });
                }
            } else if matches!(id, "zoom-reset" | "zoom-in" | "zoom-out") {
                if let Some(window) = app.get_webview_window("main") {
                    let current = f64::from_bits(WEBVIEW_ZOOM.load(Ordering::Relaxed));
                    let zoom = match id {
                        "zoom-in" => (current + 0.25).min(2.0),
                        "zoom-out" => (current - 0.25).max(0.75),
                        _ => 1.0,
                    };
                    WEBVIEW_ZOOM.store(zoom.to_bits(), Ordering::Relaxed);
                    let _ = window.set_zoom(zoom);
                }
            } else if MENU_ACTION_IDS.contains(&id) {
                dispatch_menu_action(app, id);
            }
        })
        .build(tauri::generate_context!())
        .expect("Money Map native shell could not initialize");
    app.run(|handle, event| match event {
        RunEvent::ExitRequested { api, .. } => {
            if !EXIT_CLEANUP_STARTED.swap(true, Ordering::SeqCst) {
                api.prevent_exit();
                if let Some(controller) = handle.try_state::<Arc<RuntimeController>>() {
                    controller.shutdown();
                }
                handle.exit(0);
            }
        }
        RunEvent::Exit => {
            if let Some(controller) = handle.try_state::<Arc<RuntimeController>>() {
                controller.shutdown();
            }
        }
        RunEvent::Reopen { .. } => {
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }
        RunEvent::Resumed => {
            if let Some(controller) = handle.try_state::<Arc<RuntimeController>>() {
                let status = controller.revalidate();
                if status.state == lifecycle::LifecycleState::Failed {
                    show_safe_error(handle);
                }
            }
        }
        _ => {}
    });
}

#[cfg(test)]
mod menu_tests {
    use super::{
        approved_external_link, diagnostic_backup_verification, internal_navigation_allowed,
        menu_action_script, MENU_ACTION_IDS, OPERATION_MENU_IDS,
    };

    #[test]
    fn native_menu_dispatch_covers_principal_operations_and_navigation() {
        for required in [
            "import-private-inbox",
            "import-existing-data",
            "create-backup",
            "restore-backup",
            "generate-report",
            "print-current-view",
            "reload-safe",
            "export-diagnostics",
            "view-cash-flow",
            "view-goals",
            "view-overview",
            "view-retirement",
            "view-lab",
        ] {
            assert!(MENU_ACTION_IDS.contains(&required));
        }
        assert!(OPERATION_MENU_IDS
            .iter()
            .all(|id| MENU_ACTION_IDS.contains(id)));
        assert_eq!(
            MENU_ACTION_IDS
                .iter()
                .filter(|id| **id == "view-overview")
                .count(),
            1
        );
        assert!(!OPERATION_MENU_IDS.contains(&"view-overview"));
        assert_eq!(
            menu_action_script("view-overview"),
            "window.dispatchEvent(new CustomEvent('money-map-menu', { detail: 'view-overview' }));"
        );
        assert!(!menu_action_script("view-overview").contains("view-review"));
    }

    #[test]
    fn navigation_and_external_links_are_exact_allowlists() {
        for allowed in [
            "tauri://localhost",
            "tauri://localhost/index.html#view=goals",
        ] {
            assert!(
                internal_navigation_allowed(&allowed.parse().unwrap()),
                "{allowed}"
            );
        }
        for rejected in [
            "https://example.invalid/",
            "file:///private/tmp/private",
            "data:text/html,attack",
            "javascript:alert(1)",
            "tauri://localhost/index.html?token=secret",
            "tauri://evil.invalid/index.html",
        ] {
            assert!(
                !internal_navigation_allowed(&rejected.parse().unwrap()),
                "{rejected}"
            );
        }
        assert!(approved_external_link("https://dashboard.plaid.com/"));
        assert!(!approved_external_link(
            "https://dashboard.plaid.com.evil.invalid/"
        ));
        assert!(!approved_external_link("http://dashboard.plaid.com/"));
    }

    #[test]
    fn missing_backup_diagnostics_never_report_verified() {
        let fallback = diagnostic_backup_verification(&serde_json::json!({}));
        assert_eq!(fallback["count"], 0);
        assert_eq!(fallback["all_verified"], false);
        assert_eq!(fallback["status"], "unavailable");

        let observed = serde_json::json!({"count": 2, "all_verified": true});
        assert_eq!(
            diagnostic_backup_verification(
                &serde_json::json!({"backup_verification": observed.clone()})
            ),
            observed
        );
    }
}
