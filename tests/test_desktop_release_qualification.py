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


def test_contract_is_frozen_to_v3_candidate_identity() -> None:
    loaded = module()
    assert loaded.VERSION == "3.0.0-beta.1"
    assert loaded.SCHEMA == "0009_goal_persistence"
    assert loaded.TEAM == "E3G5D247ZN"
    assert loaded.BUNDLE_ID == "com.moneymap.desktop"
    assert loaded.DMG_NAME == "Money Map-3.0.0-beta.1-arm64.dmg"
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
    contract = loaded.launch_contract(
        tmp_path,
        campaign_id="a" * 32,
        nonce="b" * 64,
        candidate_sha256="c" * 64,
        source_commit="d" * 40,
    )
    env = loaded.clean_runtime_env(tmp_path, contract)
    assert env == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "MONEY_MAP_ACCEPTANCE_FAKE_HOME": str(tmp_path),
        "MONEY_MAP_QUALIFICATION_CONTRACT": json.dumps(
            contract, sort_keys=True, separators=(",", ":")
        ),
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


def test_launcher_contract_derives_exact_nonce_bound_roots(tmp_path: Path) -> None:
    loaded = module()
    contract = loaded.launch_contract(
        tmp_path,
        campaign_id="a" * 32,
        nonce="b" * 64,
        candidate_sha256="c" * 64,
        source_commit="d" * 40,
    )
    application = tmp_path / "Library/Application Support/Money Map"
    assert contract == {
        "contract": loaded.LAUNCH_CONTRACT,
        "schema_version": 1,
        "campaign_id": "a" * 32,
        "nonce": "b" * 64,
        "mode": "acceptance-synthetic-v1",
        "campaign_root": str(tmp_path),
        "application_root": str(application),
        "database_path": str(application / "data/paycheck-map.sqlite3"),
        "writer_lock_path": str(application / ".money-map-writer.lock"),
        "cache_root": str(tmp_path / "Library/Caches/com.moneymap.desktop"),
        "log_root": str(tmp_path / "Library/Logs/Money Map"),
        "result_path": str(tmp_path / "native-attestation-result.json"),
        "candidate_sha256": "c" * 64,
        "source_commit": "d" * 40,
    }


def test_native_result_is_the_attestation_authority(tmp_path: Path) -> None:
    loaded = module()
    contract = loaded.launch_contract(
        tmp_path,
        campaign_id="a" * 32,
        nonce="b" * 64,
        candidate_sha256="c" * 64,
        source_commit="d" * 40,
    )
    result = {
        "contract": loaded.NATIVE_RESULT_CONTRACT,
        "result": "pass",
        "campaign_id": "a" * 32,
        "mode": "acceptance-synthetic-v1",
        "candidate_sha256": "c" * 64,
        "source_commit": "d" * 40,
        "attestation_contract": "money-map-installed-root-attestation-v1",
        "root_roles": [
            "campaign",
            "application-data",
            "database",
            "writer-lock",
            "cache",
            "safe-log",
        ],
        "database": True,
        "writer_lock": True,
        "cache": True,
        "logs": True,
        "containment": True,
        "symlink_checks": True,
        "readiness_ordering": True,
        "ui_gating": True,
        "main_window_absent_at_result": True,
        "safe_error_required": False,
        "permissions": True,
        "ownership": True,
        "hard_links": True,
        "schema": True,
        "integrity": True,
        "foreign_keys": True,
        "database_identity_stable": True,
        "engine_database_identity": True,
        "first_unmet_requirement": None,
    }
    result_path = tmp_path / "native-attestation-result.json"
    result_path.write_text(json.dumps(result))
    loaded.require_native_attestation(
        loaded.wait_native_result(result_path, expected="pass"), contract
    )
    result["database"] = False
    with pytest.raises(loaded.QualificationFailure, match="did not attest"):
        loaded.require_native_attestation(result, contract)


