"""Frozen, argument-free Apple Silicon desktop sidecar entrypoint."""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import TextIO

import uvicorn

from paycheck_map.data_home import DataHomePaths
from paycheck_map.desktop_bootstrap import (
    BOOTSTRAP_CONTRACT,
    MAX_BOOTSTRAP_BYTES,
    clear_bootstrap,
    install_bootstrap,
)
from paycheck_map.desktop_lock import WriterLock
from paycheck_map.keychain import MacOSKeychainSecretStore
from paycheck_map.safe_events import SafeEventLog


def _read_bootstrap() -> str:
    try:
        bootstrap_fd = int(os.environ.pop("PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD", ""))
    except ValueError as error:
        raise RuntimeError("Desktop bootstrap is unavailable") from error
    if not 3 <= bootstrap_fd <= 64:
        raise RuntimeError("Desktop bootstrap is unavailable")
    try:
        with os.fdopen(bootstrap_fd, "rb", closefd=True) as handle:
            payload = handle.read(MAX_BOOTSTRAP_BYTES + 1)
    except OSError as error:
        raise RuntimeError("Desktop bootstrap is unavailable") from error
    if len(payload) > MAX_BOOTSTRAP_BYTES or not payload.endswith(b"\n"):
        raise RuntimeError("Desktop bootstrap was rejected")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Desktop bootstrap was rejected") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"contract", "session"}
        or value.get("contract") != BOOTSTRAP_CONTRACT
        or not isinstance(value.get("session"), str)
    ):
        raise RuntimeError("Desktop bootstrap was rejected")
    return str(value["session"])


def _control_handle() -> TextIO:
    try:
        control_fd = int(os.environ.pop("PAYCHECK_MAP_DESKTOP_CONTROL_FD", ""))
    except ValueError as error:
        raise RuntimeError("Desktop control is unavailable") from error
    if not 4 <= control_fd <= 64:
        raise RuntimeError("Desktop control is unavailable")
    try:
        return os.fdopen(control_fd, "r", encoding="utf-8", closefd=True)
    except OSError as error:
        raise RuntimeError("Desktop control is unavailable") from error


def _owner_pid() -> int:
    try:
        owner_pid = int(os.environ.pop("PAYCHECK_MAP_DESKTOP_OWNER_PID", ""))
    except ValueError as error:
        raise RuntimeError("Desktop owner is unavailable") from error
    if owner_pid <= 1:
        raise RuntimeError("Desktop owner is unavailable")
    return owner_pid


def _owner_is_alive(owner_pid: int) -> bool:
    try:
        os.kill(owner_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _synthetic_root() -> Path:
    raw = os.environ.get("PAYCHECK_MAP_LOCAL_DIR")
    if not raw:
        raise RuntimeError("Disposable desktop data root is required")
    root = Path(raw).resolve()
    if os.environ.get("PAYCHECK_MAP_DESKTOP_DATA_MODE") != "disposable-synthetic":
        raise RuntimeError("Disposable synthetic desktop mode is required")
    if root.name != "money-map-synthetic-data" or not root.parent.name.startswith(
        "money-map-runtime-"
    ):
        raise RuntimeError("Desktop runtime refuses a non-disposable data root")
    if root.is_symlink() or ".local" in root.parts:
        raise RuntimeError("Desktop runtime refuses an unsafe data root")
    return root


def _desktop_root() -> Path:
    mode = os.environ.get("PAYCHECK_MAP_DESKTOP_DATA_MODE")
    if mode == "disposable-synthetic":
        return _synthetic_root()
    if mode in {"production-v1", "acceptance-synthetic-v1", "keychain-acceptance-v1"}:
        paths = DataHomePaths.from_trusted_environment()
        return paths.application
    raise RuntimeError("Desktop data mode is required")


def main() -> None:
    session = _read_bootstrap()
    control = _control_handle()
    owner_pid = _owner_pid()
    root = _desktop_root()
    if os.environ.get("PAYCHECK_MAP_DESKTOP_MODE") != "true":
        raise RuntimeError("Desktop mode is required")
    log_root = os.environ.get("PAYCHECK_MAP_DESKTOP_LOG_ROOT")
    if not log_root:
        raise RuntimeError("Desktop safe log location is required")
    events = SafeEventLog(Path(log_root))
    events.emit("MM-DESKTOP-START", "lifecycle")
    if os.environ.pop("PAYCHECK_MAP_KEYCHAIN_ACCEPTANCE", "") == "1":
        store = MacOSKeychainSecretStore()
        namespace = "slice4.acceptance"
        account = "slice4.signed-app"
        canary = secrets.token_hex(32)
        store.delete(namespace, account)
        store.set(namespace, account, canary)
        if store.get(namespace, account) != canary:
            raise RuntimeError("Synthetic Keychain verification failed")
        store.delete(namespace, account)
        if store.get(namespace, account) is not None:
            raise RuntimeError("Synthetic Keychain cleanup failed")
        print("MONEY_MAP_KEYCHAIN_TEST PASS", flush=True)
    delay_ms = min(
        max(int(os.environ.get("PAYCHECK_MAP_DESKTOP_STARTUP_DELAY_MS", "0")), 0), 30_000
    )
    if delay_ms:
        time.sleep(delay_ms / 1000)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    with WriterLock(root):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        install_bootstrap(session, port)
        print(f"MONEY_MAP_READY {port}", flush=True)
        config = uvicorn.Config(
            "paycheck_map.desktop_app:desktop_app",
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
            limit_concurrency=32,
            timeout_keep_alive=2,
            h11_max_incomplete_event_size=16_384,
        )
        server = uvicorn.Server(config)

        def await_shutdown() -> None:
            with control:
                for line in control:
                    if line.strip() == '{"command":"shutdown","contract":"money-map-control-v1"}':
                        server.should_exit = True
                        return

        def await_owner_exit() -> None:
            while _owner_is_alive(owner_pid):
                time.sleep(0.1)
            server.should_exit = True

        threading.Thread(target=await_shutdown, name="desktop-shutdown", daemon=True).start()
        threading.Thread(target=await_owner_exit, name="desktop-owner", daemon=True).start()
        events.emit("MM-DESKTOP-READY", "lifecycle")
        server.run(sockets=[listener])
        events.emit("MM-DESKTOP-STOP", "lifecycle")
        clear_bootstrap()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("MONEY_MAP_FAILED", flush=True)
        raise SystemExit(1) from None
