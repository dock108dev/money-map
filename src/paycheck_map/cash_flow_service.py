"""Read-only period-aware cash-flow classification and aggregation."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .business_time import local_business_date
from .models import Account, AccountTransaction, Institution, PlaidConnection, TransferMatch
from .money import ZERO, money
from .v2_contracts import EvidenceClass
from .v21_contracts import (
    CashFlowAmounts,
    CashFlowPeriodResult,
    CoverageCompleteness,
    CoverageState,
    ExcludedTransferTotals,
    Freshness,
    FreshnessState,
    MonthlyCashFlowPoint,
    PartialPeriodState,
    PeriodKind,
    SelectedPeriod,
    V21EvidencedMoney,
    V21MoneyDerivation,
)


class CashFlowValidationError(ValueError):
    """The requested period or imported source dates are invalid."""


class CashFlowUnavailableError(RuntimeError):
    """The requested cash-flow result cannot be represented from imported evidence."""


class CashFlowClassification(StrEnum):
    MATCHED_OWNED_TRANSFER = "matched_owned_transfer"
    INTERNAL_TRANSFER = "internal_transfer"
    INTEREST_RECEIVED = "interest_received"
    FEE_PAID = "fee_paid"
    EXTERNAL_INFLOW = "external_inflow"
    EXTERNAL_OUTFLOW = "external_outflow"
    ZERO_ACTIVITY = "zero_activity"


@dataclass(frozen=True)
class ImportedBankCoverage:
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("Imported bank coverage start must not follow its end")


@dataclass(frozen=True)
class ClassifiedCashTransaction:
    transaction_id: int
    posted_date: date
    amount: Decimal
    classification: CashFlowClassification
    incomplete_reason: str | None = None
    warning: str | None = None


@dataclass
class CashFlowBucket:
    external_cash_inflows: Decimal = ZERO
    interest_received: Decimal = ZERO
    external_cash_outflows: Decimal = ZERO
    fees_paid: Decimal = ZERO
    matched_owned_account_amount: Decimal = ZERO
    matched_owned_account_count: int = 0
    internal_transfer_amount: Decimal = ZERO
    internal_transfer_count: int = 0
    transaction_count: int = 0
    matched_transfer_in: Decimal = ZERO
    matched_transfer_out: Decimal = ZERO

    @property
    def money_in(self) -> Decimal:
        return money(self.external_cash_inflows + self.interest_received)

    @property
    def money_out(self) -> Decimal:
        return money(self.external_cash_outflows + self.fees_paid)

    @property
    def net_cash_flow(self) -> Decimal:
        return money(self.money_in - self.money_out)

    def add(self, row: ClassifiedCashTransaction) -> None:
        self.transaction_count += 1
        amount = money(row.amount)
        absolute = money(abs(amount))
        if row.classification is CashFlowClassification.MATCHED_OWNED_TRANSFER:
            self.matched_owned_account_amount += absolute
            self.matched_owned_account_count += 1
            if amount > ZERO:
                self.matched_transfer_in += amount
            elif amount < ZERO:
                self.matched_transfer_out += absolute
        elif row.classification is CashFlowClassification.INTERNAL_TRANSFER:
            self.internal_transfer_amount += absolute
            self.internal_transfer_count += 1
        elif row.classification is CashFlowClassification.INTEREST_RECEIVED:
            self.interest_received += amount
        elif row.classification is CashFlowClassification.FEE_PAID:
            self.fees_paid += absolute
        elif row.classification is CashFlowClassification.EXTERNAL_INFLOW:
            self.external_cash_inflows += amount
        elif row.classification is CashFlowClassification.EXTERNAL_OUTFLOW:
            self.external_cash_outflows += absolute

        self.external_cash_inflows = money(self.external_cash_inflows)
        self.interest_received = money(self.interest_received)
        self.external_cash_outflows = money(self.external_cash_outflows)
        self.fees_paid = money(self.fees_paid)
        self.matched_owned_account_amount = money(self.matched_owned_account_amount)
        self.internal_transfer_amount = money(self.internal_transfer_amount)
        self.matched_transfer_in = money(self.matched_transfer_in)
        self.matched_transfer_out = money(self.matched_transfer_out)


@dataclass(frozen=True)
class CashFlowAggregation:
    total: CashFlowBucket
    monthly: dict[str, CashFlowBucket]
    observed_start: date | None
    observed_end: date | None
    incomplete_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CoverageEvaluation:
    state: CoverageState
    warnings: tuple[str, ...]


_POSITIVE_ROLES = frozenset({"external_inflow", "external_deposit", "payroll_deposit"})
_NEGATIVE_ROLES = frozenset({"external_outflow", "external_withdrawal"})


def classify_bank_transaction(
    transaction: AccountTransaction,
    *,
    matched_transaction_ids: set[int] | frozenset[int],
) -> ClassifiedCashTransaction:
    """Classify one observed bank row using the accepted precedence."""

    amount = money(transaction.amount)
    role = transaction.role
    classification: CashFlowClassification
    incomplete_reason: str | None = None
    warning: str | None = None

    if transaction.id in matched_transaction_ids:
        classification = CashFlowClassification.MATCHED_OWNED_TRANSFER
    elif role == "internal_transfer":
        classification = CashFlowClassification.INTERNAL_TRANSFER
    elif role == "interest" and amount > ZERO:
        classification = CashFlowClassification.INTEREST_RECEIVED
    elif role == "fee" and amount < ZERO:
        classification = CashFlowClassification.FEE_PAID
    elif amount > ZERO:
        classification = CashFlowClassification.EXTERNAL_INFLOW
    elif amount < ZERO:
        classification = CashFlowClassification.EXTERNAL_OUTFLOW
    else:
        classification = CashFlowClassification.ZERO_ACTIVITY

    if transaction.id not in matched_transaction_ids and role != "internal_transfer":
        if role == "interest" and amount <= ZERO:
            incomplete_reason = "unexpected_interest_sign"
            warning = "Interest activity with a non-positive amount was classified by sign."
        elif role == "fee" and amount >= ZERO:
            incomplete_reason = "unexpected_fee_sign"
            warning = "Fee activity with a non-negative amount was classified by sign."
        elif role in _POSITIVE_ROLES and amount < ZERO:
            incomplete_reason = "unexpected_inflow_role_sign"
            warning = "Inflow-labeled activity with a negative amount was classified by sign."
        elif role in _NEGATIVE_ROLES and amount > ZERO:
            incomplete_reason = "unexpected_outflow_role_sign"
            warning = "Outflow-labeled activity with a positive amount was classified by sign."

    return ClassifiedCashTransaction(
        transaction_id=transaction.id,
        posted_date=transaction.posted_date,
        amount=amount,
        classification=classification,
        incomplete_reason=incomplete_reason,
        warning=warning,
    )


def resolve_period(
    *,
    period_kind: PeriodKind,
    as_of_date: date,
    imported_coverage: ImportedBankCoverage | None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> SelectedPeriod:
    """Resolve an inclusive selected period without consulting clocks or storage."""

    if imported_coverage is not None and imported_coverage.end_date > as_of_date:
        raise CashFlowValidationError(
            "Imported bank transaction source date "
            f"{imported_coverage.end_date.isoformat()} exceeds the as-of date."
        )

    if period_kind is PeriodKind.ALL_IMPORTED_HISTORY:
        if imported_coverage is None:
            raise CashFlowUnavailableError(
                "All imported history is unavailable because no bank transaction coverage exists."
            )
        resolved_start = imported_coverage.start_date
        resolved_end = imported_coverage.end_date
    elif period_kind is PeriodKind.TRAILING_12_MONTHS:
        resolved_start = _month_start_offset(as_of_date, -11)
        resolved_end = as_of_date
    elif period_kind is PeriodKind.YEAR_TO_DATE:
        resolved_start = date(as_of_date.year, 1, 1)
        resolved_end = as_of_date
    else:
        if start_date is None or end_date is None:
            raise CashFlowValidationError(
                "Custom cash-flow periods require both start_date and end_date."
            )
        resolved_start = start_date
        resolved_end = end_date

    if resolved_start > resolved_end:
        raise CashFlowValidationError("Cash-flow period start_date must not follow end_date.")
    if resolved_end > as_of_date:
        raise CashFlowValidationError("Cash-flow period end_date must not exceed the as-of date.")

    if period_kind is not PeriodKind.CUSTOM_RANGE:
        if start_date is not None and start_date != resolved_start:
            raise CashFlowValidationError("start_date conflicts with the selected period preset.")
        if end_date is not None and end_date != resolved_end:
            raise CashFlowValidationError("end_date conflicts with the selected period preset.")

    return SelectedPeriod(
        kind=period_kind,
        start_date=resolved_start,
        end_date=resolved_end,
        as_of_date=as_of_date,
    )


def imported_bank_coverage(session: Session) -> ImportedBankCoverage | None:
    """Read the minimum and maximum supported bank-transaction dates."""

    bounds = session.execute(
        select(
            func.min(AccountTransaction.posted_date),
            func.max(AccountTransaction.posted_date),
        )
        .join(Account, AccountTransaction.account_id == Account.id)
        .join(Institution, Account.institution_id == Institution.id)
        .where(Institution.kind == "bank")
    ).one()
    if bounds[0] is None or bounds[1] is None:
        return None
    return ImportedBankCoverage(start_date=bounds[0], end_date=bounds[1])


def aggregate_cash_flow(
    session: Session,
    start_date: date,
    end_date: date,
) -> CashFlowAggregation:
    """Aggregate selected bank rows once for both summary and monthly consumers."""

    if start_date > end_date:
        raise CashFlowValidationError("Cash-flow period start_date must not follow end_date.")
    matched_ids: set[int] = set()
    for match in session.scalars(select(TransferMatch)):
        matched_ids.update((match.left_transaction_id, match.right_transaction_id))
    rows = list(
        session.scalars(
            select(AccountTransaction)
            .join(Account, AccountTransaction.account_id == Account.id)
            .join(Institution, Account.institution_id == Institution.id)
            .where(
                Institution.kind == "bank",
                AccountTransaction.posted_date >= start_date,
                AccountTransaction.posted_date <= end_date,
            )
            .order_by(AccountTransaction.posted_date, AccountTransaction.id)
        )
    )

    total = CashFlowBucket()
    monthly: dict[str, CashFlowBucket] = {}
    incomplete_reasons: list[str] = []
    warnings: list[str] = []
    for transaction in rows:
        classified = classify_bank_transaction(
            transaction,
            matched_transaction_ids=matched_ids,
        )
        total.add(classified)
        month = transaction.posted_date.strftime("%Y-%m")
        monthly.setdefault(month, CashFlowBucket()).add(classified)
        if classified.incomplete_reason is not None:
            incomplete_reasons.append(classified.incomplete_reason)
        if classified.warning is not None:
            warnings.append(classified.warning)

    return CashFlowAggregation(
        total=total,
        monthly=monthly,
        observed_start=min((row.posted_date for row in rows), default=None),
        observed_end=max((row.posted_date for row in rows), default=None),
        incomplete_reasons=_stable_unique(incomplete_reasons),
        warnings=_stable_unique(warnings),
    )


def build_cash_flow_period_result(
    session: Session,
    *,
    period_kind: PeriodKind,
    as_of_date: date,
    now: datetime,
    start_date: date | None = None,
    end_date: date | None = None,
) -> CashFlowPeriodResult:
    """Build one contract-valid period result using only read-only source evidence."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise CashFlowValidationError("Cash-flow freshness evaluation requires an aware time.")
    with session.no_autoflush:
        imported = imported_bank_coverage(session)
        period = resolve_period(
            period_kind=period_kind,
            as_of_date=as_of_date,
            imported_coverage=imported,
            start_date=start_date,
            end_date=end_date,
        )
        aggregation = aggregate_cash_flow(session, period.start_date, period.end_date)
        coverage = _coverage_state(period, imported, aggregation)
        freshness = _freshness(
            session,
            coverage=coverage.state,
            as_of_date=as_of_date,
            observed_at=now,
        )

    monthly_points = tuple(
        _monthly_point(period, month_start, aggregation.monthly)
        for month_start in _month_sequence(period.start_date, period.end_date)
    )
    warnings = _stable_unique([*coverage.warnings, *aggregation.warnings, *freshness.warnings])
    return CashFlowPeriodResult(
        period=period,
        coverage=coverage.state,
        totals=_amounts(
            aggregation.total,
            source_prefix=(
                f"cash-flow:bank:{period.start_date.isoformat()}:{period.end_date.isoformat()}"
            ),
        ),
        monthly_points=monthly_points,
        transfers_excluded=_transfers(
            aggregation.total,
            source_prefix=(
                f"cash-flow:bank:{period.start_date.isoformat()}:{period.end_date.isoformat()}"
            ),
        ),
        freshness=freshness,
        warnings=warnings,
    )


