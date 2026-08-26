#!/usr/bin/env python3
"""Execute the sealed Slice 6 state-route oracle through a copied signed app."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import qualify_desktop_release as base  # noqa: E402
from materialize_release_state_contract import materialize  # noqa: E402

from tests.release_state_materializer import materialize_release_state  # noqa: E402

CONTRACT = "money-map-slice6-installed-state-route-matrix-v1"
OBSERVATION_CONTRACT = "money-map-installed-matrix-observation-v1"
OBSERVER_FAILURE_CONTRACT = "money-map-installed-matrix-observer-failure-v1"
GATE_CHALLENGE_CONTRACT = "money-map-qualification-gate-challenge-v1"
GATE_RELEASE_CONTRACT = "money-map-qualification-gate-release-v1"
IMPLEMENTED_SETUP_DRIVERS = frozenset(
    {
        "persistent_database_fixture",
        "transient_bounded_loading_injection",
        "controlled_unavailable_api_state",
        "one_shot_recoverable_failure",
        "fixed_clock_stale_evidence",
        "deterministic_large_history_generator",
    }
)


class MatrixFailure(RuntimeError):
    """A sealed expectation and installed observation differ."""


class ObserverFailure(MatrixFailure):
    """The installed observer produced a bounded authoritative failure."""

    def __init__(self, failure: dict[str, Any]) -> None:
        super().__init__(f"installed observer reported {failure['failure_classification']}")
        self.failure = failure


class DatabaseMutationFailure(MatrixFailure):
    """A read-only installed observation changed one or more logical tables."""

    def __init__(
        self,
        classification: str,
        *,
        phase: str,
        before: dict[str, Any],
        after: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        super().__init__(classification)
        self.phase = phase
        self.affected_tables = manifest_difference(before, after)
        self.request_inventory = sanitized_request_inventory(observation)


def validate_setup_driver(expected: dict[str, Any]) -> None:
    driver = expected.get("setup_driver")
    if not isinstance(driver, dict) or driver.get("type") not in IMPLEMENTED_SETUP_DRIVERS:
        raise MatrixFailure("sealed setup driver lacks an implemented executor")
    if driver.get("type") == "transient_bounded_loading_injection" and driver != {
        "type": "transient_bounded_loading_injection",
        "seed": "complete-current-v1",
        "gate": "qualification-response-gate-v1",
        "release": "explicit_harness_release",
        "timeout_ms": 5000,
    }:
        raise MatrixFailure("sealed loading setup driver differs")
    if driver.get("type") == "controlled_unavailable_api_state" and driver != {
        "type": "controlled_unavailable_api_state",
        "seed": "fresh-empty-0009-v1",
        "fault": "qualification-unavailable-v1",
    }:
        raise MatrixFailure("sealed unavailable setup driver differs")
    if driver.get("type") == "one_shot_recoverable_failure" and driver != {
        "type": "one_shot_recoverable_failure",
        "seed": "complete-current-v1",
        "fault": "qualification-dashboard-read-once-v1",
        "failure_count": 1,
    }:
        raise MatrixFailure("sealed recovery setup driver differs")
    if driver.get("type") == "fixed_clock_stale_evidence" and driver != {
        "type": "fixed_clock_stale_evidence",
        "seed": "complete-current-v1",
        "last_evidence_date": "2026-06-30",
        "threshold_days": 32,
    }:
        raise MatrixFailure("sealed stale-evidence setup driver differs")


def execute_setup_driver(database: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Execute the sealed database portion; transient native controls are armed at launch."""
    validate_setup_driver(expected)
    return materialize_release_state(database, str(expected["state_id"]))


def canonical(value: object) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{encoded}\n".encode()


def database_manifest(database: Path) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({name})")]
            rows = [
                {column: _json_value(row[column]) for column in columns}
                for row in connection.execute(f"SELECT * FROM {name}")
            ]
            rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
            tables[name] = {
                "count": len(rows),
                "rows_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
            }
    payload = {"tables": tables}
    return {
        "tables": tables,
        "table_counts": {name: value["count"] for name, value in tables.items()},
        "logical_digest_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
    }


