from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import (
    latest_complete_twelve_months,
)
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    Institution,
    InvestmentHolding,
)
from .money import ZERO, money


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

LOCKED_INVESTMENT_TYPES = {
    "401k",
    "403b",
    "457b",
    "529",
    "hsa",
    "ira",
    "pension",
    "retirement",
    "roth",
    "roth ira",
}
RESTRICTED_HOLDING_MARKERS = {"restricted", "rsu", "unvested", "unexercised"}


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


def _latest_balance(session: Session, account_id: int) -> BalanceSnapshot | None:
    return session.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.snapshot_date.desc(), BalanceSnapshot.id.desc())
        .limit(1)
    )


def _is_restricted_holding(holding: InvestmentHolding) -> bool:
    label = f"{holding.security_name} {holding.ticker_symbol or ''}".lower()
    return any(marker in label for marker in RESTRICTED_HOLDING_MARKERS)


def _investment_access(
    account: Account,
    current_value: Decimal,
    holdings: list[InvestmentHolding],
) -> tuple[Decimal, Decimal, str, str]:
    account_type = account.account_type.strip().lower().replace("_", " ")
    if account_type in LOCKED_INVESTMENT_TYPES:
        return ZERO, current_value, "retirement", "Retirement or tax-advantaged"
    if account_type == "stock plan" and holdings:
        restricted = money(
            sum(
                (
                    holding.institution_value
                    for holding in holdings
                    if _is_restricted_holding(holding)
                ),
                ZERO,
            )
        )
        sellable = money(
            sum(
                (
                    holding.institution_value
                    for holding in holdings
                    if not _is_restricted_holding(holding)
                ),
                ZERO,
            )
        )
        unallocated = max(ZERO, money(current_value - restricted - sellable))
        sellable = money(sellable + unallocated)
        if restricted and sellable:
            return sellable, restricted, "mixed", "Sellable shares and restricted equity"
        if restricted:
            return ZERO, current_value, "restricted", "Restricted equity"
        return current_value, ZERO, "accessible", "Sellable stock-plan shares"
    if account_type in {"brokerage", "investment", "stock plan"}:
        return current_value, ZERO, "accessible", "Sellable investment"
    return ZERO, current_value, "review", "Accessibility not confirmed"


def _snapshot_values(session: Session, account_id: int) -> dict[date, Decimal]:
    observations: dict[date, Decimal] = {}
    for snapshot in session.scalars(
        select(BalanceSnapshot)
        .where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.kind.in_(["opening", "closing", "current", "manual"]),
        )
        .order_by(BalanceSnapshot.snapshot_date, BalanceSnapshot.id)
    ):
        observations[snapshot.snapshot_date] = snapshot.amount
    return observations


def _performance_window(
    *,
    session: Session,
    account_ids: list[int],
    opening_date: date,
    closing_date: date,
    opening_value: Decimal,
    closing_value: Decimal,
    required_days: int,
    label: str,
    key: str,
) -> dict[str, Any]:
    observation_days = (closing_date - opening_date).days
    transactions = list(
        session.scalars(
            select(AccountTransaction).where(
                AccountTransaction.account_id.in_(account_ids),
                AccountTransaction.posted_date > opening_date,
                AccountTransaction.posted_date <= closing_date,
            )
        )
    )
    deposits = money(
        sum(
            (
                max(ZERO, transaction.amount)
                for transaction in transactions
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
    )
    withdrawals = money(
        sum(
            (
                abs(transaction.amount)
                for transaction in transactions
                if transaction.role == "external_withdrawal" and transaction.amount < ZERO
            ),
            ZERO,
        )
    )
    result = money(closing_value - opening_value - deposits + withdrawals)
    signed_flows = [
        (transaction.posted_date, transaction.amount)
        for transaction in transactions
        if transaction.role
        in {
            "employee_contribution",
            "employer_contribution",
            "stock_plan_contribution",
            "external_deposit",
            "external_withdrawal",
        }
    ]
    weighted_flows = ZERO
    if observation_days > 0:
        for flow_date, flow in signed_flows:
            remaining = Decimal((closing_date - flow_date).days) / Decimal(observation_days)
            weighted_flows += flow * remaining
    denominator = money(opening_value + weighted_flows)
    return_pct = (
        money(result / denominator * Decimal("100"))
        if observation_days >= required_days and denominator != ZERO
        else None
    )
    available = observation_days >= required_days and return_pct is not None
    return {
        "key": key,
        "label": label,
        "status": "available" if available else "tracking",
        "period_start": opening_date,
        "period_end": closing_date,
        "observation_days": observation_days,
        "required_days": required_days,
        "opening_value": amount(opening_value),
        "deposits": amount(deposits),
        "withdrawals": amount(withdrawals),
        "investment_result": amount(result) if available else None,
        "return_pct": amount(return_pct),
        "closing_value": amount(closing_value),
        "message": (
            "Contributions and withdrawals are removed from the investment result."
            if available
            else f"Collecting {max(0, required_days - observation_days)} more clean day"
            f"{'s' if max(0, required_days - observation_days) != 1 else ''}."
        ),
    }
