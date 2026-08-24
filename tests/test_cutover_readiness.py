from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from alembic import command
from paycheck_map.cutover_readiness import (
    OWNER_FIELDS,
    CutoverReadinessManager,
    ReadinessState,
    owner_worksheet,
    secure_file_identity,
    validate_owner_worksheet,
)
from paycheck_map.data_home import DataHomeError, DataHomeManager, DataHomePaths
from paycheck_map.product_metadata import SCHEMA_HEAD

from .conftest import PROJECT_ROOT
from .v2_migration_support import migration_config

COMMIT = "b51465476d4cd628ff58553df466c200a1ac565e"
REHEARSAL = hashlib.sha256(b"invented-synthetic-rehearsal").hexdigest()


def _paths(root: Path) -> DataHomePaths:
    return DataHomePaths(
        application=root / "Library/Application Support/Money Map",
        cache=root / "Library/Caches/com.moneymap.desktop",
        logs=root / "Library/Logs/Money Map",
        mode="acceptance-synthetic-v1",
    )


def _manager(root: Path, **kwargs: object) -> CutoverReadinessManager:
    data_home = DataHomeManager(
        _paths(root / "home"),
        migration_dir=PROJECT_ROOT / "alembic",
        **kwargs,  # type: ignore[arg-type]
    )
    return CutoverReadinessManager(data_home)


def _source(root: Path, revision: str = "0008_life_lab_v01") -> Path:
    database = root / f"invented-{revision}.sqlite3"
    command.upgrade(migration_config(database), revision)
    return database


def test_preflight_state_contract_is_complete_and_summary_is_allowlisted(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)

    summary = manager.inspect(source)

    assert summary["state"] == ReadinessState.ELIGIBLE_LEGACY_SOURCE
    assert summary["source"] == "Eligible legacy data"
    assert summary["schema"] == "Eligible legacy schema"
    assert summary["size"] in {"small", "medium", "large"}
    serialized = json.dumps(summary)
    assert str(tmp_path) not in serialized
    assert source.name not in serialized
    assert secure_file_identity(source).sha256 not in serialized
    assert {state.value for state in ReadinessState} == {
        "fresh_setup",
        "eligible_legacy_source",
        "current_0009_source",
        "unsupported_newer_source",
        "missing_or_unknown_revision",
        "integrity_failure",
        "foreign_key_failure",
        "required_table_failure",
        "source_unavailable",
        "read_only_source",
        "insufficient_destination_space",
        "unwritable_destination",
        "rehearsal_required",
        "rehearsal_in_progress",
        "rehearsal_passed",
        "confirmation_required",
        "activation_ready",
        "recoverable_interruption",
        "rollback_available",
        "completed_cutover",
    }


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("missing", ReadinessState.SOURCE_UNAVAILABLE),
        ("not_sqlite", ReadinessState.INTEGRITY_FAILURE),
        ("missing_revision", ReadinessState.REQUIRED_TABLE_FAILURE),
        ("unknown_revision", ReadinessState.UNKNOWN_REVISION),
        ("newer", ReadinessState.UNSUPPORTED_NEWER_SOURCE),
    ],
)
def test_preflight_classifies_rejected_sources(
    tmp_path: Path, setup: str, expected: ReadinessState
) -> None:
    manager = _manager(tmp_path)
    source = tmp_path / "invented.sqlite3"
    if setup == "not_sqlite":
        source.write_bytes(b"invented invalid sqlite")
    elif setup == "missing_revision":
        sqlite3.connect(source).close()
    elif setup in {"unknown_revision", "newer"}:
        with sqlite3.connect(source) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.execute(
                "INSERT INTO alembic_version VALUES (?)",
                ("invented_revision" if setup == "unknown_revision" else "0010_invented",),
            )

    summary = manager.inspect(source)

    assert summary["state"] == expected
    assert "failure_code" in summary
    assert str(tmp_path) not in json.dumps(summary)


def test_destination_space_and_fresh_destination_readiness(tmp_path: Path) -> None:
    manager = _manager(tmp_path, available_space=lambda _path: 0)
    source = _source(tmp_path)

    assert manager.fresh_summary()["state"] == ReadinessState.FRESH_SETUP
    assert manager.inspect(source)["state"] == ReadinessState.INSUFFICIENT_SPACE


def test_rehearsal_migrates_only_disposable_copy_and_preserves_original(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)
    before = secure_file_identity(source)
    manager.inspect(source)

    result = manager.rehearse()

    assert result["state"] == ReadinessState.REHEARSAL_PASSED
    assert secure_file_identity(source) == before
    assert not manager.data_home.paths.database.exists()
    assert not list(tmp_path.glob("**/money-map-cutover-*"))


