from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import anyio
import pytest
from sqlalchemy.orm import Session
from starlette.types import Message, Scope

from paycheck_map.config import settings
from paycheck_map.desktop_app import DesktopSecurityMiddleware
from paycheck_map.desktop_bootstrap import clear_bootstrap, install_bootstrap
from paycheck_map.desktop_data_api import _call
from paycheck_map.goal_observation import (
    CompletedOperationState,
    SourceCurrentnessUpdate,
    coordinate_goal_observation,
)
from paycheck_map.goal_service import GoalCheckInTrigger
from paycheck_map.local_security import LocalSecurityMiddleware, RequestFailureMiddleware
from paycheck_map.models import ApplicationSetting
from paycheck_map.safe_events import SafeEventLog, record_failure
from paycheck_map.v2_contracts import GoalObservationResult


@pytest.mark.parametrize("failed_commit", [1, 2])
def test_commit_failure_cannot_claim_financial_operation_completed(
    migrated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failed_commit: int,
) -> None:
    session = migrated_session
    session.add(ApplicationSetting(key="failure-test-operation", value="saved"))
    commit = session.commit
    calls = 0

    def fail_commit() -> None:
        nonlocal calls
        calls += 1
        if calls == failed_commit:
            raise RuntimeError("PRIVATE-COMMIT-CANARY")
        commit()

    monkeypatch.setattr(session, "commit", fail_commit)

    def observe() -> GoalObservationResult:
        return coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            observed_on=date(2026, 9, 6),
            operation_state=CompletedOperationState.COMPLETE,
            source_updates=(SourceCurrentnessUpdate("manual_import", "complete", "test:1"),),
        )

    if failed_commit == 1:
        with pytest.raises(RuntimeError, match="PRIVATE-COMMIT-CANARY"):
            observe()
        assert session.get(ApplicationSetting, "failure-test-operation") is None
    else:
        result = observe()
        assert result.status == "unavailable"
        assert session.get(ApplicationSetting, "failure-test-operation") is not None


@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("phase", ["receive", "cancel", "send", "inner"])
def test_interrupted_requests_always_release_capacity(desktop: bool, phase: str) -> None:
    clear_bootstrap()
    install_bootstrap("a" * 64, 43123)
    port = 43123 if desktop else 8765
    path = "/api/desktop/health" if desktop and phase != "inner" else "/api/test"
    headers = [(b"host", f"127.0.0.1:{port}".encode())]
    if desktop:
        headers.append((b"x-money-map-session", b"a" * 64))
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": headers,
        "server": ("127.0.0.1", port),
        "scheme": "http",
    }

    async def receive() -> Message:
        if phase == "cancel":
            raise asyncio.CancelledError()
        if phase == "receive":
            raise OSError("PRIVATE-RECEIVE-CANARY")
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if phase == "send":
            raise OSError("PRIVATE-SEND-CANARY")

    async def inner(*args: object) -> None:
        if phase == "inner":
            raise OSError("PRIVATE-INNER-CANARY")
        await send({"type": "http.response.start", "status": 200})

    middleware = DesktopSecurityMiddleware(inner) if desktop else LocalSecurityMiddleware(inner)

    async def exercise() -> None:
        # More than the admission limit demonstrates that failures cannot exhaust the service.
        for _ in range(35):
            with pytest.raises(asyncio.CancelledError if phase == "cancel" else OSError):
                await middleware(scope, receive, send)
            assert middleware._active_requests == 0

    try:
        anyio.run(exercise)
    finally:
        clear_bootstrap()


def test_unexpected_api_failure_is_private_and_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "desktop_log_root", tmp_path / "logs")
    messages: list[Message] = []

    async def inner(*args: object) -> None:
        raise RuntimeError("PRIVATE-API-CANARY")

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        messages.append(message)

    async def exercise() -> None:
        await RequestFailureMiddleware(inner)({"type": "http"}, receive, send)

    anyio.run(exercise)
    assert messages[0]["status"] == 500
    event = json.loads((tmp_path / "logs" / "failure-events.jsonl").read_text())
    assert event["code"] == "MM-REQUEST-FAIL"
    assert any(frame.startswith("local_security.py:") for frame in event["frames"])
    assert "PRIVATE-API-CANARY" not in str(messages) + json.dumps(event) + caplog.text
    assert str(tmp_path) not in json.dumps(event)


