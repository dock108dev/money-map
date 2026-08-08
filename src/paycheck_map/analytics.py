from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    PayrollAllocation,
    PayrollScheduleEntry,
    ReconciliationResult,
    TransferMatch,
)
from .money import ZERO, money
from .reconciliation import investment_performance_available

REPORTING_NET_DESTINATIONS = {
    "1206": ("net.1206", "SoFi Checking"),
    "0697": ("net.0697", "SoFi Savings"),
}


def serialized(value: Decimal | None) -> str | None:
    return None if value is None else f"{money(value):.2f}"


def month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def month_sequence(start_date: date, end_date: date) -> list[date]:
    current = start_date.replace(day=1)
    rows: list[date] = []
    while current <= end_date:
        rows.append(current)
        current = next_month(current)
    return rows


def latest_complete_twelve_months(as_of: date | None = None) -> tuple[date, date]:
    current = as_of or date.today()
    first_current = current.replace(day=1)
    end = first_current.fromordinal(first_current.toordinal() - 1)
    start = date(end.year - 1, end.month + 1, 1) if end.month < 12 else date(end.year, 1, 1)
    return start, end


def transfer_transaction_ids(session: Session) -> set[int]:
    output: set[int] = set()
    for match in session.scalars(select(TransferMatch)):
        output.update({match.left_transaction_id, match.right_transaction_id})
    return output


def _reporting_destination(section: str, category: str, label: str) -> tuple[str, str, str]:
    """Collapse historical payroll labels into the two current SoFi destinations.

    The stored allocation retains its source-derived label. Reporting treats checking
    suffix 1206 as checking and every other historical/undetailed payroll destination
    as savings, per the current-account reporting policy.
    """

    if section != "net":
        return section, category, label
    suffix = category.rsplit(".", 1)[-1]
    normalized_category, normalized_label = REPORTING_NET_DESTINATIONS.get(
        suffix,
        REPORTING_NET_DESTINATIONS["0697"],
    )
    return section, normalized_category, normalized_label


def payroll_allocation_summary(
    session: Session, start_date: date, end_date: date
) -> dict[str, Any]:
    allocations = list(
        session.scalars(
            select(PayrollAllocation)
            .join(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
            .order_by(PayrollAllocation.section, PayrollAllocation.category)
        )
    )
    by_category: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: ZERO)
    by_section: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for allocation in allocations:
        destination = _reporting_destination(
            allocation.section,
            allocation.category,
            allocation.label,
        )
        by_category[destination] += allocation.amount
        by_section[allocation.section] += allocation.amount
    imputed_non_cash = money(
        session.scalar(
            select(func.coalesce(func.sum(PayrollScheduleEntry.imputed_earnings), 0)).where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
        )
        or ZERO
    )
    if imputed_non_cash:
        by_category[("imputed", "imputed.non_cash", "Non-cash taxable benefits")] += (
            imputed_non_cash
        )
        by_section["imputed"] += imputed_non_cash
    gross = money(by_section.get("compensation", ZERO))
    accounted_from_gross = money(
        sum(
            (
                by_section.get(section, ZERO)
                for section in ("pretax", "tax", "after_tax", "net", "imputed")
            ),
            ZERO,
        )
    )
    residual = money(gross - accounted_from_gross)
    return {
        "sections": {key: serialized(value) for key, value in sorted(by_section.items())},
        "destinations": [
            {
                "section": section,
                "category": category,
                "label": label,
                "amount": serialized(value),
            }
            for (section, category, label), value in sorted(
                by_category.items(), key=lambda item: (item[0][0], -item[1], item[0][2])
            )
            if value != ZERO
        ],
        "reconciliation": {
            "gross": serialized(gross),
            "accounted_from_gross": serialized(accounted_from_gross),
            "residual": serialized(residual),
            "status": "reconciled" if residual == ZERO else "unreconciled",
            "employer_additions": serialized(by_section.get("employer", ZERO)),
        },
    }


