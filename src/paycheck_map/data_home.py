"""Production macOS data-home, migration, backup, and recovery authority.

Only this module owns persistent desktop database activation.  It deliberately
keeps journals digest-only and operates exclusively on synthetic fixtures until
the separately authorized owner-cutover slice.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from alembic.config import Config

from alembic import command
from paycheck_map.logical_manifest import (
    build_logical_manifest,
    logical_tables,
    manifest_digest,
)

SCHEMA_HEAD = "0009_goal_persistence"
PATH_CONTRACT = "money-map-macos-data-home-v1"
JOURNAL_CONTRACT = "money-map-recovery-journal-v1"
BACKUP_CONTRACT = "money-map-verified-backup-v1"
SUPPORTED_REVISIONS = frozenset(
    {
        "0001_local_v01",
        "0002_plaid_read_only",
        "0003_payroll_detail",
        "0004_completed_payroll_schedule",
        "0005_money_map_v1",
        "0006_daily_data_refresh",
        "0007_refresh_timestamp_integrity",
        "0008_life_lab_v01",
        SCHEMA_HEAD,
    }
)


class DataHomeError(RuntimeError):
    """A sanitized, owner-actionable data-home failure."""

    def __init__(self, code: str, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class InjectedFailure(DataHomeError):
    def __init__(self, phase: str) -> None:
        super().__init__(
            "injected_failure",
            "The synthetic acceptance interruption was recorded safely.",
            recoverable=True,
        )
        self.phase = phase


class Phase(StrEnum):
    FRESH_SETUP_AVAILABLE = "fresh_setup_available"
    CANDIDATE_SELECTED = "candidate_selected"
    SOURCE_INSPECTION = "source_inspection"
    PREVIEW_READY = "preview_ready"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BACKUP_IN_PROGRESS = "backup_in_progress"
    BACKUP_VERIFIED = "backup_verified"
    STAGING_COPY = "staging_copy_in_progress"
    STAGING_VALIDATION = "staging_validation"
    SCHEMA_MIGRATION = "schema_migration_in_progress"
    MANIFEST_VALIDATION = "logical_manifest_validation"
    ACTIVATION_PENDING = "activation_pending"
    ACTIVATION_COMPLETE = "activation_complete"
    ALREADY_MIGRATED = "already_migrated"
    RECOVERABLE_FAILURE = "recoverable_failure"
    RESUME_AVAILABLE = "resume_available"
    ROLLBACK_AVAILABLE = "rollback_available"
    RESTORE_PREVIEW = "restore_preview"
    RESTORE_IN_PROGRESS = "restore_in_progress"
    RESTORE_COMPLETE = "restore_complete"


@dataclass(frozen=True)
class DataHomePaths:
    application: Path
    cache: Path
    logs: Path
    mode: str

    @property
    def data(self) -> Path:
        return self.application / "data"

    @property
    def database(self) -> Path:
        return self.data / "paycheck-map.sqlite3"

    @property
    def inbox(self) -> Path:
        return self.application / "inbox"

    @property
    def reports(self) -> Path:
        return self.application / "reports"

    @property
    def backups(self) -> Path:
        return self.application / "backups"

    @property
    def migration(self) -> Path:
        return self.application / "migration"

    @property
    def state(self) -> Path:
        return self.application / "state"

    @property
    def journal(self) -> Path:
        return self.state / "recovery-journal.json"

    @property
    def backup_catalog(self) -> Path:
        return self.state / "backup-catalog.json"

    @classmethod
    def from_trusted_environment(cls) -> DataHomePaths:
        required = {
            "application": os.environ.get("PAYCHECK_MAP_DESKTOP_APP_ROOT"),
            "cache": os.environ.get("PAYCHECK_MAP_DESKTOP_CACHE_ROOT"),
            "logs": os.environ.get("PAYCHECK_MAP_DESKTOP_LOG_ROOT"),
            "mode": os.environ.get("PAYCHECK_MAP_DESKTOP_DATA_MODE"),
        }
        if not all(required.values()):
            raise DataHomeError("path_configuration", "The private data location is unavailable.")
        paths = cls(
            application=Path(str(required["application"])),
            cache=Path(str(required["cache"])),
            logs=Path(str(required["logs"])),
            mode=str(required["mode"]),
        )
        paths.validate()
        return paths

    def validate(self) -> None:
        if self.mode not in {"production-v1", "acceptance-synthetic-v1"}:
            raise DataHomeError("path_mode", "The private data location was rejected.")
        roots = (self.application, self.cache, self.logs)
        if any(not path.is_absolute() for path in roots):
            raise DataHomeError("path_absolute", "The private data location was rejected.")
        normalized = [Path(os.path.abspath(path)) for path in roots]
        if len(set(normalized)) != len(normalized):
            raise DataHomeError(
                "path_overlap", "Private data, cache, and log locations must differ."
            )
        if self.application.name != "Money Map":
            raise DataHomeError("path_application", "The private data location was rejected.")
        if self.cache.name != "com.moneymap.desktop" or self.logs.name != "Money Map":
            raise DataHomeError("path_auxiliary", "The cache or log location was rejected.")
        for root in roots:
            _reject_existing_symlink_chain(root)
        if _paths_related(self.application, self.cache) or _paths_related(
            self.application, self.logs
        ):
            raise DataHomeError("path_relationship", "Private data locations must remain separate.")

    def ensure_directories(self) -> None:
        self.validate()
        directories = (
            self.application,
            self.data,
            self.inbox,
            self.inbox / "payroll",
            self.inbox / "sofi",
            self.inbox / "fidelity",
            self.reports,
            self.backups,
            self.migration,
            self.state,
            self.cache,
            self.logs,
        )
        for directory in directories:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise DataHomeError("unsafe_directory", "A private data directory was rejected.")
            directory.chmod(0o700)

    def safe_contract(self) -> dict[str, str]:
        return {
            "contract": PATH_CONTRACT,
            "application": "Application Support / Money Map",
            "data": "Application Support / Money Map / data",
            "inbox": "Application Support / Money Map / inbox",
            "reports": "Application Support / Money Map / reports",
            "backups": "Application Support / Money Map / backups",
            "migration": "Application Support / Money Map / migration",
            "state": "Application Support / Money Map / state",
            "cache": "Money Map cache",
            "logs": "Money Map diagnostic logs",
        }


@dataclass(frozen=True)
class DatabaseVerification:
    revision: str
    size: int
    sha256: str
    manifest_digest: str
    table_count: int


@dataclass
class Candidate:
    token: str
    path: Path
    verification: DatabaseVerification
    required_space: int
    classification: str = "selected existing Money Map data"

    def preview(self) -> dict[str, Any]:
        return {
            "candidate_token": self.token,
            "phase": Phase.CONFIRMATION_REQUIRED,
            "source_classification": self.classification,
            "destination_classification": "Money Map private application data",
            "schema_revision": self.verification.revision,
            "size": self.verification.size,
            "required_space": self.required_space,
            "backup_required": True,
            "source_is_read_only": True,
            "confirmation_required": True,
        }


FailureHook = Callable[[str], None]


class DataHomeManager:
    """Serial data-home state machine protected by the desktop writer lock."""

    def __init__(
        self,
        paths: DataHomePaths,
        *,
        migration_dir: Path,
        bundle_root: Path | None = None,
        repository_root: Path | None = None,
        failure_hook: FailureHook | None = None,
        available_space: Callable[[Path], int] | None = None,
    ) -> None:
        paths.validate()
        self.paths = paths
        self.migration_dir = migration_dir.resolve()
        self.bundle_root = bundle_root.resolve() if bundle_root else None
        self.repository_root = repository_root.resolve() if repository_root else None
        self.failure_hook = failure_hook
        self.available_space = available_space or (lambda path: shutil.disk_usage(path).free)
        self._candidate: Candidate | None = None
        self._restore_preview: dict[str, Any] | None = None

    def prepare(self) -> dict[str, Any]:
        self.paths.ensure_directories()
        recovery = self.recover()
        return recovery or self.status()

    def status(self) -> dict[str, Any]:
        journal = self._read_journal()
        if journal:
            if journal.get("completed"):
                try:
                    verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
                except DataHomeError as error:
                    return self._failure(error)
            return self._public_journal(journal)
        if self.paths.database.exists():
            try:
                verification = verify_database(self.paths.database)
            except DataHomeError as error:
                return self._failure(error)
            return {
                "phase": Phase.ALREADY_MIGRATED,
                "ready": verification.revision == SCHEMA_HEAD,
                "schema_revision": verification.revision,
                "paths": self.paths.safe_contract(),
                "backup_count": len(self._catalog()),
            }
        return {
            "phase": Phase.FRESH_SETUP_AVAILABLE,
            "ready": False,
            "paths": self.paths.safe_contract(),
            "backup_count": len(self._catalog()),
        }

    def fresh_setup(self) -> dict[str, Any]:
        self.paths.ensure_directories()
        if self.paths.database.exists():
            return self.status()
        operation_id = _operation_id()
        staging_name = f"fresh-{operation_id}.staging.sqlite3"
        staging = self.paths.migration / staging_name
        journal = self._new_journal("fresh_setup", operation_id, staging_name=staging_name)
        try:
            self._phase(journal, Phase.STAGING_COPY)
            self._inject("before_fresh_staging")
            _upgrade(staging, self.migration_dir)
            self._inject("after_fresh_staging")
            self._phase(journal, Phase.STAGING_VALIDATION)
            verification = verify_database(staging, expected_revision=SCHEMA_HEAD)
            journal["expected_active_digest"] = verification.sha256
            journal["logical_manifest_digest"] = verification.manifest_digest
            self._activate_new(staging, journal)
            return self._complete(journal, Phase.ACTIVATION_COMPLETE)
        except Exception as error:
            return self._record_failure(journal, error)

    def inspect_candidate(self, selected: Path) -> dict[str, Any]:
        self._inject("before_source_inspection")
        path = self._resolve_candidate(selected)
        before = _file_identity(path)
        verification = verify_database(path)
        after = _file_identity(path)
        if before != after:
            raise DataHomeError("source_changed", "The selected source changed during preview.")
        if verification.revision not in SUPPORTED_REVISIONS:
            raise DataHomeError(
                "unsupported_revision", "This Money Map data version is not supported."
            )
        required = max(verification.size * 4, verification.size + 16 * 1024 * 1024)
        if self.available_space(self.paths.application) < required:
            raise DataHomeError(
                "insufficient_space", "More disk space is required before migration."
            )
        candidate = Candidate(
            token=secrets.token_urlsafe(24),
            path=path,
            verification=verification,
            required_space=required,
        )
        self._candidate = candidate
        self._inject("after_source_inspection")
        self._inject("before_preview_confirmation")
        return candidate.preview()

    def confirm_migration(self, token: str) -> dict[str, Any]:
        candidate = self._candidate
        if candidate is None or not secrets.compare_digest(candidate.token, token):
            raise DataHomeError(
                "candidate_expired", "Choose the existing data again before importing."
            )
        prior = self._read_journal()
        if (
            prior
            and prior.get("completed")
            and prior.get("operation_kind") == "migration"
            and prior.get("source_digest") == candidate.verification.sha256
            and self.paths.database.is_file()
        ):
            verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
            return {
                "phase": Phase.ALREADY_MIGRATED,
                "ready": True,
                "schema_revision": SCHEMA_HEAD,
            }
        if self._destination_matches(candidate.verification.manifest_digest):
            return {
                "phase": Phase.ALREADY_MIGRATED,
                "ready": True,
                "schema_revision": SCHEMA_HEAD,
            }
        operation_id = _operation_id()
        backup_name = f"migration-source-{operation_id}.sqlite3"
        staging_name = f"migration-{operation_id}.staging.sqlite3"
        journal = self._new_journal(
            "migration",
            operation_id,
            source_revision=candidate.verification.revision,
            source_digest=candidate.verification.sha256,
            source_manifest_digest=candidate.verification.manifest_digest,
            backup_name=backup_name,
            staging_name=staging_name,
        )
        try:
            self._migrate(candidate, journal)
            self._candidate = None
            return self._complete(journal, Phase.ACTIVATION_COMPLETE)
        except Exception as error:
            return self._record_failure(journal, error)

    def create_backup(self, *, label: str = "manual") -> dict[str, Any]:
        if not self.paths.database.is_file():
            raise DataHomeError("no_active_database", "Set up Money Map before creating a backup.")
        operation_id = _operation_id()
        filename = f"paycheck-map-{label}-{operation_id}.sqlite3"
        destination = self.paths.backups / filename
        source_verification = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
        self._inject("before_backup_creation")
        backup = online_backup(
            self.paths.database,
            destination,
            fail_during=lambda: self._inject("during_backup"),
        )
        self._inject("after_backup_creation_before_verification")
        verified = verify_database(destination, expected_revision=SCHEMA_HEAD)
        if (
            verified.manifest_digest != source_verification.manifest_digest
            or verified.sha256 != backup.sha256
        ):
            raise DataHomeError(
                "backup_mismatch", "The backup did not verify and was not accepted."
            )
        self._inject("after_backup_verification")
        record = self._record_backup(filename, operation_id, verified, label)
        return {
            **record,
            "phase": Phase.BACKUP_VERIFIED,
            "ready": True,
            "schema_revision": SCHEMA_HEAD,
            "backup_count": len(self._catalog()),
        }

    def list_backups(self) -> list[dict[str, Any]]:
        return [self._public_backup(item) for item in self._catalog()]

    def backup_path(self, backup_id: str) -> Path:
        record = self._backup_record(backup_id)
        path = self._approved_artifact(self.paths.backups, str(record["filename"]))
        self._verify_catalog_record(path, record)
        return path

    def preview_restore(self, backup_id: str) -> dict[str, Any]:
        record = self._backup_record(backup_id)
        path = self.backup_path(backup_id)
        verification = verify_database(path, expected_revision=SCHEMA_HEAD)
        preview = {
            "phase": Phase.RESTORE_PREVIEW,
            "backup_id": backup_id,
            "backup_classification": "verified Money Map backup",
            "verified": True,
            "schema_revision": verification.revision,
            "created_at": record["created_at"],
            "size": verification.size,
            "destination_classification": "current Money Map database",
            "replacement_warning": "Restore replaces the current Money Map database.",
            "pre_restore_backup": True,
            "rollback_available": True,
            "confirmation_required": True,
        }
        self._restore_preview = preview
        return preview

    def confirm_restore(self, backup_id: str) -> dict[str, Any]:
        if self._restore_preview is None or self._restore_preview.get("backup_id") != backup_id:
            raise DataHomeError(
                "restore_preview_required", "Preview the backup again before restore."
            )
        selected = self.backup_path(backup_id)
        if not self.paths.database.is_file():
            raise DataHomeError("no_active_database", "There is no current database to replace.")
        operation_id = _operation_id()
        staging_name = f"restore-{operation_id}.staging.sqlite3"
        safety_name = f"pre-restore-{operation_id}.sqlite3"
        journal = self._new_journal(
            "restore",
            operation_id,
            backup_name=selected.name,
            staging_name=staging_name,
            safety_backup_name=safety_name,
        )
        try:
            self._phase(journal, Phase.RESTORE_IN_PROGRESS)
            selected_verification = verify_database(selected, expected_revision=SCHEMA_HEAD)
            safety = self.paths.backups / safety_name
            current = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
            online_backup(self.paths.database, safety)
            safety_verification = verify_database(safety, expected_revision=SCHEMA_HEAD)
            if safety_verification.manifest_digest != current.manifest_digest:
                raise DataHomeError(
                    "safety_backup_mismatch", "The current database remained active."
                )
            self._record_backup(safety.name, operation_id, safety_verification, "pre-restore")
            staging = self.paths.migration / staging_name
            online_backup(selected, staging, fail_during=lambda: self._inject("during_restore"))
            restored = verify_database(staging, expected_revision=SCHEMA_HEAD)
            if restored.manifest_digest != selected_verification.manifest_digest:
                raise DataHomeError("restore_mismatch", "The restore staging copy did not verify.")
            journal["expected_active_digest"] = restored.sha256
            journal["logical_manifest_digest"] = restored.manifest_digest
            self._replace_active(staging, journal)
            self._restore_preview = None
            return self._complete(journal, Phase.RESTORE_COMPLETE)
        except Exception as error:
            return self._record_failure(journal, error)

    def recover(self) -> dict[str, Any] | None:
        journal = self._read_journal()
        if not journal or journal.get("completed"):
            return None
        expected = journal.get("expected_active_digest")
        if expected and self.paths.database.is_file():
            try:
                active = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
                if active.sha256 == expected:
                    return self._complete(journal, self._completion_phase(journal))
            except DataHomeError:
                pass
        rollback = journal.get("rollback_name")
        if rollback:
            rollback_path = self._approved_artifact(self.paths.migration, str(rollback))
            if rollback_path.is_file():
                journal["phase"] = Phase.ROLLBACK_AVAILABLE
                journal["recoverable"] = True
                self._write_journal(journal)
                return self._public_journal(journal)
        staging_name = journal.get("staging_name")
        if staging_name:
            staging = self._approved_artifact(self.paths.migration, str(staging_name))
            if staging.is_file():
                try:
                    staged = verify_database(staging, expected_revision=SCHEMA_HEAD)
                    journal["expected_active_digest"] = staged.sha256
                    journal["logical_manifest_digest"] = staged.manifest_digest
                    journal["phase"] = Phase.RESUME_AVAILABLE
                    journal["recoverable"] = True
                    self._write_journal(journal)
                    return self._public_journal(journal)
                except DataHomeError:
                    pass
        journal["phase"] = Phase.RECOVERABLE_FAILURE
        journal["failure_code"] = "restart_requires_retry"
        journal["recoverable"] = True
        self._write_journal(journal)
        return self._public_journal(journal)

    def resume(self) -> dict[str, Any]:
        journal = self._read_journal()
        if not journal or journal.get("phase") != Phase.RESUME_AVAILABLE:
            raise DataHomeError("resume_unavailable", "There is no verified operation to resume.")
        staging = self._approved_artifact(self.paths.migration, str(journal["staging_name"]))
        verification = verify_database(staging, expected_revision=SCHEMA_HEAD)
        journal["expected_active_digest"] = verification.sha256
        try:
            if self.paths.database.exists():
                self._replace_active(staging, journal)
            else:
                self._activate_new(staging, journal)
            return self._complete(journal, self._completion_phase(journal))
        except Exception as error:
            return self._record_failure(journal, error)

    def rollback(self) -> dict[str, Any]:
        journal = self._read_journal()
        if not journal or not journal.get("rollback_name"):
            raise DataHomeError(
                "rollback_unavailable", "There is no accepted database to roll back."
            )
        self._inject("during_rollback")
        rollback = self._approved_artifact(self.paths.migration, str(journal["rollback_name"]))
        verification = verify_database(rollback, expected_revision=SCHEMA_HEAD)
        failed = self.paths.migration / f"failed-active-{journal['operation_id']}.sqlite3"
        if self.paths.database.exists():
            os.replace(self.paths.database, failed)
        os.replace(rollback, self.paths.database)
        _fsync_file(self.paths.database)
        _fsync_directory(self.paths.data)
        active = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
        if active.manifest_digest != verification.manifest_digest:
            raise DataHomeError("rollback_mismatch", "Rollback verification failed.")
        journal["completed"] = True
        journal["phase"] = Phase.ACTIVATION_COMPLETE
        journal["rolled_back"] = True
        journal["rollback_name"] = None
        journal["expected_active_digest"] = active.sha256
        journal["logical_manifest_digest"] = active.manifest_digest
        journal["completed_at"] = _now()
        self._write_journal(journal)
        return self._public_journal(journal)

    def _migrate(self, candidate: Candidate, journal: dict[str, Any]) -> None:
        source_before = _file_identity(candidate.path)
        source_manifest = build_logical_manifest(candidate.path)
        backup = self.paths.backups / str(journal["backup_name"])
        staging = self.paths.migration / str(journal["staging_name"])
        self._phase(journal, Phase.BACKUP_IN_PROGRESS)
        self._inject("before_backup_creation")
        online_backup(candidate.path, backup, fail_during=lambda: self._inject("during_backup"))
        self._inject("after_backup_creation_before_verification")
        backup_verification = verify_database(backup)
        if backup_verification.manifest_digest != candidate.verification.manifest_digest:
            raise DataHomeError("backup_manifest_mismatch", "The source backup did not verify.")
        self._inject("after_backup_verification")
        self._phase(journal, Phase.BACKUP_VERIFIED)
        self._record_backup(
            backup.name, str(journal["operation_id"]), backup_verification, "migration-source"
        )
        self._phase(journal, Phase.STAGING_COPY)
        online_backup(backup, staging, fail_during=lambda: self._inject("during_isolated_restore"))
        self._inject("after_isolated_restore")
        restored = verify_database(staging)
        if restored.manifest_digest != candidate.verification.manifest_digest:
            raise DataHomeError("staging_restore_mismatch", "The isolated restore did not verify.")
        preexisting_tables = set(source_manifest["tables"])
        if restored.revision != SCHEMA_HEAD:
            self._phase(journal, Phase.SCHEMA_MIGRATION)
            self._inject("before_schema_migration")
            self._inject("during_schema_migration")
            _upgrade(staging, self.migration_dir)
            self._inject("after_schema_migration")
        self._phase(journal, Phase.MANIFEST_VALIDATION)
        self._inject("during_logical_manifest_validation")
        staged = verify_database(staging, expected_revision=SCHEMA_HEAD)
        migrated_existing = build_logical_manifest(staging, include_tables=preexisting_tables)
        if logical_tables(migrated_existing) != logical_tables(source_manifest):
            raise DataHomeError(
                "logical_manifest_mismatch", "Existing Money Map data did not match."
            )
        journal["expected_active_digest"] = staged.sha256
        journal["logical_manifest_digest"] = staged.manifest_digest
        if self.paths.database.exists():
            self._replace_active(staging, journal)
        else:
            self._activate_new(staging, journal)
        if _file_identity(candidate.path) != source_before:
            raise DataHomeError("source_changed", "The original selected data changed.")

    def _activate_new(self, staging: Path, journal: dict[str, Any]) -> None:
        self._phase(journal, Phase.ACTIVATION_PENDING)
        self._inject("before_fsync")
        _fsync_file(staging)
        _fsync_directory(staging.parent)
        self._inject("before_activation_rename")
        if self.paths.database.exists():
            raise DataHomeError(
                "activation_conflict", "A current database appeared before activation."
            )
        os.replace(staging, self.paths.database)
        journal["activated"] = True
        self._write_journal(journal)
        self._inject("immediately_after_activation_rename")
        _fsync_directory(self.paths.data)
        self._post_activation(journal)

    def _replace_active(self, staging: Path, journal: dict[str, Any]) -> None:
        self._phase(journal, Phase.ACTIVATION_PENDING)
        active_verification = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
        safety_name = str(
            journal.get("safety_backup_name")
            or f"pre-replacement-{journal['operation_id']}.sqlite3"
        )
        safety = self.paths.backups / safety_name
        if not safety.exists():
            online_backup(self.paths.database, safety)
            safety_verification = verify_database(safety, expected_revision=SCHEMA_HEAD)
            if safety_verification.manifest_digest != active_verification.manifest_digest:
                raise DataHomeError(
                    "replacement_backup_mismatch", "The current database remained active."
                )
            self._record_backup(
                safety.name, str(journal["operation_id"]), safety_verification, "pre-replacement"
            )
        rollback_name = f"rollback-{journal['operation_id']}.sqlite3"
        rollback = self.paths.migration / rollback_name
        journal["rollback_name"] = rollback_name
        self._write_journal(journal)
        self._inject("before_fsync")
        _fsync_file(staging)
        _fsync_directory(staging.parent)
        self._inject("before_activation_rename")
        os.replace(self.paths.database, rollback)
        _fsync_directory(self.paths.data)
        self._inject("between_replacement_steps")
        os.replace(staging, self.paths.database)
        journal["activated"] = True
        self._write_journal(journal)
        self._inject("immediately_after_activation_rename")
        _fsync_directory(self.paths.data)
        self._post_activation(journal)

    def _post_activation(self, journal: dict[str, Any]) -> None:
        self._inject("during_post_activation_verification")
        active = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
        if active.sha256 != journal.get("expected_active_digest"):
            raise DataHomeError(
                "post_activation_mismatch", "Activation needs recovery.", recoverable=True
            )
        self._inject("before_journal_completion")

    def _resolve_candidate(self, selected: Path) -> Path:
        raw = selected.expanduser()
        _reject_existing_symlink_chain(raw)
        if raw.is_dir():
            raw = raw / "data" / "paycheck-map.sqlite3"
            _reject_existing_symlink_chain(raw)
        if raw.is_symlink() or not raw.is_file():
            raise DataHomeError(
                "source_missing", "The selected Money Map data could not be opened."
            )
        path = raw.resolve(strict=True)
        if path.suffix not in {".sqlite", ".sqlite3", ".db"}:
            raise DataHomeError("source_type", "Choose a Money Map database or data folder.")
        forbidden = [self.paths.application, self.paths.database]
        if self.bundle_root:
            forbidden.append(self.bundle_root)
        if self.repository_root:
            forbidden.append(self.repository_root)
        if any(_paths_related(path, root) for root in forbidden):
            raise DataHomeError("source_forbidden", "The selected source location was rejected.")
        if self.paths.database.exists() and os.path.samefile(path, self.paths.database):
            raise DataHomeError(
                "source_active", "The current database cannot be imported into itself."
            )
        return path

    def _destination_matches(self, source_manifest_digest: str) -> bool:
        if not self.paths.database.exists():
            return False
        try:
            current = verify_database(self.paths.database, expected_revision=SCHEMA_HEAD)
        except DataHomeError:
            return False
        return current.manifest_digest == source_manifest_digest

    def _phase(self, journal: dict[str, Any], phase: Phase) -> None:
        journal["phase"] = phase
        journal["updated_at"] = _now()
        self._write_journal(journal)

    def _inject(self, phase: str) -> None:
        if self.failure_hook:
            self.failure_hook(phase)

    def _new_journal(self, kind: str, operation_id: str, **values: Any) -> dict[str, Any]:
        journal: dict[str, Any] = {
            "contract": JOURNAL_CONTRACT,
            "operation_id": operation_id,
            "operation_kind": kind,
            "source_classification": "explicit synthetic selection"
            if kind == "migration"
            else None,
            "destination_classification": "Money Map private application data",
            "expected_schema_revision": SCHEMA_HEAD,
            "phase": Phase.CONFIRMATION_REQUIRED,
            "created_at": _now(),
            "updated_at": _now(),
            "activated": False,
            "completed": False,
            "recoverable": False,
            "failure_code": None,
        }
        journal.update(values)
        self._write_journal(journal)
        return journal

    def _complete(self, journal: dict[str, Any], phase: Phase) -> dict[str, Any]:
        journal["phase"] = phase
        journal["completed"] = True
        journal["recoverable"] = False
        journal["failure_code"] = None
        journal["completed_at"] = _now()
        journal["updated_at"] = _now()
        self._write_journal(journal)
        return self._public_journal(journal)

    def _record_failure(self, journal: dict[str, Any], error: Exception) -> dict[str, Any]:
        code = error.code if isinstance(error, DataHomeError) else "operation_interrupted"
        journal["phase"] = Phase.RECOVERABLE_FAILURE
        journal["failure_code"] = code
        journal["recoverable"] = True
        journal["updated_at"] = _now()
        self._write_journal(journal)
        return self._public_journal(journal)

    def _failure(self, error: DataHomeError) -> dict[str, Any]:
        return {
            "phase": Phase.RECOVERABLE_FAILURE,
            "ready": False,
            "failure_code": error.code,
            "recoverable": error.recoverable,
            "message": str(error),
        }

    def _read_journal(self) -> dict[str, Any] | None:
        if not self.paths.journal.exists():
            return None
        try:
            value = json.loads(self.paths.journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DataHomeError(
                "journal_invalid", "Recovery information could not be verified."
            ) from error
        if not isinstance(value, dict) or value.get("contract") != JOURNAL_CONTRACT:
            raise DataHomeError("journal_invalid", "Recovery information could not be verified.")
        return value

    def _write_journal(self, journal: Mapping[str, Any]) -> None:
        self.paths.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        _atomic_json(self.paths.journal, journal)

    def _catalog(self) -> list[dict[str, Any]]:
        if not self.paths.backup_catalog.exists():
            return []
        try:
            payload = json.loads(self.paths.backup_catalog.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DataHomeError(
                "catalog_invalid", "Backup status could not be verified."
            ) from error
        if not isinstance(payload, dict) or payload.get("contract") != BACKUP_CONTRACT:
            raise DataHomeError("catalog_invalid", "Backup status could not be verified.")
        records = payload.get("backups", [])
        if not isinstance(records, list):
            raise DataHomeError("catalog_invalid", "Backup status could not be verified.")
        return [item for item in records if isinstance(item, dict)]

    def _record_backup(
        self,
        filename: str,
        operation_id: str,
        verification: DatabaseVerification,
        label: str,
    ) -> dict[str, Any]:
        records = self._catalog()
        backup_id = hashlib.sha256(f"{operation_id}:{filename}".encode()).hexdigest()[:24]
        record = {
            "backup_id": backup_id,
            "filename": filename,
            "operation_id": operation_id,
            "label": label,
            "created_at": _now(),
            "schema_revision": verification.revision,
            "size": verification.size,
            "sha256": verification.sha256,
            "manifest_digest": verification.manifest_digest,
            "verified": True,
        }
        records = [item for item in records if item.get("backup_id") != backup_id]
        records.append(record)
        _atomic_json(
            self.paths.backup_catalog,
            {"contract": BACKUP_CONTRACT, "backups": records},
        )
        return self._public_backup(record)

    def _backup_record(self, backup_id: str) -> dict[str, Any]:
        if not backup_id or any(char not in "0123456789abcdef" for char in backup_id):
            raise DataHomeError("backup_selection", "The selected backup was rejected.")
        record = next(
            (item for item in self._catalog() if item.get("backup_id") == backup_id), None
        )
        if record is None:
            raise DataHomeError("backup_missing", "The selected backup is unavailable.")
        return record

    def _verify_catalog_record(self, path: Path, record: Mapping[str, Any]) -> None:
        verification = verify_database(path, expected_revision=SCHEMA_HEAD)
        if verification.sha256 != record.get(
            "sha256"
        ) or verification.manifest_digest != record.get("manifest_digest"):
            raise DataHomeError("backup_changed", "The selected backup no longer verifies.")
        if self.paths.database.exists() and os.path.samefile(path, self.paths.database):
            raise DataHomeError("backup_active", "The current database cannot be its own backup.")

    def _approved_artifact(self, root: Path, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise DataHomeError("artifact_path", "A recovery artifact path was rejected.")
        candidate = root / filename
        _reject_existing_symlink_chain(candidate)
        if candidate.is_symlink() or candidate.resolve(strict=False).parent != root.resolve():
            raise DataHomeError("artifact_path", "A recovery artifact path was rejected.")
        return candidate

    @staticmethod
    def _public_backup(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "backup_id": record["backup_id"],
            "filename": record["filename"],
            "label": record["label"],
            "created_at": record["created_at"],
            "schema_revision": record["schema_revision"],
            "size": record["size"],
            "verified": bool(record["verified"]),
        }

    def _public_journal(self, journal: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "operation_id": journal.get("operation_id"),
            "operation_kind": journal.get("operation_kind"),
            "phase": journal.get("phase"),
            "ready": bool(journal.get("completed") and self.paths.database.exists()),
            "schema_revision": journal.get("expected_schema_revision"),
            "recoverable": bool(journal.get("recoverable")),
            "resume_available": journal.get("phase") == Phase.RESUME_AVAILABLE,
            "rollback_available": bool(journal.get("rollback_name")),
            "failure_code": journal.get("failure_code"),
            "activated": bool(journal.get("activated")),
            "paths": self.paths.safe_contract(),
            "backup_count": len(self._catalog()),
        }

    @staticmethod
    def _completion_phase(journal: Mapping[str, Any]) -> Phase:
        return (
            Phase.RESTORE_COMPLETE
            if journal.get("operation_kind") == "restore"
            else Phase.ACTIVATION_COMPLETE
        )


def verify_database(path: Path, *, expected_revision: str | None = None) -> DatabaseVerification:
    _reject_existing_symlink_chain(path)
    if path.is_symlink() or not path.is_file():
        raise DataHomeError("database_missing", "The database could not be verified.")
    try:
        with _read_only_connection(path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA query_only=ON")
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            versions = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
    except sqlite3.Error as error:
        raise DataHomeError("database_invalid", "The database could not be verified.") from error
    if integrity != [("ok",)]:
        raise DataHomeError("integrity_failed", "The database failed integrity verification.")
    if foreign_keys:
        raise DataHomeError("foreign_keys_failed", "The database failed relationship verification.")
    if len(versions) != 1:
        raise DataHomeError("revision_invalid", "The database version could not be verified.")
    revision = str(versions[0][0])
    if expected_revision is not None and revision != expected_revision:
        raise DataHomeError("revision_incompatible", "The database version is not compatible.")
    manifest = build_logical_manifest(path)
    size = path.stat().st_size
    return DatabaseVerification(
        revision=revision,
        size=size,
        sha256=_sha256(path),
        manifest_digest=manifest_digest(manifest),
        table_count=len(manifest["tables"]),
    )


def online_backup(
    source: Path,
    destination: Path,
    *,
    fail_during: Callable[[], None] | None = None,
) -> DatabaseVerification:
    _reject_existing_symlink_chain(source)
    _reject_existing_symlink_chain(destination)
    if source.is_symlink() or not source.is_file() or destination.is_symlink():
        raise DataHomeError("backup_path", "The backup path was rejected.")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists() and os.path.samefile(source, destination):
        raise DataHomeError("backup_identity", "A backup must be a distinct database.")
    destination.unlink(missing_ok=True)
    try:
        with (
            _read_only_connection(source) as source_connection,
            sqlite3.connect(destination) as target_connection,
        ):
            invoked = False

            def progress(status: int, remaining: int, total: int) -> None:
                nonlocal invoked
                del status, remaining, total
                if fail_during and not invoked:
                    invoked = True
                    fail_during()

            source_connection.backup(target_connection, pages=256, progress=progress)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    destination.chmod(0o600)
    if os.path.samefile(source, destination):
        destination.unlink(missing_ok=True)
        raise DataHomeError("backup_identity", "A backup must be a distinct database.")
    _fsync_file(destination)
    _fsync_directory(destination.parent)
    return verify_database(destination)


def _upgrade(path: Path, migration_dir: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(migration_dir))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, SCHEMA_HEAD)
    path.chmod(0o600)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve(strict=True)}?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _file_identity(path: Path) -> tuple[int, int, int, int, str]:
    metadata = path.stat(follow_symlinks=False)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        _sha256(path),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paths_related(first: Path, second: Path) -> bool:
    one = first.resolve(strict=False)
    two = second.resolve(strict=False)
    return one == two or one in two.parents or two in one.parents


def _reject_existing_symlink_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(path.expanduser()))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise DataHomeError(
                "symlink_rejected", "A symbolic link in the data path was rejected."
            )


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _operation_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(6)}"


def _now() -> str:
    return datetime.now(UTC).isoformat()