def test_one_use_confirmation_binds_source_destination_backup_candidate_and_action(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)
    manager.inspect(source)
    prepared = manager.prepare_confirmation(
        rehearsal_commitment=REHEARSAL,
        candidate_commit=COMMIT,
        candidate_artifact_identity="invented-candidate",
    )

    result = manager.confirm(
        prepared["confirmation_token"],
        requested_action="activate_reviewed_source",
        candidate_commit=COMMIT,
        candidate_artifact_identity="invented-candidate",
        rehearsal_commitment=REHEARSAL,
    )

    assert result["state"] == ReadinessState.COMPLETED
    with pytest.raises(DataHomeError, match="confirm") as replay:
        manager.confirm(
            prepared["confirmation_token"],
            requested_action="activate_reviewed_source",
            candidate_commit=COMMIT,
            candidate_artifact_identity="invented-candidate",
            rehearsal_commitment=REHEARSAL,
        )
    assert replay.value.code == "confirmation_replay"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("candidate", "candidate_drift"),
        ("action", "wrong_action"),
        ("rehearsal", "rehearsal_drift"),
        ("source", "source_changed"),
        ("destination", "destination_drift"),
        ("backup", "backup_changed"),
    ],
)
def test_confirmation_rejects_drift(tmp_path: Path, change: str, code: str) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)
    manager.inspect(source)
    prepared = manager.prepare_confirmation(
        rehearsal_commitment=REHEARSAL,
        candidate_commit=COMMIT,
        candidate_artifact_identity="invented-candidate",
    )
    confirmation = manager._confirmation
    assert confirmation is not None
    if change == "source":
        with source.open("ab") as output:
            output.write(b"drift")
    elif change == "destination":
        manager.data_home.paths.data.mkdir(parents=True, exist_ok=True)
        manager.data_home.paths.database.write_bytes(b"drift")
    elif change == "backup":
        with confirmation.reviewed.backup_path.open("ab") as output:
            output.write(b"drift")

    with pytest.raises(DataHomeError) as rejected:
        manager.confirm(
            prepared["confirmation_token"],
            requested_action="wrong" if change == "action" else "activate_reviewed_source",
            candidate_commit="0" * 40 if change == "candidate" else COMMIT,
            candidate_artifact_identity="invented-candidate",
            rehearsal_commitment="0" * 64 if change == "rehearsal" else REHEARSAL,
        )
    assert rejected.value.code == code


def test_expired_confirmation_and_stale_preview_fail_closed(tmp_path: Path) -> None:
    clock = [100.0]
    manager = _manager(tmp_path)
    manager.now = lambda: clock[0]
    manager.inspect(_source(tmp_path))
    prepared = manager.prepare_confirmation(
        rehearsal_commitment=REHEARSAL,
        candidate_commit=COMMIT,
        candidate_artifact_identity=None,
    )
    clock[0] += 301

    with pytest.raises(DataHomeError) as rejected:
        manager.confirm(
            prepared["confirmation_token"],
            requested_action="activate_reviewed_source",
            candidate_commit=COMMIT,
            candidate_artifact_identity=None,
            rehearsal_commitment=REHEARSAL,
        )
    assert rejected.value.code == "confirmation_expired"


def test_symlink_hardlink_and_traversal_substitution_are_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)
    symlink = tmp_path / "link.sqlite3"
    symlink.symlink_to(source)
    hardlink = tmp_path / "hard.sqlite3"
    os.link(source, hardlink)

    assert manager.inspect(symlink)["state"] == ReadinessState.SOURCE_UNAVAILABLE
    assert manager.inspect(hardlink)["state"] == ReadinessState.SOURCE_UNAVAILABLE
    assert (
        manager.inspect(tmp_path / ".." / tmp_path.name / "missing.sqlite3")["state"]
        == ReadinessState.SOURCE_UNAVAILABLE
    )


def test_preview_and_cancel_write_nothing(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _source(tmp_path)
    before = secure_file_identity(source)

    manager.inspect(source)
    manager.cancel()

    assert secure_file_identity(source) == before
    assert not manager.data_home.paths.application.exists()


def test_owner_worksheet_fields_are_blank_and_cannot_be_synthesized() -> None:
    worksheet = owner_worksheet()
    checked_in = json.loads(
        (PROJECT_ROOT / "docs/v3/owner-cutover-worksheet.json").read_text(encoding="utf-8")
    )
    assert checked_in == worksheet
    assert set(worksheet["owner_responses"]) == set(OWNER_FIELDS)
    assert all(value is None for value in worksheet["owner_responses"].values())
    validate_owner_worksheet(worksheet)
    worksheet["owner_responses"]["cutover_acceptance"] = "accepted"
    with pytest.raises(DataHomeError) as rejected:
        validate_owner_worksheet(worksheet)
    assert rejected.value.code == "owner_response_prepopulated"


def test_schema_remains_0009_and_no_0010_exists() -> None:
    assert SCHEMA_HEAD == "0009_goal_persistence"
    assert not list((PROJECT_ROOT / "alembic/versions").glob("0010*.py"))
