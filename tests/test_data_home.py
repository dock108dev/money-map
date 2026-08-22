from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from alembic import command
from paycheck_map.data_home import (
    PATH_CONTRACT,
    SCHEMA_HEAD,
    DataHomeError,
    DataHomeManager,
    DataHomePaths,
    InjectedFailure,
    Phase,
    online_backup,
    verify_database,
)
from paycheck_map.logical_manifest import build_logical_manifest, logical_tables

from .conftest import PROJECT_ROOT
from .v2_migration_support import materialize_state, migration_config, synthetic_states


def _paths(tmp_path: Path) -> DataHomePaths:
    home = tmp_path / "fake-home"
    return DataHomePaths(
        application=home / "Library" / "Application Support" / "Money Map",
        cache=home / "Library" / "Caches" / "com.moneymap.desktop",
        logs=home / "Library" / "Logs" / "Money Map",
        mode="acceptance-synthetic-v1",
    )


def _manager(
    tmp_path: Path,
    *,
    failure_at: str | None = None,
    available: int | None = None,
) -> DataHomeManager:
    def fail(phase: str) -> None:
        if phase == failure_at:
            raise InjectedFailure(phase)

    return DataHomeManager(
        _paths(tmp_path),
        migration_dir=PROJECT_ROOT / "alembic",
        repository_root=PROJECT_ROOT,
        failure_hook=fail if failure_at else None,
        available_space=(lambda _: available) if available is not None else None,
    )


def _source(tmp_path: Path, revision: str = SCHEMA_HEAD, *, populated: bool = False) -> Path:
    path = tmp_path / "explicit-synthetic-source" / "data" / "paycheck-map.sqlite3"
    path.parent.mkdir(parents=True)
    if populated:
        state = next(
            state for state in synthetic_states() if state["id"] == "one_enabled_goal_with_floor"
        )
        command.upgrade(migration_config(path), "0008_life_lab_v01")
        materialize_state(path, state)
        if revision == SCHEMA_HEAD:
            command.upgrade(migration_config(path), SCHEMA_HEAD)
    else:
        command.upgrade(migration_config(path), revision)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> tuple[int, int, int, str]:
    metadata = path.stat()
    return metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, _sha256(path)


