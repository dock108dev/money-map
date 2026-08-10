from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

FIXTURE_PATH = Path(__file__).parent / "fixtures/synthetic/v1_2_1/states.json"
REQUIRED_TRAITS = {
    "no_life_lab_profile",
    "profile_without_goals",
    "one_enabled_goal",
    "protected_floor",
    "multiple_enabled_goals",
    "no_unambiguous_primary",
    "stale_saved_scenarios",
    "negative_recurring_cash_flow",
    "cash_below_protected_floor",
    "completed_goal",
    "missing_or_insufficient_source_coverage",
}
MONEY_FIELDS = {
    "current_monthly_outflow",
    "essential_monthly_spend",
    "flexible_monthly_spend",
    "cash_floor",
    "target_amount",
    "reserved_amount",
    "annual_cost",
    "gross_income",
    "net_income",
    "employee_retirement",
    "employer_retirement",
    "stock_plan",
    "essential_spend",
    "flexible_spend",
    "goal_spend",
    "cash",
    "accessible_investments",
    "pretax_retirement",
    "hsa",
    "restricted_assets",
    "debt",
    "investment_result",
    "total_spendable",
    "accessible_cash",
    "retirement_assets",
    "effective_monthly_take_home",
    "observed_monthly_outflow",
}


def fixture_document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def test_all_required_v121_synthetic_states_exist() -> None:
    document = fixture_document()
    states = cast(list[dict[str, Any]], document["states"])
    traits = {trait for state in states for trait in cast(list[str], state["traits"])}

    assert document["fixture_format"] == "money-map-v1.2.1-synthetic-v1"
    assert "invented" in str(document["fixture_origin"]).lower()
    assert traits >= REQUIRED_TRAITS
    assert len(states) == 9
    assert len({state["id"] for state in states}) == len(states)


def test_fixture_rows_match_v121_life_table_shapes_and_exact_money() -> None:
    states = cast(list[dict[str, Any]], fixture_document()["states"])
    for state in states:
        tables = cast(dict[str, list[dict[str, Any]]], state["tables"])
        assert set(tables) == {
            "life_plan_profiles",
            "life_goals",
            "life_scenarios",
            "life_projection_periods",
        }
        for table_rows in tables.values():
            for row in table_rows:
                _assert_exact_money(row)
        _assert_exact_money(cast(dict[str, Any], state["source_summary"]))


def test_fixture_edge_state_expectations_are_unambiguous() -> None:
    states = {
        state["id"]: state for state in cast(list[dict[str, Any]], fixture_document()["states"])
    }
    assert states["no_life_lab_profile"]["tables"]["life_plan_profiles"] == []
    assert states["profile_without_goals"]["tables"]["life_goals"] == []

    single = states["one_enabled_goal_with_floor"]
    assert sum(goal["enabled"] for goal in single["tables"]["life_goals"]) == 1
    assert single["tables"]["life_plan_profiles"][0]["cash_floor"] == "3000.00"

    ambiguous = states["multiple_enabled_goals_ambiguous"]
    assert sum(goal["enabled"] for goal in ambiguous["tables"]["life_goals"]) == 2
    assert ambiguous["expected_slice_1"] == {
        "primary_goal_source_id": None,
        "requires_primary_selection": True,
    }

    stale = states["stale_saved_scenario"]
    assert stale["tables"]["life_scenarios"]
    assert stale["tables"]["life_projection_periods"]

    negative = states["negative_recurring_cash_flow"]["source_summary"]
    assert Decimal(negative["observed_monthly_outflow"]) > Decimal(
        negative["effective_monthly_take_home"]
    )

    breach = states["cash_below_protected_floor"]
    assert Decimal(breach["source_summary"]["accessible_cash"]) < Decimal(
        breach["tables"]["life_plan_profiles"][0]["cash_floor"]
    )

    completed_goal = states["completed_goal"]["tables"]["life_goals"][0]
    assert completed_goal["reserved_amount"] == completed_goal["target_amount"]

    missing = states["missing_source_coverage"]["source_summary"]
    assert missing["coverage"] == "insufficient"
    assert missing["accessible_cash"] is None


def _assert_exact_money(value: object, field: str | None = None) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_exact_money(item, str(key))
    elif isinstance(value, list):
        for item in value:
            _assert_exact_money(item, field)
    elif field in MONEY_FIELDS and value is not None:
        assert isinstance(value, str), f"{field} must be an exact decimal string"
        assert re.fullmatch(r"-?\d+\.\d{2}", value), f"{field} is not exact cents"
