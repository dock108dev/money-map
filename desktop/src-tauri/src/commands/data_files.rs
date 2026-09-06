//! User-selected imports and verified backup/report file actions.

use std::{fs, path::PathBuf, process::Command, sync::Arc};

use super::fetch_json;
use crate::proxy::{forward, DesktopRequest};
use crate::runtime::RuntimeController;

#[tauri::command]
pub(crate) async fn desktop_select_import(
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
pub(crate) async fn desktop_reveal_backup(
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
pub(crate) async fn desktop_report_action(
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

#[cfg(test)]
mod tests {
    use super::approved_child;

    #[test]
    fn artifact_paths_reject_traversal_directories_and_symlinks() {
        let root = tempfile::tempdir().unwrap();
        let report = root.path().join("report.pdf");
        std::fs::write(&report, b"synthetic report").unwrap();
        assert_eq!(approved_child(root.path(), "report.pdf").unwrap(), report);
        std::fs::create_dir(root.path().join("directory")).unwrap();
        std::os::unix::fs::symlink(&report, root.path().join("linked.pdf")).unwrap();
        for rejected in [
            "../report.pdf",
            "/report.pdf",
            "directory",
            "linked.pdf",
            "missing.pdf",
        ] {
            assert!(approved_child(root.path(), rejected).is_err(), "{rejected}");
        }
    }
}
