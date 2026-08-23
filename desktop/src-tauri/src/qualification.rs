use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

pub const LAUNCH_CONTRACT: &str = "money-map-installed-attestation-launch-v1";
pub const ATTESTATION_CONTRACT: &str = "money-map-installed-root-attestation-v1";
pub const RESULT_CONTRACT: &str = "money-map-native-attestation-result-v1";
pub const MAX_LAUNCH_BYTES: usize = 8_192;
pub const MAX_ATTESTATION_BYTES: usize = 8_192;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationContract {
    pub contract: String,
    pub schema_version: u8,
    pub campaign_id: String,
    pub nonce: String,
    pub mode: String,
    pub campaign_root: PathBuf,
    pub application_root: PathBuf,
    pub database_path: PathBuf,
    pub writer_lock_path: PathBuf,
    pub cache_root: PathBuf,
    pub log_root: PathBuf,
    pub result_path: PathBuf,
    pub candidate_sha256: String,
    pub source_commit: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceFacts {
    pub exists: bool,
    pub kind: String,
    pub symlink_free: bool,
    pub contained: bool,
    pub active: Option<bool>,
    pub permissions_mode: u32,
    pub owned_by_current_user: bool,
    pub single_link: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InstalledAttestation {
    pub contract: String,
    pub schema_version: u8,
    pub campaign_id: String,
    pub nonce: String,
    pub generation: u64,
    pub session: String,
    pub mode: String,
    pub campaign_root: PathBuf,
    pub application_root: PathBuf,
    pub database_path: PathBuf,
    pub writer_lock_path: PathBuf,
    pub cache_root: PathBuf,
    pub log_root: PathBuf,
    pub database: ResourceFacts,
    pub writer_lock: ResourceFacts,
    pub cache: ResourceFacts,
    pub logs: ResourceFacts,
    pub schema_revision: String,
    pub integrity: bool,
    pub foreign_keys: bool,
    pub database_identity_stable: bool,
    pub engine_database_identity: bool,
    pub sequence: u64,
}

#[derive(Serialize)]
struct NativeResult<'a> {
    contract: &'static str,
    result: &'a str,
    campaign_id: &'a str,
    attestation_contract: &'static str,
    mode: &'a str,
    candidate_sha256: &'a str,
    source_commit: &'a str,
    root_roles: [&'static str; 6],
    database: bool,
    writer_lock: bool,
    cache: bool,
    logs: bool,
    containment: bool,
    symlink_checks: bool,
    permissions: bool,
    ownership: bool,
    hard_links: bool,
    schema: bool,
    integrity: bool,
    foreign_keys: bool,
    database_identity_stable: bool,
    engine_database_identity: bool,
    readiness_ordering: bool,
    ui_gating: bool,
    main_window_absent_at_result: bool,
    safe_error_required: bool,
    first_unmet_requirement: Option<&'a str>,
}

impl QualificationContract {
    pub fn from_environment() -> Result<Option<Self>, String> {
        let raw = std::env::var("MONEY_MAP_QUALIFICATION_CONTRACT").ok();
        let fake_home = std::env::var_os("MONEY_MAP_ACCEPTANCE_FAKE_HOME");
        if raw.is_none() && fake_home.is_none() {
            if option_env!("MONEY_MAP_REQUIRE_QUALIFICATION") == Some("1") {
                return Err("Synthetic qualification contract is required.".to_string());
            }
            return Ok(None);
        }
        let raw = raw.ok_or_else(|| "Synthetic qualification contract is required.".to_string())?;
        if raw.len() > MAX_LAUNCH_BYTES || raw.contains('\n') || raw.contains('\0') {
            return Err("Synthetic qualification contract was rejected.".to_string());
        }
        for field in [
            "contract",
            "schema_version",
            "campaign_id",
            "nonce",
            "mode",
            "campaign_root",
            "application_root",
            "database_path",
            "writer_lock_path",
            "cache_root",
            "log_root",
            "result_path",
            "candidate_sha256",
            "source_commit",
        ] {
            if raw.matches(&format!("\"{field}\"")).count() != 1 {
                return Err("Synthetic qualification contract was rejected.".to_string());
            }
        }
        let value: Self = serde_json::from_str(&raw)
            .map_err(|_| "Synthetic qualification contract was rejected.".to_string())?;
        if let Err(error) = value.validate(fake_home.as_deref().map(Path::new)) {
            let _ = value.write_result(false, Some("qualification-contract"));
            return Err(error);
        }
        Ok(Some(value))
    }

    fn validate(&self, fake_home: Option<&Path>) -> Result<(), String> {
        if self.contract != LAUNCH_CONTRACT
            || self.schema_version != 1
            || self.mode != "acceptance-synthetic-v1"
            || !is_lower_hex(&self.campaign_id, 32)
            || !is_lower_hex(&self.nonce, 64)
            || !is_lower_hex(&self.candidate_sha256, 64)
            || !is_lower_hex(&self.source_commit, 40)
        {
            return Err("Synthetic qualification contract was rejected.".to_string());
        }
        let campaign = normalized(&self.campaign_root)?;
        if !(campaign.starts_with("/private/tmp") || campaign.starts_with("/tmp"))
            || fake_home.map(normalized).transpose()?.as_ref() != Some(&campaign)
        {
            return Err("Synthetic qualification root was rejected.".to_string());
        }
        reject_symlink_chain(&campaign)?;
        let expected = [
            campaign.join("Library/Application Support/Money Map"),
            campaign.join("Library/Application Support/Money Map/data/paycheck-map.sqlite3"),
            campaign.join("Library/Application Support/Money Map/.money-map-writer.lock"),
            campaign.join("Library/Caches/com.moneymap.desktop"),
            campaign.join("Library/Logs/Money Map"),
            campaign.join("native-attestation-result.json"),
        ];
        let supplied = [
            &self.application_root,
            &self.database_path,
            &self.writer_lock_path,
            &self.cache_root,
            &self.log_root,
            &self.result_path,
        ];
        for (actual, expected) in supplied.into_iter().zip(expected) {
            let actual = normalized(actual)?;
            if actual != expected || !actual.starts_with(&campaign) {
                return Err("Synthetic qualification path was rejected.".to_string());
            }
            reject_symlink_chain(&actual)?;
        }
        Ok(())
    }

    pub fn verify_attestation(
        &self,
        attestation: &InstalledAttestation,
        generation: u64,
        session: &str,
        nonce: &str,
    ) -> Result<(), String> {
        if attestation.contract != ATTESTATION_CONTRACT
            || attestation.schema_version != 1
            || attestation.campaign_id != self.campaign_id
            || attestation.nonce != nonce
            || attestation.generation != generation
            || attestation.session != session
            || attestation.mode != "acceptance-synthetic-v1"
            || attestation.sequence != 1
            || attestation.schema_revision != "0009_goal_persistence"
            || !attestation.integrity
            || !attestation.foreign_keys
            || !attestation.database_identity_stable
            || !attestation.engine_database_identity
        {
            return Err("Installed root attestation was rejected.".to_string());
        }
        let expected = [
            (&attestation.campaign_root, &self.campaign_root),
            (&attestation.application_root, &self.application_root),
            (&attestation.database_path, &self.database_path),
            (&attestation.writer_lock_path, &self.writer_lock_path),
            (&attestation.cache_root, &self.cache_root),
            (&attestation.log_root, &self.log_root),
        ];
        for (actual, expected) in expected {
            if canonical_existing(actual)? != canonical_existing(expected)?
                || !canonical_existing(actual)?
                    .starts_with(canonical_existing(&self.campaign_root)?)
            {
                return Err("Installed root attestation was rejected.".to_string());
            }
            reject_symlink_chain(actual)?;
        }
        let facts = [
            (&attestation.database, "file", None, 0o600, true),
            (&attestation.writer_lock, "file", Some(true), 0o600, true),
            (&attestation.cache, "directory", None, 0o700, false),
            (&attestation.logs, "directory", None, 0o700, false),
        ];
        if facts
            .into_iter()
            .any(|(fact, kind, active, mode, single_link)| {
                !fact.exists
                    || fact.kind != kind
                    || !fact.symlink_free
                    || !fact.contained
                    || fact.permissions_mode != mode
                    || !fact.owned_by_current_user
                    || (single_link && !fact.single_link)
                    || active.is_some_and(|required| fact.active != Some(required))
            })
        {
            return Err("Installed root attestation facts were rejected.".to_string());
        }
        verify_live_resource(&self.database_path, false, 0o600, true)?;
        verify_live_resource(&self.writer_lock_path, false, 0o600, true)?;
        verify_live_resource(&self.cache_root, true, 0o700, false)?;
        verify_live_resource(&self.log_root, true, 0o700, false)?;
        for directory in [
            &self.campaign_root,
            &self.application_root,
            self.database_path
                .parent()
                .ok_or_else(|| "Installed root attestation was rejected.".to_string())?,
        ] {
            verify_live_resource(directory, true, 0o700, false)?;
        }
        verify_private_tree(&self.application_root)?;
        verify_private_tree(&self.cache_root)?;
        verify_private_tree(&self.log_root)?;
        Ok(())
    }

    pub fn write_result(&self, passed: bool, first_unmet: Option<&str>) -> Result<(), String> {
        let campaign = normalized(&self.campaign_root)?;
        let result_path = normalized(&self.result_path)?;
        if !(campaign.starts_with("/private/tmp") || campaign.starts_with("/tmp"))
            || result_path != campaign.join("native-attestation-result.json")
            || !result_path.starts_with(&campaign)
        {
            return Err("Attestation result location was rejected.".to_string());
        }
        reject_symlink_chain(&result_path)?;
        let result = NativeResult {
            contract: RESULT_CONTRACT,
            result: if passed { "pass" } else { "failed" },
            campaign_id: &self.campaign_id,
            attestation_contract: ATTESTATION_CONTRACT,
            mode: &self.mode,
            candidate_sha256: &self.candidate_sha256,
            source_commit: &self.source_commit,
            root_roles: [
                "campaign",
                "application-data",
                "database",
                "writer-lock",
                "cache",
                "safe-log",
            ],
            database: passed,
            writer_lock: passed,
            cache: passed,
            logs: passed,
            containment: passed,
            symlink_checks: passed,
            permissions: passed,
            ownership: passed,
            hard_links: passed,
            schema: passed,
            integrity: passed,
            foreign_keys: passed,
            database_identity_stable: passed,
            engine_database_identity: passed,
            readiness_ordering: true,
            ui_gating: true,
            main_window_absent_at_result: true,
            safe_error_required: !passed,
            first_unmet_requirement: first_unmet,
        };
        let bytes = serde_json::to_vec_pretty(&result)
            .map_err(|_| "Attestation result could not be retained.".to_string())?;
        let temporary = self.result_path.with_extension("json.tmp");
        fs::write(&temporary, bytes)
            .map_err(|_| "Attestation result could not be retained.".to_string())?;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
            .map_err(|_| "Attestation result could not be retained.".to_string())?;
        fs::rename(&temporary, &self.result_path)
            .map_err(|_| "Attestation result could not be retained.".to_string())
    }
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn normalized(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err("Synthetic qualification path was rejected.".to_string());
    }
    let mut value = PathBuf::new();
    for component in path.components() {
        match component {
            Component::RootDir => value.push("/"),
            Component::Normal(part) => value.push(part),
            _ => return Err("Synthetic qualification path was rejected.".to_string()),
        }
    }
    Ok(value)
}

fn canonical_existing(path: &Path) -> Result<PathBuf, String> {
    path.canonicalize()
        .map_err(|_| "Installed attested resource was unavailable.".to_string())
}

fn verify_live_resource(
    path: &Path,
    directory: bool,
    expected_mode: u32,
    single_link: bool,
) -> Result<(), String> {
    reject_symlink_chain(path)?;
    let metadata = fs::symlink_metadata(path)
        .map_err(|_| "Installed attested resource was unavailable.".to_string())?;
    let kind_matches = if directory {
        metadata.is_dir()
    } else {
        metadata.is_file()
    };
    if !kind_matches
        || metadata.file_type().is_symlink()
        || metadata.permissions().mode() & 0o777 != expected_mode
        || metadata.uid() != unsafe { libc::geteuid() }
        || (single_link && metadata.nlink() != 1)
    {
        return Err("Installed attested resource metadata was rejected.".to_string());
    }
    Ok(())
}

fn verify_private_tree(root: &Path) -> Result<(), String> {
    for entry in fs::read_dir(root)
        .map_err(|_| "Installed attested resource was unavailable.".to_string())?
    {
        let path = entry
            .map_err(|_| "Installed attested resource was unavailable.".to_string())?
            .path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| "Installed attested resource was unavailable.".to_string())?;
        if metadata.is_dir() {
            verify_live_resource(&path, true, 0o700, false)?;
            verify_private_tree(&path)?;
        } else {
            verify_live_resource(&path, false, 0o600, true)?;
        }
    }
    Ok(())
}

fn reject_symlink_chain(path: &Path) -> Result<(), String> {
    let mut current = PathBuf::new();
    for component in path.components() {
        current.push(component.as_os_str());
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err("Synthetic qualification symlink was rejected.".to_string())
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("Synthetic qualification path could not be verified.".to_string()),
        }
    }
    Ok(())
}

