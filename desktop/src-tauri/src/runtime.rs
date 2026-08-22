use std::io::{BufRead, BufReader, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tempfile::TempDir;

use crate::lifecycle::{LifecycleMachine, LifecycleState};
use crate::proxy::health_ready;

const READY_SIGNAL_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(1500);
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
    data_parent: Mutex<Option<TempDir>>,
    data_root: PathBuf,
    sidecar_path: PathBuf,
}

enum OutputEvent {
    Ready(u16),
    Closed,
}

#[derive(Debug, Eq, PartialEq)]
enum ReadinessResult {
    Ready(u16),
    TimedOut,
    Terminated,
}

impl RuntimeController {
    pub fn new(sidecar_path: PathBuf) -> Result<Arc<Self>, String> {
        let data_parent = tempfile::Builder::new()
            .prefix("money-map-runtime-")
            .tempdir()
            .map_err(|_| "Disposable runtime setup failed.".to_string())?;
        let data_root = data_parent.path().join("money-map-synthetic-data");
        Ok(Arc::new(Self {
            inner: Mutex::new(RuntimeInner {
                lifecycle: LifecycleMachine::default(),
                process: None,
                port: None,
                session: None,
                message: None,
            }),
            operation: Mutex::new(()),
            data_parent: Mutex::new(Some(data_parent)),
            data_root,
            sidecar_path,
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
        if let Ok(mut parent) = self.data_parent.lock() {
            if let Some(parent) = parent.take() {
                let _ = parent.close();
            }
        }
    }

    fn start_generation(self: &Arc<Self>, generation: u64) -> Result<RuntimeStatus, String> {
        if requested_generation("MONEY_MAP_RUNTIME_FAIL_GENERATION") == Some(generation) {
            return self.fail_generation(generation);
        }
        if !self.sidecar_path.is_file() {
            return self.fail_generation(generation);
        }
        let session = session_token()?;
        let (process, output) = match self.spawn_process(generation, &session) {
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

        let readiness = wait_for_readiness(&output, READY_SIGNAL_TIMEOUT, || {
            child_is_running(&process.child)
        });
        let port = match readiness {
            ReadinessResult::Ready(port) => port,
            ReadinessResult::TimedOut | ReadinessResult::Terminated => {
                self.remove_and_stop(generation, &process, None);
                return self.fail_generation(generation);
            }
        };
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        while Instant::now() < deadline {
            if !self.is_current_and_active(generation) || !child_is_running(&process.child) {
                self.remove_and_stop(generation, &process, Some(port));
                return self.fail_generation(generation);
            }
            if health_ready(port, &session) {
                break;
            }
            thread::sleep(Duration::from_millis(75));
        }
        if !health_ready(port, &session) {
            self.remove_and_stop(generation, &process, Some(port));
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
        self.monitor(process);
        Ok(self.status())
    }

    fn spawn_process(
        &self,
        generation: u64,
        session: &str,
    ) -> Result<(RunningProcess, Receiver<OutputEvent>), String> {
        let mut command = Command::new(&self.sidecar_path);
        command
            .env_clear()
            .env("LC_ALL", "C")
            .env("PAYCHECK_MAP_DESKTOP_MODE", "true")
            .env("PAYCHECK_MAP_DESKTOP_DATA_MODE", "disposable-synthetic")
            .env("PAYCHECK_MAP_LOCAL_DIR", &self.data_root)
            .env("PAYCHECK_MAP_DESKTOP_SESSION", session)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if requested_generation("MONEY_MAP_RUNTIME_DELAY_GENERATION") == Some(generation) {
            if let Ok(delay) = std::env::var("MONEY_MAP_RUNTIME_DELAY_MS") {
                command.env("PAYCHECK_MAP_DESKTOP_STARTUP_DELAY_MS", delay);
            }
        }
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    Err(std::io::Error::last_os_error())
                } else {
                    Ok(())
                }
            });
        }
        let mut child = command
            .spawn()
            .map_err(|_| "Bundled service could not start.".to_string())?;
        let pid = child.id();
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Bundled service output was unavailable.".to_string())?;
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                if let Some(port) = parse_ready(&line) {
                    let _ = sender.send(OutputEvent::Ready(port));
                }
            }
            let _ = sender.send(OutputEvent::Closed);
        });
        Ok((
            RunningProcess {
                generation,
                pid,
                child: Arc::new(Mutex::new(child)),
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
            if !child_is_running(&process.child) {
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
        if let Ok(mut child) = process.child.lock() {
            if let Some(stdin) = child.stdin.as_mut() {
                let _ = stdin.write_all(b"shutdown\n");
                let _ = stdin.flush();
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
    mut running: F,
) -> ReadinessResult
where
    F: FnMut() -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        if !running() {
            return ReadinessResult::Terminated;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return ReadinessResult::TimedOut;
        }
        match receiver.recv_timeout(remaining.min(Duration::from_millis(50))) {
            Ok(OutputEvent::Ready(port)) => return ReadinessResult::Ready(port),
            Ok(OutputEvent::Closed) | Err(RecvTimeoutError::Disconnected) => {
                return ReadinessResult::Terminated;
            }
            Err(RecvTimeoutError::Timeout) => {}
        }
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

    use super::{parse_ready, session_token, wait_for_readiness, OutputEvent, ReadinessResult};

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
    fn readiness_reports_success_timeout_and_child_termination() {
        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Ready(43123)).unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), || true),
            ReadinessResult::Ready(43123)
        );

        let (_sender, receiver) = mpsc::channel();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(5), || true),
            ReadinessResult::TimedOut
        );

        let (_sender, receiver) = mpsc::channel();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), || false),
            ReadinessResult::Terminated
        );
    }

    #[test]
    fn closed_output_is_a_startup_termination() {
        let (sender, receiver) = mpsc::channel();
        sender.send(OutputEvent::Closed).unwrap();
        assert_eq!(
            wait_for_readiness(&receiver, Duration::from_millis(10), || true),
            ReadinessResult::Terminated
        );
    }

    #[test]
    fn shutdown_explicitly_removes_the_owned_synthetic_parent() {
        let controller =
            super::RuntimeController::new("/missing/synthetic-sidecar".into()).unwrap();
        let parent = controller.data_root.parent().unwrap().to_path_buf();
        assert!(parent.is_dir());
        assert!(controller.start_initial().is_err());
        controller.shutdown();
        assert!(!parent.exists());
    }
}
