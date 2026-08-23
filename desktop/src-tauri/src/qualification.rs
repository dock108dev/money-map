use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

pub const LAUNCH_CONTRACT: &str = "money-map-installed-attestation-launch-v1";
pub const ATTESTATION_CONTRACT: &str = "money-map-installed-root-attestation-v1";
pub const RESULT_CONTRACT: &str = "money-map-native-attestation-result-v1";
pub const MATRIX_RESULT_CONTRACT: &str = "money-map-installed-matrix-observation-v1";
pub const MATRIX_FAILURE_CONTRACT: &str = "money-map-installed-matrix-observer-failure-v1";
pub const RESPONSE_GATE_CONTRACT: &str = "qualification-response-gate-v1";
pub const RESPONSE_GATE_RELEASE_CONTRACT: &str = "money-map-qualification-gate-release-v1";
pub const RESPONSE_GATE_CHALLENGE_CONTRACT: &str = "money-map-qualification-gate-challenge-v1";
pub const SEALED_ORACLE_DIGEST: &str =
    "a8d34d04e5c56f42470fb74a6ea8dc287aa8b20ecc4237a6da76c2432202ae45";
pub const MAX_LAUNCH_BYTES: usize = 8_192;
pub const MAX_ATTESTATION_BYTES: usize = 8_192;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixDriverPlan {
    #[serde(rename = "type")]
    pub driver_type: String,
    pub seed: String,
    pub gate: String,
    pub release: String,
    pub timeout_ms: u64,
}

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
    #[serde(default)]
    pub matrix_state: Option<String>,
    #[serde(default)]
    pub matrix_route: Option<String>,
    #[serde(default)]
    pub matrix_contract_digest: Option<String>,
    #[serde(default)]
    pub matrix_result_path: Option<PathBuf>,
    #[serde(default)]
    pub matrix_driver: Option<MatrixDriverPlan>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixUiObservation {
    pub sequence: u8,
    pub phase: String,
    pub route: String,
    pub location_hash: String,
    pub headings: Vec<String>,
    pub statuses: Vec<String>,
    pub alerts: Vec<String>,
    pub buttons: Vec<String>,
    pub disabled_buttons: Vec<String>,
    pub messages: Vec<String>,
    pub loading_visible: bool,
    pub loading_busy: bool,
    pub loading_live: String,
    pub dialog_count: u32,
    pub progress_count: u32,
    pub unsafe_console_errors: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixObserverFailure {
    pub sequence: u8,
    pub requested_route: String,
    pub expected_phase: String,
    pub last_completed_stage: String,
    pub failure_classification: String,
    pub hash_matched: bool,
    pub global_loading_present: bool,
    pub route_local_loading_present: bool,
    pub native_invocation_accepted: bool,
    pub timeout_classification: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GateRelease {
    contract: String,
    combination_id: String,
    runtime_generation: u64,
    gate_generation: u8,
    challenge: String,
}

#[derive(Serialize)]
struct GateChallenge<'a> {
    contract: &'static str,
    combination_id: &'a str,
    runtime_generation: u64,
    gate_generation: u8,
    challenge: &'a str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GateStatus {
    Idle,
    Armed,
    Released,
    Failed,
}

#[derive(Debug)]
struct GateState {
    status: GateStatus,
    runtime_generation: u64,
    gate_generation: u8,
    session: String,
    challenge: String,
}

pub struct QualificationResponseGate {
    contract: QualificationContract,
    state: Mutex<GateState>,
    changed: Condvar,
}

impl QualificationResponseGate {
    pub fn from_contract(contract: &QualificationContract) -> Option<Arc<Self>> {
        contract.response_gate_requested().then(|| {
            Arc::new(Self {
                contract: contract.clone(),
                state: Mutex::new(GateState {
                    status: GateStatus::Idle,
                    runtime_generation: 0,
                    gate_generation: 0,
                    session: String::new(),
                    challenge: String::new(),
                }),
                changed: Condvar::new(),
            })
        })
    }

    pub fn arm(
        self: &Arc<Self>,
        runtime_generation: u64,
        gate_generation: u8,
        session: &str,
    ) -> Result<(), String> {
        if runtime_generation == 0
            || !matches!(gate_generation, 1 | 2)
            || session.len() != 64
            || !session.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return Err("Synthetic qualification response gate was rejected.".to_string());
        }
        let challenge_path = self.contract.gate_challenge_path();
        let release_path = self.contract.gate_release_path();
        if challenge_path.exists() || release_path.exists() {
            self.fail_and_clean();
            return Err("Synthetic qualification response gate replay was rejected.".to_string());
        }
        let challenge = random_hex(32)?;
        let combination = self.contract.gate_combination()?;
        write_private_json(
            &challenge_path,
            &GateChallenge {
                contract: RESPONSE_GATE_CHALLENGE_CONTRACT,
                combination_id: &combination,
                runtime_generation,
                gate_generation,
                challenge: &challenge,
            },
        )?;
        {
            let mut state = self
                .state
                .lock()
                .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
            if gate_generation == 2
                && (state.status != GateStatus::Released
                    || state.runtime_generation != runtime_generation
                    || state.gate_generation != 1)
            {
                drop(state);
                self.fail_and_clean();
                return Err("Synthetic qualification response gate rearm was rejected.".to_string());
            }
            state.status = GateStatus::Armed;
            state.runtime_generation = runtime_generation;
            state.gate_generation = gate_generation;
            state.session = session.to_string();
            state.challenge = challenge;
        }
        let gate = Arc::clone(self);
        thread::spawn(move || gate.watch_release());
        Ok(())
    }

    pub fn wait_for_release(&self) -> Result<(), String> {
        let deadline = Instant::now() + Duration::from_millis(5_100);
        let mut state = self
            .state
            .lock()
            .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
        loop {
            match state.status {
                GateStatus::Released => return Ok(()),
                GateStatus::Failed | GateStatus::Idle => {
                    return Err("Synthetic qualification response gate failed safely.".to_string())
                }
                GateStatus::Armed => {}
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                drop(state);
                self.fail_and_clean();
                return Err("Synthetic qualification response gate timed out safely.".to_string());
            }
            let (next, _) = self
                .changed
                .wait_timeout(state, remaining)
                .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
            state = next;
        }
    }

    pub fn cleanup(&self) {
        self.fail_and_clean();
    }

    fn watch_release(&self) {
        let timeout = self
            .contract
            .matrix_driver
            .as_ref()
            .map_or(5_000, |driver| driver.timeout_ms);
        let deadline = Instant::now() + Duration::from_millis(timeout);
        let release_path = self.contract.gate_release_path();
        while Instant::now() < deadline {
            if release_path.exists() {
                let accepted = self.consume_release(&release_path);
                let mut state = self
                    .state
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
                state.status = if accepted {
                    GateStatus::Released
                } else {
                    GateStatus::Failed
                };
                drop(state);
                self.remove_gate_files();
                self.changed.notify_all();
                return;
            }
            thread::sleep(Duration::from_millis(20));
        }
        self.fail_and_clean();
    }

    fn consume_release(&self, path: &Path) -> bool {
        if verify_private_gate_file(path).is_err() {
            return false;
        }
        let bytes = match fs::read(path) {
            Ok(bytes) if bytes.len() <= 4_096 => bytes,
            _ => return false,
        };
        let release: GateRelease = match serde_json::from_slice(&bytes) {
            Ok(release) => release,
            Err(_) => return false,
        };
        let state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let combination = match self.contract.gate_combination() {
            Ok(value) => value,
            Err(_) => return false,
        };
        state.status == GateStatus::Armed
            && !state.session.is_empty()
            && release.contract == RESPONSE_GATE_RELEASE_CONTRACT
            && release.combination_id == combination
            && release.runtime_generation == state.runtime_generation
            && release.gate_generation == state.gate_generation
            && release.challenge == state.challenge
    }

    fn fail_and_clean(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        state.status = GateStatus::Failed;
        state.session.clear();
        state.challenge.clear();
        drop(state);
        self.remove_gate_files();
        self.changed.notify_all();
    }

    fn remove_gate_files(&self) {
        for path in [
            self.contract.gate_challenge_path(),
            self.contract.gate_release_path(),
        ] {
            if fs::symlink_metadata(&path).is_ok() {
                let _ = fs::remove_file(path);
            }
        }
    }
}

