from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from itertools import combinations, pairwise

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .balances import generate_account_balance_points
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    ExternalFlow,
    Institution,
    InvestmentValueBridge,
    PayrollAllocation,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
    PayrollTransactionMatch,
    ReconciliationResult,
    TransferMatch,
)
from .money import ZERO, money
from .payroll import schedule_validation

TOLERANCE = Decimal("0.01")
MIN_INVESTMENT_PERFORMANCE_DAYS = 7
AVAILABLE_INVESTMENT_RETURN_METHODS = {"modified_dietz", "dollar_residual"}
INVESTMENT_CASH_FLOW_ROLES = {
    "employee_contribution",
    "employer_contribution",
    "stock_plan_contribution",
    "external_deposit",
    "external_withdrawal",
    "internal_transfer",
}
DEBT_ACCOUNT_TYPES = {
    "auto",
    "consumer",
    "credit card",
    "credit",
    "home equity",
    "loan",
    "mortgage",
    "overdraft",
    "student",
}
INVESTMENT_ACCOUNT_TYPES = {
    "401k",
    "403b",
    "529",
    "brokerage",
    "ira",
    "investment",
    "pension",
    "retirement",
    "roth",
    "stock plan",
}


def payroll_residual(statement: PayrollStatement) -> Decimal:
    """Cash gross less non-cash imputed earnings and all deductions equals net pay."""

    return money(
        statement.gross_earnings
        - statement.imputed_earnings
        - statement.pretax_deductions
        - statement.tax_withholdings
        - statement.after_tax_deductions
        - statement.net_payment
    )


def sofi_balance_residual(
    opening_balance: Decimal, transactions: list[Decimal], closing_balance: Decimal
) -> Decimal:
    return money(opening_balance + sum(transactions, ZERO) - closing_balance)


def fidelity_investment_result(
    *,
    opening_value: Decimal,
    closing_value: Decimal,
    employee_contributions: Decimal = ZERO,
    employer_contributions: Decimal = ZERO,
    stock_plan_contributions: Decimal = ZERO,
    other_deposits: Decimal = ZERO,
    withdrawals: Decimal = ZERO,
) -> Decimal:
    return money(
        closing_value
        - opening_value
        - employee_contributions
        - employer_contributions
        - stock_plan_contributions
        - other_deposits
        + withdrawals
    )


def investment_performance_available(bridge: InvestmentValueBridge) -> bool:
    return bridge.return_method in AVAILABLE_INVESTMENT_RETURN_METHODS


def _currency(value: Decimal) -> str:
    return f"${money(value):,.2f}"


def _transaction_total(transactions: list[AccountTransaction], role: str) -> Decimal:
    return money(sum((row.amount for row in transactions if row.role == role), ZERO))


def _payroll_section_total(lines: list[PayrollLineItem], section: str) -> Decimal:
    prefix = f"{section}."
    return money(sum((line.amount for line in lines if line.category.startswith(prefix)), ZERO))


def _result(
    session: Session,
    entity_type: str,
    entity_id: int | str,
    rule: str,
    status: str,
    residual: Decimal | None = None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        ReconciliationResult(
            entity_type=entity_type,
            entity_id=str(entity_id),
            rule=rule,
            status=status,
            residual=residual,
            details=details or {},
        )
    )


