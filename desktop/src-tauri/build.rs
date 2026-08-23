fn main() {
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_COMMIT");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_ID");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_ACCEPTANCE_FAKE_HOME");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_KEYCHAIN_ACCEPTANCE");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_REQUIRE_QUALIFICATION");
    const COMMANDS: &[&str] = &[
        "desktop_fetch",
        "desktop_reload",
        "desktop_print",
        "desktop_runtime_status",
        "desktop_restart",
        "desktop_about",
        "desktop_select_import",
        "desktop_reveal_backup",
        "desktop_report_action",
        "desktop_diagnostics_preview",
        "desktop_export_diagnostics",
        "desktop_set_operations_enabled",
        "desktop_open_external",
        "desktop_qualification_observe",
    ];
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("Money Map's reviewed application command manifest must compile")
}