pub fn parse_attestation(line: &str) -> Result<InstalledAttestation, String> {
    let raw = line
        .strip_prefix("MONEY_MAP_ATTEST ")
        .ok_or_else(|| "Installed root attestation was malformed.".to_string())?;
    if raw.len() > MAX_ATTESTATION_BYTES || raw.contains('\n') || raw.contains('\0') {
        return Err("Installed root attestation was malformed.".to_string());
    }
    let value: InstalledAttestation = serde_json::from_str(raw)
        .map_err(|_| "Installed root attestation was malformed.".to_string())?;
    let exact_key_counts = [
        ("contract", 1),
        ("schema_version", 1),
        ("campaign_id", 1),
        ("nonce", 1),
        ("generation", 1),
        ("session", 1),
        ("mode", 1),
        ("campaign_root", 1),
        ("application_root", 1),
        ("database_path", 1),
        ("writer_lock_path", 1),
        ("cache_root", 1),
        ("log_root", 1),
        ("database", 1),
        ("writer_lock", 1),
        ("cache", 1),
        ("logs", 1),
        ("schema_revision", 1),
        ("integrity", 1),
        ("foreign_keys", 1),
        ("database_identity_stable", 1),
        ("engine_database_identity", 1),
        ("sequence", 1),
        ("exists", 4),
        ("kind", 4),
        ("symlink_free", 4),
        ("contained", 4),
        ("active", 4),
        ("permissions_mode", 4),
        ("owned_by_current_user", 4),
        ("single_link", 4),
    ];
    if exact_key_counts
        .iter()
        .any(|(key, count)| raw.matches(&format!("\"{key}\"")).count() != *count)
    {
        return Err("Installed root attestation was malformed.".to_string());
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (
        tempfile::TempDir,
        QualificationContract,
        InstalledAttestation,
    ) {
        let campaign = tempfile::Builder::new()
            .prefix("money-map-attestation-test-")
            .tempdir_in("/private/tmp")
            .unwrap();
        let application = campaign
            .path()
            .join("Library/Application Support/Money Map");
        fs::set_permissions(campaign.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let database = application.join("data/paycheck-map.sqlite3");
        let writer_lock = application.join(".money-map-writer.lock");
        let cache = campaign.path().join("Library/Caches/com.moneymap.desktop");
        let logs = campaign.path().join("Library/Logs/Money Map");
        fs::create_dir_all(database.parent().unwrap()).unwrap();
        fs::create_dir_all(&cache).unwrap();
        fs::create_dir_all(&logs).unwrap();
        fs::write(&database, b"sqlite").unwrap();
        fs::write(&writer_lock, b"held").unwrap();
        for directory in [
            application.clone(),
            database.parent().unwrap().to_path_buf(),
            cache.clone(),
            logs.clone(),
        ] {
            fs::set_permissions(directory, fs::Permissions::from_mode(0o700)).unwrap();
        }
        for file in [&database, &writer_lock] {
            fs::set_permissions(file, fs::Permissions::from_mode(0o600)).unwrap();
        }
        let contract = QualificationContract {
            contract: LAUNCH_CONTRACT.into(),
            schema_version: 1,
            campaign_id: "a".repeat(32),
            nonce: "b".repeat(64),
            mode: "acceptance-synthetic-v1".into(),
            campaign_root: campaign.path().to_path_buf(),
            application_root: application.clone(),
            database_path: database.clone(),
            writer_lock_path: writer_lock.clone(),
            cache_root: cache.clone(),
            log_root: logs.clone(),
            result_path: campaign.path().join("native-attestation-result.json"),
            candidate_sha256: "c".repeat(64),
            source_commit: "d".repeat(40),
        };
        let file = ResourceFacts {
            exists: true,
            kind: "file".into(),
            symlink_free: true,
            contained: true,
            active: None,
            permissions_mode: 0o600,
            owned_by_current_user: true,
            single_link: true,
        };
        let directory = ResourceFacts {
            exists: true,
            kind: "directory".into(),
            symlink_free: true,
            contained: true,
            active: None,
            permissions_mode: 0o700,
            owned_by_current_user: true,
            single_link: false,
        };
        let attestation = InstalledAttestation {
            contract: ATTESTATION_CONTRACT.into(),
            schema_version: 1,
            campaign_id: contract.campaign_id.clone(),
            nonce: contract.nonce.clone(),
            generation: 1,
            session: "e".repeat(64),
            mode: contract.mode.clone(),
            campaign_root: campaign.path().to_path_buf(),
            application_root: application,
            database_path: database,
            writer_lock_path: writer_lock,
            cache_root: cache,
            log_root: logs,
            database: file.clone(),
            writer_lock: ResourceFacts {
                active: Some(true),
                ..file
            },
            cache: directory.clone(),
            logs: directory,
            schema_revision: "0009_goal_persistence".into(),
            integrity: true,
            foreign_keys: true,
            database_identity_stable: true,
            engine_database_identity: true,
            sequence: 1,
        };
        (campaign, contract, attestation)
    }

    #[test]
    fn exact_live_resource_attestation_passes() {
        let (_campaign, contract, attestation) = fixture();
        contract
            .verify_attestation(&attestation, 1, &"e".repeat(64), &contract.nonce)
            .unwrap();
        let line = format!(
            "MONEY_MAP_ATTEST {}",
            serde_json::to_string(&attestation).unwrap()
        );
        assert_eq!(
            parse_attestation(&line).unwrap_or_else(|error| panic!("{error}: {line}")),
            attestation
        );
    }

    #[test]
    fn identity_replay_mode_and_order_are_rejected() {
        let (_campaign, contract, attestation) = fixture();
        for changed in [
            InstalledAttestation {
                nonce: "f".repeat(64),
                ..attestation.clone()
            },
            InstalledAttestation {
                generation: 2,
                ..attestation.clone()
            },
            InstalledAttestation {
                session: "f".repeat(64),
                ..attestation.clone()
            },
            InstalledAttestation {
                mode: "production-v1".into(),
                ..attestation.clone()
            },
            InstalledAttestation {
                sequence: 2,
                ..attestation.clone()
            },
        ] {
            assert!(contract
                .verify_attestation(&changed, 1, &"e".repeat(64), &contract.nonce)
                .is_err());
        }
    }

    #[test]
    fn escaped_missing_wrong_type_and_inactive_resources_are_rejected() {
        let (campaign, contract, attestation) = fixture();
        let outside = campaign.path().parent().unwrap().join("outside.sqlite3");
        fs::write(&outside, b"sqlite").unwrap();
        let cases = [
            InstalledAttestation {
                database_path: outside.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                database: ResourceFacts {
                    exists: false,
                    ..attestation.database.clone()
                },
                ..attestation.clone()
            },
            InstalledAttestation {
                cache: ResourceFacts {
                    kind: "file".into(),
                    ..attestation.cache.clone()
                },
                ..attestation.clone()
            },
            InstalledAttestation {
                writer_lock: ResourceFacts {
                    active: Some(false),
                    ..attestation.writer_lock.clone()
                },
                ..attestation.clone()
            },
            InstalledAttestation {
                logs: ResourceFacts {
                    contained: false,
                    ..attestation.logs.clone()
                },
                ..attestation.clone()
            },
        ];
        for changed in cases {
            assert!(contract
                .verify_attestation(&changed, 1, &"e".repeat(64), &contract.nonce)
                .is_err());
        }
        fs::remove_file(outside).unwrap();
    }

    #[test]
    fn every_exact_path_role_schema_and_database_check_is_fail_closed() {
        let (_campaign, contract, attestation) = fixture();
        let cases = [
            InstalledAttestation {
                application_root: attestation.cache_root.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                database_path: attestation.writer_lock_path.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                writer_lock_path: attestation.database_path.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                cache_root: attestation.log_root.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                log_root: attestation.cache_root.clone(),
                ..attestation.clone()
            },
            InstalledAttestation {
                schema_revision: "0008_life_lab_v01".into(),
                ..attestation.clone()
            },
            InstalledAttestation {
                integrity: false,
                ..attestation.clone()
            },
            InstalledAttestation {
                foreign_keys: false,
                ..attestation.clone()
            },
            InstalledAttestation {
                database_identity_stable: false,
                ..attestation.clone()
            },
            InstalledAttestation {
                engine_database_identity: false,
                ..attestation.clone()
            },
        ];
        for changed in cases {
            assert!(contract
                .verify_attestation(&changed, 1, &"e".repeat(64), &contract.nonce)
                .is_err());
        }
    }

    #[test]
    fn permissions_and_hard_link_substitution_are_rejected_independently() {
        let (campaign, contract, attestation) = fixture();
        fs::set_permissions(&contract.database_path, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(contract
            .verify_attestation(&attestation, 1, &"e".repeat(64), &contract.nonce)
            .is_err());
        fs::set_permissions(&contract.database_path, fs::Permissions::from_mode(0o600)).unwrap();
        let hard_link = campaign.path().join("database-hard-link");
        fs::hard_link(&contract.database_path, &hard_link).unwrap();
        assert!(contract
            .verify_attestation(&attestation, 1, &"e".repeat(64), &contract.nonce)
            .is_err());
    }

    #[test]
    fn qualification_contract_rejects_production_missing_nonce_traversal_and_symlinks() {
        let (campaign, contract, _attestation) = fixture();
        assert!(contract.validate(Some(campaign.path())).is_ok());
        assert!(QualificationContract {
            mode: "production-v1".into(),
            ..contract.clone()
        }
        .validate(Some(campaign.path()))
        .is_err());
        assert!(QualificationContract {
            nonce: String::new(),
            ..contract.clone()
        }
        .validate(Some(campaign.path()))
        .is_err());
        assert!(QualificationContract {
            database_path: campaign.path().join("child/../escape"),
            ..contract.clone()
        }
        .validate(Some(campaign.path()))
        .is_err());
        let link = campaign.path().join("linked-cache");
        std::os::unix::fs::symlink(&contract.cache_root, &link).unwrap();
        assert!(QualificationContract {
            cache_root: link,
            ..contract.clone()
        }
        .validate(Some(campaign.path()))
        .is_err());
        let lookalike = campaign.path().parent().unwrap().join(format!(
            "{}-lookalike",
            campaign.path().file_name().unwrap().to_string_lossy()
        ));
        fs::create_dir(&lookalike).unwrap();
        assert!(QualificationContract {
            campaign_root: lookalike,
            ..contract
        }
        .validate(Some(campaign.path()))
        .is_err());
    }

    #[test]
    fn malformed_duplicate_and_oversized_attestations_are_rejected() {
        assert!(parse_attestation("MONEY_MAP_ATTEST not-json").is_err());
        assert!(parse_attestation(&format!(
            "MONEY_MAP_ATTEST {}",
            "x".repeat(MAX_ATTESTATION_BYTES + 1)
        ))
        .is_err());
        let (_campaign, _contract, attestation) = fixture();
        let mut raw = serde_json::to_string(&serde_json::json!({
            "contract": attestation.contract, "schema_version": 1, "campaign_id": attestation.campaign_id,
            "nonce": attestation.nonce, "generation": 1, "session": attestation.session,
            "mode": attestation.mode, "campaign_root": attestation.campaign_root,
            "application_root": attestation.application_root, "database_path": attestation.database_path,
            "writer_lock_path": attestation.writer_lock_path, "cache_root": attestation.cache_root,
            "log_root": attestation.log_root, "database": {"exists":true,"kind":"file","symlink_free":true,"contained":true,"active":null},
            "writer_lock": {"exists":true,"kind":"file","symlink_free":true,"contained":true,"active":true},
            "cache": {"exists":true,"kind":"directory","symlink_free":true,"contained":true,"active":null},
            "logs": {"exists":true,"kind":"directory","symlink_free":true,"contained":true,"active":null,"mode":448,"owned_by_current_user":true,"single_link":false},
            "schema_revision":"0009_goal_persistence","integrity":true,"foreign_keys":true,
            "database_identity_stable":true,"engine_database_identity":true,"sequence": 1
        })).unwrap();
        raw = raw.replacen("{", "{\"nonce\":\"f\",", 1);
        assert!(parse_attestation(&format!("MONEY_MAP_ATTEST {raw}")).is_err());
    }

    #[test]
    fn retained_native_result_contains_no_attested_path_or_session() {
        let (campaign, contract, _attestation) = fixture();
        contract.write_result(true, None).unwrap();
        let retained = fs::read_to_string(&contract.result_path).unwrap();
        assert!(!retained.contains(campaign.path().to_string_lossy().as_ref()));
        assert!(!retained.contains("session"));
        assert!(!retained.contains("database_path"));
        assert!(!retained.contains("writer_lock_path"));
        assert!(!retained.contains("cache_root"));
        assert!(!retained.contains("log_root"));
    }
}