def _coverage_state(
    period: SelectedPeriod,
    imported: ImportedBankCoverage | None,
    aggregation: CashFlowAggregation,
) -> _CoverageEvaluation:
    reasons: list[str] = []
    warnings: list[str] = []
    if imported is None:
        coverage_start = period.start_date
        coverage_end = period.end_date
        reasons.append("bank_transaction_coverage_unavailable")
        warnings.append("Imported bank transaction coverage is unavailable.")
    else:
        coverage_start = max(period.start_date, imported.start_date)
        coverage_end = min(period.end_date, imported.end_date)
        if coverage_start > coverage_end:
            anchor = period.start_date if imported.end_date < period.start_date else period.end_date
            coverage_start = anchor
            coverage_end = anchor
        if imported.start_date > period.start_date:
            reasons.append("selected_start_not_covered")
            warnings.append("Imported cash evidence does not establish the selected start date.")
        if imported.end_date < period.end_date:
            reasons.append("selected_end_not_covered")
            warnings.append("Imported cash evidence does not establish the selected end date.")

    reasons.extend(aggregation.incomplete_reasons)
    return _CoverageEvaluation(
        state=CoverageState(
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            transaction_count=aggregation.total.transaction_count,
            opening_month=(
                PartialPeriodState.FULL
                if period.start_date.day == 1
                else PartialPeriodState.PARTIAL
            ),
            closing_month=(
                PartialPeriodState.FULL
                if period.end_date.day == _month_end(period.end_date).day
                else PartialPeriodState.PARTIAL
            ),
            completeness=(
                CoverageCompleteness.COMPLETE if not reasons else CoverageCompleteness.INCOMPLETE
            ),
            incomplete_reasons=_stable_unique(reasons),
        ),
        warnings=_stable_unique(warnings),
    )


