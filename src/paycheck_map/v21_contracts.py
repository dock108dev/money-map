"""Pure Money Map v2.1 cash-flow-first contracts; no runtime wiring lives here."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .money import ZERO, money
from .v2_contracts import (
    GOAL_CALCULATION_VERSION,
    EvidenceClass,
)
from .v2_contracts import remaining_funding_months as remaining_funding_months
from .v2_contracts import required_funding_pace as required_funding_pace

CONTRACT_VERSION: Final = "money-map-v2.1-contract-v1"
EXACT_MONEY_PATTERN: Final = re.compile(r"^-?(?:0|[1-9]\d*)\.\d{2}$")
MONTH_PATTERN: Final = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
MONTH_FRACTION: Final = Decimal("0.000000000001")


class ContractModel(BaseModel):
    """Strict immutable base for serialized v2.1 values."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PeriodKind(StrEnum):
    ALL_IMPORTED_HISTORY = "all_imported_history"
    TRAILING_12_MONTHS = "trailing_12_months"
    YEAR_TO_DATE = "year_to_date"
    CUSTOM_RANGE = "custom_range"


class PartialPeriodState(StrEnum):
    FULL = "full"
    PARTIAL = "partial"


class CoverageCompleteness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class FreshnessState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    INCOMPLETE = "incomplete"


class V21MoneyDerivation(StrEnum):
    EFFECTIVE_RECURRING_TAKE_HOME = "effective_recurring_take_home"
    MONEY_IN = "money_in"
    MONEY_OUT = "money_out"
    NET_CASH_FLOW = "net_cash_flow"
    CURRENT_MONTHLY_MARGIN = "current_monthly_margin"
    STABILIZATION_GAP = "stabilization_gap"
    REMAINING_TARGET = "remaining_target"
    REQUIRED_GOAL_PACE = "required_goal_pace"
    COMBINED_MONTHLY_IMPROVEMENT = "combined_monthly_improvement"


