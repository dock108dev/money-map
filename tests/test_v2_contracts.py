from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from paycheck_map.v2_contracts import (
    ComparisonComponentKind,
    EvidenceClass,
    EvidencedMoney,
    FingerprintGoalConfiguration,
    FingerprintSourceRecord,
    GoalCheckIn,
    GoalCheckInHistory,
    GoalComparison,
    GoalComparisonComponent,
    GoalMilestone,
    GoalPosition,
    LabExperimentSeedKind,
    LifeLabExperimentSeed,
    LifeLabPromotionChange,
    LifeLabPromotionPreview,
    MoneyDerivation,
    PrimaryGoalProgram,
    PromotionField,
    PromotionTarget,
    RetirementGoalInclusion,
    RetirementPath,
    RetirementRunSelection,
    SourceFingerprintMaterial,
    SourceMoneyFact,
    SourceRecordKind,
    check_in_identity,
    contract_milestone,
    remaining_funding_months,
    required_funding_pace,
)

FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def observed(value: str, ref: str = "balance:cash:2026-08-10") -> EvidencedMoney:
    return EvidencedMoney(
        amount=Decimal(value), evidence=EvidenceClass.OBSERVED, source_refs=(ref,)
    )


def entered(value: str, ref: str) -> EvidencedMoney:
    return EvidencedMoney(
        amount=Decimal(value), evidence=EvidenceClass.USER_ENTERED, source_refs=(ref,)
    )


def derived(value: str, derivation: MoneyDerivation, *refs: str) -> EvidencedMoney:
    return EvidencedMoney(
        amount=Decimal(value),
        evidence=EvidenceClass.DERIVED,
        derivation=derivation,
        source_refs=refs or ("position:synthetic",),
    )


def unavailable(
    reason: str = "Synthetic fixture has insufficient source coverage",
) -> EvidencedMoney:
    return EvidencedMoney(
        amount=None, evidence=EvidenceClass.UNAVAILABLE, unavailable_reason=reason
    )


def position(**overrides: object) -> GoalPosition:
    values: dict[str, object] = {
        "goal_program_id": "goal_home",
        "observed_on": date(2026, 8, 10),
        "target_date": date(2027, 8, 9),
        "accessible_cash": observed("6000.00"),
        "accessible_investments": observed("1500.00", "holding:taxable:2026-08-10"),
        "retirement_assets_excluded": observed("18000.00", "balance:retirement:2026-08-10"),
        "tracked_debt": observed("400.00", "balance:debt:2026-08-10"),
        "accessible_now": derived(
            "7500.00",
            MoneyDerivation.ACCESSIBLE_NOW,
            "balance:cash:2026-08-10",
            "holding:taxable:2026-08-10",
        ),
        "protected_cash_floor": entered("3000.00", "goal-config:floor"),
        "available_above_floor": derived(
            "4500.00",
            MoneyDerivation.AVAILABLE_ABOVE_FLOOR,
            "position:accessible_now",
            "goal-config:floor",
        ),
        "reserved_for_goal": entered("2000.00", "goal-config:reserved"),
        "goal_target": entered("14000.00", "goal-config:target"),
        "remaining_target": derived(
            "12000.00",
            MoneyDerivation.REMAINING_TARGET,
            "goal-config:target",
            "goal-config:reserved",
        ),
        "effective_recurring_take_home": derived(
            "4200.00",
            MoneyDerivation.EFFECTIVE_RECURRING_TAKE_HOME,
            "payroll:synthetic",
        ),
        "observed_recurring_outflow": observed("3900.00", "outflow:synthetic-window"),
        "recurring_cash_flow_gap": derived(
            "0.00",
            MoneyDerivation.RECURRING_CASH_FLOW_GAP,
            "payroll:synthetic",
            "outflow:synthetic-window",
        ),
        "funding_months": "12.000000000000",
        "pace_status": "active",
        "required_funding_pace": derived(
            "1000.00",
            MoneyDerivation.REQUIRED_FUNDING_PACE,
            "goal-config:target",
            "goal-config:reserved",
            "calendar:2026-08-10:2027-08-09",
        ),
    }
    values.update(overrides)
    return GoalPosition.model_validate(values)


def test_money_is_decimal_evidence_bound_and_exactly_serialized() -> None:
    value = EvidencedMoney(
        amount=Decimal("10.005"),
        evidence=EvidenceClass.DERIVED,
        source_refs=("source:b", "source:a"),
        derivation=MoneyDerivation.COMPARISON_DELTA,
    )

    assert value.amount == Decimal("10.01")
    assert value.model_dump(mode="json") == {
        "amount": "10.01",
        "evidence": "derived",
        "source_refs": ["source:a", "source:b"],
        "derivation": "comparison_delta",
        "unavailable_reason": None,
    }
    with pytest.raises(ValidationError, match="binary float"):
        EvidencedMoney.model_validate(
            {"amount": 10.01, "evidence": "observed", "source_refs": ["source:a"]}
        )
    with pytest.raises(ValidationError, match="requires source references"):
        EvidencedMoney(amount=Decimal("10.01"), evidence=EvidenceClass.OBSERVED)
    with pytest.raises(ValidationError, match="requires a reason"):
        EvidencedMoney(amount=None, evidence=EvidenceClass.UNAVAILABLE)


