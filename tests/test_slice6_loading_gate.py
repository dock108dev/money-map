from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
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


def test_overview_observation_requires_nonempty_get_only_inventory() -> None:
    campaign = load_campaign()
    expected = loading_expected()
    expected["combination_id"] = "loading::overview"
    expected["route_id"] = "overview"
    actual = pending_observation()
    actual["route"] = "overview"
    actual["request_inventory"] = [
        {"method": "GET", "endpoint": "/api/overview", "count": 1},
        {"method": "GET", "endpoint": "/api/accounts", "count": 1},
    ]
    campaign.compare_observation(expected, actual, 1, phase="pending")
    actual["request_inventory"][0]["method"] = "POST"
    with pytest.raises(campaign.MatrixFailure, match="not read-only"):
        campaign.compare_observation(expected, actual, 1, phase="pending")
    actual["request_inventory"] = []
    with pytest.raises(campaign.MatrixFailure, match="not read-only"):
        campaign.compare_observation(expected, actual, 1, phase="pending")


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


def test_database_mutation_failure_reports_only_sanitized_tables_and_requests() -> None:
    campaign = load_campaign()
    before = {
        "tables": {
            "goal_check_ins": {"count": 0, "rows_sha256": "a" * 64},
            "goal_check_in_components": {"count": 0, "rows_sha256": "b" * 64},
        },
        "table_counts": {"goal_check_ins": 0, "goal_check_in_components": 0},
        "logical_digest_sha256": "c" * 64,
    }
    after = {
        "tables": {
            "goal_check_ins": {"count": 1, "rows_sha256": "d" * 64},
            "goal_check_in_components": {"count": 12, "rows_sha256": "e" * 64},
        },
        "table_counts": {"goal_check_ins": 1, "goal_check_in_components": 12},
        "logical_digest_sha256": "f" * 64,
    }
    observation = {
        "request_inventory": [
            {"method": "GET", "endpoint": "/api/v2/goals/primary", "count": 1},
            {"method": "POST", "endpoint": "/api/v2/goals/check-ins/backfill", "count": 1},
            {"method": "GET", "endpoint": "/api/private?identifier=unsafe", "count": 1},
        ]
    }
    with pytest.raises(campaign.DatabaseMutationFailure) as raised:
        campaign.require_database_unchanged(
            before,
            after,
            classification="opening the installed route changed the database",
            phase="initial-settled",
            observation=observation,
        )
    failure = raised.value
    assert failure.affected_tables == {
        "goal_check_in_components": {
            "before_count": 0,
            "after_count": 12,
            "count_delta": 12,
            "rows_changed": True,
        },
        "goal_check_ins": {
            "before_count": 0,
            "after_count": 1,
            "count_delta": 1,
            "rows_changed": True,
        },
    }
    assert failure.request_inventory == [
        {"method": "GET", "endpoint": "/api/v2/goals/primary", "count": 1},
        {"method": "POST", "endpoint": "/api/v2/goals/check-ins/backfill", "count": 1},
    ]


def test_observer_failure_is_reported_immediately_and_sanitized() -> None:
    campaign = load_campaign()
    with tempfile.TemporaryDirectory(prefix="money-map-observer-test-", dir="/private/tmp") as root:
        observation = Path(root) / "matrix-observation.json"
        failure_path = Path(root) / "matrix-observer-failure-1.json"
        failure = {
            "contract": campaign.OBSERVER_FAILURE_CONTRACT,
            "result": "failed",
            "state": "loading",
            "route": "overview",
            "contract_digest_sha256": DIGEST,
            "candidate_sha256": "a" * 64,
            "source_commit": "b" * 40,
            "sequence": 1,
            "requested_route": "overview",
            "expected_phase": "settled",
            "last_completed_stage": "awaiting-route",
            "failure_classification": "observer-timeout",
            "hash_matched": True,
            "global_loading_present": False,
            "route_local_loading_present": True,
            "native_invocation_accepted": True,
            "timeout_classification": True,
            "raw_paths_retained": False,
            "private_content_retained": False,
        }
        failure_path.write_text(json.dumps(failure), encoding="utf-8")
        started = time.monotonic()
        with pytest.raises(campaign.ObserverFailure) as raised:
            campaign.wait_observation(observation, sequence=1, timeout=1)
        assert time.monotonic() - started < 0.5
        assert raised.value.failure == failure
        assert str(Path(root)) not in json.dumps(raised.value.failure)


def test_stale_failure_sequence_cannot_satisfy_reload_observation() -> None:
    campaign = load_campaign()
    with tempfile.TemporaryDirectory(prefix="money-map-observer-test-", dir="/private/tmp") as root:
        observation = Path(root) / "matrix-observation.json"
        stale = {
            "contract": campaign.OBSERVER_FAILURE_CONTRACT,
            "result": "failed",
            "state": "loading",
            "route": "overview",
            "contract_digest_sha256": DIGEST,
            "candidate_sha256": "a" * 64,
            "source_commit": "b" * 40,
            "sequence": 1,
            "requested_route": "overview",
            "expected_phase": "settled",
            "last_completed_stage": "awaiting-route",
            "failure_classification": "observer-timeout",
            "hash_matched": True,
            "global_loading_present": False,
            "route_local_loading_present": True,
            "native_invocation_accepted": True,
            "timeout_classification": True,
            "raw_paths_retained": False,
            "private_content_retained": False,
        }
        (Path(root) / "matrix-observer-failure-1.json").write_text(
            json.dumps(stale), encoding="utf-8"
        )
        with pytest.raises(campaign.MatrixFailure, match="was not produced"):
            campaign.wait_observation(observation, sequence=2, timeout=0.1)