def _freshness(
    session: Session,
    *,
    coverage: CoverageState,
    as_of_date: date,
    observed_at: datetime,
) -> Freshness:
    connections = list(
        session.scalars(
            select(PlaidConnection)
            .join(Account, Account.plaid_connection_id == PlaidConnection.id)
            .join(Institution, Account.institution_id == Institution.id)
            .where(PlaidConnection.status == "active", Institution.kind == "bank")
            .distinct()
            .order_by(PlaidConnection.id)
        )
    )
    stale_sources = _stable_unique(
        [
            _safe_connection_label(connection)
            for connection in connections
            if connection.last_synced_at is None
            or local_business_date(connection.last_synced_at) != as_of_date
        ]
    )
    warnings: list[str] = []
    if coverage.completeness is CoverageCompleteness.INCOMPLETE:
        state = FreshnessState.INCOMPLETE
        warnings.append("Cash-flow evidence coverage is incomplete.")
    elif stale_sources:
        state = FreshnessState.STALE
    else:
        state = FreshnessState.CURRENT
    if stale_sources:
        warnings.append("One or more applicable bank connections are not current.")
    return Freshness(
        state=state,
        observed_at=observed_at,
        stale_sources=stale_sources,
        warnings=_stable_unique(warnings),
    )


def _safe_connection_label(connection: PlaidConnection) -> str:
    value = " ".join(connection.institution_name.split()).strip()
    if not value:
        value = "Bank"
    return f"{value[:80]} connection"