def _reconcile_payroll(session: Session) -> None:
    statements = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date))
    )
    for statement in statements:
        residual = payroll_residual(statement)
        _result(
            session,
            "payroll_statement",
            statement.id,
            "payroll_arithmetic",
            "reconciled" if abs(residual) <= TOLERANCE else "unreconciled",
            residual,
            {"formula": ("gross - imputed non-cash - pretax - taxes - after-tax - net payment")},
        )
        detail_results: dict[str, Decimal] = {}
        if statement.detail_complete:
            lines = list(
                session.scalars(
                    select(PayrollLineItem).where(
                        PayrollLineItem.statement_id == statement.id,
                        PayrollLineItem.category.contains("."),
                    )
                )
            )

            detail_results = {
                "earnings_detail": money(
                    _payroll_section_total(lines, "earnings")
                    + _payroll_section_total(lines, "imputed")
                    - statement.gross_earnings
                ),
                "pretax_detail": money(
                    _payroll_section_total(lines, "pretax") - statement.pretax_deductions
                ),
                "tax_detail": money(
                    _payroll_section_total(lines, "taxes") - statement.tax_withholdings
                ),
                "after_tax_detail": money(
                    _payroll_section_total(lines, "after_tax") - statement.after_tax_deductions
                ),
                "net_distribution_detail": money(
                    _payroll_section_total(lines, "net_distribution") - statement.net_payment
                ),
            }
            for rule, detail_residual in detail_results.items():
                _result(
                    session,
                    "payroll_statement",
                    statement.id,
                    rule,
                    "reconciled" if abs(detail_residual) <= TOLERANCE else "unreconciled",
                    detail_residual,
                )

        if statement.detail_complete:
            detail_ok = bool(detail_results) and all(
                abs(value) <= TOLERANCE for value in detail_results.values()
            )
            _result(
                session,
                "payroll_statement",
                statement.id,
                "destination_detail",
                "reconciled" if detail_ok else "unreconciled",
                details={
                    "message": (
                        "Detailed earnings, deductions, employer benefits, and deposits reconcile."
                        if detail_ok
                        else "One or more detailed payroll sections do not match the summary."
                    )
                },
            )
        duplicates = [
            item
            for item in statements
            if item.id != statement.id and item.payment_date == statement.payment_date
        ]
        _result(
            session,
            "payroll_statement",
            statement.id,
            "duplicate_pay_date",
            "unreconciled" if duplicates else "reconciled",
        )


def _match_transfers(session: Session) -> set[int]:
    internal_rows = list(
        session.scalars(
            select(AccountTransaction)
            .where(AccountTransaction.role == "internal_transfer")
            .order_by(AccountTransaction.posted_date)
        )
    )
    possible_counterparts = list(
        session.scalars(
            select(AccountTransaction)
            .where(
                AccountTransaction.role.in_(
                    ["internal_transfer", "external_deposit", "external_withdrawal"]
                )
            )
            .order_by(AccountTransaction.posted_date)
        )
    )
    matched: set[int] = set()
    for left in internal_rows:
        if left.id in matched:
            continue
        for right in possible_counterparts:
            if right.id in matched or left.id == right.id or left.account_id == right.account_id:
                continue
            if left.amount != -right.amount:
                continue
            if abs((left.posted_date - right.posted_date).days) > 3:
                continue
            session.add(
                TransferMatch(
                    left_transaction_id=min(left.id, right.id),
                    right_transaction_id=max(left.id, right.id),
                    amount=abs(left.amount),
                    confidence="high" if left.posted_date == right.posted_date else "medium",
                )
            )
            matched.update({left.id, right.id})
            break
    return matched


