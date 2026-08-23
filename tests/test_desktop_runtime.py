from __future__ import annotations

import importlib
import json
import os
import select
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from paycheck_map.config import Settings
from paycheck_map.desktop_lock import WriterLock, WriterLockConflict
from paycheck_map.keychain import MemorySecretStore


def test_runtime_inventory_is_complete_through_schema_head() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "desktop" / "runtime-resources.json").read_text())
    revisions = inventory["database"]["revisions"]
    assert revisions[-1] == "0009_goal_persistence"
    assert len(revisions) == 9
    assert {path.stem for path in (root / "alembic" / "versions").glob("*.py")} == set(revisions)
    modules = {
        ".".join(path.relative_to(root / "src").with_suffix("").parts)
        for path in (root / "src" / "paycheck_map").rglob("*.py")
    }
    assert set(inventory["python"]["modules"]) == modules
    assert inventory["contract"] == "money-map-desktop-runtime-v3"
    assert (root / "web" / "dist" / "index.html").is_file()


def test_synthetic_keychain_namespace_is_isolated() -> None:
    store = MemorySecretStore()
    store.set("slice1-synthetic", "account", "synthetic-secret")
    assert store.get("slice1-synthetic", "account") == "synthetic-secret"
    assert store.get("plaid", "account") is None
    store.delete("slice1-synthetic", "account")
    assert store.get("slice1-synthetic", "account") is None


def test_desktop_resources_never_fall_back_to_repository(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    (project / "alembic").mkdir(parents=True)
    (project / "web" / "dist").mkdir(parents=True)
    packaged = Settings(
        project_root=project,
        local_dir=tmp_path / "money-map-runtime-test" / "money-map-synthetic-data",
        desktop_mode=True,
    )
    assert project not in packaged.migration_dir.parents
    assert project not in packaged.web_dist_dir.parents
    assert project not in packaged.config_dir.parents


def test_sidecar_requires_strict_disposable_synthetic_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paycheck_map import desktop_sidecar

    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_DATA_MODE", "disposable-synthetic")
    monkeypatch.setenv("PAYCHECK_MAP_LOCAL_DIR", str(tmp_path / "not-approved"))
    with pytest.raises(RuntimeError, match="non-disposable"):
        desktop_sidecar._synthetic_root()
    monkeypatch.setenv(
        "PAYCHECK_MAP_LOCAL_DIR",
        str(tmp_path / "money-map-runtime-test" / "money-map-synthetic-data"),
    )
    assert desktop_sidecar._synthetic_root().name == "money-map-synthetic-data"
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_DATA_MODE", "production")
    with pytest.raises(RuntimeError, match="synthetic"):
        desktop_sidecar._synthetic_root()


def test_writer_lock_conflict_clean_release_and_stale_recovery(tmp_path: Path) -> None:
    root = tmp_path / "money-map-runtime-test" / "money-map-synthetic-data"
    root.mkdir(parents=True)
    first = WriterLock(root)
    first.acquire()
    lock_path = root / ".money-map-writer.lock"
    assert lock_path.is_file()
    lock_payload = json.loads(lock_path.read_text())
    assert lock_payload["contract"] == "money-map-desktop-writer-v1"
    assert set(lock_payload) == {"contract", "pid"}
    with pytest.raises(WriterLockConflict, match="already in use"):
        WriterLock(root).acquire()
    assert lock_path.is_file(), "a contender must never remove an active owner's lock"
    first.release()
    assert not lock_path.exists()

    lock_path.write_text('{"contract":"stale-synthetic-proof","pid":999999}')
    recovered = WriterLock(root)
    recovered.acquire()
    assert recovered.recovered_stale_file is True
    recovered.release()
    assert not lock_path.exists()


@contextmanager
def running_sidecar(
    root: Path, session: str = "a" * 64
) -> Iterator[tuple[subprocess.Popen[str], int]]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "PAYCHECK_MAP_DESKTOP_MODE": "true",
        "PAYCHECK_MAP_DESKTOP_DATA_MODE": "disposable-synthetic",
        "PAYCHECK_MAP_LOCAL_DIR": str(root),
        "PAYCHECK_MAP_DESKTOP_LOG_ROOT": str(root.parent / "logs"),
        "PAYCHECK_MAP_DESKTOP_TEST_PROJECT_ROOT": str(Path(__file__).resolve().parents[1]),
        "PAYCHECK_MAP_DESKTOP_OWNER_PID": str(os.getpid()),
    }
    bootstrap_read, bootstrap_write = os.pipe()
    control_read, control_write = os.pipe()
    environment["PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD"] = str(bootstrap_read)
    environment["PAYCHECK_MAP_DESKTOP_CONTROL_FD"] = str(control_read)

    process = subprocess.Popen(
        [sys.executable, "-m", "paycheck_map.desktop_sidecar"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        pass_fds=(bootstrap_read, control_read),
    )
    os.close(bootstrap_read)
    os.close(control_read)
    os.write(
        bootstrap_write,
        json.dumps(
            {"contract": "money-map-desktop-bootstrap-v1", "session": session},
            separators=(",", ":"),
        ).encode()
        + b"\n",
    )
    os.close(bootstrap_write)
    assert process.stdout is not None
    deadline = time.monotonic() + 15
    port: int | None = None
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if readable:
            line = process.stdout.readline().strip()
            if line.startswith("MONEY_MAP_READY "):
                port = int(line.rsplit(" ", 1)[1])
                break
        assert process.poll() is None, process.stdout.read()
    assert port is not None
    health_deadline = time.monotonic() + 10
    while time.monotonic() < health_deadline:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/api/desktop/health",
                headers={"X-Money-Map-Session": session},
                timeout=0.25,
            )
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:
        raise AssertionError("The synthetic sidecar did not become healthy")
    try:
        yield process, port
    finally:
        if process.poll() is None:
            os.write(
                control_write,
                b'{"command":"shutdown","contract":"money-map-control-v1"}\n',
            )
            process.wait(timeout=5)
        os.close(control_write)


