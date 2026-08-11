from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.goal_gap_service import GoalGapValidationError, build_goal_gap_preview
from paycheck_map.models import GoalCheckIn, GoalProgram
from paycheck_map.v21_contracts import (
    GoalGapPreviewAvailable,
    GoalGapPreviewRequest,
    GoalGapPreviewUnavailable,
    GrossIncomeContextAvailable,
    GrossIncomeContextUnavailable,
)

from .goal_gap_support import seed_goal_gap

OBSERVED_ON = date(2026, 8, 11)


def preview(
    session: Session, request: GoalGapPreviewRequest | None = None
) -> GoalGapPreviewAvailable:
    result = build_goal_gap_preview(
        session,
        request=request or GoalGapPreviewRequest(),
        observed_on=OBSERVED_ON,
    )
    assert isinstance(result, GoalGapPreviewAvailable)
    return result


def test_accepted_synthetic_baseline_reconciles_exactly(session: Session) -> None:
    seed_goal_gap(session)

    result = preview(session)

    assert result.baseline_current_recurring_facts.current_monthly_margin.amount == Decimal(
        "-5602.98"
    )
    assert result.baseline_current_recurring_facts.stabilization_gap.amount == Decimal("5602.98")
    assert result.baseline_goal_pace_reference.required_goal_pace.amount == Decimal("39003.52")
    assert result.baseline_combined_monthly_improvement.amount == Decimal("44606.50")
    assert result.remaining_combined_monthly_improvement.amount == Decimal("44606.50")


@pytest.mark.parametrize(
    ("monthly_outflow", "expected_state", "expected_margin", "expected_combined"),
    [
        ("3900.00", "positive", "300.00", "38703.52"),
        ("4200.00", "zero", "0.00", "39003.52"),
    ],
)
def test_positive_and_zero_current_margin(
    session: Session,
    monthly_outflow: str,
    expected_state: str,
    expected_margin: str,
    expected_combined: str,
) -> None:
    seed_goal_gap(session, monthly_outflow=monthly_outflow)

    result = preview(session)

    assert result.baseline_current_recurring_facts.margin_state.value == expected_state
    assert result.baseline_current_recurring_facts.current_monthly_margin.amount == Decimal(
        expected_margin
    )
    assert result.baseline_combined_monthly_improvement.amount == Decimal(expected_combined)


def test_2035_preview_reuses_exact_calendar_fractional_months(session: Session) -> None:
    seed_goal_gap(session)

    result = preview(
        session,
        GoalGapPreviewRequest(target_date=date(2035, 11, 18)),
    )

    assert result.preview_target_date == date(2035, 11, 18)
    assert result.exact_funding_months == Decimal("111.277419354839")
    assert result.calculation_version == "goal-arithmetic-v1"


def test_reservation_reduces_pace_and_can_complete_goal(session: Session) -> None:
    seed_goal_gap(session)

    partial = preview(
        session,
        GoalGapPreviewRequest(additional_reservation=Decimal("100000.00")),
    )
    completed = preview(
        session,
        GoalGapPreviewRequest(additional_reservation=Decimal("1872168.96")),
    )

    assert partial.preview_remaining_target.amount == Decimal("1772168.96")
    assert partial.preview_required_goal_pace.amount == Decimal("36920.19")
    assert completed.preview_remaining_target.amount == Decimal("0.00")
    assert completed.preview_required_goal_pace.amount == Decimal("0.00")
    assert completed.remaining_combined_monthly_improvement.amount == Decimal("5602.98")


def test_expired_unfinished_preview_keeps_independent_stabilization(session: Session) -> None:
    seed_goal_gap(session)

    result = preview(
        session,
        GoalGapPreviewRequest(target_date=date(2026, 8, 10)),
    )

    assert result.preview_required_goal_pace.amount is None
    assert result.adjusted_stabilization_gap.amount == Decimal("5602.98")
    assert result.remaining_combined_monthly_improvement.amount is None


def test_cash_floor_breach_remains_visible_in_baseline_state(session: Session) -> None:
    seed_goal_gap(session, cash_balance="2000.00", protected_floor="3000.00")

    result = preview(session)

    assert result.baseline_goal_pace_reference.goal_state.value == "cash_floor_breach"


