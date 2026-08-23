use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crate::data_home::DataHomePaths;
use crate::lifecycle::{LifecycleMachine, LifecycleState};
use crate::proxy::health_ready;
use crate::qualification::{parse_attestation, InstalledAttestation, QualificationContract};
use serde::Serialize;

const READY_SIGNAL_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);
const CONTROL_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(250);
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);
const DISAPPEARANCE_TIMEOUT: Duration = Duration::from_secs(5);
const FAILURE_MESSAGE: &str =
    "Money Map's local service is unavailable. Financial data was not repaired or changed.";

#[derive(Clone, Debug, Serialize)]
pub struct RuntimeStatus {
    pub state: LifecycleState,
    pub generation: u64,
    pub message: Option<&'static str>,
}

#[derive(Clone)]
struct RunningProcess {
    generation: u64,
    pid: u32,
    child: Arc<Mutex<Child>>,
    control: Arc<Mutex<UnixStream>>,
    protocol_valid: Arc<AtomicBool>,
}

struct RuntimeInner {
    lifecycle: LifecycleMachine,
    process: Option<RunningProcess>,
    port: Option<u16>,
    session: Option<String>,
    message: Option<&'static str>,
}

pub struct RuntimeController {
    inner: Mutex<RuntimeInner>,
    operation: Mutex<()>,
    paths: DataHomePaths,
    sidecar_path: PathBuf,
    qualification: Option<QualificationContract>,
}

enum OutputEvent {
    Attestation(Box<InstalledAttestation>),
    Ready(u16),
    Invalid,
    Closed,
}

#[derive(Debug, Eq, PartialEq)]
enum ReadinessResult {
    Ready(Box<InstalledAttestation>, u16),
    TimedOut,
    Terminated,
}

impl RuntimeController {
    pub fn new(
        sidecar_path: PathBuf,
        paths: DataHomePaths,
        qualification: Option<QualificationContract>,
    ) -> Result<Arc<Self>, String> {
        Ok(Arc::new(Self {
            inner: Mutex::new(RuntimeInner {
                lifecycle: LifecycleMachine::default(),
                process: None,
                port: None,
                session: None,
                message: None,
            }),
            operation: Mutex::new(()),
            paths,
            sidecar_path,
            qualification,
        }))
    }

    pub fn status(&self) -> RuntimeStatus {
        let inner = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        RuntimeStatus {
            state: inner.lifecycle.state(),
            generation: inner.lifecycle.generation(),
            message: inner.message,
        }
    }

    pub fn backup_root(&self) -> PathBuf {
        self.paths.backup_root()
    }

    pub fn report_root(&self) -> PathBuf {
        self.paths.report_root()
    }