def _monthly_point(
    period: SelectedPeriod,
    month_start: date,
    buckets: dict[str, CashFlowBucket],
) -> MonthlyCashFlowPoint:
    point_start = max(period.start_date, month_start)
    point_end = min(period.end_date, _month_end(month_start))
    month = month_start.strftime("%Y-%m")
    bucket = buckets.get(month, CashFlowBucket())
    prefix = f"cash-flow:bank:{month}:{point_start.isoformat()}:{point_end.isoformat()}"
    return MonthlyCashFlowPoint(
        month=month,
        start_date=point_start,
        end_date=point_end,
        partial=point_start != month_start or point_end != _month_end(month_start),
        transaction_count=bucket.transaction_count,
        amounts=_amounts(bucket, source_prefix=prefix),
        transfers_excluded=_transfers(bucket, source_prefix=prefix),
    )


def _amounts(bucket: CashFlowBucket, *, source_prefix: str) -> CashFlowAmounts:
    return CashFlowAmounts(
        external_cash_inflows=_observed_money(
            bucket.external_cash_inflows, f"{source_prefix}:external-inflows"
        ),
        interest_received=_observed_money(bucket.interest_received, f"{source_prefix}:interest"),
        money_in=_derived_money(
            bucket.money_in, f"{source_prefix}:money-in", V21MoneyDerivation.MONEY_IN
        ),
        external_cash_outflows=_observed_money(
            bucket.external_cash_outflows, f"{source_prefix}:external-outflows"
        ),
        fees_paid=_observed_money(bucket.fees_paid, f"{source_prefix}:fees"),
        money_out=_derived_money(
            bucket.money_out, f"{source_prefix}:money-out", V21MoneyDerivation.MONEY_OUT
        ),
        net_cash_flow=_derived_money(
            bucket.net_cash_flow,
            f"{source_prefix}:net",
            V21MoneyDerivation.NET_CASH_FLOW,
        ),
    )


