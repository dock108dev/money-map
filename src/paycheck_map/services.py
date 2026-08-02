from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .analytics import (
    account_detail as build_account_detail,
)
from .analytics import (
    latest_complete_twelve_months,
    monthly_timeline,
    payroll_allocation_summary,
    period_cashflow,
    period_investments,
)
from .models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    ExternalFlow,
    ForecastScenario,
    ImportArtifact,
    ImportBatch,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    PayrollAllocation,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
    PayrollTransactionMatch,
    PlaidConnection,
    ReconciliationResult,
    SourceEvidence,
    TransferMatch,
)
from .money import ZERO, money
from .payroll import (
    RECEIVED_END,
    RECEIVED_START,
    checkpoint_artifact_hash,
    schedule_validation,
)


def amount(value: Decimal | None) -> str | None:
    return None if value is None else f"{money(value):.2f}"


def latest_complete_period(as_of: date | None = None) -> tuple[date, date]:
    return latest_complete_twelve_months(as_of)


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


def _account_category(account: Account, institution: Institution) -> str:
    account_type = account.account_type.strip().lower().replace("_", " ")
    name = account.display_name.lower()
    if account_type in DEBT_ACCOUNT_TYPES or any(
        word in name for word in ("loan", "mortgage", "credit card")
    ):
        return "debt"
    if institution.kind == "investment":
        return "investment"
    if institution.kind == "bank":
        return "cash"
    return "other"


