from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analytics import (
    payroll_allocation_summary,
    period_cashflow,
    period_investments,
)
from .models import (
    Account,
    BalanceSnapshot,
    ExternalFlow,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
)
from .money import ZERO, money
from .payroll import (
    RECEIVED_END,
    RECEIVED_START,
)
from .service_common import amount, latest_complete_period


def overview(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    period_start, period_end = latest_complete_period()
    if start_date is not None:
        period_start = start_date
    if end_date is not None:
        period_end = end_date
    if period_start > period_end:
        raise ValueError("Start date must be on or before end date")
    schedule_rows = list(
        session.scalars(
            select(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= period_start,
                PayrollScheduleEntry.observed_deposit_date <= period_end,
            )
            .order_by(PayrollScheduleEntry.observed_deposit_date)
        )
    )
    statements = list(
        session.scalars(
            select(PayrollStatement)
            .where(
                PayrollStatement.payment_date >= period_start,
                PayrollStatement.payment_date <= period_end,
            )
            .order_by(PayrollStatement.payment_date)
        )
    )

    def total(field: str) -> Decimal:
        source = schedule_rows or statements
        return money(sum((getattr(item, field) for item in source), ZERO))

    matched_sofi = session.scalar(
        select(func.coalesce(func.sum(ExternalFlow.amount), 0)).where(
            ExternalFlow.role == "payroll_deposit",
            ExternalFlow.payroll_statement_id.is_not(None),
        )
    )
    accounts_with_balances = list(session.scalars(select(Account).join(BalanceSnapshot).distinct()))
    opening_total = ZERO
    closing_total = ZERO
    for account in accounts_with_balances:
        account_balances = list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id == account.id)
                .order_by(BalanceSnapshot.snapshot_date)
            )
        )
        explicit_opening = next((row for row in account_balances if row.kind == "opening"), None)
        explicit_closing = next(
            (row for row in reversed(account_balances) if row.kind == "closing"), None
        )
        current = [row for row in account_balances if row.kind == "current"]
        opening = explicit_opening or (current[0] if len(current) >= 2 else None)
        closing = explicit_closing or (current[-1] if current else None)
        if opening is not None:
            opening_total += opening.amount
        if closing is not None:
            closing_total += closing.amount
    gross = total("gross_earnings")
    taxes = total("tax_withholdings")
    pretax = total("pretax_deductions")
    aftertax = total("after_tax_deductions")
    net = total("net_payment")
    imputed = total("imputed_earnings")
    statement_ids = [statement.id for statement in statements]
    detailed_lines = (
        list(
            session.scalars(
                select(PayrollLineItem).where(
                    PayrollLineItem.statement_id.in_(statement_ids),
                    PayrollLineItem.category.contains("."),
                )
            )
        )
        if statement_ids
        else []
    )

    def detailed_total(*categories: str) -> Decimal:
        selected = set(categories)
        return money(
            sum((line.amount for line in detailed_lines if line.category in selected), ZERO)
        )

    employee_retirement = detailed_total("pretax.employee_retirement")
    employee_hsa = detailed_total("pretax.employee_hsa")
    employee_stock_purchase = detailed_total("after_tax.employee_stock_purchase")
    stock_offset = detailed_total("after_tax.stock_offset")
    health_premiums = detailed_total(
        "pretax.dental",
        "pretax.medical",
        "pretax.vision",
    )
    known_pretax = money(
        sum(
            (line.amount for line in detailed_lines if line.category.startswith("pretax.")),
            ZERO,
        )
    )
    known_after_tax = money(
        sum(
            (line.amount for line in detailed_lines if line.category.startswith("after_tax.")),
            ZERO,
        )
    )
    employer_hsa = detailed_total("employer_benefit.employer_hsa")
    employer_retirement = detailed_total("employer_benefit.employer_retirement")
    employer_contributions = money(employer_hsa + employer_retirement)
    employee_directed = money(employee_retirement + employee_hsa + employee_stock_purchase)
    allocation = payroll_allocation_summary(session, period_start, period_end)
    allocation_destinations = allocation["destinations"]

    def allocation_total(*categories: str) -> Decimal:
        selected = set(categories)
        return money(
            sum(
                (
                    Decimal(str(item["amount"] or "0"))
                    for item in allocation_destinations
                    if item["category"] in selected
                ),
                ZERO,
            )
        )

    allocated_employee_retirement = allocation_total("pretax.employee_retirement")
    allocated_employee_hsa = allocation_total("pretax.employee_hsa")
    allocated_employee_stock = allocation_total("after_tax.employee_stock_purchase")
    allocated_employer_hsa = allocation_total("employer_benefit.employer_hsa")
    allocated_employer_retirement = allocation_total("employer_benefit.employer_retirement")
    allocated_health = allocation_total("pretax.medical", "pretax.dental", "pretax.vision")
    allocated_stock_offset = allocation_total("after_tax.stock_offset")
    allocated_other_pretax = allocation_total("pretax.other")
    allocated_other_after_tax = allocation_total("after_tax.other")
    allocated_employer = money(
        sum(
            (
                Decimal(str(item["amount"] or "0"))
                for item in allocation_destinations
                if item["section"] == "employer"
            ),
            ZERO,
        )
    )
    if allocation_destinations:
        employee_retirement = allocated_employee_retirement
        employee_hsa = allocated_employee_hsa
        employee_stock_purchase = allocated_employee_stock
        health_premiums = allocated_health
        stock_offset = allocated_stock_offset
        employer_hsa = allocated_employer_hsa
        employer_retirement = allocated_employer_retirement
        employer_contributions = allocated_employer
        employee_directed = money(employee_retirement + employee_hsa + employee_stock_purchase)
    detail_complete = sum(1 for statement in statements if statement.detail_complete)
    months_present = sorted(
        {row.observed_deposit_date.strftime("%Y-%m") for row in schedule_rows}
        or {statement.payment_date.strftime("%Y-%m") for statement in statements}
    )
    all_imported = session.scalar(select(func.count(PayrollStatement.id))) or 0
    newest = session.scalar(
        select(PayrollStatement).order_by(PayrollStatement.payment_date.desc()).limit(1)
    )
    newest_lines = (
        list(
            session.scalars(
                select(PayrollLineItem)
                .where(
                    PayrollLineItem.statement_id == newest.id,
                    PayrollLineItem.category.contains("."),
                )
                .order_by(PayrollLineItem.id)
            )
        )
        if newest is not None
        else []
    )

    def newest_line_total(*categories: str) -> Decimal:
        selected = set(categories)
        return money(sum((line.amount for line in newest_lines if line.category in selected), ZERO))

    recurring_paycheck: dict[str, Any] | None = None
    if newest is not None:
        deposit_anchor = newest.observed_deposit_date or newest.payment_date
        next_deposit = deposit_anchor
        while next_deposit <= date.today():
            next_deposit += timedelta(days=14)
        recurring_employee_retirement = newest_line_total("pretax.employee_retirement")
        recurring_employee_hsa = newest_line_total("pretax.employee_hsa")
        recurring_employee_stock = newest_line_total("after_tax.employee_stock_purchase")
        recurring_employer_retirement = newest_line_total("employer_benefit.employer_retirement")
        recurring_employer_hsa = newest_line_total("employer_benefit.employer_hsa")
        recurring_employee_fidelity = money(
            recurring_employee_retirement + recurring_employee_stock
        )
        recurring_employee_accounts = money(recurring_employee_fidelity + recurring_employee_hsa)
        recurring_employer_accounts = money(recurring_employer_retirement + recurring_employer_hsa)
        recurring_paycheck = {
            "cadence": "Every other Wednesday",
            "effective_from": deposit_anchor,
            "next_expected_deposit": next_deposit,
            "annual_salary": amount(newest.base_salary),
            "gross_earnings": amount(newest.gross_earnings),
            "net_payment": amount(newest.net_payment),
            "employee_retirement": amount(recurring_employee_retirement),
            "employee_hsa": amount(recurring_employee_hsa),
            "employee_stock_purchase": amount(recurring_employee_stock),
            "employee_fidelity_funding": amount(recurring_employee_fidelity),
            "employee_account_funding": amount(recurring_employee_accounts),
            "employer_retirement": amount(recurring_employer_retirement),
            "employer_hsa": amount(recurring_employer_hsa),
            "employer_account_funding": amount(recurring_employer_accounts),
            "all_account_value": amount(
                newest.net_payment + recurring_employee_accounts + recurring_employer_accounts
            ),
            "deposit_splits": [
                {"label": line.original_label, "amount": amount(line.amount)}
                for line in newest_lines
                if line.category.startswith("net_distribution.")
            ],
        }
    all_statements = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date))
    )
    latest_by_year: dict[int, PayrollStatement] = {}
    for statement in all_statements:
        latest_by_year[statement.payment_date.year] = statement

    def ytd_line(statement: PayrollStatement, *categories: str) -> Decimal | None:
        lines = list(
            session.scalars(
                select(PayrollLineItem).where(
                    PayrollLineItem.statement_id == statement.id,
                    PayrollLineItem.category.in_(categories),
                )
            )
        )
        values = [line.ytd_amount for line in lines if line.ytd_amount is not None]
        return money(sum(values, ZERO)) if values else None

    annual_snapshots = []
    for year, statement in sorted(latest_by_year.items(), reverse=True):
        annual_snapshots.append(
            {
                "year": year,
                "as_of": statement.payment_date,
                "official_year_end": statement.payment_date.month == 12,
                "gross_earnings": statement.ytd_values.get("gross_earnings"),
                "imputed_earnings": statement.ytd_values.get("imputed_earnings"),
                "tax_withholdings": statement.ytd_values.get("tax_withholdings"),
                "pretax_deductions": statement.ytd_values.get("pretax_deductions"),
                "after_tax_deductions": statement.ytd_values.get("after_tax_deductions"),
                "net_payment": statement.ytd_values.get("net_payment"),
                "employee_retirement": amount(ytd_line(statement, "pretax.employee_retirement")),
                "employee_hsa": amount(ytd_line(statement, "pretax.employee_hsa")),
                "health_premiums": amount(
                    ytd_line(
                        statement,
                        "pretax.dental",
                        "pretax.medical",
                        "pretax.vision",
                    )
                ),
                "employee_stock_purchase": amount(
                    ytd_line(statement, "after_tax.employee_stock_purchase")
                ),
                "stock_offset": amount(ytd_line(statement, "after_tax.stock_offset")),
                "employer_contributions": amount(
                    ytd_line(
                        statement,
                        "employer_benefit.employer_hsa",
                        "employer_benefit.employer_retirement",
                    )
                ),
            }
        )

    def pct(value: Decimal) -> str:
        return amount(value / gross * Decimal("100")) or "0.00" if gross else "0.00"

    return {
        "period": {"start": period_start, "end": period_end},
        "period_presets": {
            "trailing_12": {"start": period_start, "end": period_end},
            "current_year": {"start": date(RECEIVED_END.year, 1, 1), "end": RECEIVED_END},
            "previous_year": {"start": date(2025, 1, 1), "end": date(2025, 12, 31)},
            "all": {"start": RECEIVED_START, "end": RECEIVED_END},
        },
        "coverage": {
            "paychecks_in_period": len(schedule_rows) or len(statements),
            "all_imported_paychecks": all_imported,
            "months_present": months_present,
            "destination_detail_complete": detail_complete,
            "is_complete": (session.scalar(select(func.count(PayrollScheduleEntry.id))) or 0) == 42,
        },
        "totals": {
            "gross_compensation": amount(gross),
            "employee_directed_saving": amount(employee_directed),
            "employee_fidelity_funding": amount(employee_retirement + employee_stock_purchase),
            "employee_retirement": amount(employee_retirement),
            "employee_hsa": amount(employee_hsa),
            "employee_stock_purchase": amount(employee_stock_purchase),
            "health_premiums": amount(health_premiums),
            "other_pretax": amount(
                allocated_other_pretax
                if allocation_destinations
                else max(ZERO, pretax - known_pretax)
            ),
            "unresolved_pretax": amount(
                allocated_other_pretax
                if allocation_destinations
                else max(ZERO, pretax - known_pretax)
            ),
            "other_after_tax": amount(
                stock_offset + allocated_other_after_tax
                if allocation_destinations
                else stock_offset + max(ZERO, aftertax - known_after_tax)
            ),
            "employer_contributions": amount(employer_contributions),
            "employer_retirement": amount(employer_retirement),
            "employer_hsa": amount(employer_hsa),
            "all_account_value": amount(net + employee_directed + employer_contributions),
            "taxes": amount(taxes),
            "benefits_and_other_pretax": amount(pretax),
            "after_tax_deductions": amount(aftertax),
            "net_payments": amount(net),
            "verified_sofi_deposits": amount(Decimal(str(matched_sofi or 0))),
            "imputed_non_cash": amount(imputed),
            "opening_account_value": amount(opening_total),
            "closing_account_value": amount(closing_total),
        },
        "percent_of_gross": {
            "taxes": pct(taxes),
            "pretax_aggregate": pct(pretax),
            "after_tax_aggregate": pct(aftertax),
            "net_payments": pct(net),
            "imputed_non_cash": pct(imputed),
        },
        "latest_payroll_baseline": (
            None
            if newest is None
            else {
                "payment_date": newest.payment_date,
                "observed_deposit_date": newest.observed_deposit_date,
                "annual_salary": amount(newest.base_salary),
                "net_payment": amount(newest.net_payment),
                "detail_complete": newest.detail_complete,
                "job_title": newest.job_title,
            }
        ),
        "recurring_paycheck": recurring_paycheck,
        "annual_snapshots": annual_snapshots,
        "allocation": allocation,
        "cashflow": period_cashflow(session, period_start, period_end),
        "investments": period_investments(session, period_start, period_end),
        "warnings": [],
    }
