from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import paycheck_map.v2_contracts as v2_contracts
import paycheck_map.v21_contracts as v21_contracts
from paycheck_map.v21_contracts import (
    GoalGapPreviewRequest,
    MarginState,
    V21ContractVector,
    V21EvidencedMoney,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = PROJECT_ROOT / "examples" / "synthetic" / "money-map-v2.1-contracts.json"


def matrix() -> dict[str, object]:
    return cast(dict[str, object], json.loads(VECTOR_PATH.read_text()))


def merge_patch(base: object, patch: object) -> object:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = {str(key): copy.deepcopy(value) for key, value in base.items()}
        for key, value in patch.items():
            existing = merged.get(str(key))
            merged[str(key)] = (
                merge_patch(existing, value) if existing is not None else copy.deepcopy(value)
            )
        return merged
    return copy.deepcopy(patch)


def materialize(base: object, case: object) -> dict[str, object]:
    case_values = cast(dict[str, object], case)
    payload = cast(dict[str, object], merge_patch(base, case_values["patch"]))
    payload["vector_id"] = case_values.get("vector_id", case_values.get("case_id"))
    payload["covers"] = case_values["covers"]
    return payload


def test_all_synthetic_vectors_validate_and_cover_the_complete_state_matrix() -> None:
    values = matrix()
    base = values["base_vector"]
    valid_cases = cast(list[object], values["valid_cases"])
    invalid_cases = cast(list[object], values["invalid_cases"])

    vectors = [V21ContractVector.model_validate(materialize(base, case)) for case in valid_cases]
    covered = {tag for vector in vectors for tag in vector.covers}
    covered.update(
        tag
        for case in invalid_cases
        for tag in cast(list[str], cast(dict[str, object], case)["covers"])
    )

    assert covered == set(cast(list[str], values["required_states"]))
    assert {vector.cash_flow.period.kind.value for vector in vectors} >= {
        "all_imported_history",
        "trailing_12_months",
        "year_to_date",
        "custom_range",
    }
    assert {vector.recurring.margin_state for vector in vectors} >= {
        MarginState.NEGATIVE,
        MarginState.ZERO,
        MarginState.POSITIVE,
        MarginState.UNAVAILABLE,
    }
    assert {vector.goal.goal_state.value for vector in vectors} >= {
        "active",
        "completed",
        "expired_unfinished",
        "cash_floor_breach",
    }

    serialized = [vector.model_dump(mode="json") for vector in vectors]
    assert all(item["contract_version"] == "money-map-v2.1-contract-v1" for item in serialized)


@pytest.mark.parametrize("case_index", [0, 1])
def test_invalid_synthetic_vectors_fail_for_the_named_contract(case_index: int) -> None:
    values = matrix()
    invalid_case = cast(list[object], values["invalid_cases"])[case_index]
    case_values = cast(dict[str, object], invalid_case)

    with pytest.raises(ValidationError, match=str(case_values["expected_error"])):
        V21ContractVector.model_validate(materialize(values["base_vector"], invalid_case))


@pytest.mark.parametrize(
    "amount",
    ["1.0", "01.00", "$1.00", "NaN", "Infinity", "1.001", 1.0, 1, Decimal("NaN")],
)
def test_money_rejects_malformed_nonfinite_and_non_string_boundaries(amount: object) -> None:
    with pytest.raises(ValidationError):
        V21EvidencedMoney.model_validate(
            {
                "amount": amount,
                "evidence": "observed",
                "source_refs": ["synthetic:money"],
                "derivation": None,
                "unavailable_reason": None,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("additional_reservation", 1.25),
        ("additional_reservation", 1),
        ("additional_reservation", "1.0"),
        ("monthly_spending_reduction", "-0.01"),
        ("monthly_after_tax_income", "NaN"),
        ("target_date", "2035-02-31"),
    ],
)
def test_goal_gap_request_rejects_binary_malformed_negative_and_invalid_date(
    field: str, value: object
) -> None:
    payload: dict[str, object] = {
        "additional_reservation": "0.00",
        "monthly_spending_reduction": "0.00",
        "monthly_after_tax_income": "0.00",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        GoalGapPreviewRequest.model_validate(payload)


def test_goal_gap_request_defaults_to_zero_without_inventing_a_target_date() -> None:
    request = GoalGapPreviewRequest()

    assert request.target_date is None
    assert request.additional_reservation == Decimal("0.00")
    assert request.monthly_spending_reduction == Decimal("0.00")
    assert request.monthly_after_tax_income == Decimal("0.00")
    assert request.model_dump(mode="json")["additional_reservation"] == "0.00"


def test_current_relationship_keeps_historical_net_separate_from_recurring_margin() -> None:
    values = matrix()
    first_case = cast(list[object], values["valid_cases"])[0]
    vector = V21ContractVector.model_validate(materialize(values["base_vector"], first_case))

    assert vector.cash_flow.totals.net_cash_flow.amount == Decimal("-805.00")
    assert vector.recurring.current_monthly_margin.amount == Decimal("-5602.98")
    assert vector.recurring.stabilization_gap.amount == Decimal("5602.98")
    assert vector.goal.required_goal_pace.amount == Decimal("39003.52")
    assert vector.combined_monthly_improvement.amount == Decimal("44606.50")
    assert (
        vector.cash_flow.totals.net_cash_flow.amount
        != vector.recurring.current_monthly_margin.amount
    )


def test_transfer_heavy_vector_excludes_transfers_from_money_in_and_out() -> None:
    values = matrix()
    transfer_case = cast(list[object], values["valid_cases"])[1]
    vector = V21ContractVector.model_validate(materialize(values["base_vector"], transfer_case))

    assert vector.cash_flow.totals.money_in.amount == Decimal("0.00")
    assert vector.cash_flow.totals.money_out.amount == Decimal("0.00")
    assert vector.cash_flow.transfers_excluded.matched_owned_account_amount.amount == Decimal(
        "10000.00"
    )
    assert vector.cash_flow.transfers_excluded.internal_transfer_amount.amount == Decimal("2000.00")


def test_goal_pace_contract_reuses_the_existing_actual_calendar_helpers() -> None:
    assert v21_contracts.remaining_funding_months is v2_contracts.remaining_funding_months
    assert v21_contracts.required_funding_pace is v2_contracts.required_funding_pace

    values = matrix()
    comparison_case = cast(list[object], values["valid_cases"])[5]
    vector = V21ContractVector.model_validate(materialize(values["base_vector"], comparison_case))
    assert vector.goal.target_date.isoformat() == "2035-11-18"
    assert vector.goal.funding_months == Decimal("111.277419354839")
    assert vector.goal.required_goal_pace.amount == Decimal("107.84")


def test_unavailable_dependencies_do_not_erase_independent_period_or_goal_facts() -> None:
    values = matrix()
    missing_payroll_case = cast(list[object], values["valid_cases"])[2]
    vector = V21ContractVector.model_validate(
        materialize(values["base_vector"], missing_payroll_case)
    )

    assert vector.cash_flow.totals.net_cash_flow.amount == Decimal("0.00")
    assert vector.goal.required_goal_pace.amount == Decimal("1000.00")
    assert vector.recurring.current_monthly_margin.amount is None
    assert vector.combined_monthly_improvement.amount is None