def accounts_dashboard(session: Session) -> dict[str, Any]:
    """Return the account-first view used by the main product experience."""

    accounts = list(
        session.scalars(
            select(Account).join(Institution).order_by(Institution.canonical_name, Account.id)
        )
    )
    institutions = {
        row.id: row for row in session.scalars(select(Institution).order_by(Institution.id))
    }
    connections = {
        row.id: row for row in session.scalars(select(PlaidConnection).order_by(PlaidConnection.id))
    }
    matched_transfer_ids: set[int] = set()
    for match in session.scalars(select(TransferMatch)):
        matched_transfer_ids.update({match.left_transaction_id, match.right_transaction_id})
    bridges = {
        row.account_id: row
        for row in session.scalars(
            select(InvestmentValueBridge).order_by(InvestmentValueBridge.period_end)
        )
    }

    totals = {
        "assets": ZERO,
        "debts": ZERO,
        "cash": ZERO,
        "investments": ZERO,
        "money_in": ZERO,
        "money_out": ZERO,
    }
    account_rows: list[dict[str, Any]] = []
    all_activity: list[tuple[AccountTransaction, Account, Institution, str]] = []
    activity_dates: list[date] = []

    for account in accounts:
        institution = institutions[account.institution_id]
        category = _account_category(account, institution)
        balances = list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id == account.id)
                .order_by(BalanceSnapshot.snapshot_date, BalanceSnapshot.id)
            )
        )
        latest_balance = balances[-1] if balances else None
        derived_points = list(
            session.scalars(
                select(AccountBalancePoint)
                .where(AccountBalancePoint.account_id == account.id)
                .order_by(AccountBalancePoint.balance_date, AccountBalancePoint.id)
            )
        )
        starting_balance = balances[0] if balances else None
        derived_starting_amount = derived_points[0].amount if derived_points else None
        derived_starting_date = derived_points[0].balance_date if derived_points else None
        starting_date = derived_starting_date or (
            starting_balance.snapshot_date if starting_balance else None
        )
        starting_amount = (
            derived_starting_amount
            if derived_starting_amount is not None
            else (starting_balance.amount if starting_balance else None)
        )
        has_change_period = bool(
            starting_date and latest_balance and starting_date < latest_balance.snapshot_date
        )
        transactions = list(
            session.scalars(
                select(AccountTransaction)
                .where(AccountTransaction.account_id == account.id)
                .order_by(AccountTransaction.posted_date.desc(), AccountTransaction.id.desc())
            )
        )
        holdings = list(
            session.scalars(
                select(InvestmentHolding)
                .where(InvestmentHolding.account_id == account.id)
                .order_by(InvestmentHolding.institution_value.desc())
            )
        )
        holding_cost_basis = money(
            sum(
                (holding.cost_basis for holding in holdings if holding.cost_basis is not None), ZERO
            )
        )
        holding_value_with_basis = money(
            sum(
                (
                    holding.institution_value
                    for holding in holdings
                    if holding.cost_basis is not None
                ),
                ZERO,
            )
        )
        current_value = latest_balance.amount if latest_balance else None
        if current_value is not None:
            if category == "debt":
                totals["debts"] += abs(current_value)
            else:
                totals["assets"] += current_value
                if category == "cash":
                    totals["cash"] += current_value
                elif category == "investment":
                    totals["investments"] += current_value

        account_in = ZERO
        account_out = ZERO
        contributions = ZERO
        withdrawals = ZERO
        for transaction in transactions:
            all_activity.append((transaction, account, institution, category))
            if (
                category == "cash"
                and transaction.id not in matched_transfer_ids
                and transaction.role != "internal_transfer"
            ):
                activity_dates.append(transaction.posted_date)
                if transaction.amount > 0:
                    account_in += transaction.amount
                    totals["money_in"] += transaction.amount
                elif transaction.amount < 0:
                    account_out += abs(transaction.amount)
                    totals["money_out"] += abs(transaction.amount)
            if transaction.role in {
                "employee_contribution",
                "employer_contribution",
                "stock_plan_contribution",
                "external_deposit",
            }:
                contributions += max(ZERO, transaction.amount)
            elif transaction.role == "external_withdrawal":
                withdrawals += abs(transaction.amount)

        connection = (
            connections.get(account.plaid_connection_id) if account.plaid_connection_id else None
        )
        bridge = bridges.get(account.id)
        account_rows.append(
            {
                "id": account.id,
                "institution": institution.canonical_name,
                "name": account.display_name,
                "type": account.account_type,
                "category": category,
                "current_balance": amount(current_value),
                "balance_as_of": latest_balance.snapshot_date if latest_balance else None,
                "starting_balance": amount(starting_amount),
                "starting_balance_as_of": starting_date,
                "change": (
                    amount(latest_balance.amount - starting_amount)
                    if has_change_period and latest_balance and starting_amount is not None
                    else None
                ),
                "inflows": amount(account_in),
                "outflows": amount(account_out),
                "contributions": amount(contributions),
                "withdrawals": amount(withdrawals),
                "investment_result": amount(bridge.investment_result) if bridge else None,
                "performance_status": "available" if bridge else "tracking",
                "cost_basis": amount(holding_cost_basis) if holding_cost_basis else None,
                "unrealized_gain": (
                    amount(holding_value_with_basis - holding_cost_basis)
                    if holding_cost_basis
                    else None
                ),
                "balance_point_count": len(derived_points),
                "transaction_count": len(transactions),
                "holding_count": len(holdings),
                "holdings": [
                    {
                        "name": holding.security_name,
                        "ticker": holding.ticker_symbol,
                        "type": holding.security_type,
                        "quantity": str(holding.quantity),
                        "value": amount(holding.institution_value),
                        "cost_basis": amount(holding.cost_basis),
                        "as_of": holding.as_of,
                    }
                    for holding in holdings
                ],
                "source": "Plaid" if connection else "Manual import",
                "last_synced_at": connection.last_synced_at if connection else None,
                "status": connection.status if connection else "available",
            }
        )

    activity_rows = []
    for transaction, account, institution, category in sorted(
        all_activity,
        key=lambda item: (item[0].posted_date, item[0].id),
        reverse=True,
    ):
        if transaction.role == "internal_transfer":
            direction = "transfer"
        elif transaction.amount > 0:
            direction = "in"
        elif transaction.amount < 0:
            direction = "out"
        else:
            direction = "neutral"
        activity_rows.append(
            {
                "id": transaction.id,
                "account_id": account.id,
                "account": account.display_name,
                "institution": institution.canonical_name,
                "account_category": category,
                "date": transaction.posted_date,
                "description": transaction.original_description or transaction.role,
                "role": transaction.role,
                "direction": direction,
                "amount": amount(transaction.amount),
                "matched_transfer": transaction.id in matched_transfer_ids,
                "source": "Plaid" if account.plaid_connection_id else "Manual import",
            }
        )

    account_rows.sort(
        key=lambda row: (
            {"cash": 0, "investment": 1, "debt": 2, "other": 3}[str(row["category"])],
            -abs(Decimal(str(row["current_balance"] or "0"))),
        )
    )
    net_worth = totals["assets"] - totals["debts"]
    return {
        "as_of": max(
            (row["balance_as_of"] for row in account_rows if row["balance_as_of"]),
            default=None,
        ),
        "activity_period": {
            "start": min(activity_dates, default=None),
            "end": max(activity_dates, default=None),
        },
        "totals": {
            "net_worth": amount(net_worth),
            "assets": amount(totals["assets"]),
            "debts": amount(totals["debts"]),
            "cash": amount(totals["cash"]),
            "investments": amount(totals["investments"]),
            "money_in": amount(totals["money_in"]),
            "money_out": amount(totals["money_out"]),
            "net_cash_flow": amount(totals["money_in"] - totals["money_out"]),
        },
        "accounts": account_rows,
        "activity": activity_rows,
    }