def _reconcile_bank_accounts(session: Session, matched_transfers: set[int]) -> None:
    accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(Institution.kind == "bank")
            .options(selectinload(Account.institution))
        )
    )
    for account in accounts:
        balances = list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id == account.id)
                .order_by(BalanceSnapshot.snapshot_date)
            )
        )
        openings = [item for item in balances if item.kind == "opening"]
        closings = [item for item in balances if item.kind == "closing"]
        current = [item for item in balances if item.kind == "current"]
        if not openings and len(current) >= 2:
            openings = [current[0]]
        if not closings and current:
            closings = [current[-1]]
        all_transactions = list(
            session.scalars(
                select(AccountTransaction)
                .where(AccountTransaction.account_id == account.id)
                .order_by(AccountTransaction.posted_date, AccountTransaction.id)
            )
        )
        if openings and closings and openings[0].snapshot_date < closings[-1].snapshot_date:
            opening = openings[0]
            closing = closings[-1]
            interval_transactions = [
                transaction
                for transaction in all_transactions
                if opening.snapshot_date < transaction.posted_date <= closing.snapshot_date
            ]
            strict_residual = sofi_balance_residual(
                opening.amount,
                [transaction.amount for transaction in interval_transactions],
                closing.amount,
            )
            opening_date_transactions = [
                transaction
                for transaction in all_transactions
                if transaction.posted_date == opening.snapshot_date
                and transaction.id not in matched_transfers
                and transaction.role != "internal_transfer"
            ]
            opening_date_outflows = money(
                sum(
                    (
                        transaction.amount
                        for transaction in opening_date_transactions
                        if transaction.amount < 0
                    ),
                    ZERO,
                )
            )
            opening_date_inflows = money(
                sum(
                    (
                        transaction.amount
                        for transaction in opening_date_transactions
                        if transaction.amount > 0
                    ),
                    ZERO,
                )
            )
            boundary_explanation: str | None = None
            if abs(strict_residual + opening_date_outflows) <= TOLERANCE:
                boundary_explanation = "opening-date outflows"
            elif abs(strict_residual + opening_date_inflows) <= TOLERANCE:
                boundary_explanation = "opening-date inflows"
            timing_reconciled = boundary_explanation is not None
            reconciled = abs(strict_residual) <= TOLERANCE or timing_reconciled
            interval_total = money(sum((row.amount for row in interval_transactions), ZERO))
            expected_closing = money(opening.amount + interval_total)
            account_type = account.account_type.strip().lower().replace("_", " ")
            is_debt = account_type in DEBT_ACCOUNT_TYPES or any(
                token in account.display_name.lower()
                for token in ("loan", "mortgage", "credit card")
            )
            if timing_reconciled:
                message = (
                    f"{account.display_name} reconciles when {boundary_explanation} dated "
                    f"{opening.snapshot_date:%b %-d} are placed after the opening balance. "
                    "Plaid supplies a posting date but not a within-day posting time."
                )
                likely_cause = "same_day_posting_boundary"
                next_steps = [
                    "No adjustment is needed; the dated activity exactly explains the difference.",
                    "Keep the next observed balance so the timing boundary remains "
                    "independently checkable.",
                ]
            elif is_debt and not reconciled:
                direction = "higher" if strict_residual < 0 else "lower"
                message = (
                    f"{account.display_name} closed {_currency(abs(strict_residual))} {direction} "
                    "than its posted activity explains. Loan balances can change from accrued "
                    "interest "
                    "or provider adjustments that are not returned as transactions."
                )
                likely_cause = "interest_or_balance_adjustment"
                next_steps = [
                    "Update the connection and check whether the provider supplies the missing "
                    "loan activity.",
                    "If it persists, compare the opening and closing balances with the loan "
                    "statement.",
                    "Leave the item open unless statement evidence identifies the interest or "
                    "adjustment.",
                ]
            elif reconciled:
                message = f"{account.display_name} balances reconcile to posted activity."
                likely_cause = "none"
                next_steps = []
            else:
                direction = "below" if strict_residual > 0 else "above"
                message = (
                    f"{account.display_name} closed {_currency(abs(strict_residual))} {direction} "
                    "the balance implied by posted activity."
                )
                likely_cause = "missing_or_mistimed_activity"
                next_steps = [
                    "Update the connection to retrieve newly posted or corrected activity.",
                    "Compare the listed opening and closing evidence with the source account "
                    "statement.",
                    "Do not add a balancing adjustment without source evidence.",
                ]
            _result(
                session,
                "account",
                account.id,
                "account_balance",
                "reconciled" if reconciled else "unreconciled",
                ZERO if reconciled else strict_residual,
                {
                    "account_name": account.display_name,
                    "institution": account.institution.canonical_name,
                    "opening_date": str(opening.snapshot_date),
                    "opening_balance": f"{opening.amount:.2f}",
                    "closing_date": str(closing.snapshot_date),
                    "closing_balance": f"{closing.amount:.2f}",
                    "accounted_activity": f"{interval_total:.2f}",
                    "expected_closing_balance": f"{expected_closing:.2f}",
                    "strict_residual": f"{strict_residual:.2f}",
                    "opening_date_outflows": f"{abs(opening_date_outflows):.2f}",
                    "opening_date_inflows": f"{opening_date_inflows:.2f}",
                    "likely_cause": likely_cause,
                    "message": message,
                    "next_steps": next_steps,
                },
            )
        for transaction in all_transactions:
            if transaction.role in {
                "external_inflow",
                "external_outflow",
                "interest",
                "fee",
                "adjustment",
                "payroll_deposit",
            }:
                session.add(
                    ExternalFlow(
                        transaction_id=transaction.id,
                        role=transaction.role,
                        amount=transaction.amount,
                    )
                )
            elif (
                transaction.role == "internal_transfer" and transaction.id not in matched_transfers
            ):
                continue
            elif transaction.role == "unresolved":
                _result(
                    session,
                    "account_transaction",
                    transaction.id,
                    "transaction_role",
                    "unresolved",
                )