def test_primary_goal_contract_exposes_only_an_exclusive_reservation() -> None:
    program = PrimaryGoalProgram(
        goal_program_id="goal_home",
        name="Synthetic home reserve",
        target_date=date(2027, 8, 9),
        target_amount=entered("14000.00", "life_goal:1:target"),
        protected_cash_floor=entered("3000.00", "life_profile:1:cash_floor"),
        reserved_for_goal=entered("2000.00", "life_goal:1:reserved"),
        source_life_goal_id=1,
    )

    assert program.primary is True
    assert program.reservation_policy == "exclusive_primary_goal"
    with pytest.raises(
        ValidationError,
        match="Reserved money cannot exceed",
    ):
        PrimaryGoalProgram.model_validate(
            {
                **program.model_dump(mode="json"),
                "reserved_for_goal": entered("15000.00", "life_goal:1:reserved"),
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PrimaryGoalProgram.model_validate(
            {**program.model_dump(mode="json"), "secondary_goal_allocations": ["goal_other"]}
        )


@pytest.mark.parametrize(
    ("observed_on", "target_date", "expected"),
    [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal("1.000000000000")),
        (date(2026, 1, 16), date(2026, 2, 14), Decimal("1.016129032258")),
        (date(2028, 2, 15), date(2028, 2, 29), Decimal("0.517241379310")),
        (date(2026, 8, 10), date(2026, 8, 10), Decimal("0.032258064516")),
        (date(2026, 8, 11), date(2026, 8, 10), Decimal("0E-12")),
    ],
)
def test_required_pace_calendar_contract(
    observed_on: date, target_date: date, expected: Decimal
) -> None:
    assert remaining_funding_months(observed_on, target_date) == expected


def test_required_pace_rounds_only_the_final_money_and_handles_expiry() -> None:
    assert required_funding_pace(Decimal("1000.00"), date(2026, 1, 1), date(2026, 3, 31)) == (
        Decimal("333.33")
    )
    assert required_funding_pace(Decimal("0.00"), date(2026, 8, 11), date(2026, 8, 10)) == (
        Decimal("0.00")
    )
    assert required_funding_pace(Decimal("1000.00"), date(2026, 8, 11), date(2026, 8, 10)) is None


def test_position_enforces_goal_arithmetic_and_excludes_retirement_assets() -> None:
    result = position()

    assert result.accessible_now.amount == Decimal("7500.00")
    assert result.retirement_assets_excluded.amount == Decimal("18000.00")
    assert result.available_above_floor.amount == Decimal("4500.00")
    assert result.required_funding_pace.amount == Decimal("1000.00")
    assert result.model_dump(mode="json")["funding_months"] == "12.000000000000"
    with pytest.raises(ValidationError, match="component sum"):
        position(accessible_now=derived("25500.00", MoneyDerivation.ACCESSIBLE_NOW))
    with pytest.raises(ValidationError, match="capacity above the protected floor"):
        position(available_above_floor=derived("7500.00", MoneyDerivation.AVAILABLE_ABOVE_FLOOR))


def test_position_preserves_unavailable_source_coverage() -> None:
    result = position(
        accessible_cash=unavailable(),
        accessible_now=unavailable(),
        available_above_floor=unavailable(),
    )

    assert result.accessible_now.evidence is EvidenceClass.UNAVAILABLE
    assert result.available_above_floor.amount is None


def test_milestone_contract_uses_floor_gap_goal_completion_order() -> None:
    floor_breach = position(
        accessible_cash=observed("2000.00"),
        accessible_now=derived("3500.00", MoneyDerivation.ACCESSIBLE_NOW),
        available_above_floor=derived("500.00", MoneyDerivation.AVAILABLE_ABOVE_FLOOR),
    )
    recurring_gap = position(
        observed_recurring_outflow=observed("5000.00", "outflow:synthetic-window"),
        recurring_cash_flow_gap=derived("800.00", MoneyDerivation.RECURRING_CASH_FLOW_GAP),
    )
    complete = position(
        reserved_for_goal=entered("14000.00", "goal-config:reserved"),
        remaining_target=derived("0.00", MoneyDerivation.REMAINING_TARGET),
        pace_status="complete",
        required_funding_pace=derived("0.00", MoneyDerivation.REQUIRED_FUNDING_PACE),
    )

    assert contract_milestone(floor_breach, FINGERPRINT_A).kind == "restore_floor"
    assert contract_milestone(recurring_gap, FINGERPRINT_A).kind == "close_recurring_gap"
    assert contract_milestone(position(), FINGERPRINT_A).kind == "fund_goal"
    assert contract_milestone(complete, FINGERPRINT_A).kind == "goal_complete"


def test_check_ins_are_immutable_and_source_equivalent_duplicates_are_rejected() -> None:
    source_position = position()
    check_in_id = check_in_identity("goal_home", FINGERPRINT_A)
    check_in = GoalCheckIn(
        check_in_id=check_in_id,
        goal_program_id="goal_home",
        source_fingerprint=FINGERPRINT_A,
        effective_observation_date=date(2026, 8, 10),
        position=source_position,
        trigger="synthetic_test",
        created_at=datetime(2026, 8, 10, 16, 30, tzinfo=UTC),
    )

    assert check_in.check_in_id == check_in_identity("goal_home", FINGERPRINT_A)
    with pytest.raises(ValidationError, match="frozen"):
        check_in.created_at = datetime.now(UTC)
    with pytest.raises(ValidationError, match="Source-equivalent"):
        GoalCheckInHistory(check_ins=(check_in, check_in))


def test_comparison_requires_distinct_sources_and_forbids_causal_copy() -> None:
    residual = GoalComparisonComponent(
        component=ComparisonComponentKind.UNEXPLAINED_RESIDUAL,
        change=derived(
            "100.00",
            MoneyDerivation.UNEXPLAINED_RESIDUAL,
            "check-in:previous",
            "check-in:current",
        ),
    )
    comparison = GoalComparison(
        goal_program_id="goal_home",
        previous_check_in_id="1" * 64,
        current_check_in_id="2" * 64,
        previous_source_fingerprint=FINGERPRINT_A,
        current_source_fingerprint=FINGERPRINT_B,
        previous_observation_date=date(2026, 8, 9),
        current_observation_date=date(2026, 8, 10),
        components=(
            GoalComparisonComponent(
                component=ComparisonComponentKind.ACCESSIBLE_NOW,
                change=derived("100.00", MoneyDerivation.COMPARISON_DELTA),
            ),
            GoalComparisonComponent(
                component=ComparisonComponentKind.ACCESSIBLE_CASH,
                change=derived("100.00", MoneyDerivation.COMPARISON_DELTA),
            ),
            residual,
        ),
    )

    assert comparison.components[-1].interpretation == "arithmetic_only"
    with pytest.raises(ValidationError, match="distinct source fingerprints"):
        GoalComparison.model_validate(
            {**comparison.model_dump(mode="json"), "current_source_fingerprint": FINGERPRINT_A}
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GoalComparisonComponent.model_validate(
            {**residual.model_dump(mode="json"), "cause": "Synthetic paycheck caused this"}
        )
    with pytest.raises(ValidationError, match="explicitly evidence-supported"):
        GoalComparisonComponent(
            component=ComparisonComponentKind.SUPPORTED_PAYROLL,
            change=derived("80.00", MoneyDerivation.COMPARISON_DELTA),
        )


def test_retirement_goal_inclusion_is_explicit_and_never_mutates_goals() -> None:
    inclusion = RetirementGoalInclusion(
        goal_program_id="goal_home",
        name="Synthetic home reserve",
        target_date=date(2027, 8, 9),
        goal_source_fingerprint=FINGERPRINT_A,
        target_amount=entered("14000.00", "goal:target"),
        reserved_for_goal=entered("2000.00", "goal:reserved"),
        remaining_target=derived(
            "12000.00",
            MoneyDerivation.RETIREMENT_GOAL_SNAPSHOT,
            "goal:target",
            "goal:reserved",
        ),
        evidence_refs=("goal:reserved", "goal:target"),
    )
    omitted = RetirementRunSelection(
        run_selection_id="retirement_baseline",
        work_optional_age=50,
        path=RetirementPath.MIDDLE,
    )
    included = RetirementRunSelection(
        run_selection_id="retirement_with_goal",
        work_optional_age=50,
        path=RetirementPath.MIDDLE,
        include_operational_goal=True,
        included_goal=inclusion,
    )

    assert omitted.included_goal is None
    assert included.included_goal is not None
    assert included.operational_goal_mutation is False
    with pytest.raises(ValidationError, match="must agree"):
        RetirementRunSelection(
            run_selection_id="retirement_invalid",
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
            include_operational_goal=True,
        )


def test_lab_seed_is_isolated_and_promotion_is_only_a_reviewable_preview() -> None:
    seed = LifeLabExperimentSeed(
        experiment_id="lab_synthetic_goal",
        seed_kind=LabExperimentSeedKind.CURRENT_GOAL,
        source_fingerprint=FINGERPRINT_A,
        seeded_money={"goal_target": entered("14000.00", "goal:target")},
        source_label="Synthetic home reserve",
        draft={"mission": {"target_amount": "14000.00"}},
        experiment_fingerprint=FINGERPRINT_B,
    )
    preview = LifeLabPromotionPreview(
        preview_id="c" * 64,
        experiment_id=seed.experiment_id,
        experiment_fingerprint=FINGERPRINT_B,
        target_surface=PromotionTarget.GOALS,
        target_id="goal_home",
        target_stale_write_token=FINGERPRINT_A,
        changes=(
            LifeLabPromotionChange(
                field=PromotionField.GOAL_TARGET,
                stored_target_field="goal_programs.target_amount",
                before=entered("14000.00", "goal:target"),
                after=entered("15000.00", "lab:goal_target"),
                source_provenance=("lab:goal_target",),
                target_provenance=("goal:target",),
            ),
        ),
    )

    assert seed.edit_scope == "isolated_draft"
    assert seed.goal_mutation is False
    assert preview.state == "preview_only"
    assert preview.requires_explicit_confirmation is True
    assert preview.applied is False
    with pytest.raises(ValidationError, match="blank experiment"):
        LifeLabExperimentSeed(
            experiment_id="lab_invalid",
            seed_kind=LabExperimentSeedKind.BLANK,
            source_fingerprint=FINGERPRINT_A,
            seeded_money={"goal_target": entered("14000.00", "goal:target")},
            source_label="Invalid copied source",
            draft={"mission": {"target_amount": "14000.00"}},
            experiment_fingerprint=FINGERPRINT_B,
        )


def fingerprint_material(reverse_records: bool = False) -> SourceFingerprintMaterial:
    records: tuple[FingerprintSourceRecord, ...] = (
        FingerprintSourceRecord(
            kind=SourceRecordKind.PAYROLL,
            record_identity="payroll-synthetic-2026-08-07",
            effective_date=date(2026, 8, 7),
            money_facts=(
                SourceMoneyFact(
                    field="effective_monthly_take_home",
                    amount=Decimal("4200.00"),
                    evidence=EvidenceClass.DERIVED,
                ),
            ),
        ),
        FingerprintSourceRecord(
            kind=SourceRecordKind.BALANCE,
            record_identity="balance-synthetic-cash-2026-08-10",
            record_hash="c" * 64,
            effective_date=date(2026, 8, 10),
            money_facts=(
                SourceMoneyFact(
                    field="accessible_cash",
                    amount=Decimal("6000.00"),
                    evidence=EvidenceClass.OBSERVED,
                ),
                SourceMoneyFact(
                    field="retirement_assets_excluded",
                    amount=Decimal("18000.00"),
                    evidence=EvidenceClass.OBSERVED,
                ),
            ),
        ),
    )
    if reverse_records:
        records = tuple(reversed(records))
    return SourceFingerprintMaterial(
        goal_configuration=FingerprintGoalConfiguration(
            goal_program_id="goal_home",
            target_date=date(2027, 8, 9),
            target_amount=entered("14000.00", "goal-config:target"),
            protected_cash_floor=entered("3000.00", "goal-config:floor"),
            reserved_for_goal=entered("2000.00", "goal-config:reserved"),
        ),
        source_records=records,
    )


def test_source_fingerprint_is_stable_exact_and_excludes_request_metadata() -> None:
    material = fingerprint_material()

    assert material.fingerprint() == fingerprint_material(reverse_records=True).fingerprint()
    assert '"amount":"6000.00"' in material.canonical_json()
    assert "Synthetic home reserve" not in material.canonical_json()
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceFingerprintMaterial.model_validate(
            {**material.model_dump(mode="json"), "request_timestamp": "2026-08-10T16:30:00Z"}
        )


def test_all_serialized_contract_examples_validate_and_fingerprint_exactly() -> None:
    examples = json.loads(
        (PROJECT_ROOT / "examples/synthetic/money-map-v2-contracts.json").read_text(
            encoding="utf-8"
        )
    )

    PrimaryGoalProgram.model_validate(examples["primary_goal_program"])
    GoalPosition.model_validate(examples["goal_position"])
    GoalCheckIn.model_validate(examples["goal_check_in"])
    GoalComparison.model_validate(examples["goal_comparison"])
    GoalMilestone.model_validate(examples["goal_milestone"])
    RetirementRunSelection.model_validate(examples["retirement_run_selection"])
    LifeLabExperimentSeed.model_validate(examples["life_lab_experiment_seed"])
    LifeLabPromotionPreview.model_validate(examples["life_lab_promotion_preview"])
    vector = examples["source_fingerprint_vector"]
    material = SourceFingerprintMaterial.model_validate(vector["material"])
    assert material.canonical_json() == vector["canonical_json"]
    assert material.fingerprint() == vector["sha256"]
