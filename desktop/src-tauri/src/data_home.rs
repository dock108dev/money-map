use std::fs;
use std::path::{Component, Path, PathBuf};

use serde::Serialize;
use tauri::Manager;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct DataHomePaths {
    pub application: PathBuf,
    pub cache: PathBuf,
    pub logs: PathBuf,
    pub mode: &'static str,
}

impl DataHomePaths {
    pub fn resolve(app: &tauri::AppHandle) -> Result<Self, String> {
        if let Some(fake_home) = option_env!("MONEY_MAP_ACCEPTANCE_FAKE_HOME") {
            return Self::from_home(Path::new(fake_home), "acceptance-synthetic-v1");
        }
        let home = app
            .path()
            .home_dir()
            .map_err(|_| "The macOS user-library location is unavailable.".to_string())?;
        Self::from_home(&home, "production-v1")
    }

    pub fn from_home(home: &Path, mode: &'static str) -> Result<Self, String> {
        if !home.is_absolute() || !matches!(mode, "production-v1" | "acceptance-synthetic-v1") {
            return Err("The macOS data-home boundary was rejected.".to_string());
        }
        let home = lexical_normalize(home)?;
        if mode == "acceptance-synthetic-v1"
            && !(home.starts_with("/tmp") || home.starts_with("/private/tmp"))
        {
            return Err("The synthetic acceptance home must be disposable.".to_string());
        }
        reject_symlink_chain(&home)?;
        let application = home.join("Library/Application Support/Money Map");
        let cache = home.join("Library/Caches/com.moneymap.desktop");
        let logs = home.join("Library/Logs/Money Map");
        for path in [&application, &cache, &logs] {
            reject_symlink_chain(path)?;
        }
        Ok(Self {
            application,
            cache,
            logs,
            mode,
        })
    }

    pub fn backup_root(&self) -> PathBuf {
        self.application.join("backups")
    }

    pub fn report_root(&self) -> PathBuf {
        self.application.join("reports")
    }
}

fn lexical_normalize(path: &Path) -> Result<PathBuf, String> {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(prefix) => normalized.push(prefix.as_os_str()),
            Component::RootDir => normalized.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                if !normalized.pop() {
                    return Err("The macOS data-home boundary was rejected.".to_string());
                }
            }
            Component::Normal(value) => normalized.push(value),
        }
    }
    Ok(normalized)
}

fn reject_symlink_chain(path: &Path) -> Result<(), String> {
    let mut current = PathBuf::new();
    for component in path.components() {
        current.push(component.as_os_str());
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err("A symbolic link in the macOS data path was rejected.".to_string());
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("The macOS data path could not be verified.".to_string()),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::DataHomePaths;

    #[test]
    fn derives_the_versioned_macos_data_cache_and_log_contract() {
        let paths = DataHomePaths::from_home(
            std::path::Path::new("/private/tmp/money-map-path-test"),
            "acceptance-synthetic-v1",
        )
        .unwrap();
        assert_eq!(
            paths.application,
            std::path::Path::new(
                "/private/tmp/money-map-path-test/Library/Application Support/Money Map"
            )
        );
        assert_eq!(
            paths.cache,
            std::path::Path::new(
                "/private/tmp/money-map-path-test/Library/Caches/com.moneymap.desktop"
            )
        );
        assert_eq!(
            paths.logs,
            std::path::Path::new("/private/tmp/money-map-path-test/Library/Logs/Money Map")
        );
    }

    #[test]
    fn synthetic_home_must_be_disposable_and_symlink_free() {
        assert!(DataHomePaths::from_home(
            std::path::Path::new("/Users/example"),
            "acceptance-synthetic-v1"
        )
        .is_err());
        let parent = tempfile::tempdir().unwrap();
        let target = parent.path().join("target");
        std::fs::create_dir(&target).unwrap();
        let link = parent.path().join("link");
        std::os::unix::fs::symlink(&target, &link).unwrap();
        assert!(DataHomePaths::from_home(&link, "acceptance-synthetic-v1").is_err());
    }
}
