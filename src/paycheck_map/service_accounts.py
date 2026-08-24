from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import (
    account_detail as build_account_detail,
)
from .models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    PlaidConnection,
    TransferMatch,
)
from .money import ZERO, money
from .reconciliation import investment_performance_available
from .service_common import _account_category, amount


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
        performance_available = bool(bridge and investment_performance_available(bridge))
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
                "investment_result": (
                    amount(bridge.investment_result) if performance_available and bridge else None
                ),
                "performance_status": "available" if performance_available else "tracking",
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