def period_cashflow(session: Session, start_date: date, end_date: date) -> dict[str, Any]:
    matched = transfer_transaction_ids(session)
    rows = list(
        session.scalars(
            select(AccountTransaction)
            .join(Account)
            .join(Institution)
            .where(
                Institution.kind == "bank",
                AccountTransaction.posted_date >= start_date,
                AccountTransaction.posted_date <= end_date,
            )
        )
    )
    inflows = sum(
        (
            row.amount
            for row in rows
            if row.amount > ZERO
            and row.id not in matched
            and row.role not in {"internal_transfer", "interest"}
        ),
        ZERO,
    )
    outflows = abs(
        sum(
            (
                row.amount
                for row in rows
                if row.amount < ZERO
                and row.id not in matched
                and row.role not in {"internal_transfer", "fee"}
            ),
            ZERO,
        )
    )
    transfer_in = sum(
        (row.amount for row in rows if row.amount > ZERO and row.id in matched),
        ZERO,
    )
    transfer_out = abs(
        sum(
            (row.amount for row in rows if row.amount < ZERO and row.id in matched),
            ZERO,
        )
    )
    interest = sum((row.amount for row in rows if row.role == "interest"), ZERO)
    fees = abs(sum((row.amount for row in rows if row.role == "fee"), ZERO))
    return {
        "coverage": {
            "start": min((row.posted_date for row in rows), default=None),
            "end": max((row.posted_date for row in rows), default=None),
            "transactions": len(rows),
        },
        "external_inflows": serialized(inflows),
        "external_outflows": serialized(outflows),
        "transfer_in": serialized(transfer_in),
        "transfer_out": serialized(transfer_out),
        "interest": serialized(interest),
        "fees": serialized(fees),
        "net_external": serialized(inflows - outflows + interest - fees),
        "matched_transfer_transactions": sum(row.id in matched for row in rows),
    }


def period_investments(session: Session, start_date: date, end_date: date) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(AccountTransaction)
            .join(Account)
            .join(Institution)
            .where(
                Institution.kind == "investment",
                AccountTransaction.posted_date >= start_date,
                AccountTransaction.posted_date <= end_date,
            )
        )
    )

    def positive(role: str) -> Decimal:
        return money(sum((max(ZERO, row.amount) for row in rows if row.role == role), ZERO))

    withdrawals = money(
        sum(
            (
                abs(row.amount)
                for row in rows
                if row.role == "external_withdrawal" and row.amount < ZERO
            ),
            ZERO,
        )
    )
    bridges = list(
        session.scalars(
            select(InvestmentValueBridge).where(
                InvestmentValueBridge.period_end >= start_date,
                InvestmentValueBridge.period_end <= end_date,
            )
        )
    )
    available_bridges = [bridge for bridge in bridges if investment_performance_available(bridge)]
    payroll_destinations = {
        category: money(total)
        for category, total in session.execute(
            select(PayrollAllocation.category, func.sum(PayrollAllocation.amount))
            .join(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
                PayrollAllocation.category.in_(
                    [
                        "pretax.employee_retirement",
                        "employer_benefit.employer_retirement",
                        "after_tax.employee_stock_purchase",
                    ]
                ),
            )
            .group_by(PayrollAllocation.category)
        )
    }
    if payroll_destinations:
        employee = payroll_destinations.get("pretax.employee_retirement", ZERO)
        employer = payroll_destinations.get("employer_benefit.employer_retirement", ZERO)
        stock = payroll_destinations.get("after_tax.employee_stock_purchase", ZERO)
        total_external = money(positive("external_deposit") + positive("stock_plan_contribution"))
        other = max(ZERO, money(total_external - employee - employer - stock))
    else:
        employee = positive("employee_contribution")
        employer = positive("employer_contribution")
        stock = positive("stock_plan_contribution")
        other = positive("external_deposit")
    return {
        "coverage": {
            "start": min((row.posted_date for row in rows), default=None),
            "end": max((row.posted_date for row in rows), default=None),
            "transactions": len(rows),
        },
        "employee_contributions": serialized(employee),
        "employer_contributions": serialized(employer),
        "stock_plan_contributions": serialized(stock),
        "employee_fidelity_contributions": serialized(employee + stock),
        "total_payroll_fidelity_contributions": serialized(employee + employer + stock),
        "other_contributions": serialized(other),
        "withdrawals": serialized(withdrawals),
        "investment_result": (
            serialized(sum((bridge.investment_result for bridge in available_bridges), ZERO))
            if available_bridges
            else None
        ),
        "bridge_count": len(available_bridges),
    }


