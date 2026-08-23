from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORACLE_PATH = PROJECT_ROOT / "scripts/materialize_release_state_contract.py"
CONTRACT_PATH = PROJECT_ROOT / "tests/fixtures/synthetic/v1_2_1/release-state-contract.json"
SCHEMA_PATH = PROJECT_ROOT / "tests/fixtures/synthetic/v1_2_1/release-state-contract.schema.json"
STATES_PATH = PROJECT_ROOT / "tests/fixtures/synthetic/v1_2_1/states.json"
STANDARD_LIBRARY_IMPORTS = {
    "__future__",
    "argparse",
    "copy",
    "decimal",
    "hashlib",
    "json",
    "pathlib",
    "re",
    "typing",
}


def load_oracle() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_state_oracle", ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_variant(tmp_path: Path, mutate: Any) -> Path:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "release-state-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_oracle_materializes_exact_complete_matrix_deterministically() -> None:
    oracle = load_oracle()
    first = oracle.materialize()
    second = oracle.materialize()

    assert first == second
    assert oracle.canonical_bytes(first) == oracle.canonical_bytes(second)
    assert first["state_count"] == 17
    assert first["route_count"] == 13
    assert first["combination_count"] == 221
    combinations = first["combinations"]
    assert len(combinations) == 221
    assert len({row["combination_id"] for row in combinations}) == 221
    assert all(row["authority_refs"] for row in combinations)
    assert all(row["expected_write_count_on_open"] == 0 for row in combinations)
    assert len(first["contract_digest_sha256"]) == 64


def test_oracle_imports_only_standard_library_and_never_production_modules() -> None:
    tree = ast.parse(ORACLE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported <= STANDARD_LIBRARY_IMPORTS
    source = ORACLE_PATH.read_text(encoding="utf-8")
    assert "paycheck_map" not in source
    assert "web.src" not in source
    assert "subprocess" not in imported
    assert "urllib" not in imported
    assert "http" not in imported


def test_contract_and_schema_are_valid_json_without_binary_floats() -> None:
    oracle = load_oracle()
    contract = oracle.read_json(CONTRACT_PATH)
    schema = oracle.read_json(SCHEMA_PATH)
    oracle.validate_no_floats(contract)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["contract"]["const"] == contract["contract"]


def test_seed_fact_drift_without_reconciled_expectation_fails(tmp_path: Path) -> None:
    oracle = load_oracle()
    states = json.loads(STATES_PATH.read_text(encoding="utf-8"))
    complete = next(row for row in states["states"] if row["id"] == "complete_current")
    complete["source_summary"]["effective_monthly_take_home"] = "4200.01"
    changed_states = tmp_path / "states.json"
    changed_states.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(oracle.ContractError, match="seed money-in differs"):
        oracle.materialize(states_path=changed_states)


def test_expectation_without_authority_fails(tmp_path: Path) -> None:
    oracle = load_oracle()

    def mutate(payload: dict[str, Any]) -> None:
        payload["states"]["complete_current"]["authority_refs"] = []

    with pytest.raises(oracle.ContractError, match="lacks authority references"):
        oracle.materialize(write_variant(tmp_path, mutate))


def test_unknown_inheritance_and_binary_float_fail(tmp_path: Path) -> None:
    oracle = load_oracle()

    def unknown_route(payload: dict[str, Any]) -> None:
        payload["states"]["empty"]["route_overrides"]["not-a-route"] = {
            "expected_primary_result": "Invalid"
        }

    with pytest.raises(oracle.ContractError, match="unknown route overrides"):
        oracle.materialize(write_variant(tmp_path / "unknown", unknown_route))

    def binary_float(payload: dict[str, Any]) -> None:
        payload["states"]["large_history"]["setup_driver"]["load_factor"] = 1.5

    with pytest.raises(oracle.ContractError, match="binary floating-point"):
        oracle.materialize(write_variant(tmp_path / "float", binary_float))


def test_all_17_state_drivers_exist_and_existing_nine_meanings_are_retained() -> None:
    payload = json.loads(STATES_PATH.read_text(encoding="utf-8"))
    states = {row["id"]: row for row in payload["states"]}
    assert len(states) == 17
    assert all("driver" in state for state in states.values())
    retained = {
        "negative_recurring_cash_flow": (40, False),
        "cash_below_protected_floor": (50, False),
        "missing_source_coverage": (70, False),
        "no_life_lab_profile": (None, False),
        "profile_without_goals": (None, False),
        "one_enabled_goal_with_floor": (10, False),
        "multiple_enabled_goals_ambiguous": (None, True),
        "stale_saved_scenario": (None, False),
        "completed_goal": (60, False),
    }
    assert {
        state: (
            states[state]["expected_slice_1"]["primary_goal_source_id"],
            states[state]["expected_slice_1"]["requires_primary_selection"],
        )
        for state in retained
    } == retained
