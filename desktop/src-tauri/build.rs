fn main() {
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_COMMIT");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_ID");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_ACCEPTANCE_FAKE_HOME");
    tauri_build::build()
}