fn random_hex(bytes: usize) -> Result<String, String> {
    let mut value = vec![0_u8; bytes];
    getrandom::fill(&mut value)
        .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
    Ok(value.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn write_private_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    reject_symlink_chain(path)?;
    if path.exists() {
        return Err("Synthetic qualification response gate replay was rejected.".to_string());
    }
    let temporary = path.with_extension("json.tmp");
    if temporary.exists() {
        return Err("Synthetic qualification response gate replay was rejected.".to_string());
    }
    let bytes = serde_json::to_vec(value)
        .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
    drop(file);
    if fs::hard_link(&temporary, path).is_err() {
        let _ = fs::remove_file(&temporary);
        return Err("Synthetic qualification response gate replay was rejected.".to_string());
    }
    if fs::remove_file(&temporary).is_err() {
        let _ = fs::remove_file(path);
        let _ = fs::remove_file(&temporary);
        return Err("Synthetic qualification response gate failed safely.".to_string());
    }
    verify_private_gate_file(path)
}

fn verify_private_gate_file(path: &Path) -> Result<(), String> {
    reject_symlink_chain(path)?;
    let metadata = fs::symlink_metadata(path)
        .map_err(|_| "Synthetic qualification response gate failed safely.".to_string())?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.mode() & 0o777 != 0o600
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.nlink() != 1
    {
        return Err("Synthetic qualification response gate was rejected.".to_string());
    }
    Ok(())
}

#[derive(Clone, Debug, Serialize)]
pub struct MatrixApiObservation {
    pub endpoint_class: &'static str,
    pub status: u16,
    pub response_class: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MatrixRequestObservation {
    pub method: String,
    pub endpoint: String,
    pub count: u32,
}

#[derive(Serialize)]
struct MatrixResult<'a> {
    contract: &'static str,
    result: &'static str,
    state: &'a str,
    route: &'a str,
    contract_digest_sha256: &'a str,
    ui: &'a MatrixUiObservation,
    api: &'a [MatrixApiObservation],
    request_inventory: &'a [MatrixRequestObservation],
    raw_paths_retained: bool,
}

#[derive(Serialize)]
struct MatrixFailureResult<'a> {
    contract: &'static str,
    result: &'static str,
    state: &'a str,
    route: &'a str,
    contract_digest_sha256: &'a str,
    candidate_sha256: &'a str,
    source_commit: &'a str,
    sequence: u8,
    requested_route: &'a str,
    expected_phase: &'a str,
    last_completed_stage: &'a str,
    failure_classification: &'a str,
    hash_matched: bool,
    global_loading_present: bool,
    route_local_loading_present: bool,
    native_invocation_accepted: bool,
    timeout_classification: bool,
    raw_paths_retained: bool,
    private_content_retained: bool,
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
        let matrix_values = [
            self.matrix_state.is_some(),
            self.matrix_route.is_some(),
            self.matrix_contract_digest.is_some(),
            self.matrix_result_path.is_some(),
        ];
        if matrix_values.iter().any(|value| *value) && !matrix_values.iter().all(|value| *value) {
            return Err("Synthetic qualification matrix contract was rejected.".to_string());
        }
        if let (Some(state), Some(route), Some(digest), Some(path)) = (
            self.matrix_state.as_deref(),
            self.matrix_route.as_deref(),
            self.matrix_contract_digest.as_deref(),
            self.matrix_result_path.as_deref(),
        ) {
            if !approved_matrix_state(state)
                || !approved_matrix_route(route)
                || !is_lower_hex(digest, 64)
                || normalized(path)? != campaign.join("matrix-observation.json")
            {
                return Err("Synthetic qualification matrix contract was rejected.".to_string());
            }
            reject_symlink_chain(path)?;
            if state == "loading" {
                let driver = self.matrix_driver.as_ref().ok_or_else(|| {
                    "Synthetic qualification response gate was rejected.".to_string()
                })?;
                if digest != SEALED_ORACLE_DIGEST
                    || driver.driver_type != "transient_bounded_loading_injection"
                    || driver.seed != "complete-current-v1"
                    || driver.gate != RESPONSE_GATE_CONTRACT
                    || driver.release != "explicit_harness_release"
                    || driver.timeout_ms != 5_000
                {
                    return Err("Synthetic qualification response gate was rejected.".to_string());
                }
            } else if self.matrix_driver.is_some() {
                return Err("Synthetic qualification response gate was rejected.".to_string());
            }
        } else if self.matrix_driver.is_some() {
            return Err("Synthetic qualification response gate was rejected.".to_string());
        }
        Ok(())
    }

    pub fn matrix_plan(&self) -> Option<(&str, &str)> {
        self.matrix_state
            .as_deref()
            .zip(self.matrix_route.as_deref())
    }

    pub fn response_gate_requested(&self) -> bool {
        self.matrix_state.as_deref() == Some("loading") && self.matrix_driver.is_some()
    }

    fn gate_combination(&self) -> Result<String, String> {
        let (state, route) = self
            .matrix_plan()
            .ok_or_else(|| "Synthetic qualification response gate was rejected.".to_string())?;
        Ok(format!("{state}::{route}"))
    }

    fn gate_challenge_path(&self) -> PathBuf {
        self.campaign_root
            .join("qualification-response-gate.challenge.json")
    }

    fn gate_release_path(&self) -> PathBuf {
        self.campaign_root
            .join("qualification-response-gate.release.json")
    }

    pub fn write_matrix_result(
        &self,
        ui: &MatrixUiObservation,
        api: &[MatrixApiObservation],
        request_inventory: &[MatrixRequestObservation],
    ) -> Result<(), String> {
        let (state, route) = self
            .matrix_plan()
            .ok_or_else(|| "Synthetic qualification matrix plan is unavailable.".to_string())?;
        let digest = self
            .matrix_contract_digest
            .as_deref()
            .ok_or_else(|| "Synthetic qualification matrix plan is unavailable.".to_string())?;
        let path = self
            .matrix_result_path
            .as_deref()
            .ok_or_else(|| "Synthetic qualification matrix plan is unavailable.".to_string())?;
        if !self.valid_matrix_observation(ui, request_inventory) {
            return Err("Synthetic qualification matrix observation was rejected.".to_string());
        }
        let result = MatrixResult {
            contract: MATRIX_RESULT_CONTRACT,
            result: "observed",
            state,
            route,
            contract_digest_sha256: digest,
            ui,
            api,
            request_inventory,
            raw_paths_retained: false,
        };
        let bytes = serde_json::to_vec_pretty(&result)
            .map_err(|_| "Synthetic qualification matrix observation was rejected.".to_string())?;
        let path = if ui.phase == "pending" {
            path.with_file_name(format!("matrix-observation-pending-{}.json", ui.sequence))
        } else {
            path.to_path_buf()
        };
        let temporary = path.with_extension("json.tmp");
        fs::write(&temporary, bytes)
            .map_err(|_| "Synthetic qualification matrix observation was rejected.".to_string())?;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
            .map_err(|_| "Synthetic qualification matrix observation was rejected.".to_string())?;
        fs::rename(temporary, path)
            .map_err(|_| "Synthetic qualification matrix observation was rejected.".to_string())
    }

    pub fn valid_matrix_observation(
        &self,
        ui: &MatrixUiObservation,
        request_inventory: &[MatrixRequestObservation],
    ) -> bool {
        let Some((state, route)) = self.matrix_plan() else {
            return false;
        };
        let expected_hash = match route {
            "add-account" => Some("#view=connections"),
            "cash-flow" | "goals" | "activity" | "accounts" | "income" | "wealth"
            | "retirement" | "lab" | "overview" => Some(route),
            _ => None,
        };
        let hash_matches = expected_hash.is_none_or(|value| {
            ui.location_hash
                == if value.starts_with('#') {
                    value.to_string()
                } else {
                    format!("#view={value}")
                }
        });
        let loading_phase_matches = if ui.phase == "pending" {
            ui.headings == ["Loading accounts…"]
                && ui.statuses.is_empty()
                && ui.alerts.is_empty()
                && ui.buttons.is_empty()
                && ui.disabled_buttons.is_empty()
                && ui.messages.is_empty()
                && ui.loading_visible
                && ui.loading_busy
                && ui.loading_live == "polite"
                && ui.dialog_count == 0
                && ui.progress_count == 0
        } else {
            state != "loading" || (!ui.loading_visible && !ui.loading_busy)
        };
        ui.route == route
            && matches!(ui.sequence, 1 | 2)
            && matches!(ui.phase.as_str(), "pending" | "settled")
            && (state == "loading" || ui.phase == "settled")
            && hash_matches
            && loading_phase_matches
            && safe_matrix_observation(ui)
            && request_inventory.iter().all(|item| {
                item.count > 0
                    && matches!(
                        item.method.as_str(),
                        "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
                    )
                    && item.endpoint.starts_with("/api/")
                    && !item.endpoint.contains('?')
                    && item.endpoint.len() <= 256
                    && item.endpoint.is_ascii()
            })
    }

    pub fn write_matrix_failure(&self, failure: &MatrixObserverFailure) -> Result<(), String> {
        let (state, route) = self
            .matrix_plan()
            .ok_or_else(|| "Synthetic qualification matrix failure was rejected.".to_string())?;
        let digest = self
            .matrix_contract_digest
            .as_deref()
            .ok_or_else(|| "Synthetic qualification matrix failure was rejected.".to_string())?;
        if failure.requested_route != route
            || !matches!(failure.sequence, 1 | 2)
            || !matches!(failure.expected_phase.as_str(), "pending" | "settled")
            || !matches!(
                failure.last_completed_stage.as_str(),
                "awaiting-global-loading"
                    | "pending-observed"
                    | "awaiting-global-release"
                    | "route-requested"
                    | "awaiting-route"
                    | "native-api-probe"
                    | "evidence-write"
            )
            || !matches!(
                failure.failure_classification.as_str(),
                "observer-timeout"
                    | "route-control-unavailable"
                    | "native-observation-rejected"
                    | "native-validation-rejected"
                    | "native-api-probe-failed"
                    | "evidence-write-failed"
            )
        {
            return Err("Synthetic qualification matrix failure was rejected.".to_string());
        }
        let result = MatrixFailureResult {
            contract: MATRIX_FAILURE_CONTRACT,
            result: "failed",
            state,
            route,
            contract_digest_sha256: digest,
            candidate_sha256: &self.candidate_sha256,
            source_commit: &self.source_commit,
            sequence: failure.sequence,
            requested_route: &failure.requested_route,
            expected_phase: &failure.expected_phase,
            last_completed_stage: &failure.last_completed_stage,
            failure_classification: &failure.failure_classification,
            hash_matched: failure.hash_matched,
            global_loading_present: failure.global_loading_present,
            route_local_loading_present: failure.route_local_loading_present,
            native_invocation_accepted: failure.native_invocation_accepted,
            timeout_classification: failure.timeout_classification,
            raw_paths_retained: false,
            private_content_retained: false,
        };
        write_private_json(
            &self
                .campaign_root
                .join(format!("matrix-observer-failure-{}.json", failure.sequence)),
            &result,
        )
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

fn approved_matrix_state(value: &str) -> bool {
    matches!(
        value,
        "empty"
            | "loading"
            | "unavailable"
            | "partial_coverage"
            | "recoverable_failure"
            | "stale_evidence"
            | "complete_current"
            | "large_history"
            | "negative_recurring_cash_flow"
            | "cash_below_protected_floor"
            | "missing_source_coverage"
            | "no_life_lab_profile"
            | "profile_without_goals"
            | "one_enabled_goal_with_floor"
            | "multiple_enabled_goals_ambiguous"
            | "stale_saved_scenario"
            | "completed_goal"
    )
}

fn approved_matrix_route(value: &str) -> bool {
    matches!(
        value,
        "cash-flow"
            | "goals"
            | "activity"
            | "accounts"
            | "income"
            | "wealth"
            | "retirement"
            | "lab"
            | "overview"
            | "add-account"
            | "data-home"
            | "diagnostics"
            | "reports"
    )
}

fn safe_matrix_observation(value: &MatrixUiObservation) -> bool {
    let fields = value
        .headings
        .iter()
        .chain(value.statuses.iter())
        .chain(value.alerts.iter())
        .chain(value.buttons.iter())
        .chain(value.disabled_buttons.iter())
        .chain(value.messages.iter());
    value.location_hash.len() <= 64
        && matches!(value.loading_live.as_str(), "" | "polite")
        && value
            .location_hash
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'#' | b'=' | b'-' | b'_'))
        && value.headings.len() <= 16
        && value.statuses.len() <= 16
        && value.alerts.len() <= 16
        && value.buttons.len() <= 64
        && value.disabled_buttons.len() <= 64
        && value.messages.len() <= 64
        && fields.clone().all(|text| {
            !text.is_empty()
                && text.len() <= 240
                && !text.contains('\\')
                && !text
                    .split('/')
                    .any(|segment| matches!(segment, "Users" | "private"))
                && !text.contains("Traceback")
                && !text.contains("Exception")
                && !text.contains("127.0.0.1")
        })
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
            matrix_state: None,
            matrix_route: None,
            matrix_contract_digest: None,
            matrix_result_path: None,
            matrix_driver: None,
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
    fn matrix_plan_is_exact_bounded_and_writes_only_sanitized_observations() {
        let (campaign, contract, _attestation) = fixture();
        let mut matrix = QualificationContract {
            matrix_state: Some("empty".into()),
            matrix_route: Some("cash-flow".into()),
            matrix_contract_digest: Some("f".repeat(64)),
            matrix_result_path: Some(campaign.path().join("matrix-observation.json")),
            ..contract
        };
        matrix.validate(Some(campaign.path())).unwrap();
        let observation = MatrixUiObservation {
            sequence: 1,
            phase: "settled".into(),
            route: "cash-flow".into(),
            location_hash: "#view=cash-flow".into(),
            headings: vec!["Cash Flow".into()],
            statuses: vec!["Cash Flow unavailable".into()],
            alerts: vec![],
            buttons: vec!["Reload".into()],
            disabled_buttons: vec![],
            messages: vec!["Cash Flow unavailable".into()],
            loading_visible: false,
            loading_busy: false,
            loading_live: String::new(),
            dialog_count: 0,
            progress_count: 0,
            unsafe_console_errors: 0,
        };
        matrix
            .write_matrix_result(
                &observation,
                &[MatrixApiObservation {
                    endpoint_class: "cash-flow-period",
                    status: 409,
                    response_class: "unavailable".into(),
                }],
                &[MatrixRequestObservation {
                    method: "GET".into(),
                    endpoint: "/api/v2/cash-flow".into(),
                    count: 1,
                }],
            )
            .unwrap();
        let retained = fs::read_to_string(matrix.matrix_result_path.as_ref().unwrap()).unwrap();
        assert!(retained.contains(MATRIX_RESULT_CONTRACT));
        assert!(retained.contains("/api/v2/cash-flow"));
        assert!(!retained.contains(campaign.path().to_str().unwrap()));

        assert!(matrix
            .write_matrix_result(
                &observation,
                &[],
                &[MatrixRequestObservation {
                    method: "GET".into(),
                    endpoint: "/api/private?identifier=unsafe".into(),
                    count: 1,
                }],
            )
            .is_err());

        matrix.matrix_route = Some("not-a-route".into());
        assert!(matrix.validate(Some(campaign.path())).is_err());
        matrix.matrix_route = Some("cash-flow".into());
        matrix.matrix_contract_digest = None;
        assert!(matrix.validate(Some(campaign.path())).is_err());
    }

    #[test]
    fn overview_is_an_exact_qualification_route_and_unknown_routes_are_rejected() {
        let (campaign, contract, _attestation) = fixture();
        let overview = QualificationContract {
            matrix_state: Some("empty".into()),
            matrix_route: Some("overview".into()),
            matrix_contract_digest: Some("f".repeat(64)),
            matrix_result_path: Some(campaign.path().join("matrix-observation.json")),
            ..contract
        };
        overview.validate(Some(campaign.path())).unwrap();
        let mut unknown = overview;
        unknown.matrix_route = Some("overview-unknown".into());
        assert!(unknown.validate(Some(campaign.path())).is_err());
    }

    fn loading_contract() -> (tempfile::TempDir, QualificationContract) {
        let (campaign, contract, _attestation) = fixture();
        let contract = QualificationContract {
            matrix_state: Some("loading".into()),
            matrix_route: Some("cash-flow".into()),
            matrix_contract_digest: Some(SEALED_ORACLE_DIGEST.into()),
            matrix_result_path: Some(campaign.path().join("matrix-observation.json")),
            matrix_driver: Some(MatrixDriverPlan {
                driver_type: "transient_bounded_loading_injection".into(),
                seed: "complete-current-v1".into(),
                gate: RESPONSE_GATE_CONTRACT.into(),
                release: "explicit_harness_release".into(),
                timeout_ms: 5_000,
            }),
            ..contract
        };
        contract.validate(Some(campaign.path())).unwrap();
        (campaign, contract)
    }

    fn gate_release(contract: &QualificationContract) -> GateRelease {
        let value: serde_json::Value = serde_json::from_slice(
            &fs::read(contract.gate_challenge_path()).expect("gate challenge"),
        )
        .unwrap();
        GateRelease {
            contract: RESPONSE_GATE_RELEASE_CONTRACT.into(),
            combination_id: value["combination_id"].as_str().unwrap().into(),
            runtime_generation: value["runtime_generation"].as_u64().unwrap(),
            gate_generation: value["gate_generation"].as_u64().unwrap() as u8,
            challenge: value["challenge"].as_str().unwrap().into(),
        }
    }

    #[test]
    fn loading_gate_requires_the_exact_sealed_driver_and_oracle() {
        let (campaign, contract) = loading_contract();
        assert!(contract.response_gate_requested());
        let (_ordinary_campaign, ordinary, _attestation) = fixture();
        assert!(QualificationResponseGate::from_contract(&ordinary).is_none());
        for changed in [
            QualificationContract {
                matrix_driver: None,
                ..contract.clone()
            },
            QualificationContract {
                matrix_contract_digest: Some("f".repeat(64)),
                ..contract.clone()
            },
            QualificationContract {
                matrix_state: Some("empty".into()),
                ..contract.clone()
            },
            QualificationContract {
                nonce: "f".repeat(63),
                ..contract.clone()
            },
            QualificationContract {
                mode: "production-v1".into(),
                ..contract.clone()
            },
        ] {
            assert!(changed.validate(Some(campaign.path())).is_err());
        }
    }

    #[test]
    fn loading_gate_releases_once_and_rearms_with_a_new_challenge() {
        let (_campaign, contract) = loading_contract();
        let gate = QualificationResponseGate::from_contract(&contract).unwrap();
        gate.arm(1, 1, &"e".repeat(64)).unwrap();
        let first = gate_release(&contract);
        write_private_json(&contract.gate_release_path(), &first).unwrap();
        gate.wait_for_release().unwrap();
        assert!(!contract.gate_challenge_path().exists());
        assert!(!contract.gate_release_path().exists());

        gate.arm(1, 2, &"e".repeat(64)).unwrap();
        let second = gate_release(&contract);
        assert_ne!(first.challenge, second.challenge);
        assert_eq!(second.gate_generation, 2);
        write_private_json(&contract.gate_release_path(), &second).unwrap();
        gate.wait_for_release().unwrap();
        gate.cleanup();
        assert!(!contract.gate_challenge_path().exists());
        assert!(!contract.gate_release_path().exists());
    }

    #[test]
    fn loading_gate_rejects_stale_wrong_generation_and_replayed_release() {
        for mutation in ["stale", "runtime", "challenge"] {
            let (_campaign, contract) = loading_contract();
            let gate = QualificationResponseGate::from_contract(&contract).unwrap();
            gate.arm(1, 1, &"e".repeat(64)).unwrap();
            let mut first = gate_release(&contract);
            if mutation == "runtime" {
                first.runtime_generation = 2;
            } else if mutation == "challenge" {
                first.challenge = "f".repeat(64);
            }
            if mutation == "stale" {
                write_private_json(&contract.gate_release_path(), &first).unwrap();
                gate.wait_for_release().unwrap();
                gate.arm(1, 2, &"e".repeat(64)).unwrap();
            }
            write_private_json(&contract.gate_release_path(), &first).unwrap();
            assert!(gate.wait_for_release().is_err());
            gate.cleanup();
        }
    }

    #[test]
    fn loading_gate_timeout_fails_closed_and_removes_private_material() {
        let (_campaign, contract) = loading_contract();
        let gate = QualificationResponseGate::from_contract(&contract).unwrap();
        gate.arm(1, 1, &"e".repeat(64)).unwrap();
        assert!(gate.wait_for_release().is_err());
        assert!(!contract.gate_challenge_path().exists());
        assert!(!contract.gate_release_path().exists());
    }

    #[test]
    fn matrix_observation_rejects_private_paths_and_route_substitution() {
        let (campaign, contract, _attestation) = fixture();
        let matrix = QualificationContract {
            matrix_state: Some("empty".into()),
            matrix_route: Some("cash-flow".into()),
            matrix_contract_digest: Some("f".repeat(64)),
            matrix_result_path: Some(campaign.path().join("matrix-observation.json")),
            ..contract
        };
        let mut observation = MatrixUiObservation {
            sequence: 1,
            phase: "settled".into(),
            route: "goals".into(),
            location_hash: "#view=goals".into(),
            headings: vec!["Goals".into()],
            statuses: vec![],
            alerts: vec![],
            buttons: vec![],
            disabled_buttons: vec![],
            messages: vec![],
            loading_visible: false,
            loading_busy: false,
            loading_live: String::new(),
            dialog_count: 0,
            progress_count: 0,
            unsafe_console_errors: 0,
        };
        assert!(matrix.write_matrix_result(&observation, &[], &[]).is_err());
        observation.route = "cash-flow".into();
        observation.headings = vec!["/private/tmp/forbidden".into()];
        assert!(matrix.write_matrix_result(&observation, &[], &[]).is_err());
    }

    #[test]
    fn matrix_failure_is_bounded_private_and_sequence_specific() {
        let (campaign, contract, _attestation) = fixture();
        let matrix = QualificationContract {
            matrix_state: Some("loading".into()),
            matrix_route: Some("overview".into()),
            matrix_contract_digest: Some(SEALED_ORACLE_DIGEST.into()),
            matrix_result_path: Some(campaign.path().join("matrix-observation.json")),
            matrix_driver: Some(MatrixDriverPlan {
                driver_type: "transient_bounded_loading_injection".into(),
                seed: "complete-current-v1".into(),
                gate: RESPONSE_GATE_CONTRACT.into(),
                release: "explicit_harness_release".into(),
                timeout_ms: 5_000,
            }),
            ..contract
        };
        let failure = MatrixObserverFailure {
            sequence: 2,
            requested_route: "overview".into(),
            expected_phase: "settled".into(),
            last_completed_stage: "awaiting-route".into(),
            failure_classification: "observer-timeout".into(),
            hash_matched: true,
            global_loading_present: false,
            route_local_loading_present: true,
            native_invocation_accepted: true,
            timeout_classification: true,
        };
        matrix.write_matrix_failure(&failure).unwrap();
        let path = campaign.path().join("matrix-observer-failure-2.json");
        let metadata = fs::metadata(&path).unwrap();
        assert_eq!(metadata.mode() & 0o777, 0o600);
        assert_eq!(metadata.nlink(), 1);
        let retained = fs::read_to_string(path).unwrap();
        assert!(retained.contains(MATRIX_FAILURE_CONTRACT));
        assert!(retained.contains("observer-timeout"));
        assert!(retained.contains("\"raw_paths_retained\":false"));
        assert!(retained.contains("\"private_content_retained\":false"));
        assert!(!retained.contains(campaign.path().to_str().unwrap()));

        for changed in [
            MatrixObserverFailure {
                sequence: 3,
                ..failure.clone()
            },
            MatrixObserverFailure {
                requested_route: "/private/tmp/private".into(),
                ..failure.clone()
            },
            MatrixObserverFailure {
                failure_classification: "session-secret-leaked-on-port-1234".into(),
                ..failure.clone()
            },
            MatrixObserverFailure {
                last_completed_stage: "unbounded-private-stage".into(),
                ..failure.clone()
            },
        ] {
            assert!(matrix.write_matrix_failure(&changed).is_err());
        }
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