def test_financial_webview_is_constructed_only_after_native_startup_passes() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    setup = source[source.index(".setup(|app|") : source.index(".on_menu_event")]
    assert setup.index("controller.start_initial().is_ok()") < setup.index("build_main_window")
    assert "visible(false)" not in setup
    safe_capability = json.loads(
        (PROJECT_ROOT / "desktop/src-tauri/capabilities/safe-error.json").read_text()
    )
    main_capability = json.loads(
        (PROJECT_ROOT / "desktop/src-tauri/capabilities/default.json").read_text()
    )
    assert "allow-desktop-qualification-observer-failure" in main_capability["permissions"]
    artifact_scanner = (PROJECT_ROOT / "scripts/check_desktop_artifact.py").read_text()
    assert '"allow-desktop-qualification-observer-failure"' in artifact_scanner
    assert "allow-desktop-fetch" not in safe_capability["permissions"]
    assert "allow-desktop-qualification-observe" not in safe_capability["permissions"]
    assert "allow-desktop-qualification-observer-failure" not in safe_capability["permissions"]
    assert all(
        forbidden not in safe_capability["permissions"]
        for forbidden in (
            "allow-desktop-select-import",
            "allow-desktop-report-action",
            "allow-desktop-export-diagnostics",
        )
    )
    combined_frontend = "\n".join(
        path.read_text() for path in (PROJECT_ROOT / "web/src").rglob("*") if path.is_file()
    )
    assert "MONEY_MAP_ATTEST" not in combined_frontend
    assert "MONEY_MAP_QUALIFICATION_CONTRACT" not in combined_frontend
    assert "database_path" not in combined_frontend
    assert "writer_lock_path" not in combined_frontend


def test_matrix_observer_uses_the_accessible_navigation_label() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    observer = source[source.index("fn qualification_observer_script") :]
    assert 'button.getAttribute("aria-label")' in observer
    assert "buttonLabel(button) === label" in observer


def test_matrix_observer_distinguishes_global_and_route_local_loading() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    observer = source[source.index("fn qualification_observer_script") :]
    assert 'data-qualification-loading="global-dashboard"' in observer
    assert (
        '".loading-state,.goals-loading,.goals-view[aria-busy=\\"true\\"],'
        '.retirement-loading,.cash-flow-busy"' in observer
    )
    assert "!element.matches(globalSelector)" in observer
    assert "new MutationObserver(schedule)" in observer
    assert "setInterval" not in observer
    assert "attempts" not in observer
    assert "window.location.hash === expectedHashes[requestedRoute]" in observer
    assert 'await observe("pending")' in observer
    assert 'await observe("settled")' in observer
    assert (
        'fail(routeControlUnavailable ? "route-control-unavailable" : "observer-timeout", true)'
        in observer
    )
    assert 'fail("native-observation-rejected")' in observer


def test_matrix_observer_accepts_a_route_prefixed_safe_state_heading_for_readiness() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    observer = source[source.index("fn qualification_observer_script") :]
    assert 'text(element).startsWith(heading + " ")' in observer
    assert '"retirement": "Retirement"' in observer


def test_matrix_observer_prioritizes_active_dialog_copy_within_the_privacy_bound() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    observer = source[source.index("fn qualification_observer_script") :]
    assert "const prioritizedValues" in observer
    assert "[...values(prioritySelector, limit), ...values(selector, limit)]" in observer
    assert "combined.indexOf(value) === index" in observer
    assert "messages: prioritizedValues(" in observer
    assert '[role="dialog"] p' in observer
    assert observer.index("messages: prioritizedValues(") < observer.index("64\n              ),")


def test_matrix_observer_waits_for_installed_runtime_before_requesting_a_route() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    observer = source[source.index("fn qualification_observer_script") :]
    readiness_wait = "if (!boundedLoading && !routeRequested && (global || routeLocalLoading()))"
    assert readiness_wait in observer
    assert observer.index(readiness_wait) < observer.index("const button = routeButton();")
    assert 'stage = "awaiting-route";' in observer
    assert "routeControlUnavailable = true;" in observer
    assert (
        'fail(routeControlUnavailable ? "route-control-unavailable" : "observer-timeout", true)'
        in observer
    )
    route_branch = observer[
        observer.index("const button = routeButton();") : observer.index("routeRequested = true;")
    ]
    assert 'fail("route-control-unavailable")' not in route_branch


def test_global_loading_marker_is_exclusive_to_the_sealed_app_gate() -> None:
    source = (PROJECT_ROOT / "web/src/App.tsx").read_text()
    marker = 'data-qualification-loading="global-dashboard"'
    assert source.count(marker) == 1
    marked = source[source.index(marker) - 120 : source.index(marker) + 260]
    assert 'aria-busy="true"' in marked
    assert 'aria-live="polite"' in marked
    assert "Loading accounts…" in marked
    overview_fallback = source[
        source.index("Opening Overview…") - 240 : source.index("Opening Overview…") + 40
    ]
    assert marker not in overview_fallback


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
