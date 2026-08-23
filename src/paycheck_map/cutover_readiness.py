"""Fail-closed owner cutover readiness layered on the Slice 2 data-home authority."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from paycheck_map.data_home import (
    CONFIRMATION_TTL_SECONDS,
    SCHEMA_HEAD,
    SUPPORTED_REVISIONS,
    Candidate,
    DatabaseVerification,
    DataHomeError,
    DataHomeManager,
    DataHomePaths,
    Phase,
    online_backup,
    verify_database,
)
from paycheck_map.desktop_bootstrap import active_bootstrap

CUTOVER_CONTRACT = "money-map-cutover-readiness-v1"
CONFIRMATION_CONTRACT = "money-map-cutover-confirmation-v1"
OWNER_WORKSHEET_CONTRACT = "money-map-owner-cutover-worksheet-v1"
OWNER_FIELDS = (
    "source_selection",
    "migration_confirmation",
    "rollback_decision",
    "provider_choice",
    "keychain_response",
    "usability_result",
    "coaching_required",
    "cutover_acceptance",
    "final_beta_decision",
)


class ReadinessState(StrEnum):
    FRESH_SETUP = "fresh_setup"
    ELIGIBLE_LEGACY_SOURCE = "eligible_legacy_source"
    CURRENT_SOURCE = "current_0009_source"
    UNSUPPORTED_NEWER_SOURCE = "unsupported_newer_source"
    UNKNOWN_REVISION = "missing_or_unknown_revision"
    INTEGRITY_FAILURE = "integrity_failure"
    FOREIGN_KEY_FAILURE = "foreign_key_failure"
    REQUIRED_TABLE_FAILURE = "required_table_failure"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_READ_ONLY = "read_only_source"
    INSUFFICIENT_SPACE = "insufficient_destination_space"
    DESTINATION_UNWRITABLE = "unwritable_destination"
    REHEARSAL_REQUIRED = "rehearsal_required"
    REHEARSAL_IN_PROGRESS = "rehearsal_in_progress"
    REHEARSAL_PASSED = "rehearsal_passed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ACTIVATION_READY = "activation_ready"
    RECOVERABLE_INTERRUPTION = "recoverable_interruption"
    ROLLBACK_AVAILABLE = "rollback_available"
    COMPLETED = "completed_cutover"


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    sha256: str

    @property
    def commitment(self) -> str:
        value = f"{self.device}:{self.inode}:{self.size}:{self.modified_ns}:{self.sha256}"
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class ReviewedCutover:
    candidate: Candidate
    source_identity: FileIdentity
    destination_identity: str
    backup_path: Path
    backup_identity: str
    rehearsal_commitment: str
    candidate_commit: str
    candidate_artifact_identity: str | None
    requested_action: str


@dataclass
class Confirmation:
    token: str
    reviewed: ReviewedCutover
    created_at: float
    expires_at: float
    used: bool = False


def owner_worksheet() -> dict[str, Any]:
    return {
        "contract": OWNER_WORKSHEET_CONTRACT,
        "owner_responses": {field: None for field in OWNER_FIELDS},
        "engineering": {
            "schema": SCHEMA_HEAD,
            "campaigns_a_through_j": None,
            "owner_validation": None,
            "cutover_result": None,
        },
    }


def validate_owner_worksheet(payload: Mapping[str, Any]) -> None:
    if payload.get("contract") != OWNER_WORKSHEET_CONTRACT:
        raise DataHomeError("worksheet_contract", "The owner worksheet was rejected.")
    responses = payload.get("owner_responses")
    if not isinstance(responses, Mapping) or set(responses) != set(OWNER_FIELDS):
        raise DataHomeError("worksheet_fields", "The owner worksheet was rejected.")
    if any(value is not None and value != "" for value in responses.values()):
        raise DataHomeError(
            "owner_response_prepopulated",
            "Owner decisions must remain blank until the live owner run.",
        )


class CutoverReadinessManager:
    """Binds a reviewed cutover to the existing DataHomeManager operation."""

    def __init__(
        self, data_home: DataHomeManager, *, now: Callable[[], float] = time.monotonic
    ) -> None:
        self.data_home = data_home
        self.now = now
        self._confirmation: Confirmation | None = None
        self._rehearsal_commitment: str | None = None

    def fresh_summary(self) -> dict[str, Any]:
        writable = _destination_writable_without_creation(self.data_home.paths.application)
        return self._summary(
            ReadinessState.FRESH_SETUP if writable else ReadinessState.DESTINATION_UNWRITABLE,
            source="No existing data selected",
            schema="Fresh database through 0009",
            size="empty",
            integrity="not applicable",
            foreign_keys="not applicable",
            backup="not required",
            destination="ready" if writable else "not writable",
            rehearsal="not required",
            rollback="not available",
            candidate="not reviewed",
            action="Start fresh" if writable else "Choose a writable private data location",
        )

    def inspect(self, selected: Path) -> dict[str, Any]:
        """Preview an explicit source without writing to source or destination."""

        try:
            path = self.data_home._resolve_candidate(selected)
            identity = secure_file_identity(path)
            verification = _classified_verification(path)
            if identity != secure_file_identity(path):
                raise DataHomeError("source_changed", "The selected source changed during review.")
            state = (
                ReadinessState.CURRENT_SOURCE
                if verification.revision == SCHEMA_HEAD
                else ReadinessState.ELIGIBLE_LEGACY_SOURCE
            )
            required = max(verification.size * 4, verification.size + 16 * 1024 * 1024)
            space_probe = self.data_home.paths.application
            while not space_probe.exists() and space_probe != space_probe.parent:
                space_probe = space_probe.parent
            if self.data_home.available_space(space_probe) < required:
                state = ReadinessState.INSUFFICIENT_SPACE
            elif not _destination_writable_without_creation(self.data_home.paths.application):
                state = ReadinessState.DESTINATION_UNWRITABLE
            elif not os.access(path, os.W_OK):
                state = ReadinessState.SOURCE_READ_ONLY
            candidate = Candidate(
                token=secrets.token_urlsafe(24),
                path=path,
                verification=verification,
                required_space=required,
                expires_at=self.now() + CONFIRMATION_TTL_SECONDS,
                classification="explicit reviewed Money Map source",
            )
            self.data_home._candidate = candidate
            return self._summary(
                state,
                source="Eligible legacy data"
                if verification.revision != SCHEMA_HEAD
                else "Current Money Map data",
                schema="Eligible legacy schema"
                if verification.revision != SCHEMA_HEAD
                else "Current 0009 schema",
                size=_size_class(verification.size),
                integrity="passed",
                foreign_keys="passed",
                backup="required before activation",
                destination="ready"
                if state
                not in {ReadinessState.INSUFFICIENT_SPACE, ReadinessState.DESTINATION_UNWRITABLE}
                else "not ready",
                rehearsal="required",
                rollback="available after replacement"
                if self.data_home.paths.database.exists()
                else "not yet available",
                candidate="source identity reviewed",
                action="Run synthetic rehearsal",
                candidate_token=candidate.token,
            )
        except DataHomeError as error:
            return self._failure_summary(error)

    def begin_rehearsal(self) -> dict[str, Any]:
        if self.data_home._candidate is None:
            raise DataHomeError("preview_required", "Review an explicit source first.")
        return self._summary(
            ReadinessState.REHEARSAL_IN_PROGRESS,
            source="Reviewed Money Map data",
            schema="Reviewed schema",
            size=_size_class(self.data_home._candidate.verification.size),
            integrity="passed",
            foreign_keys="passed",
            backup="rehearsal backup in progress",
            destination="ready",
            rehearsal="in progress",
            rollback="will be exercised",
            candidate="source identity reviewed",
            action="Wait for rehearsal verification",
        )

    def rehearse(self) -> dict[str, Any]:
        """Run the selected source only through a disposable fake-home authority."""

        candidate = self.data_home._candidate
        if candidate is None:
            raise DataHomeError("preview_required", "Review an explicit source first.")
        source_before = secure_file_identity(candidate.path)
        with tempfile.TemporaryDirectory(
            prefix="money-map-cutover-", dir="/private/tmp"
        ) as temporary:
            home = Path(temporary)
            paths = DataHomePaths(
                application=home / "Library/Application Support/Money Map",
                cache=home / "Library/Caches/com.moneymap.desktop",
                logs=home / "Library/Logs/Money Map",
                mode="acceptance-synthetic-v1",
            )
            rehearsal = DataHomeManager(paths, migration_dir=self.data_home.migration_dir)
            rehearsal.prepare()
            preview = rehearsal.inspect_candidate(candidate.path)
            result = rehearsal.confirm_migration(str(preview["candidate_token"]))
            if not result.get("ready"):
                raise DataHomeError("rehearsal_failed", "The cutover rehearsal stopped safely.")
            active = verify_database(paths.database, expected_revision=SCHEMA_HEAD)
            backup = rehearsal.create_backup(label="rehearsal-safety")
            if not backup.get("verified"):
                raise DataHomeError("rehearsal_failed", "The cutover rehearsal stopped safely.")
            commitment = hashlib.sha256(
                f"{candidate.verification.manifest_digest}:{active.manifest_digest}:{SCHEMA_HEAD}".encode()
            ).hexdigest()
        if secure_file_identity(candidate.path) != source_before:
            raise DataHomeError("source_changed", "The selected source changed during rehearsal.")
        self._rehearsal_commitment = commitment
        return self._summary(
            ReadinessState.REHEARSAL_PASSED,
            source="Reviewed Money Map data",
            schema="Rehearsed through current 0009 schema",
            size=_size_class(candidate.verification.size),
            integrity="passed",
            foreign_keys="passed",
            backup="rehearsal backup verified",
            destination="disposable rehearsal passed",
            rehearsal="passed",
            rollback="rehearsal recovery verified",
            candidate="source identity unchanged",
            action="Review activation confirmation",
        )

    def prepare_current_confirmation(self) -> dict[str, Any]:
        if self._rehearsal_commitment is None:
            raise DataHomeError("rehearsal_required", "Complete the cutover rehearsal first.")
        bootstrap = active_bootstrap()
        return self.prepare_confirmation(
            rehearsal_commitment=self._rehearsal_commitment,
            candidate_commit=bootstrap.candidate_commit,
            candidate_artifact_identity=bootstrap.candidate_artifact,
        )

    def confirm_current(self, token: str, requested_action: str) -> dict[str, Any]:
        if self._rehearsal_commitment is None:
            raise DataHomeError("rehearsal_required", "Complete the cutover rehearsal first.")
        bootstrap = active_bootstrap()
        return self.confirm(
            token,
            requested_action=requested_action,
            candidate_commit=bootstrap.candidate_commit,
            candidate_artifact_identity=bootstrap.candidate_artifact,
            rehearsal_commitment=self._rehearsal_commitment,
        )

    def prepare_confirmation(
        self,
        *,
        rehearsal_commitment: str,
        candidate_commit: str,
        candidate_artifact_identity: str | None,
        requested_action: str = "activate_reviewed_source",
    ) -> dict[str, Any]:
        candidate = self.data_home._candidate
        if candidate is None:
            raise DataHomeError("preview_required", "Review an explicit source first.")
        if requested_action != "activate_reviewed_source":
            raise DataHomeError("wrong_action", "The requested cutover action was rejected.")
        if not _digest(rehearsal_commitment) or not _commit(candidate_commit):
            raise DataHomeError("candidate_identity", "Candidate readiness could not be verified.")
        source_identity = secure_file_identity(candidate.path)
        if source_identity.sha256 != candidate.verification.sha256:
            raise DataHomeError("source_changed", "Review the selected source again.")
        self.data_home.paths.ensure_directories()
        backup = self.data_home.paths.backups / f"cutover-preview-{secrets.token_hex(12)}.sqlite3"
        copied = online_backup(candidate.path, backup)
        verified = verify_database(backup)
        if (
            verified.sha256 != copied.sha256
            or verified.manifest_digest != candidate.verification.manifest_digest
        ):
            raise DataHomeError("backup_changed", "The verified backup changed.")
        reviewed = ReviewedCutover(
            candidate=candidate,
            source_identity=source_identity,
            destination_identity=destination_identity(self.data_home),
            backup_path=backup,
            backup_identity=secure_file_identity(backup).commitment,
            rehearsal_commitment=rehearsal_commitment,
            candidate_commit=candidate_commit,
            candidate_artifact_identity=candidate_artifact_identity,
            requested_action=requested_action,
        )
        confirmation = Confirmation(
            token=secrets.token_urlsafe(32),
            reviewed=reviewed,
            created_at=self.now(),
            expires_at=self.now() + CONFIRMATION_TTL_SECONDS,
        )
        self._confirmation = confirmation
        return self._summary(
            ReadinessState.CONFIRMATION_REQUIRED,
            source="Reviewed Money Map data",
            schema="Current 0009 candidate after rehearsal",
            size=_size_class(candidate.verification.size),
            integrity="passed",
            foreign_keys="passed",
            backup="verified",
            destination="ready",
            rehearsal="passed",
            rollback="available before replacement"
            if self.data_home.paths.database.exists()
            else "not required for empty destination",
            candidate="candidate identity bound",
            action="Confirm activation",
            confirmation_token=confirmation.token,
            expires_in_seconds=CONFIRMATION_TTL_SECONDS,
        )

    def confirm(
        self,
        token: str,
        *,
        requested_action: str,
        candidate_commit: str,
        candidate_artifact_identity: str | None,
        rehearsal_commitment: str,
    ) -> dict[str, Any]:
        confirmation = self._confirmation
        if confirmation is None or confirmation.used:
            raise DataHomeError("confirmation_replay", "Review and confirm the cutover again.")
        confirmation.used = True
        reviewed = confirmation.reviewed
        if self.now() > confirmation.expires_at:
            raise DataHomeError("confirmation_expired", "Review and confirm the cutover again.")
        if not secrets.compare_digest(token, confirmation.token):
            raise DataHomeError("confirmation_mismatch", "Review and confirm the cutover again.")
        if requested_action != reviewed.requested_action:
            raise DataHomeError("wrong_action", "The confirmed action no longer matches.")
        if (
            candidate_commit != reviewed.candidate_commit
            or candidate_artifact_identity != reviewed.candidate_artifact_identity
        ):
            raise DataHomeError("candidate_drift", "The candidate changed after review.")
        if rehearsal_commitment != reviewed.rehearsal_commitment:
            raise DataHomeError("rehearsal_drift", "The rehearsal result changed after review.")
        if destination_identity(self.data_home) != reviewed.destination_identity:
            raise DataHomeError("destination_drift", "The destination changed after review.")
        if secure_file_identity(reviewed.backup_path).commitment != reviewed.backup_identity:
            raise DataHomeError("backup_changed", "The verified backup changed after review.")
        if secure_file_identity(reviewed.candidate.path) != reviewed.source_identity:
            raise DataHomeError("source_changed", "The source changed after review.")
        if self.data_home._candidate is not reviewed.candidate:
            raise DataHomeError("stale_preview", "Review the selected source again.")
        prior = self.data_home._read_journal()
        if prior and not prior.get("completed"):
            raise DataHomeError("interrupted_operation", "Resolve the interrupted operation first.")
        result = self.data_home.confirm_migration(reviewed.candidate.token)
        if result.get("phase") == Phase.RECOVERABLE_FAILURE:
            return self._summary_from_operation(ReadinessState.RECOVERABLE_INTERRUPTION, result)
        return self._summary_from_operation(ReadinessState.COMPLETED, result)

    def cancel(self) -> dict[str, Any]:
        self._confirmation = None
        self._rehearsal_commitment = None
        self.data_home._candidate = None
        return self.fresh_summary()

    def _failure_summary(self, error: DataHomeError) -> dict[str, Any]:
        mapping = {
            "source_missing": ReadinessState.SOURCE_UNAVAILABLE,
            "source_type": ReadinessState.SOURCE_UNAVAILABLE,
            "source_open": ReadinessState.SOURCE_UNAVAILABLE,
            "unsupported_revision": ReadinessState.UNSUPPORTED_NEWER_SOURCE,
            "unknown_revision": ReadinessState.UNKNOWN_REVISION,
            "integrity_failed": ReadinessState.INTEGRITY_FAILURE,
            "foreign_key_failed": ReadinessState.FOREIGN_KEY_FAILURE,
            "required_table_missing": ReadinessState.REQUIRED_TABLE_FAILURE,
            "insufficient_space": ReadinessState.INSUFFICIENT_SPACE,
        }
        state = mapping.get(error.code, ReadinessState.SOURCE_UNAVAILABLE)
        return self._summary(
            state,
            source="Source could not be approved",
            schema="not approved",
            size="unknown",
            integrity="failed" if state == ReadinessState.INTEGRITY_FAILURE else "not verified",
            foreign_keys="failed"
            if state == ReadinessState.FOREIGN_KEY_FAILURE
            else "not verified",
            backup="not ready",
            destination="not evaluated",
            rehearsal="blocked",
            rollback="not available",
            candidate="not approved",
            action="Choose a supported source or resolve the reported condition",
            failure_code=error.code,
        )

    @staticmethod
    def _summary(state: ReadinessState, **values: Any) -> dict[str, Any]:
        return {"contract": CUTOVER_CONTRACT, "state": state, **values}

    def _summary_from_operation(
        self, state: ReadinessState, operation: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._summary(
            state,
            source="Reviewed Money Map data",
            schema="Current 0009 schema",
            size="reviewed",
            integrity="passed",
            foreign_keys="passed",
            backup="verified",
            destination="activated" if state == ReadinessState.COMPLETED else "protected",
            rehearsal="passed",
            rollback="available" if operation.get("rollback_available") else "not available",
            candidate="identity verified",
            action="Relaunch Money Map"
            if state == ReadinessState.COMPLETED
            else "Resume or roll back",
            ready=bool(operation.get("ready")),
        )


def secure_file_identity(path: Path) -> FileIdentity:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DataHomeError("source_open", "The selected source could not be opened.") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DataHomeError("source_substitution", "The selected source identity was rejected.")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise DataHomeError("source_changed", "The selected source changed during review.")
        return FileIdentity(
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, digest.hexdigest()
        )
    finally:
        os.close(descriptor)


def destination_identity(manager: DataHomeManager) -> str:
    database = manager.paths.database
    if database.exists():
        return f"active:{secure_file_identity(database).commitment}"
    parent = manager.paths.application
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    metadata = parent.stat()
    return hashlib.sha256(f"empty:{metadata.st_dev}:{metadata.st_ino}".encode()).hexdigest()


def _classified_verification(path: Path) -> DatabaseVerification:
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise DataHomeError("integrity_failed", "The source failed integrity verification.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise DataHomeError(
                    "foreign_key_failed", "The source failed relationship verification."
                )
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "alembic_version" not in tables:
                raise DataHomeError(
                    "required_table_missing", "The source is missing required tables."
                )
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if row is None or not isinstance(row[0], str) or not row[0]:
                raise DataHomeError(
                    "unknown_revision", "The source schema could not be identified."
                )
            revision = row[0]
    except DataHomeError:
        raise
    except sqlite3.Error as error:
        raise DataHomeError(
            "integrity_failed", "The source failed integrity verification."
        ) from error
    if revision not in SUPPORTED_REVISIONS:
        match = re.match(r"^(\d{4})_", revision)
        if match and int(match.group(1)) > 9:
            raise DataHomeError(
                "unsupported_revision", "The source is newer than this Money Map candidate."
            )
        raise DataHomeError("unknown_revision", "The source schema could not be identified.")
    return verify_database(path)


def _destination_writable_without_creation(path: Path) -> bool:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current.is_dir() and os.access(current, os.W_OK | os.X_OK)


def _size_class(size: int) -> str:
    if size < 16 * 1024 * 1024:
        return "small"
    if size < 256 * 1024 * 1024:
        return "medium"
    return "large"


def _digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _commit(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)