class V21EvidencedMoney(ContractModel):
    """Exact cents inseparable from evidence or an explicit unavailable reason."""

    amount: Decimal | None
    evidence: EvidenceClass
    source_refs: tuple[str, ...] = ()
    derivation: V21MoneyDerivation | None = None
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("amount", mode="before")
    @classmethod
    def parse_exact_money(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, (bool, float, int)):
            raise ValueError("Money must cross the contract boundary as an exact decimal string")
        if isinstance(value, str):
            if EXACT_MONEY_PATTERN.fullmatch(value) is None:
                raise ValueError("Money must be a finite exact two-place decimal string")
            parsed = Decimal(value)
        elif isinstance(value, Decimal):
            parsed = value
        else:
            raise ValueError("Money must be Decimal internally or an exact decimal string")
        if not parsed.is_finite():
            raise ValueError("Money cannot be NaN or infinite")
        exact = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if exact != parsed:
            raise ValueError("Money cannot contain fractions of a cent")
        return exact

    @field_validator("source_refs")
    @classmethod
    def stable_unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("Source references must be non-empty")
        if len(set(value)) != len(value):
            raise ValueError("Source references must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.evidence is EvidenceClass.UNAVAILABLE:
            if self.amount is not None or self.derivation is not None or self.source_refs:
                raise ValueError("Unavailable money cannot claim an amount, derivation, or source")
            if self.unavailable_reason is None:
                raise ValueError("Unavailable money requires a reason")
            return self
        if self.amount is None:
            raise ValueError("Available evidence requires an exact amount")
        if self.unavailable_reason is not None:
            raise ValueError("Available money cannot carry an unavailable reason")
        if not self.source_refs:
            raise ValueError("Every available monetary value requires source references")
        if self.evidence is EvidenceClass.DERIVED and self.derivation is None:
            raise ValueError("Derived money requires a supported derivation")
        if self.evidence is not EvidenceClass.DERIVED and self.derivation is not None:
            raise ValueError("Only derived money can declare a derivation")
        return self

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")


class SelectedPeriod(ContractModel):
    kind: PeriodKind
    start_date: date
    end_date: date
    as_of_date: date

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("Selected period start must not follow its end")
        if self.end_date > self.as_of_date:
            raise ValueError("Selected period cannot extend beyond its as-of date")
        if self.kind is PeriodKind.TRAILING_12_MONTHS:
            expected = _month_start_offset(self.as_of_date, -11)
            if self.start_date != expected or self.end_date != self.as_of_date:
                raise ValueError("Trailing-12 period must cover twelve calendar-month rows")
        elif self.kind is PeriodKind.YEAR_TO_DATE:
            if (
                self.start_date != date(self.as_of_date.year, 1, 1)
                or self.end_date != self.as_of_date
            ):
                raise ValueError("Year-to-date period must run from January 1 through as-of")
        return self


class CoverageState(ContractModel):
    coverage_start: date
    coverage_end: date
    transaction_count: int = Field(ge=0)
    opening_month: PartialPeriodState
    closing_month: PartialPeriodState
    completeness: CoverageCompleteness
    incomplete_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.coverage_start > self.coverage_end:
            raise ValueError("Coverage start must not follow coverage end")
        if self.completeness is CoverageCompleteness.COMPLETE and self.incomplete_reasons:
            raise ValueError("Complete coverage cannot carry incomplete reasons")
        if self.completeness is CoverageCompleteness.INCOMPLETE and not self.incomplete_reasons:
            raise ValueError("Incomplete coverage requires at least one reason")
        return self


class Freshness(ContractModel):
    state: FreshnessState
    observed_at: datetime
    stale_sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_freshness(self) -> Self:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Freshness time must be timezone-aware")
        if self.state is FreshnessState.CURRENT and self.stale_sources:
            raise ValueError("Current freshness cannot identify stale sources")
        if self.state is FreshnessState.STALE and not self.stale_sources:
            raise ValueError("Stale freshness requires at least one stale source")
        return self


class ExcludedTransferTotals(ContractModel):
    matched_owned_account_amount: V21EvidencedMoney
    matched_owned_account_count: int = Field(ge=0)
    internal_transfer_amount: V21EvidencedMoney
    internal_transfer_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_exclusions(self) -> Self:
        for name, value in (
            ("matched_owned_account_amount", self.matched_owned_account_amount),
            ("internal_transfer_amount", self.internal_transfer_amount),
        ):
            _require_evidence(value, EvidenceClass.OBSERVED, name)
            if _amount(value, name) < ZERO:
                raise ValueError("Excluded transfer amounts cannot be negative")
        return self


class CashFlowAmounts(ContractModel):
    external_cash_inflows: V21EvidencedMoney
    interest_received: V21EvidencedMoney
    money_in: V21EvidencedMoney
    external_cash_outflows: V21EvidencedMoney
    fees_paid: V21EvidencedMoney
    money_out: V21EvidencedMoney
    net_cash_flow: V21EvidencedMoney

    @model_validator(mode="after")
    def validate_cash_flow(self) -> Self:
        for name, value in (
            ("external_cash_inflows", self.external_cash_inflows),
            ("interest_received", self.interest_received),
            ("external_cash_outflows", self.external_cash_outflows),
            ("fees_paid", self.fees_paid),
        ):
            _require_evidence(value, EvidenceClass.OBSERVED, name)
            if _amount(value, name) < ZERO:
                raise ValueError(f"{name} cannot be negative")
        _require_derivation(self.money_in, V21MoneyDerivation.MONEY_IN, "money_in")
        _require_derivation(self.money_out, V21MoneyDerivation.MONEY_OUT, "money_out")
        _require_derivation(self.net_cash_flow, V21MoneyDerivation.NET_CASH_FLOW, "net_cash_flow")
        expected_in = money(
            _amount(self.external_cash_inflows, "external_cash_inflows")
            + _amount(self.interest_received, "interest_received")
        )
        expected_out = money(
            _amount(self.external_cash_outflows, "external_cash_outflows")
            + _amount(self.fees_paid, "fees_paid")
        )
        if _amount(self.money_in, "money_in") != expected_in:
            raise ValueError("Money in must equal external cash inflows plus interest")
        if _amount(self.money_out, "money_out") != expected_out:
            raise ValueError("Money out must equal external cash outflows plus fees")
        if min(expected_in, expected_out) < ZERO:
            raise ValueError("Money in and money out cannot be negative")
        expected_net = money(expected_in - expected_out)
        if _amount(self.net_cash_flow, "net_cash_flow") != expected_net:
            raise ValueError("Net cash flow must equal money in minus money out")
        return self


class MonthlyCashFlowPoint(ContractModel):
    month: str = Field(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")
    start_date: date
    end_date: date
    partial: bool
    transaction_count: int = Field(ge=0)
    amounts: CashFlowAmounts
    transfers_excluded: ExcludedTransferTotals

    @model_validator(mode="after")
    def validate_month(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("Monthly point start must not follow its end")
        if (self.start_date.year, self.start_date.month) != (
            self.end_date.year,
            self.end_date.month,
        ):
            raise ValueError("A monthly point cannot cross a calendar month")
        if self.month != self.start_date.strftime("%Y-%m"):
            raise ValueError("Monthly point label must match its dates")
        whole_month = (
            self.start_date.day == 1
            and self.end_date.day == monthrange(self.end_date.year, self.end_date.month)[1]
        )
        if self.partial == whole_month:
            raise ValueError("Monthly partial flag must match its covered dates")
        excluded_count = (
            self.transfers_excluded.matched_owned_account_count
            + self.transfers_excluded.internal_transfer_count
        )
        if excluded_count > self.transaction_count:
            raise ValueError("Excluded transfer count cannot exceed the transaction count")
        return self


class CashFlowPeriodResult(ContractModel):
    period: SelectedPeriod
    coverage: CoverageState
    totals: CashFlowAmounts
    monthly_points: tuple[MonthlyCashFlowPoint, ...] = Field(min_length=1)
    transfers_excluded: ExcludedTransferTotals
    freshness: Freshness
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_period_result(self) -> Self:
        if not (
            self.period.start_date
            <= self.coverage.coverage_start
            <= self.coverage.coverage_end
            <= self.period.end_date
        ):
            raise ValueError("Coverage dates must be inside the selected period")
        if self.period.kind is PeriodKind.ALL_IMPORTED_HISTORY and (
            self.coverage.coverage_start != self.period.start_date
            or self.coverage.coverage_end != self.period.end_date
        ):
            raise ValueError("All imported history must use the reported coverage boundaries")

        previous_end: date | None = None
        for point in self.monthly_points:
            if not (
                self.period.start_date <= point.start_date <= point.end_date <= self.period.end_date
            ):
                raise ValueError("Monthly points must stay inside the selected period")
            if previous_end is not None and point.start_date <= previous_end:
                raise ValueError("Monthly points must be ordered and non-overlapping")
            previous_end = point.end_date

        expected_opening = (
            PartialPeriodState.PARTIAL
            if self.period.start_date.day != 1
            else PartialPeriodState.FULL
        )
        expected_closing = (
            PartialPeriodState.PARTIAL
            if self.period.end_date.day
            != monthrange(self.period.end_date.year, self.period.end_date.month)[1]
            else PartialPeriodState.FULL
        )
        if self.coverage.opening_month is not expected_opening:
            raise ValueError("Coverage opening-month state must match the first monthly point")
        if self.coverage.closing_month is not expected_closing:
            raise ValueError("Coverage closing-month state must match the last monthly point")

        _validate_monthly_reconciliation(self)
        return self


class MarginState(StrEnum):
    NEGATIVE = "negative"
    ZERO = "zero"
    POSITIVE = "positive"
    UNAVAILABLE = "unavailable"


class CurrentRecurringFacts(ContractModel):
    as_of_date: date
    effective_recurring_take_home: V21EvidencedMoney
    observed_recurring_monthly_outflow: V21EvidencedMoney
    current_monthly_margin: V21EvidencedMoney
    stabilization_gap: V21EvidencedMoney
    margin_state: MarginState
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_recurring_facts(self) -> Self:
        _require_evidence_or_unavailable(
            self.effective_recurring_take_home,
            EvidenceClass.DERIVED,
            "effective_recurring_take_home",
        )
        _require_evidence_or_unavailable(
            self.observed_recurring_monthly_outflow,
            EvidenceClass.OBSERVED,
            "observed_recurring_monthly_outflow",
        )
        dependencies = (
            self.effective_recurring_take_home.amount,
            self.observed_recurring_monthly_outflow.amount,
        )
        if None in dependencies:
            _require_evidence(
                self.current_monthly_margin, EvidenceClass.UNAVAILABLE, "current_monthly_margin"
            )
            _require_evidence(
                self.stabilization_gap, EvidenceClass.UNAVAILABLE, "stabilization_gap"
            )
            if self.margin_state is not MarginState.UNAVAILABLE:
                raise ValueError("Missing recurring evidence requires unavailable margin state")
            return self

        take_home = _amount(self.effective_recurring_take_home, "effective_recurring_take_home")
        outflow = _amount(
            self.observed_recurring_monthly_outflow, "observed_recurring_monthly_outflow"
        )
        if min(take_home, outflow) < ZERO:
            raise ValueError("Recurring take-home and outflow cannot be negative")
        _require_derivation(
            self.effective_recurring_take_home,
            V21MoneyDerivation.EFFECTIVE_RECURRING_TAKE_HOME,
            "effective_recurring_take_home",
        )
        _require_derivation(
            self.current_monthly_margin,
            V21MoneyDerivation.CURRENT_MONTHLY_MARGIN,
            "current_monthly_margin",
        )
        _require_derivation(
            self.stabilization_gap,
            V21MoneyDerivation.STABILIZATION_GAP,
            "stabilization_gap",
        )
        margin = money(take_home - outflow)
        if _amount(self.current_monthly_margin, "current_monthly_margin") != margin:
            raise ValueError("Current monthly margin must equal recurring take-home minus outflow")
        expected_gap = money(max(-margin, ZERO))
        if _amount(self.stabilization_gap, "stabilization_gap") != expected_gap:
            raise ValueError("Stabilization gap must equal max(-current monthly margin, 0)")
        expected_state = (
            MarginState.NEGATIVE
            if margin < ZERO
            else MarginState.POSITIVE
            if margin > ZERO
            else MarginState.ZERO
        )
        if self.margin_state is not expected_state:
            raise ValueError("Margin state must match the current recurring margin")
        return self


class GoalState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED_UNFINISHED = "expired_unfinished"
    CASH_FLOOR_BREACH = "cash_floor_breach"
    UNAVAILABLE = "unavailable"


class RequiredGoalPaceReference(ContractModel):
    goal_program_id: str = Field(pattern=r"^goal_[a-z0-9_]+$")
    observed_on: date
    target_date: date
    goal_target: V21EvidencedMoney
    reserved_for_goal: V21EvidencedMoney
    remaining_target: V21EvidencedMoney
    accessible_cash: V21EvidencedMoney
    protected_cash_floor: V21EvidencedMoney
    funding_months: Decimal
    goal_state: GoalState
    required_goal_pace: V21EvidencedMoney
    calculation_version: Literal["goal-arithmetic-v1"] = GOAL_CALCULATION_VERSION

    @field_validator("funding_months", mode="before")
    @classmethod
    def parse_funding_months(cls, value: object) -> Decimal:
        if isinstance(value, (float, bool)):
            raise ValueError("Funding months cannot pass through binary float or bool")
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise ValueError("Funding months must be finite")
        parsed = parsed.quantize(MONTH_FRACTION, rounding=ROUND_HALF_UP)
        if parsed < ZERO:
            raise ValueError("Funding months cannot be negative")
        return parsed

    @field_serializer("funding_months")
    def serialize_funding_months(self, value: Decimal) -> str:
        return format(value, ".12f")

    @model_validator(mode="after")
    def validate_goal_pace(self) -> Self:
        _require_evidence_or_unavailable(
            self.goal_target, EvidenceClass.USER_ENTERED, "goal_target"
        )
        _require_evidence_or_unavailable(
            self.reserved_for_goal, EvidenceClass.USER_ENTERED, "reserved_for_goal"
        )
        _require_evidence_or_unavailable(
            self.accessible_cash, EvidenceClass.OBSERVED, "accessible_cash"
        )
        _require_evidence_or_unavailable(
            self.protected_cash_floor, EvidenceClass.USER_ENTERED, "protected_cash_floor"
        )

        if self.goal_target.amount is None or self.reserved_for_goal.amount is None:
            _require_evidence(self.remaining_target, EvidenceClass.UNAVAILABLE, "remaining_target")
            _require_evidence(
                self.required_goal_pace, EvidenceClass.UNAVAILABLE, "required_goal_pace"
            )
            if self.goal_state is not GoalState.UNAVAILABLE:
                raise ValueError("Missing goal configuration requires unavailable goal state")
            return self

        target = _amount(self.goal_target, "goal_target")
        reserved = _amount(self.reserved_for_goal, "reserved_for_goal")
        if min(target, reserved) < ZERO or reserved > target:
            raise ValueError("Goal target and reservation must be nonnegative and bounded")
        _require_derivation(
            self.remaining_target, V21MoneyDerivation.REMAINING_TARGET, "remaining_target"
        )
        remaining = money(max(target - reserved, ZERO))
        if _amount(self.remaining_target, "remaining_target") != remaining:
            raise ValueError("Remaining target must equal target minus explicit reservation")

        expected_months = remaining_funding_months(self.observed_on, self.target_date)
        if self.funding_months != expected_months:
            raise ValueError("Funding months must reuse the goal-arithmetic-v1 calendar helper")
        expected_pace = required_funding_pace(remaining, self.observed_on, self.target_date)

        floor_breach = False
        if self.accessible_cash.amount is not None and self.protected_cash_floor.amount is not None:
            cash = _amount(self.accessible_cash, "accessible_cash")
            floor = _amount(self.protected_cash_floor, "protected_cash_floor")
            if min(cash, floor) < ZERO:
                raise ValueError("Accessible cash and protected floor cannot be negative")
            floor_breach = cash < floor

        expected_state = (
            GoalState.COMPLETED
            if remaining == ZERO
            else GoalState.EXPIRED_UNFINISHED
            if expected_pace is None
            else GoalState.CASH_FLOOR_BREACH
            if floor_breach
            else GoalState.ACTIVE
        )
        if self.goal_state is not expected_state:
            raise ValueError("Goal state must distinguish completion, expiry, and floor breach")
        if expected_pace is None:
            _require_evidence(
                self.required_goal_pace, EvidenceClass.UNAVAILABLE, "required_goal_pace"
            )
            return self
        _require_derivation(
            self.required_goal_pace,
            V21MoneyDerivation.REQUIRED_GOAL_PACE,
            "required_goal_pace",
        )
        if _amount(self.required_goal_pace, "required_goal_pace") != expected_pace:
            raise ValueError("Required goal pace must reuse goal-arithmetic-v1")
        return self


class V21ContractVector(ContractModel):
    vector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    covers: tuple[str, ...] = Field(min_length=1)
    cash_flow: CashFlowPeriodResult
    recurring: CurrentRecurringFacts
    goal: RequiredGoalPaceReference
    combined_monthly_improvement: V21EvidencedMoney
    contract_version: Literal["money-map-v2.1-contract-v1"] = CONTRACT_VERSION

    @model_validator(mode="after")
    def validate_combined_improvement(self) -> Self:
        margin = self.recurring.current_monthly_margin.amount
        pace = self.goal.required_goal_pace.amount
        if margin is None or pace is None:
            _require_evidence(
                self.combined_monthly_improvement,
                EvidenceClass.UNAVAILABLE,
                "combined_monthly_improvement",
            )
            return self
        _require_derivation(
            self.combined_monthly_improvement,
            V21MoneyDerivation.COMBINED_MONTHLY_IMPROVEMENT,
            "combined_monthly_improvement",
        )
        expected = money(max(pace - margin, ZERO))
        if _amount(self.combined_monthly_improvement, "combined_monthly_improvement") != expected:
            raise ValueError(
                "Combined monthly improvement must use required pace minus recurring margin"
            )
        return self


def _month_start_offset(value: date, offset: int) -> date:
    absolute = value.year * 12 + (value.month - 1) + offset
    return date(absolute // 12, absolute % 12 + 1, 1)


def _amount(value: V21EvidencedMoney, name: str) -> Decimal:
    if value.amount is None:
        raise ValueError(f"{name} must be available")
    return value.amount


def _require_evidence(value: V21EvidencedMoney, evidence: EvidenceClass, name: str) -> None:
    if value.evidence is not evidence:
        raise ValueError(f"{name} must use {evidence.value} evidence")


def _require_evidence_or_unavailable(
    value: V21EvidencedMoney, evidence: EvidenceClass, name: str
) -> None:
    if value.evidence not in {evidence, EvidenceClass.UNAVAILABLE}:
        raise ValueError(f"{name} must use {evidence.value} or unavailable evidence")


def _require_derivation(
    value: V21EvidencedMoney, derivation: V21MoneyDerivation, name: str
) -> None:
    _require_evidence(value, EvidenceClass.DERIVED, name)
    if value.derivation is not derivation:
        raise ValueError(f"{name} must use the {derivation.value} derivation")


def _sum_monthly_money(points: tuple[MonthlyCashFlowPoint, ...], field: str) -> Decimal:
    total = ZERO
    for point in points:
        value = getattr(point.amounts, field)
        if not isinstance(value, V21EvidencedMoney):
            raise TypeError(f"Unexpected monthly money field: {field}")
        total += _amount(value, field)
    return money(total)


def _validate_monthly_reconciliation(result: CashFlowPeriodResult) -> None:
    for field in (
        "external_cash_inflows",
        "interest_received",
        "money_in",
        "external_cash_outflows",
        "fees_paid",
        "money_out",
        "net_cash_flow",
    ):
        total = getattr(result.totals, field)
        if not isinstance(total, V21EvidencedMoney):
            raise TypeError(f"Unexpected period money field: {field}")
        if _sum_monthly_money(result.monthly_points, field) != _amount(total, field):
            raise ValueError(f"Monthly {field} values must reconcile exactly to period totals")

    matched_amount = money(
        sum(
            (
                _amount(
                    point.transfers_excluded.matched_owned_account_amount,
                    "matched_owned_account_amount",
                )
                for point in result.monthly_points
            ),
            ZERO,
        )
    )
    internal_amount = money(
        sum(
            (
                _amount(
                    point.transfers_excluded.internal_transfer_amount,
                    "internal_transfer_amount",
                )
                for point in result.monthly_points
            ),
            ZERO,
        )
    )
    if matched_amount != _amount(
        result.transfers_excluded.matched_owned_account_amount,
        "matched_owned_account_amount",
    ) or internal_amount != _amount(
        result.transfers_excluded.internal_transfer_amount, "internal_transfer_amount"
    ):
        raise ValueError("Monthly excluded-transfer amounts must reconcile to period totals")
    if sum(
        point.transfers_excluded.matched_owned_account_count for point in result.monthly_points
    ) != (result.transfers_excluded.matched_owned_account_count):
        raise ValueError("Monthly matched-transfer counts must reconcile to period totals")
    if sum(point.transfers_excluded.internal_transfer_count for point in result.monthly_points) != (
        result.transfers_excluded.internal_transfer_count
    ):
        raise ValueError("Monthly internal-transfer counts must reconcile to period totals")
    if (
        sum(point.transaction_count for point in result.monthly_points)
        != result.coverage.transaction_count
    ):
        raise ValueError("Monthly transaction counts must reconcile to coverage")