def _match_payroll_deposits(session: Session) -> None:
    statements = list(session.scalars(select(PayrollStatement)))
    flows = list(
        session.scalars(
            select(ExternalFlow)
            .join(AccountTransaction, ExternalFlow.transaction_id == AccountTransaction.id)
            .where(ExternalFlow.amount > 0)
        )
    )
    used: set[int] = set()
    for statement in statements:
        candidates: list[tuple[int, ExternalFlow]] = []
        for flow in flows:
            if flow.id in used or flow.amount != statement.net_payment:
                continue
            transaction = session.get(AccountTransaction, flow.transaction_id)
            if transaction is None:
                continue
            gap = abs((transaction.posted_date - statement.payment_date).days)
            if gap <= 5:
                candidates.append((gap, flow))
        if candidates:
            _, selected = min(candidates, key=lambda item: item[0])
            selected.payroll_statement_id = statement.id
            selected.role = "payroll_deposit"
            used.add(selected.id)
            _result(
                session,
                "payroll_statement",
                statement.id,
                "payroll_to_sofi",
                "reconciled",
            )


def _match_completed_payroll_deposits(session: Session) -> None:
    session.execute(delete(PayrollTransactionMatch))
    entries = list(
        session.scalars(
            select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.observed_deposit_date)
        )
    )
    transactions = list(
        session.scalars(
            select(AccountTransaction)
            .join(Account)
            .join(Institution)
            .where(
                Institution.kind == "bank",
                AccountTransaction.amount > 0,
            )
            .order_by(AccountTransaction.posted_date, AccountTransaction.id)
        )
    )
    used: set[int] = set()
    for entry in entries:
        candidates = [
            transaction
            for transaction in transactions
            if transaction.id not in used
            and abs((transaction.posted_date - entry.observed_deposit_date).days) <= 3
            and any(
                token in transaction.original_description.lower() for token in ("optum", "payroll")
            )
        ]
        matches: list[AccountTransaction] | None = None
        best_key: tuple[int, int, tuple[int, ...]] | None = None
        for size in range(1, min(6, len(candidates)) + 1):
            for group in combinations(candidates, size):
                if money(sum((transaction.amount for transaction in group), ZERO)) != money(
                    entry.net_payment
                ):
                    continue
                key = (
                    max(
                        abs((transaction.posted_date - entry.observed_deposit_date).days)
                        for transaction in group
                    ),
                    size,
                    tuple(transaction.id for transaction in group),
                )
                if best_key is None or key < best_key:
                    best_key = key
                    matches = list(group)
        if not matches:
            continue
        digest_input = f"{entry.id}:" + ",".join(str(transaction.id) for transaction in matches)
        match_group = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:32]
        for transaction in matches:
            used.add(transaction.id)
            session.add(
                PayrollTransactionMatch(
                    schedule_entry_id=entry.id,
                    transaction_id=transaction.id,
                    amount=transaction.amount,
                    match_group=match_group,
                )
            )
            flow = session.scalar(
                select(ExternalFlow).where(ExternalFlow.transaction_id == transaction.id)
            )
            if flow is not None:
                flow.role = "payroll_deposit"
                flow.payroll_statement_id = entry.payroll_statement_id