def _transfers(bucket: CashFlowBucket, *, source_prefix: str) -> ExcludedTransferTotals:
    return ExcludedTransferTotals(
        matched_owned_account_amount=_observed_money(
            bucket.matched_owned_account_amount, f"{source_prefix}:matched-transfers"
        ),
        matched_owned_account_count=bucket.matched_owned_account_count,
        internal_transfer_amount=_observed_money(
            bucket.internal_transfer_amount, f"{source_prefix}:internal-transfers"
        ),
        internal_transfer_count=bucket.internal_transfer_count,
    )


def _observed_money(amount: Decimal, source_ref: str) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=money(amount),
        evidence=EvidenceClass.OBSERVED,
        source_refs=(source_ref,),
    )


def _derived_money(
    amount: Decimal,
    source_ref: str,
    derivation: V21MoneyDerivation,
) -> V21EvidencedMoney:
    return V21EvidencedMoney(
        amount=money(amount),
        evidence=EvidenceClass.DERIVED,
        source_refs=(source_ref,),
        derivation=derivation,
    )


def _month_start_offset(value: date, offset: int) -> date:
    absolute = value.year * 12 + value.month - 1 + offset
    return date(absolute // 12, absolute % 12 + 1, 1)


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _month_sequence(start_date: date, end_date: date) -> tuple[date, ...]:
    current = start_date.replace(day=1)
    values: list[date] = []
    while current <= end_date:
        values.append(current)
        current = _next_month(current)
    return tuple(values)


def _stable_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