def account_detail(
    session: Session,
    account_id: int,
    start_date: date,
    end_date: date,
) -> dict[str, Any] | None:
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")
    return build_account_detail(session, account_id, start_date, end_date)


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
    employer_contributions = detailed_total(
        "employer_benefit.employer_hsa",
        "employer_benefit.employer_retirement",
    )
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
        recurring_paycheck = {
            "cadence": "Every other Wednesday",
            "effective_from": deposit_anchor,
            "next_expected_deposit": next_deposit,
            "annual_salary": amount(newest.base_salary),
            "gross_earnings": amount(newest.gross_earnings),
            "net_payment": amount(newest.net_payment),
            "employee_retirement": amount(newest_line_total("pretax.employee_retirement")),
            "employer_retirement": amount(
                newest_line_total("employer_benefit.employer_retirement")
            ),
            "employee_stock_purchase": amount(
                newest_line_total("after_tax.employee_stock_purchase")
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


def payroll_history(
    session: Session,
    start_date: date = RECEIVED_START,
    end_date: date = RECEIVED_END,
) -> dict[str, Any]:
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")
    rows = list(
        session.scalars(
            select(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
            .order_by(PayrollScheduleEntry.observed_deposit_date.desc())
        )
    )
    allocations_by_entry: dict[int, list[PayrollAllocation]] = defaultdict(list)
    for allocation in session.scalars(
        select(PayrollAllocation).where(
            PayrollAllocation.schedule_entry_id.in_([row.id for row in rows])
        )
    ):
        allocations_by_entry[allocation.schedule_entry_id].append(allocation)
    matches_by_entry: dict[int, list[dict[str, Any]]] = defaultdict(list)
    matches = list(
        session.scalars(select(PayrollTransactionMatch).order_by(PayrollTransactionMatch.id))
    )
    for match in matches:
        transaction = session.get(AccountTransaction, match.transaction_id)
        account = session.get(Account, transaction.account_id) if transaction else None
        institution = session.get(Institution, account.institution_id) if account else None
        matches_by_entry[match.schedule_entry_id].append(
            {
                "transaction_id": match.transaction_id,
                "date": transaction.posted_date if transaction else None,
                "amount": amount(match.amount),
                "account": account.display_name if account else "Unknown account",
                "institution": institution.canonical_name if institution else "Unknown",
                "description": transaction.original_description if transaction else "",
            }
        )

    def row_payload(row: PayrollScheduleEntry) -> dict[str, Any]:
        adjustments = {
            "variable_compensation": amount(row.gross_adjustment),
            "imputed_income": amount(row.imputed_adjustment),
            "pretax": amount(row.pretax_adjustment),
            "tax": amount(row.tax_adjustment),
            "after_tax": amount(row.after_tax_adjustment),
            "federal_taxable": amount(row.federal_taxable_adjustment),
            "net_payment": amount(row.net_adjustment),
        }
        linked = matches_by_entry.get(row.id, [])
        return {
            "id": row.id,
            "payment_date": row.payment_date,
            "observed_deposit_date": row.observed_deposit_date,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "payroll_year": row.payroll_year,
            "payroll_index": row.payroll_index,
            "source_kind": row.source_kind,
            "calculation_version": row.calculation_version,
            "employer": row.employer,
            "job_title": row.job_title,
            "base_salary": amount(row.base_salary),
            "gross_earnings": amount(row.gross_earnings),
            "imputed_earnings": amount(row.imputed_earnings),
            "pretax_deductions": amount(row.pretax_deductions),
            "tax_withholdings": amount(row.tax_withholdings),
            "after_tax_deductions": amount(row.after_tax_deductions),
            "federal_taxable_gross": amount(row.federal_taxable_gross),
            "net_payment": amount(row.net_payment),
            "adjustments": adjustments,
            "has_adjustments": any(
                Decimal(str(value or "0")) != ZERO for value in adjustments.values()
            ),
            "deposit_splits": row.deposit_splits,
            "plaid_match_status": "matched" if linked else "not_available",
            "plaid_transactions": linked,
            "previous_checkpoint_id": row.previous_checkpoint_id,
            "next_checkpoint_id": row.next_checkpoint_id,
            "source_hash": checkpoint_artifact_hash(session, row.payroll_statement_id),
            "fingerprint": row.fingerprint,
            "allocations": [
                {
                    "section": allocation.section,
                    "category": allocation.category,
                    "label": allocation.label,
                    "amount": amount(allocation.amount),
                    "source_kind": allocation.source_kind,
                }
                for allocation in sorted(
                    allocations_by_entry.get(row.id, []),
                    key=lambda item: (item.section, item.category),
                )
            ],
        }

    totals = {
        "gross_compensation": amount(sum((row.gross_earnings for row in rows), ZERO)),
        "imputed_earnings": amount(sum((row.imputed_earnings for row in rows), ZERO)),
        "pretax_deductions": amount(sum((row.pretax_deductions for row in rows), ZERO)),
        "tax_withholdings": amount(sum((row.tax_withholdings for row in rows), ZERO)),
        "after_tax_deductions": amount(sum((row.after_tax_deductions for row in rows), ZERO)),
        "federal_taxable_gross": amount(sum((row.federal_taxable_gross for row in rows), ZERO)),
        "net_payments": amount(sum((row.net_payment for row in rows), ZERO)),
    }
    return {
        "period": {"start": start_date, "end": end_date},
        "count": len(rows),
        "statement_count": sum(row.source_kind == "statement" for row in rows),
        "calculated_count": sum(row.source_kind == "calculated" for row in rows),
        "totals": totals,
        "rows": [row_payload(row) for row in rows],
    }


def payroll_entry(session: Session, entry_id: int) -> dict[str, Any] | None:
    row = session.get(PayrollScheduleEntry, entry_id)
    if row is None:
        return None
    history = payroll_history(session, row.observed_deposit_date, row.observed_deposit_date)
    return next((item for item in history["rows"] if item["id"] == entry_id), None)


def payroll_reconciliation(session: Session) -> dict[str, Any]:
    checks = schedule_validation(session)
    return {
        "status": (
            "reconciled"
            if checks and all(check["status"] == "reconciled" for check in checks)
            else "unreconciled"
        ),
        "checks": checks,
    }


def paychecks(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date.desc()))
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        results = list(
            session.scalars(
                select(ReconciliationResult).where(
                    ReconciliationResult.entity_type == "payroll_statement",
                    ReconciliationResult.entity_id == str(row.id),
                )
            )
        )
        evidence = list(
            session.scalars(
                select(SourceEvidence)
                .join(ImportArtifact)
                .where(
                    SourceEvidence.entity_type == "payroll_statement",
                    SourceEvidence.entity_id == str(row.id),
                )
            )
        )
        artifact = session.get(ImportArtifact, row.artifact_id)
        lines = list(
            session.scalars(
                select(PayrollLineItem)
                .where(
                    PayrollLineItem.statement_id == row.id,
                    PayrollLineItem.category.contains("."),
                )
                .order_by(PayrollLineItem.id)
            )
        )
        output.append(
            {
                "id": row.id,
                "payment_date": row.payment_date,
                "observed_deposit_date": row.observed_deposit_date,
                "period_start": row.period_start,
                "period_end": row.period_end,
                "employer": row.employer,
                "job_title": row.job_title,
                "base_salary": amount(row.base_salary),
                "gross_earnings": amount(row.gross_earnings),
                "imputed_earnings": amount(row.imputed_earnings),
                "pretax_deductions": amount(row.pretax_deductions),
                "tax_withholdings": amount(row.tax_withholdings),
                "after_tax_deductions": amount(row.after_tax_deductions),
                "federal_taxable_gross": amount(row.federal_taxable_gross),
                "net_payment": amount(row.net_payment),
                "detail_complete": row.detail_complete,
                "details": [
                    {
                        "section": line.category.split(".", 1)[0],
                        "category": line.category.split(".", 1)[1],
                        "label": line.original_label,
                        "amount": amount(line.amount),
                        "ytd_amount": amount(line.ytd_amount),
                        "reduces_net": line.reduces_net,
                    }
                    for line in lines
                ],
                "source": {
                    "filename": artifact.original_filename if artifact else "unknown",
                    "hash": artifact.sha256 if artifact else "",
                    "parser_version": artifact.parser_version if artifact else "",
                },
                "evidence": [
                    {
                        "field": item.field_name,
                        "location": item.location,
                        "label": item.original_label,
                        "confidence": item.confidence,
                        "review_status": item.review_status,
                    }
                    for item in evidence
                ],
                "reconciliation": [
                    {
                        "rule": result.rule,
                        "status": result.status,
                        "residual": amount(result.residual),
                        "details": result.details,
                    }
                    for result in results
                ],
            }
        )
    return output


def sofi_summary(session: Session) -> dict[str, Any]:
    accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(Institution.kind == "bank")
            .order_by(Account.account_type, Account.display_name)
        )
    )
    matched_ids: set[int] = set()
    for match in session.scalars(select(TransferMatch)):
        matched_ids.update({match.left_transaction_id, match.right_transaction_id})
    account_output: list[dict[str, Any]] = []
    consolidated_external = ZERO
    for account in accounts:
        transactions = list(
            session.scalars(
                select(AccountTransaction)
                .where(AccountTransaction.account_id == account.id)
                .order_by(AccountTransaction.posted_date)
            )
        )
        balances = list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id == account.id)
                .order_by(BalanceSnapshot.snapshot_date)
            )
        )
        external = [
            row
            for row in transactions
            if row.id not in matched_ids and row.role != "internal_transfer"
        ]
        inflows = sum((row.amount for row in external if row.amount > 0), ZERO)
        outflows = abs(sum((row.amount for row in external if row.amount < 0), ZERO))
        consolidated_external += inflows - outflows
        internal = sum(
            (abs(row.amount) for row in transactions if row.id in matched_ids), ZERO
        ) / Decimal("2")
        opening = next((row.amount for row in balances if row.kind == "opening"), None)
        closing = next((row.amount for row in reversed(balances) if row.kind == "closing"), None)
        current = [row for row in balances if row.kind == "current"]
        if opening is None and len(current) >= 2:
            opening = current[0].amount
        if closing is None and current:
            closing = current[-1].amount
        observed_balances = [
            row.balance_after for row in transactions if row.balance_after is not None
        ]
        account_output.append(
            {
                "id": account.id,
                "name": account.display_name,
                "type": account.account_type,
                "opening_balance": amount(opening),
                "inflows": amount(inflows),
                "outflows": amount(outflows),
                "internal_transfers": amount(internal),
                "interest": amount(
                    sum((row.amount for row in transactions if row.role == "interest"), ZERO)
                ),
                "fees": amount(
                    abs(sum((row.amount for row in transactions if row.role == "fee"), ZERO))
                ),
                "closing_balance": amount(closing),
                "lowest_observed_balance": amount(min(observed_balances))
                if observed_balances
                else None,
                "highest_observed_balance": amount(max(observed_balances))
                if observed_balances
                else None,
                "source": "Plaid" if account.plaid_connection_id else "Manual import",
            }
        )
    return {
        "accounts": account_output,
        "consolidated_external_net": amount(consolidated_external),
        "internal_transfer_pairs": len(matched_ids) // 2,
        "warnings": [] if accounts else ["No SoFi ledger has been imported."],
    }


