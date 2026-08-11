"""Read-only goal-gap previews over accepted goal-position evidence."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from .goal_service import calculate_goal_position, primary_goal
from .models import PayrollScheduleEntry
from .money import ZERO, money
from .v2_contracts import EvidenceClass, EvidencedMoney, GoalPosition, PaceStatus
from .v21_contracts import (
    CurrentRecurringFacts,
    GoalGapPreviewAvailable,
    GoalGapPreviewRequest,
    GoalGapPreviewResponse,
    GoalGapPreviewUnavailable,
    GoalState,
    GrossIncomeContext,
    GrossIncomeContextAvailable,
    GrossIncomeContextUnavailable,
    MarginState,
    RequiredGoalPaceReference,
    V21EvidencedMoney,
    V21MoneyDerivation,
    remaining_funding_months,
    required_funding_pace,
)

RATIO_PRECISION = Decimal("0.000000000001")


class GoalGapValidationError(ValueError):
    """A draft cannot be evaluated within supported evidence boundaries."""


def build_goal_gap_preview(
    session: Session,
    *,
    request: GoalGapPreviewRequest,
    observed_on: date,
) -> GoalGapPreviewResponse:
    """Calculate one non-persistent preview without adding or mutating ORM rows."""

    with session.no_autoflush:
        program = primary_goal(session)
        if program is None:
            return GoalGapPreviewUnavailable(
                state="no_primary",
                observed_on=observed_on,
                reason="A primary goal has not been selected",
            )
        position = calculate_goal_position(
            session, program=program, observed_on=observed_on
        ).position

        recurring = _baseline_recurring_facts(position)
        goal_reference = _baseline_goal_reference(position)
        baseline_combined = _combined_improvement(
            recurring.current_monthly_margin,
            goal_reference.required_goal_pace,
            V21MoneyDerivation.COMBINED_MONTHLY_IMPROVEMENT,
            "Current recurring evidence or required goal pace is unavailable",
        )

        existing = money(program.reserved_amount)
        target = money(program.target_amount)
        baseline_remaining = money(max(target - existing, ZERO))
        if request.additional_reservation > baseline_remaining:
            raise GoalGapValidationError(
                "Additional reservation cannot exceed the remaining goal target"
            )
        baseline_outflow = recurring.observed_recurring_monthly_outflow.amount
        if baseline_outflow is not None and request.monthly_spending_reduction > baseline_outflow:
            raise GoalGapValidationError(
                "Monthly spending reduction cannot exceed supported observed monthly outflow"
            )
        if baseline_outflow is None and request.monthly_spending_reduction > ZERO:
            raise GoalGapValidationError(
                "Monthly spending reduction requires supported observed monthly outflow"
            )

        preview_target_date = request.target_date or program.target_date
        existing_reservation = _copy_available(position.reserved_for_goal)
        additional_reservation = _draft_money(
            request.additional_reservation, "additional-reservation"
        )
        draft_reduction = _draft_money(
            request.monthly_spending_reduction, "monthly-spending-reduction"
        )
        draft_income = _draft_money(request.monthly_after_tax_income, "monthly-after-tax-income")
        total_reservation = _derived_money(
            money(existing + request.additional_reservation),
            V21MoneyDerivation.PREVIEW_TOTAL_RESERVATION,
            _refs(existing_reservation, additional_reservation),
        )
        preview_remaining = _derived_money(
            money(max(target - _required(total_reservation), ZERO)),
            V21MoneyDerivation.PREVIEW_REMAINING_TARGET,
            _refs(goal_reference.goal_target, total_reservation),
        )
        funding_months = remaining_funding_months(observed_on, preview_target_date)
        preview_pace_amount = required_funding_pace(
            _required(preview_remaining), observed_on, preview_target_date
        )
        preview_pace = (
            _unavailable_money("The unfinished preview target date has expired")
            if preview_pace_amount is None
            else _derived_money(
                preview_pace_amount,
                V21MoneyDerivation.PREVIEW_REQUIRED_GOAL_PACE,
                (*_refs(preview_remaining), f"calendar:{observed_on}:{preview_target_date}"),
            )
        )

        adjusted_take_home = _adjusted_value(
            recurring.effective_recurring_take_home,
            draft_income,
            operation="add",
            derivation=V21MoneyDerivation.ADJUSTED_RECURRING_TAKE_HOME,
            unavailable_reason="Supported recurring take-home is unavailable",
        )
        adjusted_outflow = _adjusted_value(
            recurring.observed_recurring_monthly_outflow,
            draft_reduction,
            operation="subtract",
            derivation=V21MoneyDerivation.ADJUSTED_RECURRING_OUTFLOW,
            unavailable_reason="Supported recurring outflow is unavailable",
        )
        adjusted_margin = _difference(
            adjusted_take_home,
            adjusted_outflow,
            V21MoneyDerivation.ADJUSTED_MONTHLY_MARGIN,
            "Adjusted recurring take-home or outflow is unavailable",
        )
        adjusted_gap = (
            _unavailable_money("Adjusted monthly margin is unavailable")
            if adjusted_margin.amount is None
            else _derived_money(
                money(max(-adjusted_margin.amount, ZERO)),
                V21MoneyDerivation.ADJUSTED_STABILIZATION_GAP,
                _refs(adjusted_margin),
            )
        )
        remaining_combined = _combined_improvement(
            adjusted_margin,
            preview_pace,
            V21MoneyDerivation.REMAINING_COMBINED_MONTHLY_IMPROVEMENT,
            "Adjusted monthly margin or preview goal pace is unavailable",
        )
        gross_context = _gross_income_context(session, remaining_combined)

        warnings = [
            "Arithmetic only; not financial advice or a claim that the change is achievable."
        ]
        if recurring.current_monthly_margin.amount is None:
            warnings.append("Combined improvement needs supported recurring evidence.")
        if preview_pace.amount is None:
            warnings.append("A new target date is required for the unfinished goal.")

        return GoalGapPreviewAvailable(
            goal_program_id=program.public_key,
            goal_name=program.name,
            observed_on=observed_on,
            baseline_current_recurring_facts=recurring,
            baseline_goal_pace_reference=goal_reference,
            baseline_combined_monthly_improvement=baseline_combined,
            preview_target_date=preview_target_date,
            existing_explicit_reservation=existing_reservation,
            additional_draft_reservation=additional_reservation,
            preview_total_reservation=total_reservation,
            preview_remaining_target=preview_remaining,
            exact_funding_months=funding_months,
            preview_required_goal_pace=preview_pace,
            draft_spending_reduction=draft_reduction,
            draft_after_tax_income=draft_income,
            adjusted_recurring_take_home=adjusted_take_home,
            adjusted_recurring_outflow=adjusted_outflow,
            adjusted_monthly_margin=adjusted_margin,
            adjusted_stabilization_gap=adjusted_gap,
            remaining_combined_monthly_improvement=remaining_combined,
            gross_income_context=gross_context,
            warnings=tuple(warnings),
        )


def _baseline_recurring_facts(position: GoalPosition) -> CurrentRecurringFacts:
    take_home = _copy_available(
        position.effective_recurring_take_home,
        derivation=V21MoneyDerivation.EFFECTIVE_RECURRING_TAKE_HOME,
    )
    outflow = _copy_available(position.observed_recurring_outflow)
    if take_home.amount is None or outflow.amount is None:
        reason = (
            take_home.unavailable_reason
            or outflow.unavailable_reason
            or "Recurring evidence is unavailable"
        )
        margin = _unavailable_money(reason)
        gap = _unavailable_money(reason)
        state = MarginState.UNAVAILABLE
    else:
        margin_amount = money(take_home.amount - outflow.amount)
        margin = _derived_money(
            margin_amount,
            V21MoneyDerivation.CURRENT_MONTHLY_MARGIN,
            _refs(take_home, outflow),
        )
        gap = _derived_money(
            money(max(-margin_amount, ZERO)),
            V21MoneyDerivation.STABILIZATION_GAP,
            _refs(margin),
        )
        state = (
            MarginState.NEGATIVE
            if margin_amount < ZERO
            else MarginState.POSITIVE
            if margin_amount > ZERO
            else MarginState.ZERO
        )
    return CurrentRecurringFacts(
        as_of_date=position.observed_on,
        effective_recurring_take_home=take_home,
        observed_recurring_monthly_outflow=outflow,
        current_monthly_margin=margin,
        stabilization_gap=gap,
        margin_state=state,
    )


def _baseline_goal_reference(position: GoalPosition) -> RequiredGoalPaceReference:
    target = _copy_available(position.goal_target)
    reserved = _copy_available(position.reserved_for_goal)
    remaining = _copy_available(
        position.remaining_target,
        derivation=V21MoneyDerivation.REMAINING_TARGET,
    )
    cash = _copy_available(position.accessible_cash)
    floor = _copy_available(position.protected_cash_floor)
    pace = _copy_available(
        position.required_funding_pace,
        derivation=V21MoneyDerivation.REQUIRED_GOAL_PACE,
    )
    remaining_amount = _required(remaining)
    pace_status = position.pace_status
    floor_breach = (
        cash.amount is not None and floor.amount is not None and cash.amount < floor.amount
    )
    state = (
        GoalState.COMPLETED
        if remaining_amount == ZERO
        else GoalState.EXPIRED_UNFINISHED
        if pace_status is PaceStatus.EXPIRED
        else GoalState.CASH_FLOOR_BREACH
        if floor_breach
        else GoalState.ACTIVE
    )
    return RequiredGoalPaceReference(
        goal_program_id=position.goal_program_id,
        observed_on=position.observed_on,
        target_date=position.target_date,
        goal_target=target,
        reserved_for_goal=reserved,
        remaining_target=remaining,
        accessible_cash=cash,
        protected_cash_floor=floor,
        funding_months=position.funding_months,
        goal_state=state,
        required_goal_pace=pace,
    )


def _gross_income_context(session: Session, combined: V21EvidencedMoney) -> GrossIncomeContext:
    if combined.amount is None:
        return GrossIncomeContextUnavailable(
            reason="Remaining combined monthly improvement is unavailable"
        )
    row = session.scalar(
        select(PayrollScheduleEntry)
        .order_by(
            PayrollScheduleEntry.observed_deposit_date.desc(),
            PayrollScheduleEntry.payment_date.desc(),
            PayrollScheduleEntry.id.desc(),
        )
        .limit(1)
    )
    if row is None:
        return GrossIncomeContextUnavailable(
            reason="No supported paycheck supplies gross and net evidence"
        )
    gross = money(row.gross_earnings)
    net = money(row.net_payment)
    if gross <= ZERO or net <= ZERO:
        return GrossIncomeContextUnavailable(
            reason="Latest supported paycheck gross or net value is nonpositive"
        )
    with localcontext() as context:
        context.prec = 40
        ratio = (net / gross).quantize(RATIO_PRECISION, rounding=ROUND_HALF_UP)
        if ratio <= ZERO:
            return GrossIncomeContextUnavailable(
                reason="Latest supported paycheck produces no usable take-home ratio"
            )
        monthly = money(combined.amount / ratio)
    source_ref = f"payroll_schedule:{row.id}:{row.fingerprint}"
    monthly_money = _derived_money(
        monthly,
        V21MoneyDerivation.ESTIMATED_MONTHLY_GROSS_INCOME,
        (*_refs(combined), source_ref),
    )
    annual_money = _derived_money(
        money(monthly * Decimal("12")),
        V21MoneyDerivation.ESTIMATED_ANNUAL_GROSS_INCOME,
        _refs(monthly_money),
    )
    return GrossIncomeContextAvailable(
        effective_take_home_ratio=ratio,
        supporting_payroll_date=row.payment_date,
        source_ref=source_ref,
        estimated_monthly_gross_income_needed=monthly_money,
        estimated_annual_gross_income_needed=annual_money,
    )


def _copy_available(
    value: EvidencedMoney,
    *,
    derivation: V21MoneyDerivation | None = None,
) -> V21EvidencedMoney:
    if value.amount is None:
        return _unavailable_money(value.unavailable_reason or "Evidence is unavailable")
    return V21EvidencedMoney(
        amount=value.amount,
        evidence=value.evidence,
        source_refs=value.source_refs,
        derivation=derivation if value.evidence is EvidenceClass.DERIVED else None,
    )


def _draft_money(amount: Decimal, field: str) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=amount,
        evidence=EvidenceClass.USER_ENTERED,
        source_refs=(f"draft:goal-gap:{field}",),
    )


def _derived_money(
    amount: Decimal,
    derivation: V21MoneyDerivation,
    refs: tuple[str, ...],
) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=money(amount),
        evidence=EvidenceClass.DERIVED,
        source_refs=tuple(sorted(set(refs))),
        derivation=derivation,
    )


def _unavailable_money(reason: str) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=None,
        evidence=EvidenceClass.UNAVAILABLE,
        unavailable_reason=reason,
    )


def _refs(*values: V21EvidencedMoney) -> tuple[str, ...]:
    return tuple(sorted({ref for value in values for ref in value.source_refs}))


def _required(value: V21EvidencedMoney) -> Decimal:
    if value.amount is None:
        raise ValueError("Expected available goal-gap evidence")
    return value.amount


def _difference(
    left: V21EvidencedMoney,
    right: V21EvidencedMoney,
    derivation: V21MoneyDerivation,
    unavailable_reason: str,
) -> V21EvidencedMoney:
    if left.amount is None or right.amount is None:
        return _unavailable_money(unavailable_reason)
    return _derived_money(left.amount - right.amount, derivation, _refs(left, right))


def _adjusted_value(
    baseline: V21EvidencedMoney,
    draft: V21EvidencedMoney,
    *,
    operation: str,
    derivation: V21MoneyDerivation,
    unavailable_reason: str,
) -> V21EvidencedMoney:
    if baseline.amount is None:
        return _unavailable_money(unavailable_reason)
    draft_amount = _required(draft)
    amount = (
        baseline.amount + draft_amount if operation == "add" else baseline.amount - draft_amount
    )
    return _derived_money(amount, derivation, _refs(baseline, draft))


def _combined_improvement(
    margin: V21EvidencedMoney,
    pace: V21EvidencedMoney,
    derivation: V21MoneyDerivation,
    unavailable_reason: str,
) -> V21EvidencedMoney:
    if margin.amount is None or pace.amount is None:
        return _unavailable_money(unavailable_reason)
    return _derived_money(
        max(pace.amount - margin.amount, ZERO),
        derivation,
        _refs(margin, pace),
    )
