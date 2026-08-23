"""Frozen, argument-free Apple Silicon desktop sidecar entrypoint."""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any, TextIO

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


def _read_bootstrap() -> dict[str, Any]:
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
        or set(value)
        != {"attestation", "candidate_artifact", "candidate_commit", "contract", "session"}
        or value.get("contract") != BOOTSTRAP_CONTRACT
        or not isinstance(value.get("session"), str)
    ):
        raise RuntimeError("Desktop bootstrap was rejected")
    session = str(value["session"])
    if len(session) != 64 or any(character not in "0123456789abcdef" for character in session):
        raise RuntimeError("Desktop bootstrap was rejected")
    attestation = value.get("attestation")
    if attestation is not None and (not isinstance(attestation, dict) or len(attestation) != 12):
        raise RuntimeError("Desktop bootstrap was rejected")
    candidate_commit = value.get("candidate_commit")
    candidate_artifact = value.get("candidate_artifact")
    if (
        not isinstance(candidate_commit, str)
        or (
            candidate_commit != "development"
            and (
                len(candidate_commit) != 40
                or any(character not in "0123456789abcdef" for character in candidate_commit)
            )
        )
        or (candidate_artifact is not None and not isinstance(candidate_artifact, str))
    ):
        raise RuntimeError("Desktop bootstrap was rejected")
    return {
        "session": session,
        "attestation": attestation,
        "candidate_commit": candidate_commit,
        "candidate_artifact": candidate_artifact,
    }


def _resource_facts(
    path: Path, campaign: Path, kind: str, *, active: bool | None = None
) -> dict[str, object]:
    canonical = path.resolve(strict=True)
    symlink_free = all(
        not parent.is_symlink() for parent in (path, *path.parents) if parent.exists()
    )
    metadata = canonical.stat(follow_symlinks=False)
    facts: dict[str, object] = {
        "exists": True,
        "kind": kind,
        "symlink_free": symlink_free,
        "contained": canonical.is_relative_to(campaign),
        "active": active,
        "permissions_mode": stat.S_IMODE(metadata.st_mode),
        "owned_by_current_user": metadata.st_uid == os.geteuid(),
        "single_link": metadata.st_nlink == 1,
    }
    return facts


def _attestation_record(
    spec: dict[str, Any], session: str, connection: sqlite3.Connection
) -> dict[str, object]:
    required = {
        "contract",
        "schema_version",
        "campaign_id",
        "nonce",
        "generation",
        "mode",
        "campaign_root",
        "application_root",
        "database_path",
        "writer_lock_path",
        "cache_root",
        "log_root",
    }
    if set(spec) != required or spec.get("mode") != "acceptance-synthetic-v1":
        raise RuntimeError("Desktop attestation bootstrap was rejected")
    campaign = Path(str(spec["campaign_root"])).resolve(strict=True)
    identity_before = database_identity = None
    rows = connection.execute("PRAGMA database_list").fetchall()
    main_rows = [row for row in rows if row[1] == "main"]
    if len(main_rows) != 1 or not main_rows[0][2]:
        raise RuntimeError("Desktop SQLite identity was unavailable")
    actual_database = Path(str(main_rows[0][2])).resolve(strict=True)
    expected_database = Path(str(spec["database_path"])).resolve(strict=True)
    if actual_database != expected_database:
        raise RuntimeError("Desktop SQLite identity was rejected")
    metadata = actual_database.stat(follow_symlinks=False)
    identity_before = (metadata.st_dev, metadata.st_ino)
    versions = connection.execute(
        "SELECT version_num FROM alembic_version ORDER BY version_num"
    ).fetchall()
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    rows_after = connection.execute("PRAGMA database_list").fetchall()
    main_after = [row for row in rows_after if row[1] == "main"]
    if len(main_after) == 1 and main_after[0][2]:
        after_path = Path(str(main_after[0][2])).resolve(strict=True)
        after_metadata = after_path.stat(follow_symlinks=False)
        database_identity = (after_metadata.st_dev, after_metadata.st_ino)
    application = Path(str(spec["application_root"])).resolve(strict=True)
    writer_lock = Path(str(spec["writer_lock_path"])).resolve(strict=True)
    cache = Path(str(spec["cache_root"])).resolve(strict=True)
    logs = Path(str(spec["log_root"])).resolve(strict=True)
    return {
        "contract": spec["contract"],
        "schema_version": spec["schema_version"],
        "campaign_id": spec["campaign_id"],
        "nonce": spec["nonce"],
        "generation": spec["generation"],
        "session": session,
        "mode": spec["mode"],
        "campaign_root": str(campaign),
        "application_root": str(application),
        "database_path": str(actual_database),
        "writer_lock_path": str(writer_lock),
        "cache_root": str(cache),
        "log_root": str(logs),
        "database": _resource_facts(actual_database, campaign, "file"),
        "writer_lock": _resource_facts(writer_lock, campaign, "file", active=True),
        "cache": _resource_facts(cache, campaign, "directory"),
        "logs": _resource_facts(logs, campaign, "directory"),
        "schema_revision": str(versions[0][0]) if len(versions) == 1 else "unavailable",
        "integrity": integrity == [("ok",)],
        "foreign_keys": not foreign_keys,
        "database_identity_stable": identity_before == database_identity,
        "engine_database_identity": actual_database == expected_database,
        "sequence": 1,
    }


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
    bootstrap = _read_bootstrap()
    session = str(bootstrap["session"])
    attestation_spec = bootstrap["attestation"]
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
        attestation_connection: Any | None = None
        if attestation_spec is not None:
            cache_root = Path(str(attestation_spec["cache_root"]))
            cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            Path(log_root).mkdir(mode=0o700, parents=True, exist_ok=True)
            from paycheck_map.data_home import Phase
            from paycheck_map.db import engine
            from paycheck_map.desktop_data_api import data_home_manager

            manager = data_home_manager()
            status = manager.prepare()
            if status.get("phase") == Phase.FRESH_SETUP_AVAILABLE:
                status = manager.fresh_setup()
            if not status.get("ready") or status.get("schema_revision") != "0009_goal_persistence":
                raise RuntimeError("Desktop synthetic database was not ready for attestation")
            attestation_connection = engine.connect()
            driver = attestation_connection.connection.driver_connection
            if not isinstance(driver, sqlite3.Connection):
                raise RuntimeError("Desktop SQLite engine identity was unavailable")
            record = _attestation_record(attestation_spec, session, driver)
            print(
                "MONEY_MAP_ATTEST " + json.dumps(record, sort_keys=True, separators=(",", ":")),
                flush=True,
            )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        install_bootstrap(
            session,
            port,
            str(bootstrap["candidate_commit"]),
            str(bootstrap["candidate_artifact"])
            if bootstrap["candidate_artifact"] is not None
            else None,
        )
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

        def request_graceful_shutdown(_signal: int, _frame: object) -> None:
            server.should_exit = True

        signal.signal(signal.SIGTERM, request_graceful_shutdown)

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
        if attestation_connection is not None:
            attestation_connection.close()
        events.emit("MM-DESKTOP-STOP", "lifecycle")
        clear_bootstrap()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("MONEY_MAP_FAILED", flush=True)
        raise SystemExit(1) from None
