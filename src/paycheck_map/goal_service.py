"""Deterministic Money Map v2 operational-goal service.

This module owns the Slice 2 goal domain.  Reads calculate from accepted evidence;
check-in creation is explicit and never coupled to an API read or existing refresh flow.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal, cast

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .cash_months import complete_observed_cash_months
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    GoalCheckInComponent,
    GoalProgram,
    ImportArtifact,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    PayrollScheduleEntry,
    PayrollTransactionMatch,
    TransferMatch,
    utcnow,
)
from .models import (
    GoalCheckIn as StoredGoalCheckIn,
)
from .money import ZERO, money
from .reconciliation import investment_performance_available
from .services import DEBT_ACCOUNT_TYPES, RESTRICTED_HOLDING_MARKERS, _investment_access
from .v2_contracts import (
    CONTRACT_VERSION,
    FINGERPRINT_VERSION,
    GOAL_CALCULATION_VERSION,
    ComparisonComponentKind,
    EvidenceClass,
    EvidencedMoney,
    FingerprintGoalConfiguration,
    FingerprintSourceRecord,
    GoalCandidateList,
    GoalCheckIn,
    GoalComparison,
    GoalComparisonComponent,
    GoalEditRequest,
    GoalMilestone,
    GoalPosition,
    GoalProgramView,
    MoneyDerivation,
    PaceStatus,
    PrimaryGoalSelectionRequest,
    PrimaryGoalState,
    SourceFingerprintMaterial,
    SourceMoneyFact,
    SourceRecordKind,
    check_in_identity,
    contract_milestone,
    remaining_funding_months,
    required_funding_pace,
)

PAYCHECKS_PER_YEAR: Final = Decimal("26")
MONTHS_PER_YEAR: Final = Decimal("12")
POSITION_PAYLOAD_VERSION: Final = "goal-position-payload-v1"
COMPONENT_VERSION: Final = "goal-check-in-component-v1"


class GoalServiceError(ValueError):
    """Base class for explicit goal-domain failures."""


class UnknownGoalError(GoalServiceError):
    pass


class StaleGoalWriteError(GoalServiceError):
    pass


class IneligibleGoalError(GoalServiceError):
    pass


class GoalValidationError(GoalServiceError):
    pass


class GoalCheckInTrigger(StrEnum):
    POST_REFRESH = "post_refresh"
    POST_IMPORT = "post_import"
    POST_PAYROLL = "post_payroll"
    LOAD_BACKFILL = "load_backfill"
    LAB_PROMOTION = "lab_promotion"
    SYNTHETIC_TEST = "synthetic_test"


@dataclass(frozen=True)
class CalculatedGoalPosition:
    position: GoalPosition
    source_material: SourceFingerprintMaterial
    source_fingerprint: str


@dataclass(frozen=True)
class GoalComparisonResult:
    state: Literal["available", "no_previous_check_in", "unavailable"]
    comparison: GoalComparison | None = None
    reason: str | None = None


@dataclass(frozen=True)
class GoalTimelinePage:
    check_ins: tuple[GoalCheckIn, ...]
    comparisons: tuple[GoalComparison, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class EnsuredGoalCheckIn:
    check_in: GoalCheckIn
    created: bool


def primary_goal(session: Session) -> GoalProgram | None:
    return session.scalar(
        select(GoalProgram)
        .where(GoalProgram.is_primary.is_(True))
        .order_by(GoalProgram.id)
        .limit(1)
    )


def primary_goal_state(session: Session) -> PrimaryGoalState:
    program = primary_goal(session)
    return PrimaryGoalState(
        state="primary" if program is not None else "no_primary",
        goal=program_view(program) if program is not None else None,
    )


def goal_candidates(session: Session) -> GoalCandidateList:
    rows = tuple(
        program_view(program)
        for program in session.scalars(
            select(GoalProgram)
            .where(
                GoalProgram.is_primary.is_(False),
                GoalProgram.status == "active",
            )
            .order_by(GoalProgram.target_date, GoalProgram.public_key)
        )
    )
    return GoalCandidateList(
        state="selection_required" if rows else "no_candidates",
        candidates=rows,
    )


def program_edit_token(program: GoalProgram) -> str:
    updated = _aware_utc(program.updated_at).isoformat(timespec="microseconds")
    payload = f"{program.public_key}|{updated}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def program_view(program: GoalProgram) -> GoalProgramView:
    return GoalProgramView(
        goal_program_id=program.public_key,
        name=program.name,
        target_date=program.target_date,
        target_amount=_entered_money(
            program.target_amount, _program_refs(program, "target_amount")
        ),
        protected_cash_floor=_entered_money(
            program.protected_cash_floor, _program_refs(program, "protected_cash_floor")
        ),
        reserved_for_goal=_entered_money(
            program.reserved_amount, _program_refs(program, "reserved_amount")
        ),
        status=cast(Literal["active", "complete"], program.status),
        is_primary=program.is_primary,
        source_life_goal_id=program.source_life_goal_id,
        edit_token=program_edit_token(program),
        updated_at=_aware_utc(program.updated_at),
    )


def calculate_primary_goal_position(
    session: Session, *, observed_on: date
) -> CalculatedGoalPosition | None:
    program = primary_goal(session)
    if program is None:
        return None
    return calculate_goal_position(session, program=program, observed_on=observed_on)


def calculate_goal_position(
    session: Session,
    *,
    program: GoalProgram,
    observed_on: date,
) -> CalculatedGoalPosition:
    records: list[FingerprintSourceRecord] = []
    account_evidence = _account_position_evidence(session)
    records.extend(account_evidence.records)

    payroll_money, payroll_record = _payroll_evidence(session)
    if payroll_record is not None:
        records.append(payroll_record)

    outflow_money, outflow_record = _recurring_outflow_evidence(session)
    if outflow_record is not None:
        records.append(outflow_record)

    target = _entered_money(program.target_amount, _program_refs(program, "target_amount"))
    floor = _entered_money(
        program.protected_cash_floor, _program_refs(program, "protected_cash_floor")
    )
    reserved = _entered_money(program.reserved_amount, _program_refs(program, "reserved_amount"))
    goal_record = _goal_configuration_record(program)
    records.append(goal_record)

    accessible_now = _derived_sum(
        account_evidence.accessible_cash,
        account_evidence.accessible_investments,
        MoneyDerivation.ACCESSIBLE_NOW,
        "Accessible cash or confirmed investment evidence is unavailable",
    )
    available_above_floor = _derived_max_difference(
        accessible_now,
        floor,
        MoneyDerivation.AVAILABLE_ABOVE_FLOOR,
        "Accessible capital evidence is unavailable",
    )
    remaining_target = _derived_max_difference(
        target,
        reserved,
        MoneyDerivation.REMAINING_TARGET,
        "Goal configuration is unavailable",
    )
    recurring_gap = _derived_max_difference(
        outflow_money,
        payroll_money,
        MoneyDerivation.RECURRING_CASH_FLOW_GAP,
        "Recurring payroll or outflow coverage is unavailable",
    )

    remaining = _available_amount(remaining_target)
    funding_months = remaining_funding_months(observed_on, program.target_date)
    pace = required_funding_pace(remaining, observed_on, program.target_date)
    calendar_ref = f"calendar:{observed_on.isoformat()}:{program.target_date.isoformat()}"
    pace_refs = tuple(sorted({*target.source_refs, *reserved.source_refs, calendar_ref}))
    if remaining == ZERO:
        pace_status = PaceStatus.COMPLETE
        required_pace = _derived_money(ZERO, MoneyDerivation.REQUIRED_FUNDING_PACE, pace_refs)
    elif pace is None:
        pace_status = PaceStatus.EXPIRED
        required_pace = _unavailable_money("The unfinished goal target date has expired")
    else:
        pace_status = PaceStatus.ACTIVE
        required_pace = _derived_money(pace, MoneyDerivation.REQUIRED_FUNDING_PACE, pace_refs)

    position = GoalPosition(
        goal_program_id=program.public_key,
        observed_on=observed_on,
        target_date=program.target_date,
        accessible_cash=account_evidence.accessible_cash,
        accessible_investments=account_evidence.accessible_investments,
        retirement_assets_excluded=account_evidence.retirement_assets_excluded,
        tracked_debt=account_evidence.tracked_debt,
        accessible_now=accessible_now,
        protected_cash_floor=floor,
        available_above_floor=available_above_floor,
        reserved_for_goal=reserved,
        goal_target=target,
        remaining_target=remaining_target,
        effective_recurring_take_home=payroll_money,
        observed_recurring_outflow=outflow_money,
        recurring_cash_flow_gap=recurring_gap,
        funding_months=funding_months,
        pace_status=pace_status,
        required_funding_pace=required_pace,
    )
    material = SourceFingerprintMaterial(
        goal_configuration=FingerprintGoalConfiguration(
            goal_program_id=program.public_key,
            target_date=program.target_date,
            target_amount=target,
            protected_cash_floor=floor,
            reserved_for_goal=reserved,
        ),
        source_records=tuple(records),
    )
    return CalculatedGoalPosition(
        position=position,
        source_material=material,
        source_fingerprint=material.fingerprint(),
    )


@dataclass(frozen=True)
class _AccountPositionEvidence:
    accessible_cash: EvidencedMoney
    accessible_investments: EvidencedMoney
    retirement_assets_excluded: EvidencedMoney
    tracked_debt: EvidencedMoney
    records: tuple[FingerprintSourceRecord, ...]


def _account_position_evidence(session: Session) -> _AccountPositionEvidence:
    pairs = list(
        session.execute(select(Account, Institution).join(Institution).order_by(Account.id))
    )
    cash_accounts: list[tuple[Account, Institution]] = []
    investment_accounts: list[tuple[Account, Institution]] = []
    debt_accounts: list[tuple[Account, Institution]] = []
    for account, institution in pairs:
        category = _goal_account_category(account, institution)
        account_type = _normalized_account_type(account)
        if category == "cash" and account_type in {"checking", "savings"}:
            cash_accounts.append((account, institution))
        elif category == "investment":
            investment_accounts.append((account, institution))
        elif category == "debt":
            debt_accounts.append((account, institution))

    records: list[FingerprintSourceRecord] = []
    cash_value, cash_refs, cash_complete = _balance_total(
        session,
        cash_accounts,
        field="accessible_cash_contribution",
        absolute=False,
        records=records,
    )
    cash = (
        _observed_money(cash_value, cash_refs)
        if cash_accounts and cash_complete
        else _unavailable_money("Latest checking and savings balance coverage is incomplete")
    )

    investment_total = ZERO
    retirement_total = ZERO
    investment_refs: list[str] = []
    retirement_refs: list[str] = []
    investment_complete = True
    for account, _institution in investment_accounts:
        snapshot = _latest_balance(session, account.id)
        if snapshot is None:
            investment_complete = False
            continue
        holdings = list(
            session.scalars(
                select(InvestmentHolding)
                .where(InvestmentHolding.account_id == account.id)
                .order_by(InvestmentHolding.id)
            )
        )
        accessible, excluded, status, _reason = _investment_access(
            account, snapshot.amount, holdings
        )
        ref = f"investment_access:account:{account.id}:balance:{snapshot.id}"
        if accessible or status in {"accessible", "mixed"}:
            investment_refs.append(ref)
        if status == "retirement":
            retirement_refs.append(ref)
            retirement_total += excluded
        investment_total += accessible
        access_facts = [
            _source_fact("accessible_investments", accessible, EvidenceClass.OBSERVED),
            _source_fact(
                "retirement_assets_excluded",
                excluded if status == "retirement" else ZERO,
                EvidenceClass.OBSERVED,
            ),
            _source_fact(
                "other_inaccessible_assets_excluded",
                excluded if status != "retirement" else ZERO,
                EvidenceClass.OBSERVED,
            ),
        ]
        records.append(
            FingerprintSourceRecord(
                kind=SourceRecordKind.INVESTMENT_ACCESS,
                record_identity=ref,
                record_hash=_investment_access_hash(
                    session,
                    account=account,
                    snapshot=snapshot,
                    holdings=holdings,
                    status=status,
                ),
                effective_date=snapshot.snapshot_date,
                money_facts=tuple(access_facts),
            )
        )
        records.append(_balance_record(session, snapshot, "investment_account_balance"))

    if not investment_accounts:
        inventory_ref = "investment_access:account_inventory:none"
        inventory_hash = _canonical_hash(
            {"kind": "investment_account_inventory", "account_ids": []}
        )
        records.append(
            FingerprintSourceRecord(
                kind=SourceRecordKind.INVESTMENT_ACCESS,
                record_identity=inventory_ref,
                record_hash=inventory_hash,
                effective_date=date(1970, 1, 1),
                money_facts=(
                    _source_fact("accessible_investments", ZERO, EvidenceClass.OBSERVED),
                    _source_fact("retirement_assets_excluded", ZERO, EvidenceClass.OBSERVED),
                ),
            )
        )
        investment_refs.append(inventory_ref)
        retirement_refs.append(inventory_ref)
    investments = (
        _observed_money(investment_total, investment_refs)
        if investment_complete
        else _unavailable_money("Latest investment balance coverage is incomplete")
    )
    retirement = (
        _observed_money(retirement_total, retirement_refs or investment_refs)
        if investment_complete
        else _unavailable_money("Latest retirement balance coverage is incomplete")
    )

    debt_value, debt_refs, debt_complete = _balance_total(
        session,
        debt_accounts,
        field="tracked_debt_contribution",
        absolute=True,
        records=records,
    )
    if not debt_accounts:
        inventory_ref = "balance:debt_account_inventory:none"
        records.append(
            FingerprintSourceRecord(
                kind=SourceRecordKind.BALANCE,
                record_identity=inventory_ref,
                record_hash=_canonical_hash({"kind": "debt_account_inventory", "ids": []}),
                effective_date=date(1970, 1, 1),
                money_facts=(_source_fact("tracked_debt", ZERO, EvidenceClass.OBSERVED),),
            )
        )
        debt_refs.append(inventory_ref)
    debt = (
        _observed_money(debt_value, debt_refs)
        if debt_complete
        else _unavailable_money("Latest tracked-debt balance coverage is incomplete")
    )
    return _AccountPositionEvidence(
        accessible_cash=cash,
        accessible_investments=investments,
        retirement_assets_excluded=retirement,
        tracked_debt=debt,
        records=tuple(records),
    )


def _balance_total(
    session: Session,
    accounts: Iterable[tuple[Account, Institution]],
    *,
    field: str,
    absolute: bool,
    records: list[FingerprintSourceRecord],
) -> tuple[Decimal, list[str], bool]:
    total = ZERO
    refs: list[str] = []
    complete = True
    for account, _institution in accounts:
        snapshot = _latest_balance(session, account.id)
        if snapshot is None:
            complete = False
            continue
        contribution = abs(snapshot.amount) if absolute else snapshot.amount
        total += contribution
        ref = f"balance_snapshot:{snapshot.id}:account:{account.id}"
        refs.append(ref)
        records.append(_balance_record(session, snapshot, field, identity=ref))
    return money(total), refs, complete


def _balance_record(
    session: Session,
    snapshot: BalanceSnapshot,
    field: str,
    *,
    identity: str | None = None,
) -> FingerprintSourceRecord:
    contribution = abs(snapshot.amount) if field == "tracked_debt_contribution" else snapshot.amount
    return FingerprintSourceRecord(
        kind=SourceRecordKind.BALANCE,
        record_identity=identity or f"balance_snapshot:{snapshot.id}:account:{snapshot.account_id}",
        record_hash=_artifact_hash(session, snapshot.artifact_id),
        effective_date=snapshot.snapshot_date,
        money_facts=(_source_fact(field, contribution, EvidenceClass.OBSERVED),),
    )


def _payroll_evidence(
    session: Session,
) -> tuple[EvidencedMoney, FingerprintSourceRecord | None]:
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
        return _unavailable_money("No supported recurring payroll baseline is available"), None
    monthly = money(row.net_payment * PAYCHECKS_PER_YEAR / MONTHS_PER_YEAR)
    ref = f"payroll_schedule:{row.id}:{row.fingerprint}"
    record = FingerprintSourceRecord(
        kind=SourceRecordKind.PAYROLL,
        record_identity=f"payroll_schedule:{row.id}",
        record_hash=row.fingerprint,
        effective_date=row.observed_deposit_date,
        money_facts=(
            _source_fact("net_pay_per_paycheck", row.net_payment, EvidenceClass.OBSERVED),
            _source_fact("effective_monthly_take_home", monthly, EvidenceClass.DERIVED),
            _source_fact("paychecks_per_year", PAYCHECKS_PER_YEAR, EvidenceClass.ASSUMED),
            _source_fact("months_per_year", MONTHS_PER_YEAR, EvidenceClass.ASSUMED),
        ),
    )
    return (
        _derived_money(
            monthly,
            MoneyDerivation.EFFECTIVE_RECURRING_TAKE_HOME,
            (ref, "cadence:biweekly:26-per-year"),
        ),
        record,
    )


def _recurring_outflow_evidence(
    session: Session,
) -> tuple[EvidencedMoney, FingerprintSourceRecord | None]:
    complete_evidence = complete_observed_cash_months(session)
    cash_accounts = list(complete_evidence.accounts)
    if not cash_accounts:
        return _unavailable_money("No cash accounts establish recurring-outflow coverage"), None
    complete_months = set(complete_evidence.months)
    if not complete_months:
        return _unavailable_money("No complete observed cash months establish outflow"), None

    account_ids = [account.id for account in cash_accounts]
    transactions = list(
        session.scalars(
            select(AccountTransaction)
            .where(
                AccountTransaction.account_id.in_(account_ids),
                AccountTransaction.amount < ZERO,
                AccountTransaction.role.in_(["external_outflow", "fee"]),
            )
            .order_by(AccountTransaction.id)
        )
    )
    by_month: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    used_transactions: list[AccountTransaction] = []
    for transaction in transactions:
        key = (transaction.posted_date.year, transaction.posted_date.month)
        if key in complete_months:
            by_month[key] += abs(transaction.amount)
            used_transactions.append(transaction)
    total = sum((by_month[month] for month in complete_months), ZERO)
    monthly = money(total / Decimal(len(complete_months)))
    labels = [f"{year:04d}-{month:02d}" for year, month in sorted(complete_months)]
    evidence_payload = {
        "cash_account_ids": account_ids,
        "coverage_months": labels,
        "coverage_refs": sorted(complete_evidence.coverage_refs),
        "transactions": [
            {
                "id": row.id,
                "artifact_hash": _artifact_hash(session, row.artifact_id),
                "posted_date": row.posted_date.isoformat(),
                "role": row.role,
                "amount": format(money(row.amount), ".2f"),
            }
            for row in used_transactions
        ],
    }
    evidence_hash = _canonical_hash(evidence_payload)
    ref = f"recurring_outflow:{evidence_hash}"
    latest_year, latest_month = max(complete_months)
    record = FingerprintSourceRecord(
        kind=SourceRecordKind.RECURRING_OUTFLOW,
        record_identity=f"recurring_outflow:{','.join(labels)}",
        record_hash=evidence_hash,
        effective_date=date(
            latest_year,
            latest_month,
            calendar.monthrange(latest_year, latest_month)[1],
        ),
        money_facts=(_source_fact("observed_recurring_outflow", monthly, EvidenceClass.OBSERVED),),
    )
    return _observed_money(monthly, (ref,)), record


def _goal_configuration_record(program: GoalProgram) -> FingerprintSourceRecord:
    effective_date = _aware_utc(program.updated_at).date()
    configuration_hash = _canonical_hash(
        {
            "goal_program_id": program.public_key,
            "target_date": program.target_date.isoformat(),
            "target_amount": format(money(program.target_amount), ".2f"),
            "protected_cash_floor": format(money(program.protected_cash_floor), ".2f"),
            "reserved_amount": format(money(program.reserved_amount), ".2f"),
            "field_provenance": {
                field: _program_refs(program, field)
                for field in ("target_amount", "protected_cash_floor", "reserved_amount")
            },
            "configuration_effective_date": effective_date.isoformat(),
        }
    )
    return FingerprintSourceRecord(
        kind=SourceRecordKind.GOAL_CONFIGURATION,
        record_identity=f"goal_configuration:{program.public_key}",
        record_hash=configuration_hash,
        effective_date=effective_date,
        money_facts=(
            _source_fact("goal_target", program.target_amount, EvidenceClass.USER_ENTERED),
            _source_fact(
                "protected_cash_floor",
                program.protected_cash_floor,
                EvidenceClass.USER_ENTERED,
            ),
            _source_fact("reserved_for_goal", program.reserved_amount, EvidenceClass.USER_ENTERED),
        ),
    )


def ensure_goal_check_in(
    session: Session,
    *,
    trigger: GoalCheckInTrigger,
    effective_observation_date: date,
) -> GoalCheckIn:
    """Insert one immutable check-in inside the caller's transaction.

    The savepoint makes parent and components atomic.  The database uniqueness
    constraint, rather than only a preflight read, converges concurrent callers.
    """

    return ensure_goal_check_in_result(
        session,
        trigger=trigger,
        effective_observation_date=effective_observation_date,
    ).check_in


def ensure_goal_check_in_result(
    session: Session,
    *,
    trigger: GoalCheckInTrigger,
    effective_observation_date: date,
) -> EnsuredGoalCheckIn:
    """Return the accepted check-in and whether this transaction inserted it."""

    calculated = calculate_primary_goal_position(session, observed_on=effective_observation_date)
    if calculated is None:
        raise GoalValidationError("A primary goal is required before creating a check-in")
    program = primary_goal(session)
    if program is None:  # defensive against an impossible same-session disappearance
        raise GoalValidationError("A primary goal is required before creating a check-in")
    identity = check_in_identity(program.public_key, calculated.source_fingerprint)
    existing = _stored_check_in(session, identity)
    if existing is not None:
        return EnsuredGoalCheckIn(check_in=serialize_check_in(existing), created=False)

    row = _stored_check_in_row(
        program=program,
        identity=identity,
        calculated=calculated,
        trigger=trigger,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
            session.add_all(_component_rows(row, calculated.position))
            session.flush()
    except IntegrityError:
        existing = _stored_check_in(session, identity)
        if existing is None:
            raise
        return EnsuredGoalCheckIn(check_in=serialize_check_in(existing), created=False)
    return EnsuredGoalCheckIn(check_in=serialize_check_in(row), created=True)


def _stored_check_in_row(
    *,
    program: GoalProgram,
    identity: str,
    calculated: CalculatedGoalPosition,
    trigger: GoalCheckInTrigger,
) -> StoredGoalCheckIn:
    position = calculated.position
    return StoredGoalCheckIn(
        check_in_id=identity,
        goal_program_id=program.id,
        source_fingerprint=calculated.source_fingerprint,
        effective_observation_date=position.observed_on,
        accessible_cash=position.accessible_cash.amount,
        accessible_investments=position.accessible_investments.amount,
        retirement_assets_excluded=position.retirement_assets_excluded.amount,
        tracked_debt=position.tracked_debt.amount,
        accessible_now=position.accessible_now.amount,
        protected_cash_floor=_available_amount(position.protected_cash_floor),
        available_above_floor=position.available_above_floor.amount,
        reserved_amount=_available_amount(position.reserved_for_goal),
        goal_target=_available_amount(position.goal_target),
        remaining_target=_available_amount(position.remaining_target),
        effective_recurring_take_home=position.effective_recurring_take_home.amount,
        observed_recurring_outflow=position.observed_recurring_outflow.amount,
        recurring_cash_flow_gap=position.recurring_cash_flow_gap.amount,
        funding_months=position.funding_months,
        pace_status=position.pace_status.value,
        required_funding_pace=position.required_funding_pace.amount,
        position_evidence={
            "source_fingerprint": calculated.source_fingerprint,
            "source_material": calculated.source_material.model_dump(mode="json"),
        },
        canonical_position_payload=position.model_dump(mode="json"),
        position_payload_version=POSITION_PAYLOAD_VERSION,
        contract_version=CONTRACT_VERSION,
        calculation_version=GOAL_CALCULATION_VERSION,
        fingerprint_version=FINGERPRINT_VERSION,
        trigger=trigger.value,
        created_at=utcnow(),
    )


def _component_rows(
    check_in: StoredGoalCheckIn, position: GoalPosition
) -> list[GoalCheckInComponent]:
    rows: list[GoalCheckInComponent] = []
    for key in (
        "accessible_cash",
        "accessible_investments",
        "retirement_assets_excluded",
        "tracked_debt",
        "accessible_now",
        "protected_cash_floor",
        "available_above_floor",
        "reserved_for_goal",
        "goal_target",
        "remaining_target",
        "effective_recurring_take_home",
        "observed_recurring_outflow",
        "recurring_cash_flow_gap",
        "required_funding_pace",
    ):
        value = getattr(position, key)
        if value.amount is None:
            continue
        rows.append(
            GoalCheckInComponent(
                check_in_id=check_in.check_in_id,
                component_key=key,
                component_version=COMPONENT_VERSION,
                amount=value.amount,
                evidence_class=value.evidence.value,
                derivation=value.derivation.value if value.derivation is not None else None,
                supporting_source_refs=list(value.source_refs),
            )
        )
    return rows


def serialize_check_in(row: StoredGoalCheckIn) -> GoalCheckIn:
    return GoalCheckIn(
        check_in_id=row.check_in_id,
        goal_program_id=row.goal_program.public_key,
        source_fingerprint=row.source_fingerprint,
        effective_observation_date=row.effective_observation_date,
        position=GoalPosition.model_validate(row.canonical_position_payload),
        trigger=cast(Any, row.trigger),
        created_at=_aware_utc(row.created_at),
    )


def latest_check_in(session: Session, *, program: GoalProgram) -> GoalCheckIn | None:
    row = session.scalar(_ordered_check_ins(program.id).limit(1))
    return serialize_check_in(row) if row is not None else None


def check_in_timeline(
    session: Session,
    *,
    program: GoalProgram,
    limit: int = 20,
    cursor: str | None = None,
) -> GoalTimelinePage:
    if limit < 1 or limit > 100:
        raise GoalValidationError("Timeline limit must be between 1 and 100")
    statement = _ordered_check_ins(program.id)
    if cursor is not None:
        created_at, check_in_id_value = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                StoredGoalCheckIn.created_at < created_at,
                and_(
                    StoredGoalCheckIn.created_at == created_at,
                    StoredGoalCheckIn.check_in_id < check_in_id_value,
                ),
            )
        )
    rows = list(session.scalars(statement.limit(limit + 1)))
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = _encode_cursor(page_rows[-1]) if has_more and page_rows else None
    return GoalTimelinePage(
        check_ins=tuple(serialize_check_in(row) for row in page_rows),
        comparisons=tuple(
            result.comparison
            for index, row in enumerate(page_rows)
            if index + 1 < len(rows)
            for result in (_comparison_between(session, previous=rows[index + 1], current=row),)
            if result.comparison is not None
        ),
        next_cursor=next_cursor,
    )


def latest_comparison(session: Session, *, program: GoalProgram) -> GoalComparisonResult:
    rows = list(session.scalars(_ordered_check_ins(program.id).limit(2)))
    if len(rows) < 2:
        return GoalComparisonResult(
            state="no_previous_check_in",
            reason="At least two distinct persisted check-ins are required",
        )
    current, previous = rows[0], rows[1]
    return _comparison_between(session, previous=previous, current=current)


def _comparison_between(
    session: Session,
    *,
    previous: StoredGoalCheckIn,
    current: StoredGoalCheckIn,
) -> GoalComparisonResult:
    program = current.goal_program
    direct_fields = (
        (ComparisonComponentKind.ACCESSIBLE_NOW, "accessible_now"),
        (ComparisonComponentKind.ACCESSIBLE_CASH, "accessible_cash"),
        (ComparisonComponentKind.ACCESSIBLE_INVESTMENTS, "accessible_investments"),
        (ComparisonComponentKind.TRACKED_DEBT, "tracked_debt"),
        (ComparisonComponentKind.GOAL_TARGET, "goal_target"),
        (ComparisonComponentKind.PROTECTED_CASH_FLOOR, "protected_cash_floor"),
        (ComparisonComponentKind.RESERVED_FOR_GOAL, "reserved_amount"),
    )
    unavailable_fields = [
        attribute
        for _kind, attribute in direct_fields
        if getattr(previous, attribute) is None or getattr(current, attribute) is None
    ]
    if unavailable_fields:
        return GoalComparisonResult(
            state="unavailable",
            reason="Required comparison values are unavailable: " + ", ".join(unavailable_fields),
        )

    components = [
        _comparison_component(
            kind,
            money(getattr(current, attribute) - getattr(previous, attribute)),
            refs=(
                f"check_in:{previous.check_in_id}:{attribute}",
                f"check_in:{current.check_in_id}:{attribute}",
            ),
        )
        for kind, attribute in direct_fields
    ]
    supported_events: list[GoalComparisonComponent] = []
    for kind, detector in (
        (ComparisonComponentKind.SUPPORTED_PAYROLL, _supported_payroll_change),
        (ComparisonComponentKind.SUPPORTED_TRANSFER, _supported_transfer_change),
        (
            ComparisonComponentKind.SUPPORTED_MARKET_MOVEMENT,
            _supported_market_change,
        ),
    ):
        event = detector(session, previous, current)
        if event is not None:
            change, refs = event
            supported_events.append(
                _comparison_component(kind, change, refs=refs, supported_event=True)
            )
    components.extend(supported_events)
    previous_accessible = cast(Decimal, previous.accessible_now)
    current_accessible = cast(Decimal, current.accessible_now)
    accessible_delta = money(current_accessible - previous_accessible)
    supported_total = sum((_available_amount(item.change) for item in supported_events), ZERO)
    residual = money(accessible_delta - supported_total)
    components.append(
        GoalComparisonComponent(
            component=ComparisonComponentKind.UNEXPLAINED_RESIDUAL,
            change=_derived_money(
                residual,
                MoneyDerivation.UNEXPLAINED_RESIDUAL,
                (
                    f"check_in:{previous.check_in_id}:accessible_now",
                    f"check_in:{current.check_in_id}:accessible_now",
                ),
            ),
        )
    )
    return GoalComparisonResult(
        state="available",
        comparison=GoalComparison(
            goal_program_id=program.public_key,
            previous_check_in_id=previous.check_in_id,
            current_check_in_id=current.check_in_id,
            previous_source_fingerprint=previous.source_fingerprint,
            current_source_fingerprint=current.source_fingerprint,
            previous_observation_date=previous.effective_observation_date,
            current_observation_date=current.effective_observation_date,
            components=tuple(components),
        ),
    )


def current_milestone(calculated: CalculatedGoalPosition) -> GoalMilestone:
    return contract_milestone(calculated.position, calculated.source_fingerprint)


def edit_goal(
    session: Session,
    *,
    goal_program_id: str,
    request: GoalEditRequest,
    provenance_origin: str = "v2_owner_edit",
    provenance_source_ref: str | None = None,
) -> GoalProgramView:
    program = session.scalar(
        select(GoalProgram).where(GoalProgram.public_key == goal_program_id).limit(1)
    )
    if program is None:
        raise UnknownGoalError(f"Unknown goal program: {goal_program_id}")
    if request.expected_edit_token != program_edit_token(program):
        raise StaleGoalWriteError("Goal configuration changed after this edit was loaded")

    next_values: dict[str, object] = {
        "name": request.name if request.name is not None else program.name,
        "target_date": (
            request.target_date if request.target_date is not None else program.target_date
        ),
        "target_amount": (
            request.target_amount if request.target_amount is not None else program.target_amount
        ),
        "protected_cash_floor": (
            request.protected_cash_floor
            if request.protected_cash_floor is not None
            else program.protected_cash_floor
        ),
        "reserved_amount": (
            request.reserved_for_goal
            if request.reserved_for_goal is not None
            else program.reserved_amount
        ),
    }
    target = money(cast(Decimal, next_values["target_amount"]))
    floor = money(cast(Decimal, next_values["protected_cash_floor"]))
    reserved = money(cast(Decimal, next_values["reserved_amount"]))
    if min(target, floor, reserved) < ZERO:
        raise GoalValidationError("Goal money inputs cannot be negative")
    if reserved > target:
        raise GoalValidationError("Reserved amount cannot exceed the goal target")
    changed_fields = {
        field
        for field, current in (
            ("name", program.name),
            ("target_date", program.target_date),
            ("target_amount", program.target_amount),
            ("protected_cash_floor", program.protected_cash_floor),
            ("reserved_amount", program.reserved_amount),
        )
        if next_values[field] != current
    }
    if not changed_fields:
        raise GoalValidationError("The submitted goal edit does not change any value")

    changed_at = utcnow()
    provenance = dict(program.field_provenance)
    for field in changed_fields:
        provenance[field] = _owner_edit_provenance(
            program.public_key,
            field,
            changed_at,
            origin=provenance_origin,
            source_ref=provenance_source_ref,
        )
    status = "complete" if reserved >= target else "active"
    if status != program.status:
        changed_fields.add("status")
        provenance["status"] = {
            "evidence": "derived",
            "source_refs": sorted(
                {
                    *_program_refs_from_mapping(provenance, "target_amount"),
                    *_program_refs_from_mapping(provenance, "reserved_amount"),
                }
            ),
            "edit_origin": provenance_origin,
        }
    result = session.execute(
        update(GoalProgram)
        .where(
            GoalProgram.id == program.id,
            GoalProgram.updated_at == program.updated_at,
        )
        .values(
            **next_values,
            status=status,
            field_provenance=provenance,
            updated_at=changed_at,
        )
    )
    if cast(Any, result).rowcount != 1:
        raise StaleGoalWriteError("Goal configuration changed during this edit")
    session.flush()
    session.expire(program)
    session.refresh(program)
    return program_view(program)


def select_primary_goal(
    session: Session, *, request: PrimaryGoalSelectionRequest
) -> GoalProgramView:
    candidate = session.scalar(
        select(GoalProgram).where(GoalProgram.public_key == request.goal_program_id).limit(1)
    )
    if candidate is None:
        raise UnknownGoalError(f"Unknown goal program: {request.goal_program_id}")
    if request.expected_edit_token != program_edit_token(candidate):
        raise StaleGoalWriteError("Goal candidate changed after the list was loaded")
    if candidate.is_primary:
        raise IneligibleGoalError("The selected goal is already primary")
    if candidate.status != "active":
        raise IneligibleGoalError("Only an active goal may become primary")

    changed_at = utcnow()
    previous = list(
        session.scalars(
            select(GoalProgram).where(GoalProgram.is_primary.is_(True)).order_by(GoalProgram.id)
        )
    )
    try:
        for program in previous:
            provenance = dict(program.field_provenance)
            provenance["is_primary"] = _owner_edit_provenance(
                program.public_key, "is_primary", changed_at
            )
            program.is_primary = False
            program.field_provenance = provenance
            program.updated_at = changed_at
        session.flush()
        candidate_provenance = dict(candidate.field_provenance)
        candidate_provenance["is_primary"] = _owner_edit_provenance(
            candidate.public_key, "is_primary", changed_at
        )
        candidate.is_primary = True
        candidate.field_provenance = candidate_provenance
        candidate.updated_at = changed_at
        session.flush()
    except IntegrityError as exc:
        raise StaleGoalWriteError("Primary-goal selection conflicted with another write") from exc
    return program_view(candidate)


def _ordered_check_ins(program_id: int) -> Select[tuple[StoredGoalCheckIn]]:
    return (
        select(StoredGoalCheckIn)
        .options(
            selectinload(StoredGoalCheckIn.goal_program),
            selectinload(StoredGoalCheckIn.components),
        )
        .where(StoredGoalCheckIn.goal_program_id == program_id)
        .order_by(
            StoredGoalCheckIn.created_at.desc(),
            StoredGoalCheckIn.check_in_id.desc(),
        )
    )


def _stored_check_in(session: Session, identity: str) -> StoredGoalCheckIn | None:
    return session.scalar(
        select(StoredGoalCheckIn)
        .options(
            selectinload(StoredGoalCheckIn.goal_program),
            selectinload(StoredGoalCheckIn.components),
        )
        .where(StoredGoalCheckIn.check_in_id == identity)
        .limit(1)
    )


def _supported_payroll_change(
    session: Session,
    previous: StoredGoalCheckIn,
    current: StoredGoalCheckIn,
) -> tuple[Decimal, tuple[str, ...]] | None:
    schedules = list(
        session.scalars(
            select(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date > previous.effective_observation_date,
                PayrollScheduleEntry.observed_deposit_date <= current.effective_observation_date,
            )
            .order_by(PayrollScheduleEntry.id)
        )
    )
    total = ZERO
    refs: set[str] = set()
    for schedule in schedules:
        matches = list(
            session.scalars(
                select(PayrollTransactionMatch)
                .where(PayrollTransactionMatch.schedule_entry_id == schedule.id)
                .order_by(PayrollTransactionMatch.id)
            )
        )
        if not matches:
            continue
        transactions = [session.get(AccountTransaction, match.transaction_id) for match in matches]
        if any(transaction is None for transaction in transactions):
            continue
        supported = [transaction for transaction in transactions if transaction is not None]
        matched_total = money(sum((transaction.amount for transaction in supported), ZERO))
        if matched_total != money(schedule.net_payment):
            continue
        if any(not _transaction_account_is_accessible(session, row) for row in supported):
            continue
        total += matched_total
        refs.add(f"payroll_schedule:{schedule.id}:{schedule.fingerprint}")
        refs.update(f"payroll_transaction_match:{match.id}" for match in matches)
        refs.update(f"account_transaction:{row.id}" for row in supported)
    return (money(total), tuple(sorted(refs))) if refs else None


def _supported_transfer_change(
    session: Session,
    previous: StoredGoalCheckIn,
    current: StoredGoalCheckIn,
) -> tuple[Decimal, tuple[str, ...]] | None:
    matches = list(session.scalars(select(TransferMatch).order_by(TransferMatch.id)))
    total = ZERO
    refs: set[str] = set()
    for match in matches:
        left = session.get(AccountTransaction, match.left_transaction_id)
        right = session.get(AccountTransaction, match.right_transaction_id)
        if left is None or right is None:
            continue
        if max(left.posted_date, right.posted_date) <= previous.effective_observation_date:
            continue
        if max(left.posted_date, right.posted_date) > current.effective_observation_date:
            continue
        if left.amount * right.amount >= ZERO:
            continue
        if abs(left.amount) != money(match.amount) or abs(right.amount) != money(match.amount):
            continue
        impact = ZERO
        for transaction in (left, right):
            if _transaction_account_is_accessible(session, transaction):
                impact += transaction.amount
        total += impact
        refs.update(
            {
                f"transfer_match:{match.id}",
                f"account_transaction:{left.id}",
                f"account_transaction:{right.id}",
            }
        )
    return (money(total), tuple(sorted(refs))) if refs else None


def _supported_market_change(
    session: Session,
    previous: StoredGoalCheckIn,
    current: StoredGoalCheckIn,
) -> tuple[Decimal, tuple[str, ...]] | None:
    bridges = list(
        session.scalars(
            select(InvestmentValueBridge)
            .where(
                InvestmentValueBridge.period_start == previous.effective_observation_date,
                InvestmentValueBridge.period_end == current.effective_observation_date,
            )
            .order_by(InvestmentValueBridge.id)
        )
    )
    total = ZERO
    refs: set[str] = set()
    for bridge in bridges:
        account = session.get(Account, bridge.account_id)
        if account is None or not _investment_account_is_confirmed_accessible(session, account):
            continue
        if not investment_performance_available(bridge):
            continue
        total += bridge.investment_result
        refs.add(f"investment_value_bridge:{bridge.id}")
    return (money(total), tuple(sorted(refs))) if refs else None


def _comparison_component(
    kind: ComparisonComponentKind,
    change: Decimal,
    *,
    refs: tuple[str, ...],
    supported_event: bool = False,
) -> GoalComparisonComponent:
    return GoalComparisonComponent(
        component=kind,
        change=_derived_money(change, MoneyDerivation.COMPARISON_DELTA, refs),
        interpretation=("evidence_supported_event" if supported_event else "arithmetic_only"),
        supporting_evidence_refs=refs if supported_event else (),
    )


def _transaction_account_is_accessible(session: Session, transaction: AccountTransaction) -> bool:
    account = session.get(Account, transaction.account_id)
    if account is None:
        return False
    institution = session.get(Institution, account.institution_id)
    if institution is None:
        return False
    category = _goal_account_category(account, institution)
    if category == "cash":
        return _normalized_account_type(account) in {"checking", "savings"}
    if category == "investment":
        return _investment_account_is_confirmed_accessible(session, account)
    return False


def _investment_account_is_confirmed_accessible(session: Session, account: Account) -> bool:
    account_type = _normalized_account_type(account)
    if account_type in {"brokerage", "investment"}:
        return True
    if account_type != "stock plan":
        return False
    snapshot = _latest_balance(session, account.id)
    if snapshot is None:
        return False
    holdings = list(
        session.scalars(select(InvestmentHolding).where(InvestmentHolding.account_id == account.id))
    )
    accessible, excluded, status, _reason = _investment_access(account, snapshot.amount, holdings)
    return accessible > ZERO and excluded == ZERO and status == "accessible"


def _latest_balance(session: Session, account_id: int) -> BalanceSnapshot | None:
    return session.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.snapshot_date.desc(), BalanceSnapshot.id.desc())
        .limit(1)
    )


def _artifact_hash(session: Session, artifact_id: int) -> str | None:
    artifact = session.get(ImportArtifact, artifact_id)
    return artifact.sha256 if artifact is not None else None


def _investment_access_hash(
    session: Session,
    *,
    account: Account,
    snapshot: BalanceSnapshot,
    holdings: list[InvestmentHolding],
    status: str,
) -> str:
    return _canonical_hash(
        {
            "account_id": account.id,
            "account_type": _normalized_account_type(account),
            "snapshot_id": snapshot.id,
            "snapshot_artifact_hash": _artifact_hash(session, snapshot.artifact_id),
            "status": status,
            "holdings": [
                {
                    "id": row.id,
                    "security_id": row.security_id,
                    "restricted": _holding_is_restricted(row),
                    "institution_value": format(money(row.institution_value), ".2f"),
                    "as_of": row.as_of.isoformat(),
                    "artifact_hash": _artifact_hash(session, row.artifact_id),
                }
                for row in holdings
            ],
        }
    )


def _source_fact(field: str, amount: Decimal, evidence: EvidenceClass) -> SourceMoneyFact:
    return SourceMoneyFact(
        field=field,
        amount=money(amount),
        evidence=cast(Any, evidence),
    )


def _entered_money(value: Decimal, refs: Iterable[str]) -> EvidencedMoney:
    return EvidencedMoney(
        amount=money(value),
        evidence=EvidenceClass.USER_ENTERED,
        source_refs=tuple(refs),
    )


def _observed_money(value: Decimal, refs: Iterable[str]) -> EvidencedMoney:
    normalized_refs = tuple(sorted(set(refs)))
    if not normalized_refs:
        raise ValueError("Observed money requires stable source references")
    return EvidencedMoney(
        amount=money(value),
        evidence=EvidenceClass.OBSERVED,
        source_refs=normalized_refs,
    )


def _derived_money(
    value: Decimal,
    derivation: MoneyDerivation,
    refs: Iterable[str],
) -> EvidencedMoney:
    return EvidencedMoney(
        amount=money(value),
        evidence=EvidenceClass.DERIVED,
        source_refs=tuple(sorted(set(refs))),
        derivation=derivation,
    )


def _unavailable_money(reason: str) -> EvidencedMoney:
    return EvidencedMoney(
        amount=None,
        evidence=EvidenceClass.UNAVAILABLE,
        unavailable_reason=reason,
    )


def _derived_sum(
    left: EvidencedMoney,
    right: EvidencedMoney,
    derivation: MoneyDerivation,
    unavailable_reason: str,
) -> EvidencedMoney:
    if left.amount is None or right.amount is None:
        return _unavailable_money(unavailable_reason)
    return _derived_money(
        money(left.amount + right.amount),
        derivation,
        (*left.source_refs, *right.source_refs),
    )


def _derived_max_difference(
    minuend: EvidencedMoney,
    subtrahend: EvidencedMoney,
    derivation: MoneyDerivation,
    unavailable_reason: str,
) -> EvidencedMoney:
    if minuend.amount is None or subtrahend.amount is None:
        return _unavailable_money(unavailable_reason)
    return _derived_money(
        money(max(minuend.amount - subtrahend.amount, ZERO)),
        derivation,
        (*minuend.source_refs, *subtrahend.source_refs),
    )


def _available_amount(value: EvidencedMoney) -> Decimal:
    if value.amount is None:
        raise ValueError("Expected an available exact monetary value")
    return value.amount


def _program_refs(program: GoalProgram, field: str) -> tuple[str, ...]:
    return _program_refs_from_mapping(program.field_provenance, field) or (
        f"goal_program:{program.public_key}:{field}",
    )


def _program_refs_from_mapping(provenance: dict[str, Any], field: str) -> tuple[str, ...]:
    raw = provenance.get(field, {})
    if not isinstance(raw, dict):
        return ()
    refs = raw.get("source_refs", [])
    if not isinstance(refs, list):
        return ()
    return tuple(sorted({str(ref) for ref in refs if str(ref)}))


def _owner_edit_provenance(
    goal_program_id: str,
    field: str,
    changed_at: datetime,
    *,
    origin: str = "v2_owner_edit",
    source_ref: str | None = None,
) -> dict[str, object]:
    refs = [
        source_ref
        or (
            f"goal_program:{goal_program_id}:{origin}:{field}:"
            f"{changed_at.isoformat(timespec='microseconds')}"
        )
    ]
    return {
        "evidence": "user_entered",
        "source_refs": refs,
        "edit_origin": origin,
    }


def _normalized_account_type(account: Account) -> str:
    return account.account_type.strip().lower().replace("_", " ")


def _goal_account_category(account: Account, institution: Institution) -> str:
    account_type = _normalized_account_type(account)
    if account_type in DEBT_ACCOUNT_TYPES:
        return "debt"
    if institution.kind == "investment":
        return "investment"
    if institution.kind == "bank":
        return "cash"
    return "other"


def _holding_is_restricted(holding: InvestmentHolding) -> bool:
    label = f"{holding.security_name} {holding.ticker_symbol or ''}".lower()
    return any(marker in label for marker in RESTRICTED_HOLDING_MARKERS)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(row: StoredGoalCheckIn) -> str:
    payload = json.dumps(
        [
            _aware_utc(row.created_at).isoformat(timespec="microseconds"),
            row.check_in_id,
        ],
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        created_text, check_in_id_value = json.loads(raw)
        created_at = datetime.fromisoformat(created_text)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        if len(check_in_id_value) != 64:
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise GoalValidationError("Invalid goal check-in cursor") from exc
    return created_at, check_in_id_value
