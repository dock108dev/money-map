from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from paycheck_map.api import get_secret_store
from paycheck_map.config import Settings, settings
from paycheck_map.ingestion import import_private_inbox
from paycheck_map.keychain import MemorySecretStore
from paycheck_map.reporting import REPORT_ID, approved_report, generate_trailing_report


def test_generated_report_uses_an_opaque_identity_and_approved_private_file(
    migrated_session: Session,
    runtime_settings: Settings,
    populated_inbox: Path,
) -> None:
    del populated_inbox
    import_private_inbox(migrated_session, runtime_settings)
    report = generate_trailing_report(migrated_session, runtime_settings)
    assert report.name == "trailing-12-month-money-map.html"
    assert report.stat().st_mode & 0o777 == 0o600
    assert approved_report(REPORT_ID, runtime_settings) == report
    with pytest.raises(ValueError, match="unavailable"):
        approved_report("../private", runtime_settings)

    report.unlink()
    report.symlink_to(runtime_settings.database_path)
    with pytest.raises(ValueError, match="unavailable"):
        approved_report(REPORT_ID, runtime_settings)


def test_diagnostics_backend_is_a_strict_financial_data_free_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paycheck_map import desktop_data_api

    class Manager:
        @staticmethod
        def status() -> dict[str, object]:
            return {
                "phase": "already_migrated",
                "ready": True,
                "schema_revision": "0009_goal_persistence",
                "account_name": "forbidden synthetic account",
            }

        @staticmethod
        def list_backups() -> list[dict[str, object]]:
            return [{"verified": True, "filename": "forbidden-private-name.sqlite3"}]

    class Result:
        def __init__(self, query: str) -> None:
            self.query = query

        def scalar_one(self) -> str:
            return "ok"

        def fetchall(self) -> list[object]:
            return []

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @staticmethod
        def exec_driver_sql(query: str) -> Result:
            return Result(query)

    class Engine:
        @staticmethod
        def connect() -> Connection:
            return Connection()

    monkeypatch.setattr(desktop_data_api, "data_home_manager", lambda: Manager())
    monkeypatch.setattr(desktop_data_api, "engine", Engine())
    payload = desktop_data_api.diagnostics()
    assert set(payload) == {
        "schema_revision",
        "data_home_phase",
        "backup_verification",
        "database_checks",
    }
    encoded = json.dumps(payload).lower()
    for forbidden in (
        "account_name",
        "synthetic account",
        "filename",
        ".sqlite3",
        "balance",
        "transaction",
        "token",
        "port",
        "path",
    ):
        assert forbidden not in encoded


def test_synthetic_desktop_acceptance_never_reads_the_macos_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_data_mode", "acceptance-synthetic-v1")

    assert isinstance(get_secret_store(), MemorySecretStore)