def account_detail(
    session: Session, account_id: int, start_date: date, end_date: date
) -> dict[str, Any] | None:
    account = session.get(Account, account_id)
    if account is None:
        return None
    institution = session.get(Institution, account.institution_id)
    if institution is None:
        return None
    transactions = list(
        session.scalars(
            select(AccountTransaction)
            .where(
                AccountTransaction.account_id == account.id,
                AccountTransaction.posted_date >= start_date,
                AccountTransaction.posted_date <= end_date,
            )
            .order_by(AccountTransaction.posted_date.desc(), AccountTransaction.id.desc())
        )
    )
    balance_points = list(
        session.scalars(
            select(AccountBalancePoint)
            .where(
                AccountBalancePoint.account_id == account.id,
                AccountBalancePoint.balance_date >= start_date,
                AccountBalancePoint.balance_date <= end_date,
            )
            .order_by(AccountBalancePoint.balance_date, AccountBalancePoint.kind)
        )
    )
    snapshots = list(
        session.scalars(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account.id)
            .order_by(BalanceSnapshot.snapshot_date, BalanceSnapshot.id)
        )
    )
    holdings = list(
        session.scalars(
            select(InvestmentHolding)
            .where(InvestmentHolding.account_id == account.id)
            .order_by(InvestmentHolding.institution_value.desc())
        )
    )
    bridges = list(
        session.scalars(
            select(InvestmentValueBridge)
            .where(
                InvestmentValueBridge.account_id == account.id,
                InvestmentValueBridge.period_end >= start_date,
                InvestmentValueBridge.period_end <= end_date,
            )
            .order_by(InvestmentValueBridge.period_end)
        )
    )
    latest = snapshots[-1] if snapshots else None
    cost_basis_value = money(
        sum((holding.cost_basis for holding in holdings if holding.cost_basis is not None), ZERO)
    )
    market_with_basis = money(
        sum(
            (holding.institution_value for holding in holdings if holding.cost_basis is not None),
            ZERO,
        )
    )
    unrealized = money(market_with_basis - cost_basis_value) if cost_basis_value else None
    matched = transfer_transaction_ids(session)
    monthly: list[dict[str, Any]] = []
    for month in month_sequence(start_date, end_date):
        end = min(month_end(month), end_date)
        rows = [row for row in transactions if month <= row.posted_date <= end]
        opening = next(
            (
                point
                for point in balance_points
                if point.balance_date == month and point.kind == "month_open"
            ),
            None,
        )
        closing_candidates = [
            point
            for point in balance_points
            if month <= point.balance_date <= end and point.kind in {"month_close", "observed"}
        ]
        closing = closing_candidates[-1] if closing_candidates else None
        monthly.append(
            {
                "month": month,
                "opening": serialized(opening.amount) if opening else None,
                "inflows": serialized(sum((row.amount for row in rows if row.amount > ZERO), ZERO)),
                "outflows": serialized(
                    abs(sum((row.amount for row in rows if row.amount < ZERO), ZERO))
                ),
                "closing": serialized(closing.amount) if closing else None,
            }
        )
    return {
        "id": account.id,
        "name": account.display_name,
        "institution": institution.canonical_name,
        "institution_kind": institution.kind,
        "type": account.account_type,
        "period": {"start": start_date, "end": end_date},
        "current_balance": serialized(latest.amount) if latest else None,
        "balance_as_of": latest.snapshot_date if latest else None,
        "balance_points": [
            {
                "date": point.balance_date,
                "kind": point.kind,
                "amount": serialized(point.amount),
                "source_kind": point.source_kind,
            }
            for point in balance_points
        ],
        "monthly": monthly,
        "activity": [
            {
                "id": row.id,
                "date": row.posted_date,
                "description": row.original_description,
                "role": row.role,
                "amount": serialized(row.amount),
                "matched_transfer": row.id in matched,
            }
            for row in transactions
        ],
        "holdings": [
            {
                "name": holding.security_name,
                "ticker": holding.ticker_symbol,
                "quantity": str(holding.quantity),
                "value": serialized(holding.institution_value),
                "cost_basis": serialized(holding.cost_basis),
                "as_of": holding.as_of,
            }
            for holding in holdings
        ],
        "cost_basis": serialized(cost_basis_value) if cost_basis_value else None,
        "unrealized_gain": serialized(unrealized),
        "bridges": [
            {
                "period_start": bridge.period_start,
                "period_end": bridge.period_end,
                "opening_value": serialized(bridge.opening_value),
                "employee_contributions": serialized(bridge.employee_contributions),
                "employer_contributions": serialized(bridge.employer_contributions),
                "stock_plan_contributions": serialized(bridge.stock_plan_contributions),
                "other_deposits": serialized(bridge.other_deposits),
                "withdrawals": serialized(bridge.withdrawals),
                "investment_result": (
                    serialized(bridge.investment_result)
                    if investment_performance_available(bridge)
                    else None
                ),
                "closing_value": serialized(bridge.closing_value),
                "calculated_return_pct": serialized(bridge.calculated_return_pct),
                "return_method": bridge.return_method,
                "performance_status": (
                    "available" if investment_performance_available(bridge) else "tracking"
                ),
                "performance_message": (
                    "This interval is long enough and has unambiguous boundary activity."
                    if investment_performance_available(bridge)
                    else (
                        "Performance is tracking until a longer interval without "
                        "boundary-day cash activity is available."
                    )
                ),
            }
            for bridge in bridges
        ],
        "performance_status": (
            "available"
            if any(investment_performance_available(bridge) for bridge in bridges)
            else "tracking"
        ),
    }


