#!/usr/bin/env python3
"""Fail-closed qualification of an exact installed Money Map DMG candidate."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import plistlib
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.1.0"
SCHEMA = "0009_goal_persistence"
TEAM = "E3G5D247ZN"
BUNDLE_ID = "com.moneymap.desktop"
MINIMUM_MACOS = "13.0"
DMG_NAME = "Money Map-Slice5-arm64.dmg"
CONTRACT = "money-map-slice6-installed-qualification-v1"
LAUNCH_CONTRACT = "money-map-installed-attestation-launch-v1"
NATIVE_RESULT_CONTRACT = "money-map-native-attestation-result-v1"
SECRET_ENV = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|CREDENTIAL|ACCESS_KEY|PRIVATE_KEY)($|_)|"
    r"^(PLAID|AWS|AZURE|GCP|GH_|GITHUB_|OPENAI_|ANTHROPIC_|APPLE_)"
)
HEX_64 = re.compile(r"[0-9a-f]{64}")
HEX_40 = re.compile(r"[0-9a-f]{40}")


class QualificationFailure(RuntimeError):
    """A safe, user-actionable qualification failure."""


@dataclass(frozen=True)
class CycleResult:
    cycle: int
    ready_ms: int
    shutdown_ms: int
    app_instances: int
    sidecar_tree_processes: int
    listeners: int
    listener_class: str
    external_connections: int
    writer_lock_ready: bool
    writer_lock_clean: bool
    session_material_clean: bool
    graceful_stop: bool
    second_launch_single_instance: bool
    synthetic_roots_attested: bool
    production_mode_refused: bool
    attestation_campaign_id: str
    attestation_contract: str
    root_roles: tuple[str, ...]
    schema_attested: bool
    integrity_attested: bool
    foreign_keys_attested: bool
    database_identity_stable: bool
    engine_database_identity: bool
    permissions_attested: bool
    ownership_attested: bool
    hard_links_attested: bool


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signed_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(sha256(path).encode() + b"\n")
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        label = Path(command[0]).name
        raise QualificationFailure(f"{label} failed during installed-artifact qualification")
    return result.stdout.strip() if capture else ""


def launch_contract(
    fake_home: Path,
    *,
    campaign_id: str,
    nonce: str,
    candidate_sha256: str,
    source_commit: str,
    mode: str = "acceptance-synthetic-v1",
) -> dict[str, object]:
    application = fake_home / "Library/Application Support/Money Map"
    return {
        "contract": LAUNCH_CONTRACT,
        "schema_version": 1,
        "campaign_id": campaign_id,
        "nonce": nonce,
        "mode": mode,
        "campaign_root": str(fake_home),
        "application_root": str(application),
        "database_path": str(application / "data/paycheck-map.sqlite3"),
        "writer_lock_path": str(application / ".money-map-writer.lock"),
        "cache_root": str(fake_home / "Library/Caches/com.moneymap.desktop"),
        "log_root": str(fake_home / "Library/Logs/Money Map"),
        "result_path": str(fake_home / "native-attestation-result.json"),
        "candidate_sha256": candidate_sha256,
        "source_commit": source_commit,
    }


def clean_runtime_env(fake_home: Path, contract: dict[str, object]) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(fake_home),
        "MONEY_MAP_ACCEPTANCE_FAKE_HOME": str(fake_home),
        "MONEY_MAP_QUALIFICATION_CONTRACT": json.dumps(
            contract, sort_keys=True, separators=(",", ":")
        ),
    }
    if any(SECRET_ENV.search(name) for name in env):
        raise QualificationFailure("credential-bearing runtime environment name was retained")
    return env


def validate_cli_identity(expected_hash: str, expected_commit: str) -> None:
    if not HEX_64.fullmatch(expected_hash):
        raise QualificationFailure("expected DMG SHA-256 must be 64 lowercase hexadecimal bytes")
    if not HEX_40.fullmatch(expected_commit):
        raise QualificationFailure("expected source commit must be 40 lowercase hexadecimal bytes")


def validate_artifact_path(dmg: Path) -> None:
    resolved = dmg.resolve(strict=True)
    if resolved.name != DMG_NAME or not resolved.is_file() or resolved.is_symlink():
        raise QualificationFailure("DMG path or filename is outside the accepted contract")
    if (
        resolved.is_relative_to(Path("/Applications")) or resolved.is_relative_to(Path.home())
    ) and not resolved.is_relative_to(ROOT):
        raise QualificationFailure("owner or Applications paths are forbidden qualification inputs")


def require_no_existing_runtime() -> None:
    for pattern in ("money-map-desktop", "money-map-sidecar"):
        result = subprocess.run(["/usr/bin/pgrep", "-x", pattern], capture_output=True, check=False)
        if result.returncode == 0:
            raise QualificationFailure(
                "an existing Money Map runtime would contaminate the campaign"
            )


def codesign_details(path: Path) -> str:
    result = subprocess.run(
        ["/usr/bin/codesign", "-dv", "--verbose=4", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise QualificationFailure("code-signing identity could not be inspected")
    return result.stderr


def verify_signature(path: Path, *, deep: bool) -> None:
    command = ["/usr/bin/codesign", "--verify", "--strict"]
    if deep:
        command.append("--deep")
    command.extend(
        [
            '-R=anchor apple generic and certificate leaf[subject.OU] = "E3G5D247ZN"',
            str(path),
        ]
    )
    run(command)
    details = codesign_details(path)
    if f"TeamIdentifier={TEAM}" not in details or "Signature=adhoc" in details:
        raise QualificationFailure("artifact is ad hoc or signed by the wrong team")


def verify_zero_entitlements(app: Path) -> None:
    result = subprocess.run(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app)],
        text=True,
        capture_output=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if "<key>" in output:
        raise QualificationFailure("candidate contains an unexpected entitlement")


def verify_bundle(app: Path, manifest: dict[str, Any], expected_commit: str) -> None:
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    expected = {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": MINIMUM_MACOS,
    }
    if any(info.get(key) != value for key, value in expected.items()):
        raise QualificationFailure("bundle identity, version, or deployment target differs")
    required_manifest = {
        "source_commit": expected_commit,
        "runtime_version": VERSION,
        "schema_revision": SCHEMA,
        "bundle_identifier": BUNDLE_ID,
        "target_architecture": "aarch64-apple-darwin",
    }
    if any(manifest.get(key) != value for key, value in required_manifest.items()):
        raise QualificationFailure(
            "build manifest source, version, schema, or architecture differs"
        )
    if manifest.get("signing") != {
        "class": "Apple Development",
        "hardened_runtime": False,
        "team": TEAM,
        "timestamp": "none",
    }:
        raise QualificationFailure("build manifest signing policy differs")
    if manifest.get("entitlements") != []:
        raise QualificationFailure("build manifest declares entitlements")
    executable = app / "Contents/MacOS/money-map-desktop"
    strings = run(["/usr/bin/strings", str(executable)], capture=True)
    if expected_commit not in strings:
        raise QualificationFailure(
            "embedded About source identity does not equal the candidate commit"
        )


def verify_architecture(app: Path, manifest_root: Path) -> int:
    native_count = 0
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        description = run(["/usr/bin/file", "-b", str(path)], capture=True)
        if "Mach-O" not in description:
            continue
        if run(["/usr/bin/lipo", "-archs", str(path)], capture=True) != "arm64":
            raise QualificationFailure("candidate includes non-thin-arm64 native code")
        verify_signature(path, deep=False)
        native_count += 1
    inventory = json.loads((manifest_root / "nested-code.json").read_text())
    if not inventory or any(
        row.get("architecture") != "arm64"
        or row.get("team_identifier") != TEAM
        or row.get("verification") != "strict-pass"
        or row.get("entitlements") != []
        for row in inventory
    ):
        raise QualificationFailure(
            "nested native-code inventory differs from the accepted contract"
        )
    return len(inventory)


def top_level_entries(mount: Path) -> list[str]:
    return sorted(path.name for path in mount.iterdir() if path.name != ".DS_Store")


def process_rows() -> list[tuple[int, int, str]]:
    output = run(["/bin/ps", "-axo", "pid=,ppid=,comm="], capture=True)
    rows: list[tuple[int, int, str]] = []
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            rows.append((int(fields[0]), int(fields[1]), fields[2]))
    return rows


def descendants(parent: int, rows: list[tuple[int, int, str]]) -> list[int]:
    found: list[int] = []
    frontier = [parent]
    while frontier:
        current = frontier.pop()
        children = [pid for pid, ppid, _ in rows if ppid == current]
        found.extend(children)
        frontier.extend(children)
    return found


def wait_for_runtime(app_pid: int, lock: Path, timeout: float = 45) -> tuple[list[int], int]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        rows = process_rows()
        children = descendants(app_pid, rows)
        sidecars = [
            pid
            for pid, _, command in rows
            if pid in children and Path(command).name == "money-map-sidecar"
        ]
        if len(sidecars) == 2 and lock.is_file():
            return sidecars, round((time.monotonic() - started) * 1000)
        time.sleep(0.1)
    raise QualificationFailure("installed app did not reach the one-sidecar ready topology")


def socket_observation(pids: list[int]) -> tuple[int, int]:
    pid_list = ",".join(str(pid) for pid in pids)
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-a", "-p", pid_list, "-iTCP"],
        text=True,
        capture_output=True,
        check=False,
    )
    lines = result.stdout.splitlines()[1:]
    listeners = [line for line in lines if "(LISTEN)" in line and "127.0.0.1:" in line]
    if any(":8765 " in line or ":8765 (" in line for line in lines):
        raise QualificationFailure("forbidden port 8765 was touched")
    external = [line for line in lines if "(ESTABLISHED)" in line and "127.0.0.1" not in line]
    return len(listeners), len(external)


def wait_native_result(
    path: Path, *, expected: str, context: str = "attestation", timeout: float = 45
) -> dict[str, Any]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 8192:
            try:
                result = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if not isinstance(result, dict) or any(not isinstance(key, str) for key in result):
                raise QualificationFailure(f"native launcher {context} result was rejected")
            result = cast(dict[str, Any], result)
            if result.get("contract") != NATIVE_RESULT_CONTRACT or result.get("result") != expected:
                raise QualificationFailure(f"native launcher {context} result was rejected")
            return result
        time.sleep(0.05)
    raise QualificationFailure(f"native launcher {context} result was not produced")


def require_native_attestation(result: dict[str, Any], contract: dict[str, object]) -> None:
    required_true = (
        "database",
        "writer_lock",
        "cache",
        "logs",
        "containment",
        "symlink_checks",
        "readiness_ordering",
        "ui_gating",
        "main_window_absent_at_result",
        "permissions",
        "ownership",
        "hard_links",
        "schema",
        "integrity",
        "foreign_keys",
        "database_identity_stable",
        "engine_database_identity",
    )
    if (
        result.get("campaign_id") != contract["campaign_id"]
        or result.get("mode") != "acceptance-synthetic-v1"
        or result.get("candidate_sha256") != contract["candidate_sha256"]
        or result.get("source_commit") != contract["source_commit"]
        or result.get("attestation_contract") != "money-map-installed-root-attestation-v1"
        or result.get("root_roles")
        != [
            "campaign",
            "application-data",
            "database",
            "writer-lock",
            "cache",
            "safe-log",
        ]
        or any(result.get(name) is not True for name in required_true)
        or result.get("first_unmet_requirement") is not None
        or result.get("safe_error_required") is not False
    ):
        raise QualificationFailure("native launcher did not attest the installed synthetic roots")


def stop_probe(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    time.sleep(1.0)


def prove_production_refusal(
    app: Path, campaign: Path, candidate_sha256: str, source_commit: str
) -> bool:
    fake_home = campaign / "production-refusal"
    fake_home.mkdir(mode=0o700)
    contract = launch_contract(
        fake_home,
        campaign_id=secrets.token_hex(16),
        nonce=secrets.token_hex(32),
        candidate_sha256=candidate_sha256,
        source_commit=source_commit,
        mode="production-v1",
    )
    process = subprocess.Popen(
        [str(app / "Contents/MacOS/money-map-desktop")],
        cwd=campaign,
        env=clean_runtime_env(fake_home, contract),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        result = wait_native_result(
            fake_home / "native-attestation-result.json",
            expected="failed",
            context="production-refusal",
        )
        application = fake_home / "Library/Application Support/Money Map"
        rows = process_rows()
        if application.exists() or descendants(process.pid, rows):
            raise QualificationFailure("production qualification reached a financial data location")
        return result.get("first_unmet_requirement") == "qualification-contract"
    finally:
        stop_probe(process)


def prove_missing_contract_refusal(app: Path, campaign: Path) -> bool:
    fake_home = campaign / "missing-contract-refusal"
    fake_home.mkdir(mode=0o700)
    process = subprocess.Popen(
        [str(app / "Contents/MacOS/money-map-desktop")],
        cwd=campaign,
        env={"PATH": "/usr/bin:/bin", "HOME": str(fake_home)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return process.returncode != 0 and not any(fake_home.iterdir())
    finally:
        stop_probe(process)


def prove_attestation_failure_cleanup(
    app: Path, campaign: Path, candidate_sha256: str, source_commit: str
) -> bool:
    fake_home = campaign / "attestation-failure"
    database = fake_home / "Library/Application Support/Money Map/data/paycheck-map.sqlite3"
    fake_home.mkdir(mode=0o700)
    database.parent.mkdir(mode=0o700, parents=True)
    for directory in (
        fake_home / "Library",
        fake_home / "Library/Application Support",
        fake_home / "Library/Application Support/Money Map",
        database.parent,
    ):
        directory.chmod(0o700)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0010_forbidden')")
    database.chmod(0o600)
    contract = launch_contract(
        fake_home,
        campaign_id=secrets.token_hex(16),
        nonce=secrets.token_hex(32),
        candidate_sha256=candidate_sha256,
        source_commit=source_commit,
    )
    process = subprocess.Popen(
        [str(app / "Contents/MacOS/money-map-desktop")],
        cwd=campaign,
        env=clean_runtime_env(fake_home, contract),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        result = wait_native_result(
            fake_home / "native-attestation-result.json",
            expected="failed",
            context="failure-cleanup",
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and descendants(process.pid, process_rows()):
            time.sleep(0.1)
        rows = process_rows()
        descendants_alive = descendants(process.pid, rows)
        lock = fake_home / "Library/Application Support/Money Map/.money-map-writer.lock"
        session_files = [
            path
            for path in fake_home.rglob("*")
            if path.is_file() and ("session" in path.name.lower() or path.suffix == ".sock")
        ]
        return (
            process.poll() is None
            and not descendants_alive
            and not lock.exists()
            and not session_files
            and result.get("first_unmet_requirement") == "installed-root-attestation"
            and result.get("main_window_absent_at_result") is True
            and result.get("safe_error_required") is True
        )
    finally:
        stop_probe(process)


def quit_app() -> None:
    run(
        [
            "/usr/bin/osascript",
            "-e",
            'tell application id "com.moneymap.desktop" to quit',
        ]
    )


def wait_gone(
    process: subprocess.Popen[bytes], sidecar_pids: list[int], timeout: float = 15
) -> int:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        app_alive = process.poll() is None
        rows = process_rows()
        sidecars_alive = any(
            pid in sidecar_pids and Path(command).name == "money-map-sidecar"
            for pid, _, command in rows
        )
        if not app_alive and not sidecars_alive:
            return round((time.monotonic() - started) * 1000)
        time.sleep(0.1)
    raise QualificationFailure("normal quit left an installed-app process alive")


def run_cycle(
    app: Path,
    campaign: Path,
    cycle: int,
    *,
    second_launch: bool,
    candidate_sha256: str,
    source_commit: str,
    production_mode_refused: bool,
) -> CycleResult:
    fake_home = campaign / f"home-{cycle:02d}"
    fake_home.mkdir(mode=0o700)
    contract = launch_contract(
        fake_home,
        campaign_id=secrets.token_hex(16),
        nonce=secrets.token_hex(32),
        candidate_sha256=candidate_sha256,
        source_commit=source_commit,
    )
    env = clean_runtime_env(fake_home, contract)
    executable = app / "Contents/MacOS/money-map-desktop"
    process = subprocess.Popen(
        [str(executable)],
        cwd=campaign,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    lock = fake_home / "Library/Application Support/Money Map/.money-map-writer.lock"
    try:
        native_result = wait_native_result(
            fake_home / "native-attestation-result.json",
            expected="pass",
            context="cycle-attestation",
        )
        require_native_attestation(native_result, contract)
        sidecars, ready_ms = wait_for_runtime(process.pid, lock)
        listeners, external = socket_observation(sidecars)
        if listeners != 1 or external != 0:
            raise QualificationFailure("runtime listener or external-connection boundary failed")
        single_instance = True
        if second_launch:
            second = subprocess.Popen(
                [str(executable)],
                cwd=campaign,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                second.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise QualificationFailure(
                    "second launch did not activate the existing app"
                ) from error
            # Launch Services can return from the activation request before the
            # Apple event has been fully delivered.  Do not race that event with
            # the normal-quit event below.
            time.sleep(0.5)
            rows = process_rows()
            app_count = sum(Path(command).name == "money-map-desktop" for _, _, command in rows)
            current_sidecars = descendants(process.pid, rows)
            sidecar_count = sum(
                pid in current_sidecars and Path(command).name == "money-map-sidecar"
                for pid, _, command in rows
            )
            single_instance = app_count == 1 and sidecar_count == 2
            if not single_instance:
                raise QualificationFailure("second launch created another app, sidecar, or writer")
        quit_app()
        shutdown_ms = wait_gone(process, sidecars)
        for _ in range(50):
            if not lock.exists():
                break
            time.sleep(0.1)
        session_files = [
            path
            for path in fake_home.rglob("*")
            if path.is_file() and ("session" in path.name.lower() or path.suffix == ".sock")
        ]
        log = fake_home / "Library/Logs/Money Map/desktop-events.jsonl"
        graceful = log.is_file() and '"code":"MM-DESKTOP-STOP"' in log.read_text()
        result = CycleResult(
            cycle=cycle,
            ready_ms=ready_ms,
            shutdown_ms=shutdown_ms,
            app_instances=1,
            sidecar_tree_processes=2,
            listeners=listeners,
            listener_class="ephemeral-ipv4-loopback",
            external_connections=external,
            writer_lock_ready=True,
            writer_lock_clean=not lock.exists(),
            session_material_clean=not session_files,
            graceful_stop=graceful,
            second_launch_single_instance=single_instance,
            synthetic_roots_attested=True,
            production_mode_refused=production_mode_refused,
            attestation_campaign_id=str(contract["campaign_id"]),
            attestation_contract=str(native_result["attestation_contract"]),
            root_roles=tuple(str(role) for role in native_result["root_roles"]),
            schema_attested=bool(native_result["schema"]),
            integrity_attested=bool(native_result["integrity"]),
            foreign_keys_attested=bool(native_result["foreign_keys"]),
            database_identity_stable=bool(native_result["database_identity_stable"]),
            engine_database_identity=bool(native_result["engine_database_identity"]),
            permissions_attested=bool(native_result["permissions"]),
            ownership_attested=bool(native_result["ownership"]),
            hard_links_attested=bool(native_result["hard_links"]),
        )
        failed_cleanup = [
            name
            for name, passed in (
                ("writer-lock", result.writer_lock_clean),
                ("session-material", result.session_material_clean),
                ("graceful-stop", result.graceful_stop),
                ("single-instance", result.second_launch_single_instance),
            )
            if not passed
        ]
        if failed_cleanup:
            raise QualificationFailure("normal quit cleanup failed: " + ", ".join(failed_cleanup))
        # A successful process/lock cleanup is necessary but not sufficient for
        # the macOS application service to have retired the prior instance.
        # Give that bounded service transition time to settle before relaunch.
        time.sleep(1.0)
        return result
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)


def sanitize_report(report: dict[str, Any]) -> None:
    encoded = json.dumps(report, sort_keys=True)
    forbidden = [
        str(ROOT),
        str(Path.home()),
        "/private/tmp",
        '"pid":',
        '"port":',
        '"session":',
    ]
    if any(marker in encoded for marker in forbidden):
        raise QualificationFailure("qualification report contains a forbidden private detail")


def qualification(args: argparse.Namespace) -> Path:
    validate_cli_identity(args.expected_sha256, args.expected_source_commit)
    dmg = Path(args.dmg).expanduser()
    validate_artifact_path(dmg)
    if sha256(dmg) != args.expected_sha256:
        raise QualificationFailure("DMG SHA-256 differs; qualification stopped before mount")
    require_no_existing_runtime()
    manifest_root = dmg.parent
    manifest_path = manifest_root / "manifest.json"
    if not manifest_path.is_file():
        raise QualificationFailure("candidate build manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("dmg", {}).get("sha256") != args.expected_sha256:
        raise QualificationFailure("manifest DMG identity differs")
    evidence: Path = ROOT / ".slice6-evidence" / str(args.campaign_id)
    if evidence.exists():
        raise QualificationFailure("campaign evidence ID already exists")
    evidence.mkdir(parents=True, mode=0o700)
    campaign = Path(tempfile.mkdtemp(prefix="money-map-slice6.", dir="/private/tmp"))
    campaign.chmod(0o700)
    mount = campaign / "mount"
    installed = campaign / "Applications"
    mount.mkdir(mode=0o700)
    installed.mkdir(mode=0o700)
    mounted = False
    report: dict[str, Any] = {
        "contract": CONTRACT,
        "result": "failed",
        "campaign_id": args.campaign_id,
        "source_commit": args.expected_source_commit,
        "runtime_version": VERSION,
        "schema_revision": SCHEMA,
        "dmg": {"name": DMG_NAME, "sha256": args.expected_sha256, "size": dmg.stat().st_size},
        "production_keychain_accessed": False,
        "provider_contacted": False,
        "port_8765_touched": False,
        "applications_touched": False,
        "owner_validations_performed": [],
    }
    try:
        verify_signature(dmg, deep=False)
        run(
            [
                "/usr/bin/hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-mountpoint",
                str(mount),
                str(dmg),
            ]
        )
        mounted = True
        if top_level_entries(mount) != ["Applications", "Money Map.app"]:
            raise QualificationFailure("DMG contents differ from the exact two-entry layout")
        applications_link = mount / "Applications"
        if not applications_link.is_symlink() or os.readlink(applications_link) != "/Applications":
            raise QualificationFailure("DMG Applications link differs")
        app = installed / "Money Map.app"
        run(["/usr/bin/ditto", "--norsrc", str(mount / "Money Map.app"), str(app)])
        run(["/usr/bin/hdiutil", "detach", str(mount)])
        mounted = False
        verify_signature(app, deep=True)
        if signed_tree_digest(app) != manifest.get("app", {}).get("sha256"):
            raise QualificationFailure("copied signed-app tree differs from the build manifest")
        app_size = sum(path.stat().st_size for path in app.rglob("*") if path.is_file())
        if app_size != manifest.get("app", {}).get("size"):
            raise QualificationFailure("copied signed-app size differs from the build manifest")
        verify_zero_entitlements(app)
        verify_bundle(app, manifest, args.expected_source_commit)
        nested_count = verify_architecture(app, manifest_root)
        run(
            [
                sys.executable,
                str(ROOT / "scripts/check_desktop_artifact.py"),
                str(app),
            ],
            timeout=300,
        )
        production_mode_refused = prove_production_refusal(
            app, campaign, args.expected_sha256, args.expected_source_commit
        )
        if not production_mode_refused:
            raise QualificationFailure("native launcher did not refuse production qualification")
        missing_contract_refused = prove_missing_contract_refusal(app, campaign)
        if not missing_contract_refused:
            raise QualificationFailure("qualification candidate accepted a missing synthetic home")
        attestation_failure_clean = prove_attestation_failure_cleanup(
            app, campaign, args.expected_sha256, args.expected_source_commit
        )
        if not attestation_failure_clean:
            raise QualificationFailure("failed attestation did not cleanly gate the financial UI")
        cycles: list[CycleResult] = []
        for cycle in range(1, args.launch_cycles + 1):
            try:
                cycles.append(
                    run_cycle(
                        app,
                        campaign,
                        cycle,
                        second_launch=True,
                        candidate_sha256=args.expected_sha256,
                        source_commit=args.expected_source_commit,
                        production_mode_refused=production_mode_refused,
                    )
                )
            except QualificationFailure as error:
                report["completed_cycles"] = [asdict(item) for item in cycles]
                report["failed_cycle"] = cycle
                raise QualificationFailure(f"cycle {cycle}: {error}") from error
        report.update(
            {
                "result": "pass",
                "artifact": {
                    "strict_signature": True,
                    "team": TEAM,
                    "architecture": "thin-arm64",
                    "zero_entitlements": True,
                    "nested_native_entries": nested_count,
                    "about_source_identity": args.expected_source_commit,
                    "mounted_read_only": True,
                    "mounted_entries": ["Applications", "Money Map.app"],
                },
                "cycles": [asdict(cycle) for cycle in cycles],
                "owner_data_accessed": False,
                "failed_attestation_cleanup": attestation_failure_clean,
                "missing_contract_refused": missing_contract_refused,
                "lifecycle_bounds": {
                    "cycles": len(cycles),
                    "maximum_ready_ms": max(cycle.ready_ms for cycle in cycles),
                    "maximum_shutdown_ms": max(cycle.shutdown_ms for cycle in cycles),
                },
            }
        )
        sanitize_report(report)
        (evidence / "foundation-and-endurance.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        return evidence
    except BaseException as error:
        report["failure"] = (
            str(error) if isinstance(error, QualificationFailure) else "unexpected campaign failure"
        )
        sanitize_report(report)
        (evidence / "failure.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        raise
    finally:
        if mounted:
            subprocess.run(
                ["/usr/bin/hdiutil", "detach", str(mount)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        shutil.rmtree(campaign, ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("dmg")
    value.add_argument("--expected-sha256", required=True)
    value.add_argument("--expected-source-commit", required=True)
    value.add_argument("--campaign-id", required=True)
    value.add_argument("--launch-cycles", type=int, default=10, choices=range(1, 11))
    return value


def main() -> None:
    args = parser().parse_args()
    try:
        evidence = qualification(args)
    except QualificationFailure as error:
        raise SystemExit(f"Slice 6 qualification failed closed: {error}") from None
    print(f"Slice 6 installed foundation passed: {evidence.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