    pub fn data_mode(&self) -> &'static str {
        self.paths.mode
    }

    pub fn revalidate(&self) -> RuntimeStatus {
        let failed = {
            let inner = self
                .inner
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if inner.lifecycle.state() != LifecycleState::Ready {
                false
            } else {
                match (&inner.process, inner.port, inner.session.as_ref()) {
                    (Some(process), Some(port), Some(session)) => {
                        !child_is_running(&process.child) || !health_ready(port, session)
                    }
                    _ => true,
                }
            }
        };
        if failed {
            let mut inner = self
                .inner
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if inner.lifecycle.state() == LifecycleState::Ready {
                inner.port = None;
                inner.session = None;
                inner.message = Some(FAILURE_MESSAGE);
                let _ = inner.lifecycle.fail();
            }
        }
        self.status()
    }

    pub fn target(&self) -> Result<(u16, String), String> {
        let inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
        if inner.lifecycle.state() != LifecycleState::Ready {
            return Err(FAILURE_MESSAGE.to_string());
        }
        match (inner.port, inner.session.as_ref()) {
            (Some(port), Some(session)) => Ok((port, session.clone())),
            _ => Err(FAILURE_MESSAGE.to_string()),
        }
    }

    pub fn start_initial(self: &Arc<Self>) -> Result<RuntimeStatus, String> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| FAILURE_MESSAGE.to_string())?;
        let generation = {
            let mut inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
            inner.message = None;
            inner
                .lifecycle
                .start()
                .map_err(|_| FAILURE_MESSAGE.to_string())?
        };
        self.start_generation(generation)
    }

    pub fn restart(self: &Arc<Self>) -> Result<RuntimeStatus, String> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| FAILURE_MESSAGE.to_string())?;
        let (generation, old) = {
            let mut inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
            let generation = inner
                .lifecycle
                .restart()
                .map_err(|_| "Money Map is already starting or stopping.".to_string())?;
            inner.message = None;
            inner.port = None;
            inner.session = None;
            (generation, inner.process.take())
        };
        if let Some(process) = old {
            self.stop_process(&process, None)?;
        }
        self.start_generation(generation)
    }

    pub fn shutdown(&self) {
        let process = {
            let mut inner = self
                .inner
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if inner.lifecycle.state() == LifecycleState::Stopped {
                return;
            }
            let _ = inner.lifecycle.begin_stop();
            inner.port = None;
            inner.session = None;
            inner.process.take()
        };
        if let Some(process) = process {
            let _ = self.stop_process(&process, None);
        }
        let mut inner = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let _ = inner.lifecycle.stopped();
        inner.message = None;
        drop(inner);
    }

    fn start_generation(self: &Arc<Self>, generation: u64) -> Result<RuntimeStatus, String> {
        if requested_generation("MONEY_MAP_RUNTIME_FAIL_GENERATION") == Some(generation) {
            return self.fail_generation(generation);
        }
        if verify_sidecar_artifact(&self.sidecar_path).is_err() {
            return self.fail_generation(generation);
        }
        let session = session_token()?;
        let nonce = if generation == 1 {
            self.qualification.as_ref().map(|value| value.nonce.clone())
        } else if self.qualification.is_some() {
            Some(session_token()?)
        } else {
            None
        };
        let (process, output) = match self.spawn_process(generation, &session, nonce.as_deref()) {
            Ok(value) => value,
            Err(_) => return self.fail_generation(generation),
        };
        {
            let mut inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
            if inner.lifecycle.generation() != generation
                || !matches!(
                    inner.lifecycle.state(),
                    LifecycleState::Starting | LifecycleState::Restarting
                )
            {
                drop(inner);
                let _ = self.stop_process(&process, None);
                return Err(FAILURE_MESSAGE.to_string());
            }
            inner.process = Some(process.clone());
        }

        let readiness = wait_for_readiness(
            &output,
            READY_SIGNAL_TIMEOUT,
            self.qualification.is_some(),
            || child_is_running(&process.child),
        );
        let (attestation, port) = match readiness {
            ReadinessResult::Ready(attestation, port) => (attestation, port),
            ReadinessResult::TimedOut | ReadinessResult::Terminated => {
                self.remove_and_stop(generation, &process, None);
                if let Some(contract) = &self.qualification {
                    let _ = contract.write_result(false, Some("installed-root-attestation"));
                }
                return self.fail_generation(generation);
            }
        };
        if let (Some(contract), Some(nonce)) = (&self.qualification, nonce.as_deref()) {
            if contract
                .verify_attestation(&attestation, generation, &session, nonce)
                .is_err()
            {
                self.remove_and_stop(generation, &process, None);
                let _ = contract.write_result(false, Some("installed-root-attestation"));
                return self.fail_generation(generation);
            }
        }
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        while Instant::now() < deadline {
            if !self.is_current_and_active(generation)
                || !child_is_running(&process.child)
                || !process.protocol_valid.load(Ordering::SeqCst)
            {
                self.remove_and_stop(generation, &process, Some(port));
                if let Some(contract) = &self.qualification {
                    let _ = contract.write_result(false, Some("installed-root-attestation"));
                }
                return self.fail_generation(generation);
            }
            if health_ready(port, &session) {
                break;
            }
            thread::sleep(Duration::from_millis(75));
        }
        if !health_ready(port, &session) {
            self.remove_and_stop(generation, &process, Some(port));
            if let Some(contract) = &self.qualification {
                let _ = contract.write_result(false, Some("installed-root-attestation"));
            }
            return self.fail_generation(generation);
        }
        {
            let mut inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
            if inner.lifecycle.generation() != generation
                || !matches!(
                    inner.lifecycle.state(),
                    LifecycleState::Starting | LifecycleState::Restarting
                )
            {
                drop(inner);
                self.remove_and_stop(generation, &process, Some(port));
                return Err(FAILURE_MESSAGE.to_string());
            }
            inner.port = Some(port);
            inner.session = Some(session);
            inner.message = None;
            inner
                .lifecycle
                .ready()
                .map_err(|_| FAILURE_MESSAGE.to_string())?;
        }
        self.monitor(process.clone());
        if let Some(contract) = &self.qualification {
            if contract.write_result(true, None).is_err() {
                self.remove_and_stop(generation, &process, Some(port));
                return self.fail_generation(generation);
            }
        }
        Ok(self.status())
    }

    fn spawn_process(
        &self,
        generation: u64,
        session: &str,
        nonce: Option<&str>,
    ) -> Result<(RunningProcess, Receiver<OutputEvent>), String> {
        let (mut bootstrap_writer, bootstrap_reader) = UnixStream::pair()
            .map_err(|_| "Bundled service bootstrap could not start.".to_string())?;
        let (control_writer, control_reader) = UnixStream::pair()
            .map_err(|_| "Bundled service control could not start.".to_string())?;
        let bootstrap_fd = bootstrap_reader.as_raw_fd();
        let control_fd = control_reader.as_raw_fd();
        let mut command = Command::new(&self.sidecar_path);
        command
            .env_clear()
            .env("LC_ALL", "C")
            .env("PAYCHECK_MAP_DESKTOP_MODE", "true")
            .env("PAYCHECK_MAP_DESKTOP_DATA_MODE", self.paths.mode)
            .env("PAYCHECK_MAP_DESKTOP_APP_ROOT", &self.paths.application)
            .env("PAYCHECK_MAP_DESKTOP_CACHE_ROOT", &self.paths.cache)
            .env("PAYCHECK_MAP_DESKTOP_LOG_ROOT", &self.paths.logs)
            .env("PAYCHECK_MAP_LOCAL_DIR", &self.paths.application)
            .env("PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD", "3")
            .env("PAYCHECK_MAP_DESKTOP_CONTROL_FD", "63")
            .env(
                "PAYCHECK_MAP_DESKTOP_OWNER_PID",
                std::process::id().to_string(),
            )
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if self.paths.mode == "keychain-acceptance-v1" {
            command.env("PAYCHECK_MAP_KEYCHAIN_ACCEPTANCE", "1");
        }
        if let Some(bundle_root) = self
            .sidecar_path
            .parent()
            .and_then(|path| path.parent())
            .and_then(|path| path.parent())
        {
            command.env("PAYCHECK_MAP_DESKTOP_BUNDLE_ROOT", bundle_root);
        }
        if requested_generation("MONEY_MAP_RUNTIME_DELAY_GENERATION") == Some(generation) {
            if let Ok(delay) = std::env::var("MONEY_MAP_RUNTIME_DELAY_MS") {
                command.env("PAYCHECK_MAP_DESKTOP_STARTUP_DELAY_MS", delay);
            }
        }
        unsafe {
            command.pre_exec(move || {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                if libc::dup2(bootstrap_fd, 3) == -1
                    || libc::fcntl(3, libc::F_SETFD, 0) == -1
                    || libc::dup2(control_fd, 63) == -1
                    || libc::fcntl(63, libc::F_SETFD, 0) == -1
                {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = command
            .spawn()
            .map_err(|_| "Bundled service could not start.".to_string())?;
        drop(bootstrap_reader);
        drop(control_reader);
        let bootstrap = serde_json::to_vec(&serde_json::json!({
            "contract": "money-map-desktop-bootstrap-v1",
            "session": session,
            "attestation": self.qualification.as_ref().zip(nonce).map(|(contract, nonce)| serde_json::json!({
                "contract": "money-map-installed-root-attestation-v1",
                "schema_version": 1,
                "campaign_id": contract.campaign_id,
                "nonce": nonce,
                "generation": generation,
                "mode": contract.mode,
                "campaign_root": contract.campaign_root,
                "application_root": contract.application_root,
                "database_path": contract.database_path,
                "writer_lock_path": contract.writer_lock_path,
                "cache_root": contract.cache_root,
                "log_root": contract.log_root,
            })),
        }))
        .map_err(|_| "Bundled service bootstrap was rejected.".to_string())?;
        if bootstrap.len() > 8_191
            || bootstrap_writer.write_all(&bootstrap).is_err()
            || bootstrap_writer.write_all(b"\n").is_err()
            || bootstrap_writer.flush().is_err()
        {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Bundled service bootstrap was rejected.".to_string());
        }
        drop(bootstrap_writer);
        let pid = child.id();
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Bundled service output was unavailable.".to_string())?;
        let (sender, receiver) = mpsc::channel();
        let protocol_valid = Arc::new(AtomicBool::new(true));
        let reader_protocol_valid = Arc::clone(&protocol_valid);
        let attestation_required = self.qualification.is_some();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            let mut attested = false;
            let mut ready = false;
            for line in reader.lines().map_while(Result::ok) {
                if line.starts_with("MONEY_MAP_ATTEST ") {
                    match (attested, ready, parse_attestation(&line)) {
                        (false, false, Ok(value)) => {
                            attested = true;
                            let _ = sender.send(OutputEvent::Attestation(Box::new(value)));
                        }
                        _ => {
                            reader_protocol_valid.store(false, Ordering::SeqCst);
                            let _ = sender.send(OutputEvent::Invalid);
                        }
                    }
                } else if line.starts_with("MONEY_MAP_READY ") {
                    match (ready, attestation_required && !attested, parse_ready(&line)) {
                        (false, false, Some(port)) => {
                            ready = true;
                            let _ = sender.send(OutputEvent::Ready(port));
                        }
                        _ => {
                            reader_protocol_valid.store(false, Ordering::SeqCst);
                            let _ = sender.send(OutputEvent::Invalid);
                        }
                    }
                }
            }
            let _ = sender.send(OutputEvent::Closed);
        });
        Ok((
            RunningProcess {
                generation,
                pid,
                child: Arc::new(Mutex::new(child)),
                control: Arc::new(Mutex::new(control_writer)),
                protocol_valid,
            },
            receiver,
        ))
    }

    fn monitor(self: &Arc<Self>, process: RunningProcess) {
        let controller = Arc::clone(self);
        thread::spawn(move || loop {
            thread::sleep(Duration::from_millis(100));
            if !controller.process_matches(&process) {
                return;
            }
            if !child_is_running(&process.child) || !process.protocol_valid.load(Ordering::SeqCst) {
                if !process.protocol_valid.load(Ordering::SeqCst) {
                    unsafe {
                        libc::kill(-(process.pid as i32), libc::SIGTERM);
                    }
                }
                let mut inner = controller
                    .inner
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
                if inner.process.as_ref().is_some_and(|active| {
                    active.generation == process.generation && active.pid == process.pid
                }) {
                    inner.process = None;
                    inner.port = None;
                    inner.session = None;
                    if matches!(
                        inner.lifecycle.state(),
                        LifecycleState::Starting
                            | LifecycleState::Ready
                            | LifecycleState::Restarting
                    ) {
                        let _ = inner.lifecycle.fail();
                        inner.message = Some(FAILURE_MESSAGE);
                    }
                }
                return;
            }
        });
    }

    fn process_matches(&self, process: &RunningProcess) -> bool {
        let inner = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        inner.process.as_ref().is_some_and(|active| {
            active.generation == process.generation && active.pid == process.pid
        })
    }

    fn is_current_and_active(&self, generation: u64) -> bool {
        let inner = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        inner.lifecycle.generation() == generation
            && matches!(
                inner.lifecycle.state(),
                LifecycleState::Starting | LifecycleState::Restarting
            )
    }

    fn remove_and_stop(&self, generation: u64, process: &RunningProcess, port: Option<u16>) {
        {
            let mut inner = self
                .inner
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if inner.lifecycle.generation() == generation {
                inner.process = None;
                inner.port = None;
                inner.session = None;
            }
        }
        let _ = self.stop_process(process, port);
    }

    fn fail_generation(&self, generation: u64) -> Result<RuntimeStatus, String> {
        let mut inner = self.inner.lock().map_err(|_| FAILURE_MESSAGE.to_string())?;
        if inner.lifecycle.generation() == generation
            && matches!(
                inner.lifecycle.state(),
                LifecycleState::Starting | LifecycleState::Restarting
            )
        {
            let _ = inner.lifecycle.fail();
            inner.message = Some(FAILURE_MESSAGE);
        }
        Err(FAILURE_MESSAGE.to_string())
    }

    fn stop_process(
        &self,
        process: &RunningProcess,
        known_port: Option<u16>,
    ) -> Result<(), String> {
        if let Ok(mut control) = process.control.lock() {
            let _ = control
                .write_all(b"{\"command\":\"shutdown\",\"contract\":\"money-map-control-v1\"}\n");
            let _ = control.flush();
        }
        let control_deadline = Instant::now() + CONTROL_SHUTDOWN_TIMEOUT;
        while Instant::now() < control_deadline && child_is_running(&process.child) {
            thread::sleep(Duration::from_millis(25));
        }
        if child_is_running(&process.child) {
            unsafe {
                libc::kill(-(process.pid as i32), libc::SIGTERM);
            }
        }
        let graceful_deadline = Instant::now() + GRACEFUL_SHUTDOWN_TIMEOUT;
        while Instant::now() < graceful_deadline && child_is_running(&process.child) {
            thread::sleep(Duration::from_millis(25));
        }
        if child_is_running(&process.child) {
            unsafe {
                libc::kill(-(process.pid as i32), libc::SIGKILL);
            }
            if let Ok(mut child) = process.child.lock() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        let disappearance = Instant::now() + DISAPPEARANCE_TIMEOUT;
        while Instant::now() < disappearance {
            let group_gone = !process_group_exists(process.pid);
            let listener_gone = known_port.is_none_or(|port| !listener_exists(port));
            if group_gone && listener_gone {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(25));
        }
        Err("The local service cleanup did not finish safely.".to_string())
    }
}

fn verify_sidecar_artifact(path: &std::path::Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|_| "The bundled service identity could not be verified.".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.nlink() != 1 {
        return Err("The bundled service identity could not be verified.".to_string());
    }
    let macos = path
        .parent()
        .ok_or_else(|| "The signed application layout is invalid.".to_string())?;
    if macos.file_name().and_then(|value| value.to_str()) != Some("MacOS")
        || path.file_name().and_then(|value| value.to_str()) != Some("money-map-sidecar")
    {
        return Err("The signed application layout is invalid.".to_string());
    }
    let bundle = macos
        .parent()
        .and_then(|contents| contents.parent())
        .ok_or_else(|| "The signed application layout is invalid.".to_string())?;
    if bundle.extension().and_then(|value| value.to_str()) != Some("app") {
        return Err("The signed application layout is invalid.".to_string());
    }
    let canonical_bundle = bundle
        .canonicalize()
        .map_err(|_| "The signed application identity could not be verified.".to_string())?;
    let canonical_path = path
        .canonicalize()
        .map_err(|_| "The bundled service identity could not be verified.".to_string())?;
    if !canonical_path.starts_with(&canonical_bundle) {
        return Err("The bundled service identity could not be verified.".to_string());
    }
    let mut header = [0_u8; 8];
    fs::File::open(path)
        .and_then(|mut file| file.read_exact(&mut header))
        .map_err(|_| "The bundled service identity could not be verified.".to_string())?;
    if header[..4] != [0xcf, 0xfa, 0xed, 0xfe] || header[4..] != [0x0c, 0x00, 0x00, 0x01] {
        return Err("The bundled service architecture was rejected.".to_string());
    }
    let status = Command::new("/usr/bin/codesign")
        .arg("--verify")
        .arg("--deep")
        .arg("--strict")
        .arg("-R=anchor apple generic and certificate leaf[subject.OU] = \"E3G5D247ZN\"")
        .arg(&canonical_bundle)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|_| "The signed application identity could not be verified.".to_string())?;
    if !status.success() {
        return Err("The signed application identity could not be verified.".to_string());
    }
    Ok(())
}

fn session_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "Secure session generation failed.".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn parse_ready(line: &str) -> Option<u16> {
    let value = line.strip_prefix("MONEY_MAP_READY ")?;
    let port = value.trim().parse::<u16>().ok()?;
    (port > 0).then_some(port)
}

fn wait_for_readiness<F>(
    receiver: &Receiver<OutputEvent>,
    timeout: Duration,
    require_attestation: bool,
    mut running: F,
) -> ReadinessResult
where
    F: FnMut() -> bool,
{
    let deadline = Instant::now() + timeout;
    let mut attestation = None;
    loop {
        if !running() {
            return ReadinessResult::Terminated;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return ReadinessResult::TimedOut;
        }
        match receiver.recv_timeout(remaining.min(Duration::from_millis(50))) {
            Ok(OutputEvent::Attestation(value)) if attestation.is_none() => {
                attestation = Some(value)
            }
            Ok(OutputEvent::Ready(port)) => {
                if let Some(value) = attestation.take() {
                    return ReadinessResult::Ready(value, port);
                }
                if !require_attestation {
                    return ReadinessResult::Ready(Box::new(empty_attestation()), port);
                }
                return ReadinessResult::Terminated;
            }
            Ok(OutputEvent::Attestation(_)) | Ok(OutputEvent::Invalid) => {
                return ReadinessResult::Terminated
            }
            Ok(OutputEvent::Closed) | Err(RecvTimeoutError::Disconnected) => {
                return ReadinessResult::Terminated;
            }
            Err(RecvTimeoutError::Timeout) => {}
        }
    }
}

fn empty_attestation() -> InstalledAttestation {
    use crate::qualification::ResourceFacts;
    let facts = ResourceFacts {
        exists: false,
        kind: String::new(),
        symlink_free: false,
        contained: false,
        active: None,
        permissions_mode: 0,
        owned_by_current_user: false,
        single_link: false,
    };
    InstalledAttestation {
        contract: String::new(),
        schema_version: 0,
        campaign_id: String::new(),
        nonce: String::new(),
        generation: 0,
        session: String::new(),
        mode: String::new(),
        campaign_root: PathBuf::new(),
        application_root: PathBuf::new(),
        database_path: PathBuf::new(),
        writer_lock_path: PathBuf::new(),
        cache_root: PathBuf::new(),
        log_root: PathBuf::new(),
        database: facts.clone(),
        writer_lock: facts.clone(),
        cache: facts.clone(),
        logs: facts,
        schema_revision: String::new(),
        integrity: false,
        foreign_keys: false,
        database_identity_stable: false,
        engine_database_identity: false,
        sequence: 0,
    }
}

fn child_is_running(child: &Arc<Mutex<Child>>) -> bool {
    child
        .lock()
        .map(|mut child| {
            child
                .try_wait()
                .map(|status| status.is_none())
                .unwrap_or(false)
        })
        .unwrap_or(false)
}

fn process_group_exists(pid: u32) -> bool {
    let result = unsafe { libc::kill(-(pid as i32), 0) };
    result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

fn listener_exists(port: u16) -> bool {
    TcpStream::connect_timeout(
        &SocketAddrV4::new(Ipv4Addr::LOCALHOST, port).into(),
        Duration::from_millis(50),
    )
    .is_ok()
}

fn requested_generation(name: &str) -> Option<u64> {
    std::env::var(name).ok()?.parse().ok()
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;
    use std::time::Duration;

    use super::{
        empty_attestation, parse_ready, session_token, wait_for_readiness, OutputEvent,
        ReadinessResult,
    };

    #[test]
    fn every_session_has_256_bits_and_is_replaced() {
        let first = session_token().unwrap();
        let second = session_token().unwrap();
        assert_eq!(first.len(), 64);
        assert_eq!(second.len(), 64);
        assert_ne!(first, second);
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
    }

    #[test]
    fn readiness_parser_accepts_only_a_valid_signal() {
        assert_eq!(parse_ready("MONEY_MAP_READY 43123"), Some(43123));
        assert_eq!(parse_ready("MONEY_MAP_READY 0"), None);
        assert_eq!(parse_ready("debug MONEY_MAP_READY 43123"), None);
        assert_eq!(parse_ready("MONEY_MAP_READY private"), None);
    }

    #[test]
    fn attestation_must_precede_readiness_exactly_once() {
        let (sender, receiver) = mpsc::channel();
        sender
            .send(OutputEvent::Attestation(Box::new(empty_attestation())))
            .unwrap();
        sender.send(OutputEvent::Ready(43123)).unwrap();
        assert!(matches!(
            wait_for_readiness(&receiver, Duration::from_millis(10), true, || true),
            ReadinessResult::Ready(_, 43123)
        ));

        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Ready(43123)).unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), true, || true),
            ReadinessResult::Terminated
        );

        let (sender, receiver) = mpsc::channel();
        sender
            .send(OutputEvent::Attestation(Box::new(empty_attestation())))
            .unwrap();
        sender
            .send(OutputEvent::Attestation(Box::new(empty_attestation())))
            .unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), true, || true),
            ReadinessResult::Terminated
        );
    }

    #[test]
    fn missing_malformed_or_closed_attestation_fails_closed() {
        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Invalid).unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), true, || true),
            ReadinessResult::Terminated
        );
        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Closed).unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), true, || true),
            ReadinessResult::Terminated
        );
        let (_sender, receiver) = mpsc::channel();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(2), true, || true),
            ReadinessResult::TimedOut
        );
    }

    #[test]
    fn ordinary_runtime_remains_ready_without_qualification_attestation() {
        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Ready(43123)).unwrap();
        assert!(matches!(
            wait_for_readiness(&receiver, Duration::from_millis(10), false, || true),
            ReadinessResult::Ready(_, 43123)
        ));
    }

    #[test]
    fn shutdown_preserves_the_persistent_data_home() {
        let parent = tempfile::Builder::new()
            .prefix("money-map-runtime-test-")
            .tempdir_in("/private/tmp")
            .unwrap();
        let paths =
            crate::data_home::DataHomePaths::from_home(parent.path(), "acceptance-synthetic-v1")
                .unwrap();
        let controller =
            super::RuntimeController::new("/missing/synthetic-sidecar".into(), paths.clone(), None)
                .unwrap();
        assert!(controller.start_initial().is_err());
        controller.shutdown();
        assert!(parent.path().exists());
        assert_eq!(controller.paths.application, paths.application);
    }
}
