#!/usr/bin/env python3
"""Independently validate and resolve the synthetic Slice 6 state-route oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/synthetic/v1_2_1"
SOURCE = FIXTURE_ROOT / "release-state-contract.json"
STATES = FIXTURE_ROOT / "states.json"
INVENTORY = FIXTURE_ROOT / "release-qualification.json"

EXPECTED_STATES = (
    "empty",
    "loading",
    "unavailable",
    "partial_coverage",
    "recoverable_failure",
    "stale_evidence",
    "complete_current",
    "large_history",
    "negative_recurring_cash_flow",
    "cash_below_protected_floor",
    "missing_source_coverage",
    "no_life_lab_profile",
    "profile_without_goals",
    "one_enabled_goal_with_floor",
    "multiple_enabled_goals_ambiguous",
    "stale_saved_scenario",
    "completed_goal",
)
EXPECTED_ROUTES = (
    "cash-flow",
    "goals",
    "activity",
    "accounts",
    "income",
    "wealth",
    "retirement",
    "lab",
    "overview",
    "add-account",
    "data-home",
    "diagnostics",
    "reports",
)
REQUIRED_COMBINATION_FIELDS = {
    "combination_id",
    "applicable",
    "setup_driver",
    "expected_database_facts",
    "expected_database_manifest",
    "expected_api_endpoints",
    "expected_http_status",
    "expected_stable_response_fields",
    "expected_evidence_classification",
    "expected_currentness",
    "expected_primary_result",
    "expected_next_action",
    "expected_safe_state_language",
    "expected_accessible_role",
    "expected_accessible_status",
    "expected_enabled_operations",
    "expected_disabled_operations",
    "expected_write_count_on_open",
    "expected_after_reload",
    "expected_network_classification",
    "forbidden_material",
    "authority_refs",
}
DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]{2,4}$")
FORBIDDEN_SOURCE_TOKENS = (
    "candidate_output",
    "record_expected",
    "update_snapshot",
    "golden_from_candidate",
    "datetime.now",
    "date.today",
    "time.time",
)


class ContractError(ValueError):
    """The independent fixture authority is incomplete or contradictory."""


def reject_float(value: str) -> None:
    raise ContractError(f"binary floating-point value is forbidden: {value}")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), parse_float=reject_float)
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain an object")
    return value


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise ContractError(f"{label} must be an exact decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ContractError(f"{label} is not a valid decimal") from error


def validate_no_floats(value: object, path: str = "$") -> None:
    if isinstance(value, float):
        raise ContractError(f"binary floating-point value at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            validate_no_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_no_floats(item, f"{path}[{index}]")


def validate_state_reconciliation(state: dict[str, Any]) -> None:
    totals = state.get("expected_exact_totals")
    if not isinstance(totals, dict):
        raise ContractError(f"state {state.get('id')} lacks expected_exact_totals")
    for key, value in totals.items():
        decimal(value, f"{state['id']}.expected_exact_totals.{key}")
    for equation in state.get("reconciliations", []):
        if not isinstance(equation, dict):
            raise ContractError(f"state {state['id']} has invalid reconciliation")
        result = equation.get("result")
        terms = equation.get("terms")
        operators = equation.get("operators")
        if (
            not isinstance(result, str)
            or not isinstance(terms, list)
            or not isinstance(operators, list)
        ):
            raise ContractError(f"state {state['id']} has incomplete reconciliation")
        if len(terms) != len(operators) + 1:
            raise ContractError(f"state {state['id']} reconciliation arity differs")
        current = decimal(totals[terms[0]], f"{state['id']}.{terms[0]}")
        for operator, term in zip(operators, terms[1:], strict=True):
            operand = decimal(totals[term], f"{state['id']}.{term}")
            if operator == "+":
                current += operand
            elif operator == "-":
                current -= operand
            else:
                raise ContractError(f"state {state['id']} has unsupported operator")
        if current != decimal(totals[result], f"{state['id']}.{result}"):
            raise ContractError(f"state {state['id']} reconciliation failed: {equation['id']}")


def validate_seed_summary(state: dict[str, Any], fixture_state: dict[str, Any]) -> None:
    summary = fixture_state.get("source_summary")
    totals = state["expected_exact_totals"]
    if not isinstance(summary, dict):
        raise ContractError(f"state {state['id']} lacks a source summary")

    def available(name: str) -> Decimal | None:
        value = summary.get(name)
        return None if value is None else decimal(value, f"states.json:{state['id']}.{name}")

    cash = available("accessible_cash")
    investments = available("accessible_investments")
    retirement = available("retirement_assets")
    money_in = available("effective_monthly_take_home")
    money_out = available("observed_monthly_outflow")
    if (
        cash is not None
        and investments is not None
        and retirement is not None
        and cash + investments + retirement != decimal(totals["assets"], f"{state['id']}.assets")
    ):
        raise ContractError(f"state {state['id']} seed assets differ from expectations")
    money_in_key = "monthly_money_in" if "monthly_money_in" in totals else "money_in"
    money_out_key = "monthly_money_out" if "monthly_money_out" in totals else "money_out"
    if money_in is not None and money_in != decimal(
        totals[money_in_key], f"{state['id']}.{money_in_key}"
    ):
        raise ContractError(f"state {state['id']} seed money-in differs from expectations")
    if money_out is not None and money_out != decimal(
        totals[money_out_key], f"{state['id']}.{money_out_key}"
    ):
        raise ContractError(f"state {state['id']} seed money-out differs from expectations")
    if (
        state["id"] == "missing_source_coverage"
        and retirement is not None
        and retirement
        != decimal(totals["known_retirement_assets"], f"{state['id']}.known_retirement_assets")
    ):
        raise ContractError("missing-source seed retirement assets differ from expectations")


def materialize(
    source: Path = SOURCE,
    states_path: Path = STATES,
    inventory_path: Path = INVENTORY,
) -> dict[str, Any]:
    contract = read_json(source)
    states_fixture = read_json(states_path)
    inventory = read_json(inventory_path)
    validate_no_floats(contract)
    raw_text = source.read_text(encoding="utf-8").lower()
    for token in FORBIDDEN_SOURCE_TOKENS:
        if token in raw_text:
            raise ContractError(f"forbidden candidate or wall-clock dependency: {token}")
    if tuple(inventory.get("product_states", ())) != EXPECTED_STATES:
        raise ContractError("release state inventory changed")
    if tuple(inventory.get("routes", ())) != EXPECTED_ROUTES:
        raise ContractError("release route inventory changed")
    if contract.get("contract") != "money-map-slice6-release-state-authority-v1":
        raise ContractError("fixture contract version differs")
    fixed = contract.get("fixed_authority")
    if not isinstance(fixed, dict) or fixed.get("database_revision") != "0009_goal_persistence":
        raise ContractError("fixed database revision differs")
    authorities = contract.get("authority_registry")
    if not isinstance(authorities, dict) or not authorities:
        raise ContractError("authority registry is empty")
    fixture_rows = states_fixture.get("states", [])
    fixture_ids = [item.get("id") for item in fixture_rows]
    if set(fixture_ids) != set(EXPECTED_STATES) or len(fixture_ids) != len(set(fixture_ids)):
        raise ContractError("states.json must define the exact 17-state inventory once")
    routes = contract.get("routes")
    states = contract.get("states")
    state_defaults = contract.get("state_defaults")
    if not isinstance(routes, dict) or tuple(routes) != EXPECTED_ROUTES:
        raise ContractError("route authority must define the exact ordered inventory")
    if not isinstance(states, dict) or tuple(states) != EXPECTED_STATES:
        raise ContractError("state authority must define the exact ordered inventory")
    if not isinstance(state_defaults, dict):
        raise ContractError("state defaults are unavailable")
    fixtures_by_id = {item["id"]: item for item in fixture_rows}

    combinations: list[dict[str, Any]] = []
    for state_id in EXPECTED_STATES:
        raw_state = states[state_id]
        if not isinstance(raw_state, dict) or raw_state.get("id") != state_id:
            raise ContractError(f"state authority differs for {state_id}")
        state = deep_merge(state_defaults, raw_state)
        validate_state_reconciliation(state)
        validate_seed_summary(state, fixtures_by_id[state_id])
        state_refs = state.get("authority_refs")
        if not isinstance(state_refs, list) or not state_refs:
            raise ContractError(f"state {state_id} lacks authority references")
        defaults = state.get("combination_defaults")
        overrides = state.get("route_overrides", {})
        if not isinstance(defaults, dict) or not isinstance(overrides, dict):
            raise ContractError(f"state {state_id} has invalid inheritance")
        unknown_overrides = set(overrides) - set(EXPECTED_ROUTES)
        if unknown_overrides:
            raise ContractError(f"state {state_id} has unknown route overrides")
        for route_id in EXPECTED_ROUTES:
            route = routes[route_id]
            if not isinstance(route, dict) or route.get("id") != route_id:
                raise ContractError(f"route authority differs for {route_id}")
            resolved = deep_merge(route["combination_defaults"], defaults)
            resolved = deep_merge(resolved, overrides.get(route_id, {}))
            resolved["combination_id"] = f"{state_id}::{route_id}"
            resolved["state_id"] = state_id
            resolved["route_id"] = route_id
            resolved["setup_driver"] = deepcopy(state["setup_driver"])
            resolved["setup_policy"] = deepcopy(state["setup_policy"])
            resolved["cleanup_requirements"] = deepcopy(state["cleanup_requirements"])
            resolved["expected_database_facts"] = {
                "revision": fixed["database_revision"],
                "table_counts": deepcopy(state["expected_table_counts"]),
                "logical_facts": deepcopy(state["expected_logical_facts"]),
                "exact_totals": deepcopy(state["expected_exact_totals"]),
                "provenance": deepcopy(state["expected_provenance"]),
            }
            resolved["expected_database_manifest"] = {
                "scope": "declared-table-counts-logical-facts-and-exact-totals",
                "stable_before_and_after_open": True,
            }
            resolved["authority_refs"] = list(
                dict.fromkeys(
                    [*route["authority_refs"], *state_refs, *resolved.get("authority_refs", [])]
                )
            )
            missing = REQUIRED_COMBINATION_FIELDS - set(resolved)
            if missing:
                raise ContractError(f"{state_id}::{route_id} lacks {sorted(missing)}")
            if resolved["expected_write_count_on_open"] != 0:
                raise ContractError(f"{state_id}::{route_id} view-open write count must be zero")
            if not resolved["authority_refs"]:
                raise ContractError(f"{state_id}::{route_id} lacks authority")
            unknown_refs = set(resolved["authority_refs"]) - set(authorities)
            if unknown_refs:
                raise ContractError(f"{state_id}::{route_id} has unknown authority references")
            combinations.append(resolved)

    if len(combinations) != 221 or len({row["combination_id"] for row in combinations}) != 221:
        raise ContractError("resolved state-route matrix is not exactly 221 unique combinations")
    result: dict[str, Any] = {
        "contract": "money-map-slice6-resolved-state-route-oracle-v1",
        "source_contract": contract["contract"],
        "fixed_authority": fixed,
        "source_fixture_digests": {
            "states_sha256": hashlib.sha256(canonical_bytes(states_fixture)).hexdigest(),
            "inventory_sha256": hashlib.sha256(canonical_bytes(inventory)).hexdigest(),
        },
        "state_count": 17,
        "route_count": 13,
        "combination_count": 221,
        "combinations": combinations,
    }
    digest = hashlib.sha256(canonical_bytes(result)).hexdigest()
    result["contract_digest_sha256"] = digest
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--digest-only", action="store_true")
    args = parser.parse_args()
    result = materialize(args.source)
    if args.digest_only:
        print(result["contract_digest_sha256"])
    elif args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(result))
    else:
        print(canonical_bytes(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
