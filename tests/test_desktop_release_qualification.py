from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from .conftest import PROJECT_ROOT


def module() -> Any:
    path = PROJECT_ROOT / "scripts/qualify_desktop_release.py"
    spec = importlib.util.spec_from_file_location("qualify_desktop_release", path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_contract_is_frozen_to_installed_slice6_identity() -> None:
    loaded = module()
    assert loaded.VERSION == "2.1.0"
    assert loaded.SCHEMA == "0009_goal_persistence"
    assert loaded.TEAM == "E3G5D247ZN"
    assert loaded.BUNDLE_ID == "com.moneymap.desktop"
    assert loaded.DMG_NAME == "Money Map-Slice5-arm64.dmg"
    assert not any(
        path.name.startswith("0010") for path in (PROJECT_ROOT / "alembic/versions").iterdir()
    )


@pytest.mark.parametrize(
    ("digest", "commit"),
    [("wrong", "a" * 40), ("a" * 64, "wrong"), ("A" * 64, "b" * 40)],
)
def test_cli_identity_rejects_malformed_values(digest: str, commit: str) -> None:
    loaded = module()
    with pytest.raises(loaded.QualificationFailure):
        loaded.validate_cli_identity(digest, commit)


def test_runtime_environment_is_minimal_and_credential_free(tmp_path: Path) -> None:
    loaded = module()
    env = loaded.clean_runtime_env(tmp_path)
    assert env == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "MONEY_MAP_ACCEPTANCE_FAKE_HOME": str(tmp_path),
    }
    assert "PYTHONPATH" not in env
    assert "NODE_PATH" not in env


def test_bundle_manifest_rejects_wrong_commit_version_schema_team_or_entitlements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = module()
    app = tmp_path / "Money Map.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    import plistlib

    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": loaded.BUNDLE_ID,
                "CFBundleShortVersionString": loaded.VERSION,
                "CFBundleVersion": loaded.VERSION,
                "LSMinimumSystemVersion": loaded.MINIMUM_MACOS,
            }
        )
    )
    (app / "Contents/MacOS/money-map-desktop").write_bytes(b"synthetic")
    valid = {
        "source_commit": "a" * 40,
        "runtime_version": loaded.VERSION,
        "schema_revision": loaded.SCHEMA,
        "bundle_identifier": loaded.BUNDLE_ID,
        "target_architecture": "aarch64-apple-darwin",
        "signing": {
            "class": "Apple Development",
            "hardened_runtime": False,
            "team": loaded.TEAM,
            "timestamp": "none",
        },
        "entitlements": [],
    }
    monkeypatch.setattr(loaded, "run", lambda *args, **kwargs: "a" * 40)
    loaded.verify_bundle(app, valid, "a" * 40)
    for key, wrong in [
        ("source_commit", "b" * 40),
        ("runtime_version", "2.1.1"),
        ("schema_revision", "0010_forbidden"),
        ("target_architecture", "x86_64-apple-darwin"),
    ]:
        changed = {**valid, key: wrong}
        with pytest.raises(loaded.QualificationFailure):
            loaded.verify_bundle(app, changed, "a" * 40)
    changed = {**valid, "entitlements": ["com.apple.security.network.server"]}
    with pytest.raises(loaded.QualificationFailure):
        loaded.verify_bundle(app, changed, "a" * 40)


def test_hash_mismatch_stops_before_mount_or_evidence_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = module()
    dmg = tmp_path / loaded.DMG_NAME
    dmg.write_bytes(b"synthetic unexpected artifact")
    monkeypatch.setattr(loaded, "validate_artifact_path", lambda _path: None)
    args = SimpleNamespace(
        dmg=str(dmg),
        expected_sha256="0" * 64,
        expected_source_commit="a" * 40,
        campaign_id="must-not-exist",
        launch_cycles=1,
    )
    with pytest.raises(loaded.QualificationFailure, match="before mount"):
        loaded.qualification(args)


def test_sanitized_report_allows_boolean_cleanup_facts_but_rejects_raw_details() -> None:
    loaded = module()
    loaded.sanitize_report(
        {"session_material_clean": True, "listener_class": "ephemeral-ipv4-loopback"}
    )
    for report in [
        {"pid": 123},
        {"port": 43123},
        {"path": str(PROJECT_ROOT)},
        {"session": "raw"},
    ]:
        with pytest.raises(loaded.QualificationFailure):
            loaded.sanitize_report(report)


def test_wait_gone_reaps_the_harness_owned_native_process() -> None:
    loaded = module()
    process = subprocess.Popen(["/usr/bin/true"])
    assert loaded.wait_gone(process, [], timeout=1) >= 0
    assert process.returncode == 0


def test_wait_gone_does_not_trust_a_reused_sidecar_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = module()
    process = subprocess.Popen(["/usr/bin/true"])
    process.wait()
    monkeypatch.setattr(loaded, "process_rows", lambda: [(43123, 1, "/usr/bin/unrelated")])
    assert loaded.wait_gone(process, [43123], timeout=0.1) >= 0


def test_cleanup_failure_labels_are_sanitized_and_specific() -> None:
    source = (PROJECT_ROOT / "scripts/qualify_desktop_release.py").read_text()
    for label in ("writer-lock", "session-material", "graceful-stop", "single-instance"):
        assert f'("{label}",' in source


def test_required_campaign_matrix_is_checked_in_and_complete() -> None:
    matrix = json.loads(
        (PROJECT_ROOT / "tests/fixtures/synthetic/v1_2_1/release-qualification.json").read_text()
    )
    assert matrix["contract"] == "money-map-slice6-state-matrix-v1"
    assert len(matrix["product_states"]) == 17
    assert len(matrix["routes"]) == 13
    assert len(matrix["mutations"]) >= 17
    assert len(matrix["migration_and_recovery"]) >= 35
    assert len(matrix["runtime_failures"]) >= 25
    assert len(matrix["accessibility_and_zoom"]) >= 12
    assert matrix["owner_validations_performed"] == []


def test_slice6_evidence_is_ignored() -> None:
    assert ".slice6-evidence/" in (PROJECT_ROOT / ".gitignore").read_text().splitlines()
