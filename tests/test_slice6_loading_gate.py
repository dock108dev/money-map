from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "scripts/qualify_slice6_campaign_b.py"
DIGEST = "a8d34d04e5c56f42470fb74a6ea8dc287aa8b20ecc4237a6da76c2432202ae45"


def load_campaign() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slice6_campaign_b_loading", CAMPAIGN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def loading_expected() -> dict[str, Any]:
    return {
        "combination_id": "loading::cash-flow",
        "state_id": "loading",
        "route_id": "cash-flow",
        "contract_digest_sha256": DIGEST,
        "expected_accessible_role": "heading",
        "expected_safe_state_language": ["Loading accounts…"],
        "expected_http_status": ["200", "200"],
        "setup_driver": {
            "type": "transient_bounded_loading_injection",
            "seed": "complete-current-v1",
            "gate": "qualification-response-gate-v1",
            "release": "explicit_harness_release",
            "timeout_ms": 5000,
        },
    }


def pending_observation() -> dict[str, Any]:
    return {
        "state": "loading",
        "route": "cash-flow",
        "contract_digest_sha256": DIGEST,
        "ui": {
            "sequence": 1,
            "phase": "pending",
            "headings": ["Loading accounts…"],
            "statuses": [],
            "alerts": [],
            "buttons": [],
            "messages": [],
            "loading_visible": True,
            "loading_busy": True,
            "loading_live": "polite",
            "dialog_count": 0,
            "unsafe_console_errors": 0,
        },
        "api": [
            {"status": 200},
            {"status": 200},
        ],
    }


def test_pending_loading_assertion_is_distinct_from_settled_evidence() -> None:
    campaign = load_campaign()
    expected = loading_expected()
    pending = pending_observation()
    campaign.validate_setup_driver(expected)
    campaign.compare_observation(expected, pending, 1, phase="pending")

    pending["ui"]["buttons"] = ["Generate report"]
    with pytest.raises(campaign.MatrixFailure, match="completed or mutable"):
        campaign.compare_observation(expected, pending, 1, phase="pending")


def test_loading_driver_rejects_unsealed_or_non_loading_gate_plans() -> None:
    campaign = load_campaign()
    expected = loading_expected()
    expected["setup_driver"] = {**expected["setup_driver"], "timeout_ms": 5001}
    with pytest.raises(campaign.MatrixFailure, match="driver differs"):
        campaign.validate_setup_driver(expected)


def test_harness_release_is_private_bounded_and_contains_no_runtime_secret() -> None:
    campaign = load_campaign()
    expected = loading_expected()
    with tempfile.TemporaryDirectory(prefix="money-map-gate-test-", dir="/private/tmp") as root:
        fake_home = Path(root)
        challenge = {
            "contract": campaign.GATE_CHALLENGE_CONTRACT,
            "combination_id": "loading::cash-flow",
            "runtime_generation": 1,
            "gate_generation": 1,
            "challenge": "a" * 64,
        }
        challenge_path = fake_home / "qualification-response-gate.challenge.json"
        challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
        challenge_path.chmod(0o600)
        campaign.release_loading_gate(
            fake_home,
            expected,
            runtime_generation=1,
            gate_generation=1,
        )
        release_path = fake_home / "qualification-response-gate.release.json"
        assert release_path.stat().st_mode & 0o777 == 0o600
        assert release_path.stat().st_nlink == 1
        retained = release_path.read_text(encoding="utf-8")
        assert str(fake_home) not in retained
        assert "session" not in retained
        assert "nonce" not in retained
        assert os.path.islink(release_path) is False