def monthly_timeline(session: Session, start_date: date, end_date: date) -> list[dict[str, Any]]:
    schedule = list(
        session.scalars(
            select(PayrollScheduleEntry).where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
        )
    )
    allocations = list(
        session.scalars(
            select(PayrollAllocation)
            .join(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
        )
    )
    row_by_id = {row.id: row for row in schedule}
    transactions = list(
        session.scalars(
            select(AccountTransaction).where(
                AccountTransaction.posted_date >= start_date,
                AccountTransaction.posted_date <= end_date,
            )
        )
    )
    accounts = {account.id: account for account in session.scalars(select(Account))}
    institutions = {
        institution.id: institution for institution in session.scalars(select(Institution))
    }
    bridges = list(
        session.scalars(
            select(InvestmentValueBridge).where(
                InvestmentValueBridge.period_end >= start_date,
                InvestmentValueBridge.period_end <= end_date,
            )
        )
    )
    actionable = list(
        session.scalars(
            select(ReconciliationResult).where(ReconciliationResult.status == "unreconciled")
        )
    )
    matched = transfer_transaction_ids(session)
    result: list[dict[str, Any]] = []
    for month in month_sequence(start_date, end_date):
        end = min(month_end(month), end_date)
        pay = [row for row in schedule if month <= row.observed_deposit_date <= end]
        month_allocations = [
            allocation
            for allocation in allocations
            if allocation.schedule_entry_id in row_by_id
            and month <= row_by_id[allocation.schedule_entry_id].observed_deposit_date <= end
        ]
        month_transactions = [
            transaction for transaction in transactions if month <= transaction.posted_date <= end
        ]
        bank = [
            transaction
            for transaction in month_transactions
            if institutions[accounts[transaction.account_id].institution_id].kind == "bank"
        ]
        investment = [
            transaction
            for transaction in month_transactions
            if institutions[accounts[transaction.account_id].institution_id].kind == "investment"
        ]
        month_bridges = [
            bridge
            for bridge in bridges
            if month <= bridge.period_end <= end and investment_performance_available(bridge)
        ]
        investment_result = sum(
            (bridge.investment_result for bridge in month_bridges),
            ZERO,
        )
        section_totals = {
            name: sum(
                (
                    allocation.amount
                    for allocation in month_allocations
                    if allocation.section == name
                ),
                ZERO,
            )
            for name in ("tax", "pretax", "after_tax", "employer")
        }
        result.append(
            {
                "month": month,
                "gross_pay": serialized(sum((row.gross_earnings for row in pay), ZERO)),
                "taxes": serialized(section_totals["tax"]),
                "pretax": serialized(section_totals["pretax"]),
                "after_tax": serialized(section_totals["after_tax"]),
                "employer_contributions": serialized(section_totals["employer"]),
                "net_pay": serialized(sum((row.net_payment for row in pay), ZERO)),
                "cash_inflows": serialized(
                    sum(
                        (
                            transaction.amount
                            for transaction in bank
                            if transaction.amount > ZERO
                            and transaction.id not in matched
                            and transaction.role != "internal_transfer"
                        ),
                        ZERO,
                    )
                ),
                "cash_outflows": serialized(
                    abs(
                        sum(
                            (
                                transaction.amount
                                for transaction in bank
                                if transaction.amount < ZERO
                                and transaction.id not in matched
                                and transaction.role != "internal_transfer"
                            ),
                            ZERO,
                        )
                    )
                ),
                "transfers": serialized(
                    sum(
                        (
                            abs(transaction.amount)
                            for transaction in bank
                            if transaction.id in matched
                        ),
                        ZERO,
                    )
                ),
                "investment_contributions": serialized(
                    sum(
                        (
                            max(ZERO, transaction.amount)
                            for transaction in investment
                            if transaction.role
                            in {
                                "employee_contribution",
                                "employer_contribution",
                                "stock_plan_contribution",
                                "external_deposit",
                            }
                        ),
                        ZERO,
                    )
                ),
                "investment_result": (serialized(investment_result) if month_bridges else None),
                "status": "attention" if actionable else "complete",
            }
        )
    return result