@pytest.mark.parametrize(
    ("include_payroll", "complete_months", "missing_field"),
    [
        (False, True, "effective_recurring_take_home"),
        (True, False, "observed_recurring_monthly_outflow"),
    ],
)
def test_missing_recurring_evidence_degrades_only_dependent_outputs(
    session: Session,
    include_payroll: bool,
    complete_months: bool,
    missing_field: str,
) -> None:
    seed_goal_gap(
        session,
        include_payroll=include_payroll,
        complete_months=complete_months,
    )

    result = preview(session)

    assert getattr(result.baseline_current_recurring_facts, missing_field).amount is None
    assert result.baseline_goal_pace_reference.required_goal_pace.amount == Decimal("39003.52")
    assert result.baseline_combined_monthly_improvement.amount is None
    assert isinstance(result.gross_income_context, GrossIncomeContextUnavailable)


def test_no_primary_is_an_explicit_non_error_state(session: Session) -> None:
    seed_goal_gap(session, include_goal=False)

    result = build_goal_gap_preview(
        session,
        request=GoalGapPreviewRequest(),
        observed_on=OBSERVED_ON,
    )

    assert isinstance(result, GoalGapPreviewUnavailable)
    assert result.state == "no_primary"


@pytest.mark.parametrize(
    ("draft", "expected_margin", "expected_combined"),
    [
        (
            GoalGapPreviewRequest(monthly_spending_reduction=Decimal("100.00")),
            "-5502.98",
            "44506.50",
        ),
        (
            GoalGapPreviewRequest(monthly_after_tax_income=Decimal("100.00")),
            "-5502.98",
            "44506.50",
        ),
        (
            GoalGapPreviewRequest(
                monthly_spending_reduction=Decimal("100.00"),
                monthly_after_tax_income=Decimal("200.00"),
            ),
            "-5302.98",
            "44306.50",
        ),
    ],
)
def test_spending_income_and_combined_levers_apply_once(
    session: Session,
    draft: GoalGapPreviewRequest,
    expected_margin: str,
    expected_combined: str,
) -> None:
    seed_goal_gap(session)

    result = preview(session, draft)

    assert result.adjusted_monthly_margin.amount == Decimal(expected_margin)
    assert result.remaining_combined_monthly_improvement.amount == Decimal(expected_combined)


def test_draft_bounds_are_enforced(session: Session) -> None:
    seed_goal_gap(session)

    with pytest.raises(GoalGapValidationError, match="remaining goal target"):
        preview(
            session,
            GoalGapPreviewRequest(additional_reservation=Decimal("1872168.97")),
        )
    with pytest.raises(GoalGapValidationError, match="supported observed monthly outflow"):
        preview(
            session,
            GoalGapPreviewRequest(monthly_spending_reduction=Decimal("9802.99")),
        )


def test_gross_estimate_uses_latest_positive_paycheck_ratio(session: Session) -> None:
    seed_goal_gap(session)

    result = preview(session)

    assert isinstance(result.gross_income_context, GrossIncomeContextAvailable)
    assert result.gross_income_context.effective_take_home_ratio == Decimal("0.646153333333")
    assert result.gross_income_context.supporting_payroll_date == date(2026, 8, 7)
    assert result.gross_income_context.disclaimer == "Not a tax-return estimate"
    monthly = result.gross_income_context.estimated_monthly_gross_income_needed.amount
    annual = result.gross_income_context.estimated_annual_gross_income_needed.amount
    assert monthly is not None and annual is not None
    assert annual == monthly * 12


def test_preview_does_not_create_or_dirty_persistent_goal_rows(session: Session) -> None:
    seed_goal_gap(session)
    session.commit()
    before_programs = session.scalar(select(func.count()).select_from(GoalProgram))
    before_check_ins = session.scalar(select(func.count()).select_from(GoalCheckIn))

    preview(
        session,
        GoalGapPreviewRequest(
            target_date=date(2035, 11, 18),
            additional_reservation=Decimal("100.00"),
            monthly_spending_reduction=Decimal("50.00"),
            monthly_after_tax_income=Decimal("75.00"),
        ),
    )

    assert session.scalar(select(func.count()).select_from(GoalProgram)) == before_programs
    assert session.scalar(select(func.count()).select_from(GoalCheckIn)) == before_check_ins
    assert not session.new
    assert not session.dirty
    assert not session.deleted
