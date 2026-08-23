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


class MatrixFailure(RuntimeError):
    """A sealed expectation and installed observation differ."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


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
            tables[name] = {"count": len(rows), "rows_sha256": hashlib.sha256(canonical(rows)).hexdigest()}
    payload = {"tables": tables}
    return {
        "table_counts": {name: value["count"] for name, value in tables.items()},
        "logical_digest_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
    }


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
    while time.monotonic() - started < timeout:
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


def compare_observation(expected: dict[str, Any], actual: dict[str, Any], sequence: int) -> None:
    if actual.get("state") != expected["state_id"] or actual.get("route") != expected["route_id"]:
        raise MatrixFailure("installed observation state or route differs")
    if actual.get("contract_digest_sha256") != expected["contract_digest_sha256"]:
        raise MatrixFailure("installed observation oracle digest differs")
    ui = actual["ui"]
    if ui.get("sequence") != sequence or ui.get("unsafe_console_errors") != 0:
        raise MatrixFailure("installed UI sequence or console safety differs")
    if expected["expected_accessible_role"] == "heading" and not ui.get("headings"):
        raise MatrixFailure("installed UI lacks the expected accessible heading")
    if expected["expected_accessible_role"] == "dialog" and ui.get("dialog_count", 0) < 1:
        raise MatrixFailure("installed UI lacks the expected accessible dialog")
    if expected["expected_accessible_role"] == "button" and not ui.get("buttons"):
        raise MatrixFailure("installed UI lacks the expected accessible control")
    combined = observed_text(actual)
    missing_copy = [
        phrase
        for phrase in expected["expected_safe_state_language"]
        if str(phrase).casefold() not in combined
    ]
    if missing_copy:
        raise MatrixFailure("installed UI safe-state language differs")
    expected_status = [
        int(value) for value in expected["expected_http_status"] if str(value).isdigit()
    ]
    actual_status = [int(row["status"]) for row in actual["api"]]
    if expected_status != actual_status:
        raise MatrixFailure("installed authenticated API status sequence differs")


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
) -> dict[str, Any]:
    state = expected["state_id"]
    route = expected["route_id"]
    fake_home = campaign / f"combination-{expected['combination_id'].replace('::', '--')}"
    fake_home.mkdir(mode=0o700)
    database = fake_home / "Library/Application Support/Money Map/data/paycheck-map.sqlite3"
    seed_result = materialize_release_state(database, state)
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
        first = wait_observation(fake_home / "matrix-observation.json", sequence=1)
        compare_observation(expected, first, 1)
        after_open = database_manifest(database)
        if after_open != before:
            raise MatrixFailure("opening the installed route changed the database")
        trigger_reload()
        second = wait_observation(fake_home / "matrix-observation.json", sequence=2)
        compare_observation(expected, second, 2)
        after_reload = database_manifest(database)
        if after_reload != before:
            raise MatrixFailure("reloading the installed route changed the database")
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
        if len([pid for pid, _, command in base.process_rows() if Path(command).name == "money-map-desktop"]) != 1:
            raise MatrixFailure("close and reopen changed single-instance topology")
        base.quit_app()
        shutdown_ms = base.wait_gone(process, sidecars)
        final = database_manifest(database)
        if final != before:
            raise MatrixFailure("close and reopen changed the database")
        session_files = [
            path
            for path in fake_home.rglob("*")
            if path.is_file() and ("session" in path.name.lower() or path.suffix == ".sock")
        ]
        if lock.exists() or session_files:
            raise MatrixFailure("installed matrix cleanup differs")
        return {
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
            "ready_ms": ready_ms,
            "shutdown_ms": shutdown_ms,
            "network_classification": "authenticated-ephemeral-ipv4-loopback-only",
            "external_connections": 0,
            "cleanup": "pass",
        }
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)


def qualification(args: argparse.Namespace) -> Path:
    source_commit = args.expected_source_commit
    candidate_sha256 = args.expected_candidate_sha256
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
    for row in combinations:
        row["contract_digest_sha256"] = digest
    if args.limit is not None:
        combinations = combinations[: args.limit]
    evidence = ROOT / ".slice6-evidence" / args.campaign_id
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
                    )
                )
            except (MatrixFailure, base.QualificationFailure) as error:
                report["first_failed_combination"] = expected["combination_id"]
                report["failure_classification"] = str(error)
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