def fidelity_summary(session: Session) -> dict[str, Any]:
    bridges = list(
        session.scalars(select(InvestmentValueBridge).order_by(InvestmentValueBridge.period_end))
    )
    bridge_by_account = {bridge.account_id: bridge for bridge in bridges}
    accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(Institution.kind == "investment")
            .order_by(Account.display_name)
        )
    )
    by_account: list[dict[str, Any]] = []
    for account in accounts:
        bridge = bridge_by_account.get(account.id)
        latest_balance = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account.id)
            .order_by(BalanceSnapshot.snapshot_date.desc())
            .limit(1)
        )
        holdings = list(
            session.scalars(
                select(InvestmentHolding)
                .where(InvestmentHolding.account_id == account.id)
                .order_by(InvestmentHolding.institution_value.desc())
            )
        )
        cost_basis = money(
            sum(
                (holding.cost_basis for holding in holdings if holding.cost_basis is not None), ZERO
            )
        )
        market_with_basis = money(
            sum(
                (
                    holding.institution_value
                    for holding in holdings
                    if holding.cost_basis is not None
                ),
                ZERO,
            )
        )
        by_account.append(
            {
                "account": account.display_name,
                "source": "Plaid" if account.plaid_connection_id else "Manual import",
                "current_value": amount(latest_balance.amount) if latest_balance else None,
                "current_value_as_of": (latest_balance.snapshot_date if latest_balance else None),
                "period_start": bridge.period_start if bridge else None,
                "period_end": bridge.period_end if bridge else None,
                "opening_value": amount(bridge.opening_value) if bridge else None,
                "employee_contributions": (
                    amount(bridge.employee_contributions) if bridge else None
                ),
                "employer_contributions": (
                    amount(bridge.employer_contributions) if bridge else None
                ),
                "stock_plan_contributions": (
                    amount(bridge.stock_plan_contributions) if bridge else None
                ),
                "other_deposits": amount(bridge.other_deposits) if bridge else None,
                "withdrawals": amount(bridge.withdrawals) if bridge else None,
                "investment_result": amount(bridge.investment_result) if bridge else None,
                "closing_value": amount(bridge.closing_value) if bridge else None,
                "reported_return_pct": (amount(bridge.reported_return_pct) if bridge else None),
                "calculated_return_pct": (amount(bridge.calculated_return_pct) if bridge else None),
                "return_method": bridge.return_method if bridge else "awaiting_second_value",
                "performance_status": "available" if bridge else "tracking",
                "cost_basis": amount(cost_basis) if cost_basis else None,
                "unrealized_gain": (amount(market_with_basis - cost_basis) if cost_basis else None),
                "holdings": [
                    {
                        "name": holding.security_name,
                        "ticker": holding.ticker_symbol,
                        "type": holding.security_type,
                        "quantity": str(holding.quantity),
                        "value": amount(holding.institution_value),
                        "cost_basis": amount(holding.cost_basis),
                        "as_of": holding.as_of,
                    }
                    for holding in holdings
                ],
            }
        )

    def total(field: str) -> Decimal:
        return money(sum((getattr(item, field) for item in bridges), ZERO))

    return {
        "accounts": by_account,
        "consolidated": (
            {
                field: amount(total(field))
                for field in (
                    "opening_value",
                    "employee_contributions",
                    "employer_contributions",
                    "stock_plan_contributions",
                    "other_deposits",
                    "withdrawals",
                    "investment_result",
                    "closing_value",
                )
            }
            if bridges
            else {}
        ),
        "warnings": [],
    }