def _tree(root: Path) -> list[tuple[str, int, int]]:
    if not root.exists():
        return []
    return [
        (str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
    ]


def test_macos_paths_are_central_private_versioned_and_distinct(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    paths.ensure_directories()

    assert paths.safe_contract()["contract"] == PATH_CONTRACT
    assert paths.database == paths.application / "data" / "paycheck-map.sqlite3"
    assert paths.inbox / "payroll" in [path for path in paths.inbox.iterdir()]
    assert paths.cache != paths.application
    assert paths.logs != paths.application
    for directory in (
        paths.application,
        paths.data,
        paths.inbox,
        paths.reports,
        paths.backups,
        paths.migration,
        paths.state,
        paths.cache,
        paths.logs,
    ):
        assert directory.stat().st_mode & 0o777 == 0o700


def test_path_contract_rejects_symlinks_overlap_and_nonproduction_shapes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.application.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir()
    paths.application.symlink_to(target, target_is_directory=True)
    with pytest.raises(DataHomeError, match="symbolic link"):
        paths.validate()

    with pytest.raises(DataHomeError, match="must differ"):
        DataHomePaths(
            application=tmp_path / "Money Map",
            cache=tmp_path / "Money Map",
            logs=tmp_path / "Money Map",
            mode="acceptance-synthetic-v1",
        ).validate()


def test_fresh_setup_uses_staging_then_atomically_activates_empty_head(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    result = manager.fresh_setup()

    assert result["phase"] == Phase.ACTIVATION_COMPLETE
    assert result["ready"] is True
    active = manager.paths.database
    verified = verify_database(active, expected_revision=SCHEMA_HEAD)
    assert verified.size > 0
    assert active.stat().st_mode & 0o777 == 0o600
    assert not list(manager.paths.migration.glob("*.staging.sqlite3"))
    with sqlite3.connect(f"file:{active.resolve()}?mode=ro", uri=True) as connection:
        for table in (
            "transactions",
            "imports",
            "goal_check_ins",
            "life_scenarios",
        ):
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (0,)


def test_preview_is_read_only_and_cancel_creates_no_operation_material(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.paths.ensure_directories()
    source = _source(tmp_path, populated=True)
    source_before = _identity(source)
    destination_before = _tree(manager.paths.application)

    first = manager.inspect_candidate(source)
    second = manager.inspect_candidate(source)

    assert first["schema_revision"] == SCHEMA_HEAD
    assert second["schema_revision"] == SCHEMA_HEAD
    assert first["confirmation_required"] is True
    assert _identity(source) == source_before
    assert _tree(manager.paths.application) == destination_before
    assert not manager.paths.journal.exists()


@pytest.mark.parametrize("revision", [SCHEMA_HEAD, "0008_life_lab_v01"])
def test_confirmed_migration_is_backup_first_staged_lossless_and_source_preserving(
    revision: str, tmp_path: Path
) -> None:
    manager = _manager(tmp_path)
    manager.paths.ensure_directories()
    source = _source(tmp_path, revision, populated=True)
    source_before = _identity(source)
    source_manifest = build_logical_manifest(source)
    preview = manager.inspect_candidate(source)

    result = manager.confirm_migration(preview["candidate_token"])

    assert result["phase"] == Phase.ACTIVATION_COMPLETE
    assert result["ready"] is True
    assert _identity(source) == source_before
    active = verify_database(manager.paths.database, expected_revision=SCHEMA_HEAD)
    assert active.size > 0
    backups = manager.list_backups()
    assert any(item["label"] == "migration-source" and item["verified"] for item in backups)
    migrated_existing = build_logical_manifest(
        manager.paths.database, include_tables=set(source_manifest["tables"])
    )
    assert logical_tables(migrated_existing) == logical_tables(source_manifest)
    if revision == SCHEMA_HEAD:
        assert active.manifest_digest == verify_database(source).manifest_digest


@pytest.mark.parametrize("revision", [SCHEMA_HEAD, "0008_life_lab_v01"])
def test_reopening_completed_migration_is_idempotent(revision: str, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.paths.ensure_directories()
    source = _source(tmp_path, revision, populated=True)
    preview = manager.inspect_candidate(source)
    manager.confirm_migration(preview["candidate_token"])
    before = _identity(manager.paths.database)
    counts_before = json.dumps(build_logical_manifest(manager.paths.database), sort_keys=True)

    preview = manager.inspect_candidate(source)
    repeated = manager.confirm_migration(preview["candidate_token"])

    assert repeated["phase"] == Phase.ALREADY_MIGRATED
    assert _identity(manager.paths.database) == before
    assert (
        json.dumps(build_logical_manifest(manager.paths.database), sort_keys=True) == counts_before
    )


def test_backup_and_restore_verify_manifest_and_retain_pre_restore_safety_copy(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.fresh_setup()
    first_backup = manager.create_backup()
    assert first_backup["ready"] is True
    assert first_backup["phase"] == Phase.BACKUP_VERIFIED
    active_before = verify_database(manager.paths.database)
    with sqlite3.connect(manager.paths.database) as connection:
        connection.execute(
            "INSERT INTO life_plan_profiles "
            "(birth_date, state, end_age, current_monthly_outflow, essential_monthly_spend, "
            "flexible_monthly_spend, cash_floor, retirement_tax_rate_pct, target_ages, notes, "
            "created_at, updated_at) "
            "VALUES ('1990-01-01', 'MA', 90, '1.00', '1.00', '0.00', '1.00', '20.0000', "
            "'[]', 'Synthetic restore delta', "
            "'2026-08-21T00:00:00+00:00', '2026-08-21T00:00:00+00:00')"
        )
    changed = verify_database(manager.paths.database)
    assert changed.manifest_digest != active_before.manifest_digest

    preview = manager.preview_restore(first_backup["backup_id"])
    result = manager.confirm_restore(first_backup["backup_id"])

    assert preview["replacement_warning"] == "Restore replaces the current Money Map database."
    assert result["phase"] == Phase.RESTORE_COMPLETE
    assert verify_database(manager.paths.database).manifest_digest == active_before.manifest_digest
    assert any(item["label"] == "pre-restore" for item in manager.list_backups())


def test_corrupt_unsupported_hard_link_symlink_and_insufficient_space_fail_closed(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.paths.ensure_directories()
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(DataHomeError, match="could not be verified"):
        manager.inspect_candidate(corrupt)

    unsupported = tmp_path / "unsupported.sqlite3"
    with sqlite3.connect(unsupported) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('9999_unknown')")
    with pytest.raises(DataHomeError, match="not supported"):
        manager.inspect_candidate(unsupported)

    source = _source(tmp_path, populated=True)
    symlink = tmp_path / "source-link.sqlite3"
    symlink.symlink_to(source)
    with pytest.raises(DataHomeError, match="symbolic link"):
        manager.inspect_candidate(symlink)

    manager.fresh_setup()
    hard_link = tmp_path / "active-hard-link.sqlite3"
    hard_link.hardlink_to(manager.paths.database)
    with pytest.raises(DataHomeError, match=r"rejected|itself"):
        manager.inspect_candidate(hard_link)

    low_space = _manager(tmp_path / "low-space", available=1)
    low_space.paths.ensure_directories()
    with pytest.raises(DataHomeError, match="disk space"):
        low_space.inspect_candidate(source)


@pytest.mark.parametrize(
    "phase",
    [
        "before_backup_creation",
        "during_backup",
        "after_backup_creation_before_verification",
        "after_backup_verification",
        "during_isolated_restore",
        "after_isolated_restore",
        "before_schema_migration",
        "during_schema_migration",
        "after_schema_migration",
        "during_logical_manifest_validation",
        "before_fsync",
        "before_activation_rename",
        "immediately_after_activation_rename",
        "before_journal_completion",
        "during_post_activation_verification",
    ],
)
def test_migration_failure_campaign_preserves_source_and_recovers_deterministically(
    phase: str, tmp_path: Path
) -> None:
    manager = _manager(tmp_path, failure_at=phase)
    manager.paths.ensure_directories()
    source = _source(tmp_path, "0008_life_lab_v01", populated=True)
    source_before = _identity(source)
    preview = manager.inspect_candidate(source)

    result = manager.confirm_migration(preview["candidate_token"])

    assert result["phase"] == Phase.RECOVERABLE_FAILURE
    assert _identity(source) == source_before
    restarted = _manager(tmp_path)
    recovery = restarted.prepare()
    assert recovery["phase"] in {
        Phase.ACTIVATION_COMPLETE,
        Phase.RESUME_AVAILABLE,
        Phase.RECOVERABLE_FAILURE,
    }
    if recovery["phase"] == Phase.RESUME_AVAILABLE:
        resumed = restarted.resume()
        assert resumed["phase"] == Phase.ACTIVATION_COMPLETE
    if restarted.paths.database.exists():
        verify_database(restarted.paths.database, expected_revision=SCHEMA_HEAD)
    assert _identity(source) == source_before


@pytest.mark.parametrize(
    "phase",
    ["before_source_inspection", "after_source_inspection", "before_preview_confirmation"],
)
def test_preview_failure_campaign_is_zero_write_and_source_preserving(
    phase: str, tmp_path: Path
) -> None:
    manager = _manager(tmp_path, failure_at=phase)
    manager.paths.ensure_directories()
    source = _source(tmp_path, populated=True)
    source_before = _identity(source)
    destination_before = _tree(manager.paths.application)

    with pytest.raises(InjectedFailure):
        manager.inspect_candidate(source)

    assert _identity(source) == source_before
    assert _tree(manager.paths.application) == destination_before
    assert not manager.paths.journal.exists()


@pytest.mark.parametrize(
    ("phase", "expected_recovery"),
    [
        ("between_replacement_steps", Phase.ROLLBACK_AVAILABLE),
        ("immediately_after_activation_rename", Phase.ACTIVATION_COMPLETE),
    ],
)
def test_replacement_interruption_keeps_exactly_one_recoverable_database(
    phase: str, expected_recovery: Phase, tmp_path: Path
) -> None:
    setup = _manager(tmp_path)
    setup.fresh_setup()
    accepted_before = verify_database(setup.paths.database)
    source = _source(tmp_path, populated=True)
    source_before = _identity(source)
    manager = _manager(tmp_path, failure_at=phase)
    preview = manager.inspect_candidate(source)

    result = manager.confirm_migration(preview["candidate_token"])

    assert result["phase"] == Phase.RECOVERABLE_FAILURE
    restarted = _manager(tmp_path)
    recovery = restarted.prepare()
    assert recovery["phase"] == expected_recovery
    if expected_recovery == Phase.ROLLBACK_AVAILABLE:
        rolled_back = restarted.rollback()
        assert rolled_back["rollback_available"] is False
        assert (
            verify_database(restarted.paths.database).manifest_digest
            == accepted_before.manifest_digest
        )
    else:
        verify_database(restarted.paths.database, expected_revision=SCHEMA_HEAD)
    assert _identity(source) == source_before


def test_restore_interruption_preserves_current_and_selected_backup(tmp_path: Path) -> None:
    setup = _manager(tmp_path)
    setup.fresh_setup()
    backup = setup.create_backup()
    active_before = _identity(setup.paths.database)
    backup_path = setup.backup_path(backup["backup_id"])
    backup_before = _identity(backup_path)
    manager = _manager(tmp_path, failure_at="during_restore")
    manager.preview_restore(backup["backup_id"])

    result = manager.confirm_restore(backup["backup_id"])

    assert result["phase"] == Phase.RECOVERABLE_FAILURE
    assert _identity(manager.paths.database) == active_before
    assert _identity(backup_path) == backup_before
    assert _manager(tmp_path).prepare()["phase"] == Phase.RECOVERABLE_FAILURE


def test_interrupted_rollback_remains_available_on_next_restart(tmp_path: Path) -> None:
    setup = _manager(tmp_path)
    setup.fresh_setup()
    source = _source(tmp_path, populated=True)
    interrupted = _manager(tmp_path, failure_at="between_replacement_steps")
    preview = interrupted.inspect_candidate(source)
    interrupted.confirm_migration(preview["candidate_token"])
    rollback_failure = _manager(tmp_path, failure_at="during_rollback")

    with pytest.raises(InjectedFailure):
        rollback_failure.rollback()

    assert _manager(tmp_path).prepare()["phase"] == Phase.ROLLBACK_AVAILABLE


def test_online_backup_rejects_identity_and_cleans_interrupted_output(tmp_path: Path) -> None:
    source = _source(tmp_path)
    hard_link = tmp_path / "hard-link.sqlite3"
    hard_link.hardlink_to(source)
    with pytest.raises(DataHomeError, match="distinct"):
        online_backup(source, hard_link)

    interrupted = tmp_path / "interrupted.sqlite3"
    with pytest.raises(InjectedFailure):
        online_backup(
            source,
            interrupted,
            fail_during=lambda: (_ for _ in ()).throw(InjectedFailure("during_backup")),
        )
    assert not interrupted.exists()


def test_journal_contains_only_safe_recovery_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path, failure_at="after_backup_verification")
    manager.paths.ensure_directories()
    source = _source(tmp_path, "0008_life_lab_v01", populated=True)
    preview = manager.inspect_candidate(source)
    manager.confirm_migration(preview["candidate_token"])

    journal = json.loads(manager.paths.journal.read_text())
    serialized = json.dumps(journal)
    assert str(source) not in serialized
    assert set(journal).isdisjoint({"rows", "transactions", "account_id", "token", "exception"})
    assert journal["operation_id"]
    assert journal["failure_code"] == "injected_failure"