def manifest_difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    before_tables = before["tables"]
    after_tables = after["tables"]
    for name in sorted(set(before_tables) | set(after_tables)):
        prior = before_tables.get(name, {"count": 0, "rows_sha256": None})
        current = after_tables.get(name, {"count": 0, "rows_sha256": None})
        if prior == current:
            continue
        result[name] = {
            "before_count": prior["count"],
            "after_count": current["count"],
            "count_delta": current["count"] - prior["count"],
            "rows_changed": prior["rows_sha256"] != current["rows_sha256"],
        }
    return result


def sanitized_request_inventory(observation: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = observation.get("request_inventory", [])
    if not isinstance(inventory, list):
        return []
    result = []
    for item in inventory:
        if not isinstance(item, dict):
            continue
        method = item.get("method")
        endpoint = item.get("endpoint")
        count = item.get("count")
        if (
            method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            and isinstance(endpoint, str)
            and endpoint.startswith("/api/")
            and "?" not in endpoint
            and len(endpoint) <= 256
            and isinstance(count, int)
            and count > 0
        ):
            result.append({"method": method, "endpoint": endpoint, "count": count})
    return result


def require_database_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    classification: str,
    phase: str,
    observation: dict[str, Any],
) -> None:
    if after != before:
        raise DatabaseMutationFailure(
            classification,
            phase=phase,
            before=before,
            after=after,
            observation=observation,
        )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return format(value, ".12g")
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return str(value)


def wait_observation(path: Path, *, sequence: int, timeout: float = 20) -> dict[str, Any]:
    started = time.monotonic()
    failure_path = path.with_name(f"matrix-observer-failure-{sequence}.json")
    while time.monotonic() - started < timeout:
        if failure_path.is_file() and not failure_path.is_symlink():
            try:
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            required = {
                "contract",
                "result",
                "state",
                "route",
                "contract_digest_sha256",
                "candidate_sha256",
                "source_commit",
                "sequence",
                "requested_route",
                "expected_phase",
                "last_completed_stage",
                "failure_classification",
                "hash_matched",
                "global_loading_present",
                "route_local_loading_present",
                "native_invocation_accepted",
                "timeout_classification",
                "raw_paths_retained",
                "private_content_retained",
            }
            if (
                isinstance(failure, dict)
                and set(failure) == required
                and failure.get("contract") == OBSERVER_FAILURE_CONTRACT
                and failure.get("result") == "failed"
                and failure.get("sequence") == sequence
                and failure.get("raw_paths_retained") is False
                and failure.get("private_content_retained") is False
            ):
                raise ObserverFailure(cast(dict[str, Any], failure))
            raise MatrixFailure("installed observer failure evidence was rejected")
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536:
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if (
                isinstance(result, dict)
                and result.get("contract") == OBSERVATION_CONTRACT
                and result.get("result") == "observed"
                and result.get("ui", {}).get("sequence") == sequence
            ):
                return cast(dict[str, Any], result)
        time.sleep(0.05)
    raise MatrixFailure("installed matrix observation was not produced")


def observed_text(result: dict[str, Any]) -> str:
    ui = result["ui"]
    values = [
        *ui["headings"],
        *ui["statuses"],
        *ui["alerts"],
        *ui["buttons"],
        *ui["messages"],
    ]
    return "\n".join(str(value) for value in values).casefold()


