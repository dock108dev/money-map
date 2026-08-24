from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import (
    monthly_timeline,
)
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    ForecastScenario,
    ImportBatch,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    ReconciliationResult,
    TransferMatch,
)
from .money import ZERO, money
from .reconciliation import investment_performance_available
from .service_common import amount, latest_complete_period


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
        performance_available = bool(bridge and investment_performance_available(bridge))
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
                "investment_result": (
                    amount(bridge.investment_result) if performance_available and bridge else None
                ),
                "closing_value": amount(bridge.closing_value) if bridge else None,
                "reported_return_pct": (amount(bridge.reported_return_pct) if bridge else None),
                "calculated_return_pct": (amount(bridge.calculated_return_pct) if bridge else None),
                "return_method": bridge.return_method if bridge else "awaiting_second_value",
                "performance_status": "available" if performance_available else "tracking",
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

    available_bridges = [bridge for bridge in bridges if investment_performance_available(bridge)]

    def total(field: str) -> Decimal:
        return money(sum((getattr(item, field) for item in available_bridges), ZERO))

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
            if available_bridges
            else {}
        ),
        "warnings": (
            []
            if available_bridges or not bridges
            else [
                "Investment performance is tracking until at least seven days of values produce "
                "an interval without cash activity on either observation date."
            ]
        ),
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
