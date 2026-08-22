use serde::Serialize;
use tauri::menu::AboutMetadataBuilder;

pub const RUNTIME_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const SCHEMA_REVISION: &str = "0009_goal_persistence";
pub const BUILD_COMMIT: &str = match option_env!("MONEY_MAP_BUILD_COMMIT") {
    Some(value) => value,
    None => "development",
};
pub const BUILD_ID: &str = match option_env!("MONEY_MAP_BUILD_ID") {
    Some(value) => value,
    None => "development",
};

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AboutInfo {
    pub product: &'static str,
    pub runtime_version: &'static str,
    pub schema_revision: &'static str,
    pub desktop_build: &'static str,
    pub source_commit: &'static str,
    pub target: String,
    pub data_mode: &'static str,
    pub data_location: &'static str,
    pub boundary: &'static str,
}

pub fn about_info() -> AboutInfo {
    AboutInfo {
        product: "Money Map",
        runtime_version: RUNTIME_VERSION,
        schema_revision: SCHEMA_REVISION,
        desktop_build: BUILD_ID,
        source_commit: BUILD_COMMIT,
        target: format!("{}-{}", std::env::consts::ARCH, std::env::consts::OS),
        data_mode: "disposable synthetic",
        data_location: "Private disposable runtime directory",
        boundary: "Local only; Plaid is optional and read-only",
    }
}

pub fn native_about_metadata() -> tauri::menu::AboutMetadata<'static> {
    let info = about_info();
    AboutMetadataBuilder::new()
        .name(Some(info.product))
        .version(Some(info.runtime_version))
        .short_version(Some(info.desktop_build))
        .credits(Some(format!(
            "Schema: {}\nSource: {}\nTarget: {}\nData: {}\nLocation: {}\n{}",
            info.schema_revision,
            info.source_commit,
            info.target,
            info.data_mode,
            info.data_location,
            info.boundary
        )))
        .build()
}

#[cfg(test)]
mod tests {
    use super::{about_info, RUNTIME_VERSION, SCHEMA_REVISION};

    #[test]
    fn about_metadata_uses_build_and_runtime_constants() {
        let about = about_info();
        assert_eq!(about.product, "Money Map");
        assert_eq!(about.runtime_version, RUNTIME_VERSION);
        assert_eq!(about.schema_revision, SCHEMA_REVISION);
        assert_eq!(RUNTIME_VERSION, "2.1.0");
        assert_eq!(SCHEMA_REVISION, "0009_goal_persistence");
        assert_eq!(about.data_mode, "disposable synthetic");
        assert!(about.boundary.contains("read-only"));
        assert!(!about.data_location.contains('/'));
    }
}