def compare_observation(
    expected: dict[str, Any],
    actual: dict[str, Any],
    sequence: int,
    *,
    phase: str = "settled",
    settled_expected: dict[str, Any] | None = None,
) -> None:
    if actual.get("state") != expected["state_id"] or actual.get("route") != expected["route_id"]:
        raise MatrixFailure("installed observation state or route differs")
    if actual.get("contract_digest_sha256") != expected["contract_digest_sha256"]:
        raise MatrixFailure("installed observation oracle digest differs")
    ui = actual["ui"]
    if (
        ui.get("sequence") != sequence
        or ui.get("phase") != phase
        or ui.get("unsafe_console_errors") != 0
    ):
        raise MatrixFailure("installed UI sequence or console safety differs")
    pending_loading = expected["state_id"] == "loading" and phase == "pending"
    recovered_retry = expected["state_id"] == "recoverable_failure" and sequence == 2
    if pending_loading:
        if ui.get("headings") != ["Loading accounts…"]:
            raise MatrixFailure("installed pending UI lacks the exact loading heading")
        if not ui.get("loading_visible") or not ui.get("loading_busy"):
            raise MatrixFailure("installed pending UI lacks the bounded busy loading surface")
        if ui.get("loading_live") != "polite":
            raise MatrixFailure("installed pending UI lacks polite live behavior")
        if ui.get("buttons") or ui.get("messages") or ui.get("alerts"):
            raise MatrixFailure("installed pending UI exposed completed or mutable content")
        role_expected = None
    else:
        if expected["state_id"] == "loading" or recovered_retry:
            if settled_expected is None:
                raise MatrixFailure("sealed settled loading authority is unavailable")
            role_expected = settled_expected
            if expected["state_id"] == "loading" and (
                ui.get("loading_visible") or ui.get("loading_busy")
            ):
                raise MatrixFailure("installed loading state did not settle after release")
        else:
            role_expected = expected
    if (
        role_expected
        and role_expected["expected_accessible_role"] == "heading"
        and not ui.get("headings")
    ):
        raise MatrixFailure("installed UI lacks the expected accessible heading")
    if (
        role_expected
        and role_expected["expected_accessible_role"] == "dialog"
        and ui.get("dialog_count", 0) < 1
    ):
        raise MatrixFailure("installed UI lacks the expected accessible dialog")
    if (
        role_expected
        and role_expected["expected_accessible_role"] == "button"
        and not ui.get("buttons")
    ):
        raise MatrixFailure("installed UI lacks the expected accessible control")
    combined = observed_text(actual)
    copy_expected = expected if pending_loading else role_expected
    assert copy_expected is not None
    missing_copy = [
        phrase
        for phrase in copy_expected["expected_safe_state_language"]
        if str(phrase).casefold() not in combined
    ]
    if missing_copy:
        raise MatrixFailure("installed UI safe-state language differs")
    status_authority = role_expected if recovered_retry else expected
    assert status_authority is not None
    expected_status = [
        int(value) for value in status_authority["expected_http_status"] if str(value).isdigit()
    ]
    if expected["state_id"] == "recoverable_failure" and sequence == 1:
        expected_status = expected_status[:1]
    actual_status = [int(row["status"]) for row in actual["api"]]
    status_matches = (
        bool(actual_status) and all(value == expected_status[0] for value in actual_status)
        if len(expected_status) == 1
        else expected_status == actual_status
    )
    if not status_matches:
        raise MatrixFailure("installed authenticated API status sequence differs")
    inventory = actual.get("request_inventory")
    if expected["route_id"] == "overview" and (
        not isinstance(inventory, list)
        or not inventory
        or any(not isinstance(item, dict) or item.get("method") != "GET" for item in inventory)
    ):
        raise MatrixFailure("installed Overview request inventory is not read-only")