def test_telemetry_failure_does_not_mask_original_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "desktop_log_root", tmp_path / "logs")

    def failed_log(*args: object) -> None:
        raise OSError("PRIVATE-LOG-CANARY")

    def operation() -> None:
        raise RuntimeError("PRIVATE-OPERATION-CANARY")

    monkeypatch.setattr(SafeEventLog, "emit", failed_log)
    with pytest.raises(HTTPException) as failure:
        _call(operation)
    assert failure.value.status_code == 500
    assert "MM-TELEMETRY-UNAVAILABLE" in caplog.text
    assert "PRIVATE-" not in caplog.text + str(failure.value.detail)


def test_repeated_failures_remain_distinct_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "desktop_log_root", tmp_path / "logs")
    for _ in range(3):
        record_failure("MM-SYNC-FAIL", "data_integrity", ValueError("PRIVATE-CANARY"))
    path = tmp_path / "logs" / "failure-events.jsonl"
    assert len(path.read_text().splitlines()) == 3
    assert "PRIVATE-CANARY" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_keychain_delete_failure_is_not_missing_secret_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from keyring.errors import PasswordDeleteError

    from paycheck_map.keychain import MacOSKeychainSecretStore, SecretStoreError

    monkeypatch.setattr("keyring.get_password", lambda *args: "synthetic-secret")

    def reject_delete(*args: object) -> None:
        raise PasswordDeleteError("PRIVATE-KEYCHAIN-CANARY")

    monkeypatch.setattr("keyring.delete_password", reject_delete)
    store = MacOSKeychainSecretStore()
    with pytest.raises(SecretStoreError, match="could not delete") as error:
        store.delete("test", "synthetic")
    assert "PRIVATE-KEYCHAIN-CANARY" not in str(error.value)
    monkeypatch.setattr("keyring.get_password", lambda *args: None)
    store.delete("test", "synthetic")


def test_embedded_migrations_preserve_application_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'synthetic.sqlite3'}")
    logger = logging.getLogger("paycheck_map.failures")
    handlers = list(logging.getLogger().handlers)
    command.upgrade(config, "head")
    assert logging.getLogger().handlers == handlers
    assert not logger.disabled
    record_failure("MM-SYNC-FAIL", "data_integrity")
    assert "MM-SYNC-FAIL" in caplog.text


@pytest.mark.parametrize("ready", [True, False])
def test_diagnostics_distinguish_failed_checks_from_unavailable(
    ready: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from paycheck_map import desktop_data_api

    manager = MagicMock()
    manager.status.return_value = {"ready": ready}
    manager.list_backups.return_value = []
    monkeypatch.setattr(desktop_data_api, "data_home_manager", lambda: manager)
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.exec_driver_sql.return_value.scalar_one.return_value = "corrupt"
    connection.exec_driver_sql.return_value.fetchall.return_value = [("broken relationship",)]
    monkeypatch.setattr(desktop_data_api, "engine", engine)
    result = desktop_data_api._diagnostics()
    expected = "fail" if ready else "unavailable"
    assert result["database_checks"] == {"integrity": expected, "foreign_keys": expected}
    if not ready:
        engine.connect.assert_not_called()


@pytest.mark.parametrize("hardlink", [False, True])
def test_safe_log_rejects_link_substitution(tmp_path: Path, hardlink: bool) -> None:
    import os

    root = tmp_path / "logs"
    root.mkdir()
    target = tmp_path / "untouched"
    target.write_text("PRIVATE-CANARY")
    if hardlink:
        os.link(target, root / "desktop-events.jsonl")
    else:
        (root / "desktop-events.jsonl").symlink_to(target)
    with pytest.raises((OSError, RuntimeError)):
        SafeEventLog(root).emit("MM-DESKTOP-FAIL", "lifecycle")
    assert target.read_text() == "PRIVATE-CANARY"


def test_packaged_relative_tracebacks_keep_only_source_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "desktop_log_root", tmp_path / "logs")
    try:
        exec(
            compile(
                'raise RuntimeError("PRIVATE-PACKAGED-CANARY")', "paycheck_map/refresh.py", "exec"
            )
        )
    except RuntimeError as error:
        record_failure("MM-SYNC-FAIL", "data_integrity", error)
    text = (tmp_path / "logs" / "failure-events.jsonl").read_text()
    assert json.loads(text)["frames"] == ["refresh.py:1"]
    assert "PRIVATE-PACKAGED-CANARY" not in text
