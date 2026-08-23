from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import PROJECT_ROOT


def load_packaging_module() -> Any:
    path = PROJECT_ROOT / "scripts/package_desktop_release.py"
    spec = importlib.util.spec_from_file_location("package_desktop_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sidecar_builder_module() -> Any:
    path = PROJECT_ROOT / "scripts/build_signed_sidecar.py"
    spec = importlib.util.spec_from_file_location("build_signed_sidecar", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_contract_is_frozen_to_v3_candidate_identity() -> None:
    module = load_packaging_module()
    assert module.VERSION == "3.0.0-beta.1"
    assert module.PYTHON_VERSION == "3.0.0b1"
    assert module.SCHEMA == "0009_goal_persistence"
    assert module.TARGET == "aarch64-apple-darwin"
    assert module.TEAM == "E3G5D247ZN"
    assert module.IDENTIFIER == "com.moneymap.desktop"
    assert module.ARTIFACT_NAME == "Money Map-3.0.0-beta.1-arm64.dmg"
    assert "0010" not in {path.name for path in (PROJECT_ROOT / "alembic/versions").iterdir()}


def test_native_exit_request_owns_runtime_shutdown_before_process_exit() -> None:
    source = (PROJECT_ROOT / "desktop/src-tauri/src/main.rs").read_text()
    assert "RunEvent::ExitRequested { api, .. } =>" in source
    exit_handler = source.split("RunEvent::ExitRequested { api, .. } =>", 1)[1]
    exit_handler = exit_handler.split("RunEvent::Exit =>", 1)[0]
    assert "api.prevent_exit();" in exit_handler
    assert "controller.shutdown();" in exit_handler
    assert "handle.exit(0);" in exit_handler


def test_release_builder_embeds_the_exact_source_commit_in_about() -> None:
    source = (PROJECT_ROOT / "scripts/package_desktop_release.py").read_text()
    assert 'env["MONEY_MAP_BUILD_COMMIT"] = args.commit' in source
    assert '"MONEY_MAP_REQUIRE_QUALIFICATION": "1"' in source


def test_packaged_shutdown_uses_a_private_control_descriptor() -> None:
    rust = (PROJECT_ROOT / "desktop/src-tauri/src/runtime.rs").read_text()
    sidecar = (PROJECT_ROOT / "src/paycheck_map/desktop_sidecar.py").read_text()
    assert '.env("PAYCHECK_MAP_DESKTOP_CONTROL_FD", "63")' in rust
    assert "libc::dup2(control_fd, 63)" in rust
    assert ".stdin(Stdio::null())" in rust
    assert 'os.environ.pop("PAYCHECK_MAP_DESKTOP_CONTROL_FD", "")' in sidecar
    assert "for line in sys.stdin" not in sidecar
    assert '"PAYCHECK_MAP_DESKTOP_OWNER_PID"' in rust
    assert 'os.environ.pop("PAYCHECK_MAP_DESKTOP_OWNER_PID", "")' in sidecar
    assert "await_owner_exit" in sidecar
    assert "libc::SIGTERM" in rust
    assert "signal.signal(signal.SIGTERM, request_graceful_shutdown)" in sidecar


def test_build_environment_removes_credential_bearing_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_packaging_module()
    monkeypatch.setenv("PLAID_CLIENT_SECRET", "privacy-canary")
    monkeypatch.setenv("GITHUB_TOKEN", "privacy-canary")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "privacy-canary")
    monkeypatch.setenv("ORDINARY_BUILD_SETTING", "retained")
    env = module.sanitized_env("Apple Development: Test", "build-a")
    assert "privacy-canary" not in env.values()
    assert env["ORDINARY_BUILD_SETTING"] == "retained"
    assert env["SOURCE_DATE_EPOCH"] == "0"
    assert env["CARGO_NET_OFFLINE"] == "true"


def test_native_build_path_sanitizer_is_length_preserving() -> None:
    module = load_sidecar_builder_module()
    assert bytes.fromhex("cafebabe") in module.MACHO_MAGICS
    original = (
        b"prefix /Users/runner/work/Library/Library/build/file.cc\x00 "
        b"/private/tmp/money-map-build/source/module.rs\x00 C:/Users/Barney suffix"
    )
    sanitized, count = module.sanitize_bytes(original)
    assert count == 2
    assert len(sanitized) == len(original)
    assert b"/Users/runner" not in sanitized
    assert b"/private/tmp/" not in sanitized
    assert sanitized.count(b"/build/input") == 2
    assert b"C:/Users/Barney" in sanitized


def test_wheel_record_normalization_removes_unbundled_console_scripts(tmp_path: Path) -> None:
    module = load_sidecar_builder_module()
    record = tmp_path / "RECORD"
    record.write_text("../../../bin/tool,sha256=vary,123\npackage/module.py,sha256=stable,12\n")
    module.normalize_wheel_record(record)
    assert record.read_text() == "package/module.py,sha256=stable,12\n"


def test_artifact_path_rule_allows_windows_doc_example_only() -> None:
    path = PROJECT_ROOT / "scripts/check_desktop_artifact.py"
    spec = importlib.util.spec_from_file_location("check_desktop_artifact", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._reject_markers("standard-library documentation", b"C:/Users/Barney", ())
    with pytest.raises(SystemExit, match="Forbidden private or development marker"):
        module._reject_markers("native payload", b"built at /Users/runner/work/item", ())


def test_manifest_comparison_accepts_only_equal_functional_payloads(tmp_path: Path) -> None:
    module = load_packaging_module()
    fields: dict[str, Any] = {
        "source_commit": "a" * 40,
        "runtime_version": "3.0.0-beta.1",
        "python_package_version": "3.0.0b1",
        "release_state": "candidate_not_accepted",
        "schema_revision": "0009_goal_persistence",
        "bundle_identifier": "com.moneymap.desktop",
        "target_architecture": "aarch64-apple-darwin",
        "minimum_macos": "13.0",
        "lockfile_hashes": {"uv.lock": "1"},
        "approved_input_hashes": {"pyproject.toml": "2"},
        "entitlements": [],
        "app": {"sha256": "signed-a", "sha256_tree": "payload"},
        "dmg": {"sha256": "container-a"},
    }
    build_a = tmp_path / "a"
    build_b = tmp_path / "b"
    build_a.mkdir()
    build_b.mkdir()
    (build_a / "manifest.json").write_text(json.dumps(fields))
    fields["dmg"]["sha256"] = "container-b"
    fields["app"]["sha256"] = "signed-b"
    (build_b / "manifest.json").write_text(json.dumps(fields))
    output = tmp_path / "comparison.json"
    module.compare(build_a, build_b, output)
    report = json.loads(output.read_text())
    assert report["functional_identity"] is True
    assert report["normalized_unsigned_payload_identity"] is True
    assert report["signed_dmg_byte_identity"] is False
    assert report["unexplained_payload_differences"] == []
    updated = json.loads((build_a / "manifest.json").read_text())
    assert updated["reproducibility"]["result"] == "pass"


def test_manifest_comparison_fails_on_payload_difference(tmp_path: Path) -> None:
    module = load_packaging_module()
    base: dict[str, Any] = {
        "source_commit": "a" * 40,
        "runtime_version": "3.0.0-beta.1",
        "python_package_version": "3.0.0b1",
        "release_state": "candidate_not_accepted",
        "schema_revision": "0009_goal_persistence",
        "bundle_identifier": "com.moneymap.desktop",
        "target_architecture": "aarch64-apple-darwin",
        "minimum_macos": "13.0",
        "lockfile_hashes": {},
        "approved_input_hashes": {},
        "entitlements": [],
        "app": {"sha256": "signed", "sha256_tree": "one"},
        "dmg": {"sha256": "same"},
    }
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "manifest.json").write_text(json.dumps(base))
    base["app"]["sha256_tree"] = "two"
    (b / "manifest.json").write_text(json.dumps(base))
    with pytest.raises(SystemExit, match="reproducibility comparison failed"):
        module.compare(a, b, tmp_path / "comparison.json")