def release_loading_gate(
    fake_home: Path,
    expected: dict[str, Any],
    *,
    runtime_generation: int,
    gate_generation: int,
) -> None:
    challenge_path = fake_home / "qualification-response-gate.challenge.json"
    release_path = fake_home / "qualification-response-gate.release.json"
    started = time.monotonic()
    challenge: dict[str, Any] | None = None
    while time.monotonic() - started < 2:
        if challenge_path.is_file() and not challenge_path.is_symlink():
            metadata = challenge_path.stat()
            if (
                metadata.st_mode & 0o777 != 0o600
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
            ):
                raise MatrixFailure("qualification response gate challenge permissions differ")
            try:
                loaded = json.loads(challenge_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                challenge = loaded
                break
        time.sleep(0.02)
    if challenge is None:
        raise MatrixFailure("qualification response gate challenge was not produced")
    combination_id = expected["combination_id"]
    value = challenge.get("challenge")
    if (
        challenge.get("contract") != GATE_CHALLENGE_CONTRACT
        or challenge.get("combination_id") != combination_id
        or challenge.get("runtime_generation") != runtime_generation
        or challenge.get("gate_generation") != gate_generation
        or not isinstance(value, str)
        or not base.HEX_64.fullmatch(value)
    ):
        raise MatrixFailure("qualification response gate challenge identity differs")
    release = canonical(
        {
            "contract": GATE_RELEASE_CONTRACT,
            "combination_id": combination_id,
            "runtime_generation": runtime_generation,
            "gate_generation": gate_generation,
            "challenge": value,
        }
    )
    descriptor = os.open(release_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, release)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def trigger_reload() -> None:
    base.run(
        [
            "/usr/bin/osascript",
            "-e",
            'tell application id "com.moneymap.desktop" to activate',
            "-e",
            'tell application "System Events" to keystroke "r" using command down',
        ]
    )


def trigger_close() -> None:
    base.run(
        [
            "/usr/bin/osascript",
            "-e",
            'tell application id "com.moneymap.desktop" to activate',
            "-e",
            'tell application "System Events" to keystroke "w" using command down',
        ]
    )


def run_combination(
    app: Path,
    campaign: Path,
    expected: dict[str, Any],
    *,
    source_commit: str,
    candidate_sha256: str,
    settled_expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = expected["state_id"]
    route = expected["route_id"]
    fake_home = campaign / f"combination-{expected['combination_id'].replace('::', '--')}"
    fake_home.mkdir(mode=0o700)
    database = fake_home / "Library/Application Support/Money Map/data/paycheck-map.sqlite3"
    seed_result = execute_setup_driver(database, expected)
    before = database_manifest(database)
    contract = base.launch_contract(
        fake_home,
        campaign_id=secrets.token_hex(16),
        nonce=secrets.token_hex(32),
        candidate_sha256=candidate_sha256,
        source_commit=source_commit,
        matrix_state=state,
        matrix_route=route,
        matrix_contract_digest=expected["contract_digest_sha256"],
        matrix_driver=(
            expected["setup_driver"]
            if state in {"loading", "unavailable", "recoverable_failure", "stale_evidence"}
            else None
        ),
    )
    process = subprocess.Popen(
        [str(app / "Contents/MacOS/money-map-desktop")],
        cwd=campaign,
        env=base.clean_runtime_env(fake_home, contract),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    lock = fake_home / "Library/Application Support/Money Map/.money-map-writer.lock"
    sidecars: list[int] = []
    try:
        native = base.wait_native_result(
            fake_home / "native-attestation-result.json",
            expected="pass",
            context="matrix-attestation",
        )
        base.require_native_attestation(native, contract)
        sidecars, ready_ms = base.wait_for_runtime(process.pid, lock)
        listeners, external = base.socket_observation(sidecars)
        if listeners != 1 or external != 0:
            raise MatrixFailure("installed matrix network classification differs")
        loading_phases: dict[str, Any] | None = None
        if state == "loading":
            first_pending = wait_observation(
                fake_home / "matrix-observation-pending-1.json", sequence=1
            )
            compare_observation(expected, first_pending, 1, phase="pending")
            require_database_unchanged(
                before,
                database_manifest(database),
                classification="pending loading changed the database",
                phase="initial-pending",
                observation=first_pending,
            )
            release_loading_gate(fake_home, expected, runtime_generation=1, gate_generation=1)
            first = wait_observation(fake_home / "matrix-observation.json", sequence=1)
            compare_observation(
                expected,
                first,
                1,
                phase="settled",
                settled_expected=settled_expected,
            )
            loading_phases = {
                "pending": first_pending["ui"],
                "settled": first["ui"],
            }
        else:
            first = wait_observation(fake_home / "matrix-observation.json", sequence=1)
            compare_observation(expected, first, 1)
        after_open = database_manifest(database)
        require_database_unchanged(
            before,
            after_open,
            classification="opening the installed route changed the database",
            phase="initial-settled",
            observation=first,
        )
        trigger_reload()
        if state == "loading":
            second_pending = wait_observation(
                fake_home / "matrix-observation-pending-2.json", sequence=2
            )
            compare_observation(expected, second_pending, 2, phase="pending")
            require_database_unchanged(
                before,
                database_manifest(database),
                classification="rearmed pending loading changed the database",
                phase="reload-pending",
                observation=second_pending,
            )
            release_loading_gate(fake_home, expected, runtime_generation=1, gate_generation=2)
            second = wait_observation(fake_home / "matrix-observation.json", sequence=2)
            compare_observation(
                expected,
                second,
                2,
                phase="settled",
                settled_expected=settled_expected,
            )
            assert loading_phases is not None
            loading_phases["reload_pending"] = second_pending["ui"]
            loading_phases["reload_settled"] = second["ui"]
        else:
            second = wait_observation(fake_home / "matrix-observation.json", sequence=2)
            compare_observation(
                expected,
                second,
                2,
                settled_expected=settled_expected,
            )
        after_reload = database_manifest(database)
        require_database_unchanged(
            before,
            after_reload,
            classification="reloading the installed route changed the database",
            phase="reload-settled",
            observation=second,
        )
        trigger_close()
        time.sleep(0.5)
        activation = subprocess.Popen(
            [str(app / "Contents/MacOS/money-map-desktop")],
            cwd=campaign,
            env=base.clean_runtime_env(fake_home, contract),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        activation.wait(timeout=10)
        app_processes = [
            pid
            for pid, _, command in base.process_rows()
            if Path(command).name == "money-map-desktop"
        ]
        if len(app_processes) != 1:
            raise MatrixFailure("close and reopen changed single-instance topology")
        base.quit_app()
        shutdown_ms = base.wait_gone(process, sidecars)
        final = database_manifest(database)
        require_database_unchanged(
            before,
            final,
            classification="close and reopen changed the database",
            phase="close-reopen",
            observation=second,
        )
        session_files = [
            path
            for path in fake_home.rglob("*")
            if path.is_file() and ("session" in path.name.lower() or path.suffix == ".sock")
        ]
        gate_files = list(fake_home.glob("qualification-response-gate.*"))
        if lock.exists() or session_files or gate_files:
            raise MatrixFailure("installed matrix cleanup differs")
        result = {
            "combination_id": expected["combination_id"],
            "result": "pass",
            "database": {
                "revision": seed_result["revision"],
                "declared_table_counts": seed_result["table_counts"],
                "logical_digest_sha256": before["logical_digest_sha256"],
                "unchanged_after_open_reload_close_reopen": True,
            },
            "ui": second["ui"],
            "api": second["api"],
            "request_inventory": sanitized_request_inventory(second),
            "ready_ms": ready_ms,
            "shutdown_ms": shutdown_ms,
            "network_classification": "authenticated-ephemeral-ipv4-loopback-only",
            "external_connections": 0,
            "cleanup": "pass",
        }
        if loading_phases is not None:
            result["loading_phases"] = loading_phases
            result["gate_material_retained"] = False
        return result
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            alive = {pid for pid, _, _ in base.process_rows()} & set(sidecars)
            if not alive:
                break
            for pid in alive:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM)
            time.sleep(0.1)


def qualification(args: argparse.Namespace) -> Path:
    source_commit = args.expected_source_commit
    candidate_sha256 = args.expected_candidate_sha256
    campaign_id = cast(str, args.campaign_id)
    if not base.HEX_40.fullmatch(source_commit) or not base.HEX_64.fullmatch(candidate_sha256):
        raise MatrixFailure("candidate identity is invalid")
    base.require_no_existing_runtime()
    app_source = Path(args.app).resolve(strict=True)
    if app_source.name != "Money Map.app" or app_source.is_relative_to(Path("/Applications")):
        raise MatrixFailure("candidate app path is outside the accepted contract")
    if base.signed_tree_digest(app_source) != candidate_sha256:
        raise MatrixFailure("candidate signed-app identity differs")
    base.verify_signature(app_source, deep=True)
    base.verify_zero_entitlements(app_source)
    oracle = materialize()
    digest = oracle["contract_digest_sha256"]
    combinations = oracle["combinations"]
    settled_by_route = {
        row["route_id"]: row for row in combinations if row["state_id"] == "complete_current"
    }
    for row in combinations:
        row["contract_digest_sha256"] = digest
    if args.limit is not None:
        combinations = combinations[: args.limit]
    if args.only_combination is not None:
        combinations = [
            row for row in combinations if row["combination_id"] == args.only_combination
        ]
        if len(combinations) != 1:
            raise MatrixFailure("requested diagnostic combination is unavailable")
    evidence = ROOT / ".slice6-evidence" / campaign_id
    if evidence.exists():
        raise MatrixFailure("campaign evidence ID already exists")
    evidence.mkdir(parents=True, mode=0o700)
    campaign = Path(tempfile.mkdtemp(prefix="money-map-slice6-b.", dir="/private/tmp"))
    campaign.chmod(0o700)
    installed = campaign / "Installed/Money Map.app"
    installed.parent.mkdir(mode=0o700)
    base.run(["/usr/bin/ditto", "--norsrc", str(app_source), str(installed)])
    if base.signed_tree_digest(installed) != candidate_sha256:
        raise MatrixFailure("copied candidate signed-app identity differs")
    report: dict[str, Any] = {
        "contract": CONTRACT,
        "result": "failed",
        "source_commit": source_commit,
        "candidate_sha256": candidate_sha256,
        "oracle_digest_sha256": digest,
        "required_combinations": 221,
        "planned_combinations": len(combinations),
        "results": [],
        "owner_data_accessed": False,
        "production_keychain_accessed": False,
        "provider_contacted": False,
        "port_8765_touched": False,
        "applications_touched": False,
        "push_or_remote_rewrite": False,
        "slice_7_started": False,
    }
    try:
        for expected in combinations:
            try:
                report["results"].append(
                    run_combination(
                        installed,
                        campaign,
                        expected,
                        source_commit=source_commit,
                        candidate_sha256=candidate_sha256,
                        settled_expected=settled_by_route.get(expected["route_id"]),
                    )
                )
            except (MatrixFailure, base.QualificationFailure) as error:
                report["first_failed_combination"] = expected["combination_id"]
                report["failure_classification"] = str(error)
                report["first_failure_expectation"] = {
                    "safe_state_language": expected["expected_safe_state_language"],
                    "accessible_role": expected["expected_accessible_role"],
                    "http_status": expected["expected_http_status"],
                }
                if isinstance(error, DatabaseMutationFailure):
                    report["first_failure_database"] = {
                        "phase": error.phase,
                        "affected_tables": error.affected_tables,
                    }
                    report["first_failure_request_inventory"] = error.request_inventory
                if isinstance(error, ObserverFailure):
                    report["first_failure_observer"] = error.failure
                observation_path = (
                    campaign
                    / f"combination-{expected['combination_id'].replace('::', '--')}"
                    / "matrix-observation.json"
                )
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    observation = json.loads(observation_path.read_text(encoding="utf-8"))
                    if isinstance(observation, dict):
                        report["first_failure_observation"] = observation
                raise
        report["result"] = "pass" if len(combinations) == 221 else "diagnostic-pass"
        report["passed_combinations"] = len(report["results"])
        output = evidence / "campaign-b-results.json"
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
    except BaseException:
        report["passed_combinations"] = len(report["results"])
        output = evidence / "failure.json"
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    finally:
        shutil.rmtree(campaign, ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("app")
    value.add_argument("--expected-candidate-sha256", required=True)
    value.add_argument("--expected-source-commit", required=True)
    value.add_argument("--campaign-id", required=True)
    value.add_argument("--limit", type=int, choices=range(1, 222))
    value.add_argument("--only-combination")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        output = qualification(args)
    except (MatrixFailure, base.QualificationFailure) as error:
        raise SystemExit(f"Campaign B failed closed: {error}") from None
    print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