def _reconcile_completed_schedule(session: Session) -> None:
    for index, check in enumerate(schedule_validation(session), start=1):
        entity_id = check.get("entity_id", str(index))
        residual = Decimal(str(check.get("residual", "0.00")))
        _result(
            session,
            "payroll_schedule",
            str(entity_id),
            str(check["rule"]),
            str(check["status"]),
            residual,
            dict(check.get("details", {})),
        )


def _positive_total(transactions: list[AccountTransaction], role: str) -> Decimal:
    return money(sum((max(ZERO, row.amount) for row in transactions if row.role == role), ZERO))


def _modified_dietz(
    opening: Decimal,
    result: Decimal,
    period_start: date,
    period_end: date,
    flows: list[tuple[date, Decimal]],
) -> Decimal | None:
    days = (period_end - period_start).days
    if days <= 0:
        return None
    weighted = ZERO
    for flow_date, flow in flows:
        elapsed = (flow_date - period_start).days
        weight = Decimal(days - elapsed) / Decimal(days)
        weighted += flow * weight
    denominator = opening + weighted
    if denominator == ZERO:
        return None
    return money(result / denominator * Decimal("100"))


def _reconcile_investment_accounts(session: Session) -> None:
    accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(
                or_(
                    Institution.kind == "investment",
                    func.lower(Account.account_type).in_(INVESTMENT_ACCOUNT_TYPES),
                )
            )
        )
    )
    for account in accounts:
        balances = list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id == account.id)
                .order_by(BalanceSnapshot.snapshot_date)
            )
        )
        dated: dict[date, BalanceSnapshot] = {}
        for item in balances:
            if item.kind in {"opening", "closing", "current", "manual"}:
                dated[item.snapshot_date] = item
        observations = [dated[key] for key in sorted(dated)]
        if len(observations) < 2:
            continue
        for opening, closing in pairwise(observations):
            transactions = list(
                session.scalars(
                    select(AccountTransaction).where(
                        AccountTransaction.account_id == account.id,
                        AccountTransaction.posted_date > opening.snapshot_date,
                        AccountTransaction.posted_date <= closing.snapshot_date,
                    )
                )
            )
            employee = _positive_total(transactions, "employee_contribution")
            employer = _positive_total(transactions, "employer_contribution")
            stock = _positive_total(transactions, "stock_plan_contribution")
            other = _positive_total(transactions, "external_deposit")
            if account.account_type.lower() in {"401k", "403b", "pension", "retirement"}:
                payroll_employee = money(
                    session.scalar(
                        select(func.coalesce(func.sum(PayrollAllocation.amount), 0))
                        .join(PayrollScheduleEntry)
                        .where(
                            PayrollScheduleEntry.observed_deposit_date > opening.snapshot_date,
                            PayrollScheduleEntry.observed_deposit_date <= closing.snapshot_date,
                            PayrollAllocation.category == "pretax.employee_retirement",
                        )
                    )
                    or ZERO
                )
                payroll_employer = money(
                    session.scalar(
                        select(func.coalesce(func.sum(PayrollAllocation.amount), 0))
                        .join(PayrollScheduleEntry)
                        .where(
                            PayrollScheduleEntry.observed_deposit_date > opening.snapshot_date,
                            PayrollScheduleEntry.observed_deposit_date <= closing.snapshot_date,
                            PayrollAllocation.category == "employer_benefit.employer_retirement",
                        )
                    )
                    or ZERO
                )
                if payroll_employee + payroll_employer > ZERO:
                    employee = payroll_employee
                    employer = payroll_employer
                    other = max(ZERO, money(other - employee - employer))
            withdrawals = money(
                sum(
                    (
                        abs(row.amount)
                        for row in transactions
                        if row.role == "external_withdrawal" and row.amount < ZERO
                    ),
                    ZERO,
                )
            )
            result = fidelity_investment_result(
                opening_value=opening.amount,
                closing_value=closing.amount,
                employee_contributions=employee,
                employer_contributions=employer,
                stock_plan_contributions=stock,
                other_deposits=other,
                withdrawals=withdrawals,
            )
            observation_days = (closing.snapshot_date - opening.snapshot_date).days
            boundary_transactions = list(
                session.scalars(
                    select(AccountTransaction).where(
                        AccountTransaction.account_id == account.id,
                        AccountTransaction.posted_date >= opening.snapshot_date,
                        AccountTransaction.posted_date <= closing.snapshot_date,
                    )
                )
            )
            boundary_cash_flows = [
                transaction
                for transaction in boundary_transactions
                if transaction.posted_date in {opening.snapshot_date, closing.snapshot_date}
                and transaction.role in INVESTMENT_CASH_FLOW_ROLES
            ]
            unresolved_activity = any(
                transaction.role == "unresolved" for transaction in boundary_transactions
            )
            tracking_reason: str | None = None
            if observation_days < MIN_INVESTMENT_PERFORMANCE_DAYS:
                tracking_reason = "tracking_short_window"
            elif boundary_cash_flows:
                tracking_reason = "tracking_boundary_activity"
            elif unresolved_activity:
                tracking_reason = "tracking_unresolved_activity"
            signed_flows = [
                (transaction.posted_date, transaction.amount)
                for transaction in transactions
                if (
                    transaction.amount > ZERO
                    and transaction.role
                    in {
                        "employee_contribution",
                        "employer_contribution",
                        "stock_plan_contribution",
                        "external_deposit",
                    }
                )
                or (transaction.amount < ZERO and transaction.role == "external_withdrawal")
            ]
            calculated_return = (
                _modified_dietz(
                    opening.amount,
                    result,
                    opening.snapshot_date,
                    closing.snapshot_date,
                    signed_flows,
                )
                if tracking_reason is None
                else None
            )
            return_method = tracking_reason or (
                "modified_dietz" if calculated_return is not None else "dollar_residual"
            )
            session.add(
                InvestmentValueBridge(
                    account_id=account.id,
                    period_start=opening.snapshot_date,
                    period_end=closing.snapshot_date,
                    opening_value=opening.amount,
                    employee_contributions=employee,
                    employer_contributions=employer,
                    stock_plan_contributions=stock,
                    other_deposits=other,
                    withdrawals=withdrawals,
                    investment_result=result,
                    closing_value=closing.amount,
                    calculated_return_pct=calculated_return,
                    return_method=return_method,
                )
            )
            _result(
                session,
                "investment_bridge",
                f"{account.id}:{opening.snapshot_date}:{closing.snapshot_date}",
                "investment_value_bridge",
                "reconciled" if tracking_reason is None else "tracking",
                ZERO,
                {
                    "return_method": return_method,
                    "observation_days": observation_days,
                    "boundary_cash_flow_count": len(boundary_cash_flows),
                    "message": (
                        "Performance is available for this observation interval."
                        if tracking_reason is None
                        else (
                            "Performance stays hidden until a longer, unambiguous observation "
                            "interval is available."
                        )
                    ),
                },
            )
            for transaction in transactions:
                if transaction.role == "unresolved":
                    _result(
                        session,
                        "account_transaction",
                        transaction.id,
                        "transaction_role",
                        "unresolved",
                    )


def reconcile_all(session: Session) -> None:
    session.execute(delete(TransferMatch))
    session.execute(delete(ExternalFlow))
    session.execute(delete(InvestmentValueBridge))
    session.execute(delete(ReconciliationResult))
    session.flush()
    _reconcile_payroll(session)
    matched_transfers = _match_transfers(session)
    _reconcile_bank_accounts(session, matched_transfers)
    generate_account_balance_points(session)
    has_completed_schedule = session.scalar(select(PayrollScheduleEntry.id).limit(1)) is not None
    if has_completed_schedule:
        _match_completed_payroll_deposits(session)
        _reconcile_completed_schedule(session)
    else:
        _match_payroll_deposits(session)
    _reconcile_investment_accounts(session)
    session.flush()
