//! Sanitized diagnostics preview and private, atomic export.

use std::{fs, os::unix::fs::MetadataExt, process::Command, sync::Arc};

use super::fetch_json;
use crate::metadata::about_info_for_mode;
use crate::runtime::RuntimeController;

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
pub(crate) async fn desktop_diagnostics_preview(
    state: tauri::State<'_, Arc<RuntimeController>>,
) -> Result<serde_json::Value, String> {
    let controller = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || diagnostic_payload(&controller))
        .await
        .map_err(|_| "Sanitized diagnostics are unavailable.".to_string())?
}

#[tauri::command]
pub(crate) async fn desktop_export_diagnostics(
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
        write_diagnostics_file(&selected, &payload)?;
        Ok(true)
    })
    .await
    .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?
}

fn write_diagnostics_file(
    selected: &std::path::Path,
    payload: &serde_json::Value,
) -> Result<(), String> {
    match fs::symlink_metadata(selected) {
        Ok(metadata) if !metadata.is_file() || metadata.nlink() != 1 => {
            return Err("The diagnostics destination was rejected.".to_string());
        }
        Err(error) if error.kind() != std::io::ErrorKind::NotFound => {
            return Err("The diagnostics destination was rejected.".to_string());
        }
        _ => {}
    }
    let parent = selected
        .parent()
        .ok_or_else(|| "The diagnostics destination was rejected.".to_string())?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)
        .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?;
    serde_json::to_writer_pretty(temporary.as_file_mut(), payload)
        .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?;
    temporary
        .persist(selected)
        .map_err(|_| "Sanitized diagnostics could not be saved.".to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::diagnostic_backup_verification;

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
    #[test]
    fn diagnostic_export_is_private_atomic_and_rejects_link_targets() {
        use std::os::unix::fs::{symlink, MetadataExt};
        let root = tempfile::tempdir().unwrap();
        let destination = root.path().join("diagnostics.json");
        let payload = serde_json::json!({"status": "synthetic"});
        super::write_diagnostics_file(&destination, &payload).unwrap();
        assert_eq!(
            std::fs::metadata(&destination).unwrap().mode() & 0o777,
            0o600
        );
        let replaced = serde_json::json!({"status": "updated"});
        super::write_diagnostics_file(&destination, &replaced).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&std::fs::read(&destination).unwrap())
                .unwrap(),
            replaced
        );
        let linked = root.path().join("linked.json");
        std::fs::hard_link(&destination, &linked).unwrap();
        assert!(super::write_diagnostics_file(&linked, &payload).is_err());
        std::fs::remove_file(&linked).unwrap();
        symlink(&destination, &linked).unwrap();
        assert!(super::write_diagnostics_file(&linked, &payload).is_err());
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&std::fs::read(&destination).unwrap())
                .unwrap(),
            replaced
        );
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 2);
    }
}