def timeline(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    default_start, default_end = latest_complete_period()
    start = start_date or default_start
    end = end_date or default_end
    if start > end:
        raise ValueError("Start date must be on or before end date")
    return monthly_timeline(session, start, end)


def exceptions(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(ReconciliationResult)
            .where(ReconciliationResult.status != "reconciled")
            .order_by(ReconciliationResult.entity_type, ReconciliationResult.entity_id)
        )
    )
    actionable = [row for row in rows if row.status == "unreconciled"]
    return [
        {
            "id": row.id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "rule": row.rule,
            "status": row.status,
            "residual": amount(row.residual),
            "details": row.details,
        }
        for row in actionable
    ]


def imports(session: Session) -> list[dict[str, Any]]:
    batches = list(session.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())))
    return [
        {
            "id": batch.id,
            "created_at": batch.created_at,
            "status": batch.status,
            "discovered": batch.artifact_count,
            "imported": batch.imported_count,
            "duplicates": batch.duplicate_count,
            "errors": batch.error_count,
        }
        for batch in batches
    ]


def scenarios(session: Session) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(ForecastScenario).order_by(ForecastScenario.created_at)))
    return [
        {
            "id": row.id,
            "name": row.name,
            "is_baseline": row.is_baseline,
            "inputs": row.inputs,
            "periods": [
                {
                    "month": period.month,
                    "gross_pay": amount(period.gross_pay),
                    "taxes": amount(period.taxes),
                    "benefits_and_other": amount(period.benefits_and_other),
                    "employee_retirement": amount(period.employee_retirement),
                    "employee_hsa": amount(period.employee_hsa),
                    "stock_plan": amount(period.stock_plan),
                    "employer_retirement": amount(period.employer_retirement),
                    "employer_hsa": amount(period.employer_hsa),
                    "sofi_checking": amount(period.sofi_checking),
                    "sofi_savings": amount(period.sofi_savings),
                    "external_outflow": amount(period.external_outflow),
                    "ending_checking": amount(period.ending_checking),
                    "ending_savings": amount(period.ending_savings),
                    "ending_cash": amount(period.ending_cash),
                    "cash_redirect_to_investments": amount(period.cash_redirect_to_investments),
                    "assumed_investment_result": amount(period.assumed_investment_result),
                }
                for period in sorted(row.periods, key=lambda item: item.month)
            ],
        }
        for row in rows
    ]
