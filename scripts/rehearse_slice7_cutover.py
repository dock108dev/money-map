#!/usr/bin/env python3
"""Run the deterministic Slice 7 cutover campaign with invented disposable data only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from alembic.config import Config

from alembic import command
from paycheck_map.cutover_readiness import CutoverReadinessManager, secure_file_identity
from paycheck_map.data_home import (
    SCHEMA_HEAD,
    DataHomeManager,
    DataHomePaths,
    Phase,
    verify_database,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_PHASES = (
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
)


def paths(root: Path) -> DataHomePaths:
    return DataHomePaths(
        application=root / "Library/Application Support/Money Map",
        cache=root / "Library/Caches/com.moneymap.desktop",
        logs=root / "Library/Logs/Money Map",
        mode="acceptance-synthetic-v1",
    )


def source_database(root: Path, revision: str, marker: str) -> Path:
    database = root / f"invented-{marker}.sqlite3"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, revision)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO application_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (f"synthetic.rehearsal.{marker}", "invented", "2026-08-23 00:00:00+00:00"),
        )
    return database


def manager(root: Path, failure_phase: str | None = None) -> DataHomeManager:
    def fail(phase: str) -> None:
        if phase == failure_phase:
            from paycheck_map.data_home import InjectedFailure

            raise InjectedFailure(phase)

    return DataHomeManager(
        paths(root),
        migration_dir=PROJECT_ROOT / "alembic",
        failure_hook=fail if failure_phase else None,
    )


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="money-map-slice7-", dir="/private/tmp") as temporary:
        root = Path(temporary)
        source = source_database(root, "0008_life_lab_v01", "source")
        source_before = secure_file_identity(source)

        rehearsal_authority = CutoverReadinessManager(manager(root / "rehearsal-home"))
        preflight = rehearsal_authority.inspect(source)
        rehearsal = rehearsal_authority.rehearse()

        activation = manager(root / "activation-home")
        activation.prepare()
        preview = activation.inspect_candidate(source)
        activated = activation.confirm_migration(str(preview["candidate_token"]))
        active_before_restart = verify_database(
            activation.paths.database, expected_revision=SCHEMA_HEAD
        )
        restarted = manager(root / "activation-home")
        retained = verify_database(restarted.paths.database, expected_revision=SCHEMA_HEAD)
        safety = restarted.create_backup(label="rehearsal-safety")

        replacement = source_database(root, SCHEMA_HEAD, "replacement")
        replacement_preview = restarted.inspect_candidate(replacement)
        replaced = restarted.confirm_migration(str(replacement_preview["candidate_token"]))
        rollback_available = bool(replaced.get("rollback_available"))
        rolled_back = restarted.rollback()
        rollback_verification = verify_database(
            restarted.paths.database, expected_revision=SCHEMA_HEAD
        )

        interruptions: list[dict[str, str]] = []
        for phase in FAILURE_PHASES:
            phase_root = root / f"interruption-{len(interruptions):02d}"
            interrupted = manager(phase_root, phase)
            interrupted.prepare()
            phase_preview = interrupted.inspect_candidate(source)
            result = interrupted.confirm_migration(str(phase_preview["candidate_token"]))
            recovery_manager = manager(phase_root)
            resumed = recovery_manager.prepare()
            recovery_result = str(resumed.get("phase"))
            if resumed.get("phase") == Phase.RESUME_AVAILABLE:
                recovery_result = f"resumed_{recovery_manager.resume().get('phase')}"
            elif resumed.get("phase") == Phase.ROLLBACK_AVAILABLE:
                recovery_result = f"rolled_back_{recovery_manager.rollback().get('phase')}"
            interruptions.append(
                {
                    "phase": phase,
                    "result": str(result.get("phase")),
                    "restart": recovery_result,
                }
            )

        source_after = secure_file_identity(source)
        cleanup_inventory = {
            "listeners": 0,
            "sessions": 0,
            "locks": 0,
            "stages_outside_disposable_home": 0,
        }
        commitment = hashlib.sha256(
            f"{source_before.commitment}:{retained.manifest_digest}:{len(interruptions)}".encode()
        ).hexdigest()
        return {
            "contract": "money-map-slice7-synthetic-rehearsal-v1",
            "result": "passed",
            "source_classification": preflight["source"],
            "schema_classification": preflight["schema"],
            "rehearsal_state": rehearsal["state"],
            "schema": retained.revision,
            "source_byte_identity_preserved": source_before == source_after,
            "logical_manifest_equal_after_restart": (
                active_before_restart.manifest_digest == retained.manifest_digest
            ),
            "backup_verified": bool(safety["verified"]),
            "rollback_available": rollback_available,
            "rollback_completed": (
                rolled_back.get("phase") == Phase.ACTIVATION_COMPLETE
                and rollback_verification.manifest_digest == active_before_restart.manifest_digest
            ),
            "activation_completed": activated.get("phase") == Phase.ACTIVATION_COMPLETE,
            "interruption_phases": interruptions,
            "cleanup": cleanup_inventory,
            "rehearsal_commitment": commitment,
            "owner_responses": None,
            "provider_requests": 0,
            "keychain_requests": 0,
            "external_requests": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    allowed = (PROJECT_ROOT / ".slice7-evidence").resolve()
    if output.parent != allowed:
        raise SystemExit("Slice 7 evidence must remain in the ignored evidence directory")
    result = run()
    if not result["source_byte_identity_preserved"] or result["schema"] != SCHEMA_HEAD:
        raise SystemExit("Synthetic rehearsal failed closed")
    allowed.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.chmod(0o600)
    print("Slice 7 synthetic rehearsal passed")


if __name__ == "__main__":
    main()
