fn main() {
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_COMMIT");
    println!("cargo:rerun-if-env-changed=MONEY_MAP_BUILD_ID");
    tauri_build::build()
}