def test_cross_process_runtime_auth_writer_schema_and_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "money-map-runtime-integration" / "money-map-synthetic-data"
    with running_sidecar(root) as (process, port):
        assert port != 8765
        assert (root / ".money-map-writer.lock").is_file()
        base_url = f"http://127.0.0.1:{port}"
        unauthorized = httpx.get(f"{base_url}/api/desktop/health")
        assert unauthorized.status_code == 401
        assert "a" * 64 not in unauthorized.text
        trusted = httpx.get(
            f"{base_url}/api/desktop/health",
            headers={
                "X-Money-Map-Session": "a" * 64,
                "Origin": "http://tauri.localhost",
            },
        )
        assert trusted.status_code == 200
        assert trusted.json() == {"ready": True, "version": "2.1.0"}
        hostile = httpx.get(
            f"{base_url}/api/desktop/health",
            headers={
                "X-Money-Map-Session": "a" * 64,
                "Origin": "https://untrusted.invalid",
            },
        )
        assert hostile.status_code == 403
        wrong_host = httpx.get(
            f"{base_url}/api/desktop/health",
            headers={"Host": "localhost:43123", "X-Money-Map-Session": "a" * 64},
        )
        assert wrong_host.status_code == 400
        contender_environment = {
            "PATH": os.environ.get("PATH", ""),
            "LC_ALL": "C",
            "PAYCHECK_MAP_DESKTOP_MODE": "true",
            "PAYCHECK_MAP_DESKTOP_DATA_MODE": "disposable-synthetic",
            "PAYCHECK_MAP_LOCAL_DIR": str(root),
            "PAYCHECK_MAP_DESKTOP_LOG_ROOT": str(root.parent / "logs"),
            "PAYCHECK_MAP_DESKTOP_TEST_PROJECT_ROOT": str(Path(__file__).resolve().parents[1]),
            "PAYCHECK_MAP_DESKTOP_OWNER_PID": str(os.getpid()),
        }
        bootstrap_read, bootstrap_write = os.pipe()
        control_read, control_write = os.pipe()
        contender_environment["PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD"] = str(bootstrap_read)
        contender_environment["PAYCHECK_MAP_DESKTOP_CONTROL_FD"] = str(control_read)

        os.write(
            bootstrap_write,
            b'{"contract":"money-map-desktop-bootstrap-v1","session":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}\n',
        )
        os.close(bootstrap_write)
        contender = subprocess.run(
            [sys.executable, "-m", "paycheck_map.desktop_sidecar"],
            capture_output=True,
            text=True,
            env=contender_environment,
            pass_fds=(bootstrap_read, control_read),
            timeout=5,
            check=False,
        )
        os.close(bootstrap_read)
        os.close(control_read)
        os.close(control_write)
        assert contender.returncode == 1
        assert contender.stdout.strip() == "MONEY_MAP_FAILED"
        assert contender.stderr == ""
        assert process.poll() is None, "the rejected writer must not disturb the active owner"
        assert process.poll() is None
    assert not (root / ".money-map-writer.lock").exists()
    with socket.socket() as probe:
        probe.settimeout(0.25)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    database = root / "data" / "paycheck-map.sqlite3"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0009_goal_persistence",
        )


def test_sigterm_requests_graceful_sidecar_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "money-map-runtime-signal-integration" / "money-map-synthetic-data"
    with running_sidecar(root) as (process, _port):
        assert (root / ".money-map-writer.lock").is_file()
        process.terminate()
        assert process.wait(timeout=5) == 0
    assert not (root / ".money-map-writer.lock").exists()
    events = (root.parent / "logs/desktop-events.jsonl").read_text()
    assert '"code":"MM-DESKTOP-STOP"' in events


def test_desktop_python_boundary_rejects_method_path_size_and_redacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_MODE", "true")
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_DATA_MODE", "disposable-synthetic")
    monkeypatch.setenv(
        "PAYCHECK_MAP_LOCAL_DIR",
        str(tmp_path / "money-map-runtime-auth" / "money-map-synthetic-data"),
    )
    from paycheck_map.desktop_bootstrap import clear_bootstrap, install_bootstrap

    clear_bootstrap()
    install_bootstrap("a" * 64, 43123)
    import paycheck_map.desktop_app as module

    module = importlib.reload(module)
    transport = httpx.ASGITransport(app=module.desktop_app)

    async def exercise() -> None:
        headers = {"X-Money-Map-Session": "a" * 64}
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:43123"
        ) as client:
            method = await client.patch("/api/desktop/health", headers=headers)
            assert method.status_code == 405
            traversal = await client.get("/api/../private", headers=headers)
            assert traversal.status_code == 400
            oversized = await client.post(
                "/api/plaid/configure",
                headers={**headers, "Content-Type": "application/json"},
                content=b"x" * 1_048_577,
            )
            assert oversized.status_code == 413
            for response in (method, traversal, oversized):
                assert "a" * 64 not in response.text
                assert str(tmp_path) not in response.text

    import anyio

    anyio.run(exercise)
