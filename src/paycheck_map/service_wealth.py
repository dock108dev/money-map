from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import (
    period_investments,
)
from .models import (
    Account,
    AccountTransaction,
    Institution,
    InvestmentHolding,
    PayrollAllocation,
    PayrollScheduleEntry,
)
from .money import ZERO, money
from .reconciliation import INVESTMENT_CASH_FLOW_ROLES
from .service_common import (
    _investment_access,
    _latest_balance,
    _performance_window,
    _snapshot_values,
    amount,
)


def wealth_dashboard(session: Session) -> dict[str, Any]:
    """Accessible wealth plus contribution-adjusted Fidelity performance evidence."""

    account_pairs = list(
        session.execute(
            select(Account, Institution)
            .join(Institution)
            .order_by(Institution.canonical_name, Account.id)
        )
    )
    cash = ZERO
    accessible_accounts: list[dict[str, Any]] = []
    fidelity_accounts: list[Account] = []
    fidelity_holdings: dict[int, list[InvestmentHolding]] = {}
    current_by_account: dict[int, Decimal] = {}

    for account, institution in account_pairs:
        latest = _latest_balance(session, account.id)
        current = latest.amount if latest else ZERO
        account_type = account.account_type.strip().lower().replace("_", " ")
        if institution.kind == "bank" and account_type in {"checking", "savings"}:
            cash += current
            if current:
                accessible_accounts.append(
                    {
                        "id": account.id,
                        "name": account.display_name,
                        "type": account.account_type,
                        "value": amount(current),
                        "access_status": "accessible",
                        "access_reason": "Spendable cash",
                    }
                )
        if "fidelity" not in institution.canonical_name.lower():
            continue
        fidelity_accounts.append(account)
        holdings = list(
            session.scalars(
                select(InvestmentHolding)
                .where(InvestmentHolding.account_id == account.id)
                .order_by(InvestmentHolding.institution_value.desc())
            )
        )
        fidelity_holdings[account.id] = holdings
        current_by_account[account.id] = current

    sellable_investments = ZERO
    excluded_investments = ZERO
    account_access: dict[int, tuple[Decimal, Decimal, str, str]] = {}
    for account in fidelity_accounts:
        access = _investment_access(
            account,
            current_by_account[account.id],
            fidelity_holdings[account.id],
        )
        account_access[account.id] = access
        accessible_value, excluded_value, status, reason = access
        sellable_investments += accessible_value
        excluded_investments += excluded_value
        if accessible_value:
            accessible_accounts.append(
                {
                    "id": account.id,
                    "name": account.display_name,
                    "type": account.account_type,
                    "value": amount(accessible_value),
                    "access_status": status,
                    "access_reason": reason,
                }
            )

    values_by_account = {
        account.id: _snapshot_values(session, account.id) for account in fidelity_accounts
    }
    dated_sets = [set(values) for values in values_by_account.values() if values]
    common_dates = sorted(set.intersection(*dated_sets)) if dated_sets else []
    history = [
        {
            "date": observation_date,
            "value": amount(
                sum(
                    (
                        values_by_account[account.id][observation_date]
                        for account in fidelity_accounts
                    ),
                    ZERO,
                )
            ),
        }
        for observation_date in common_dates
    ]
    fidelity_ids = [account.id for account in fidelity_accounts]
    fidelity_transactions = (
        list(
            session.scalars(
                select(AccountTransaction).where(AccountTransaction.account_id.in_(fidelity_ids))
            )
        )
        if fidelity_ids
        else []
    )
    ambiguous_dates = {
        transaction.posted_date
        for transaction in fidelity_transactions
        if transaction.role in INVESTMENT_CASH_FLOW_ROLES or transaction.role == "unresolved"
    }
    clean_dates = [
        observation_date
        for observation_date in common_dates
        if observation_date not in ambiguous_dates
    ]
    closing_date = clean_dates[-1] if clean_dates else (common_dates[-1] if common_dates else None)
    clean_anchor = clean_dates[0] if clean_dates else closing_date

    performance_periods: list[dict[str, Any]] = []
    if closing_date is not None and clean_anchor is not None:
        period_specs = [
            ("observed", "Observed", 7, clean_anchor),
            ("one_month", "1 month", 30, closing_date - timedelta(days=30)),
            ("three_months", "3 months", 90, closing_date - timedelta(days=90)),
            (
                "year_to_date",
                "YTD",
                max(7, (closing_date - date(closing_date.year, 1, 1)).days),
                date(closing_date.year, 1, 1),
            ),
            ("one_year", "1 year", 365, closing_date - timedelta(days=365)),
        ]
        for key, label, required_days, target in period_specs:
            candidates = [
                observation_date
                for observation_date in clean_dates
                if clean_anchor <= observation_date <= target
            ]
            opening_date = candidates[-1] if candidates else clean_anchor
            opening_value = sum(
                (values_by_account[account.id][opening_date] for account in fidelity_accounts),
                ZERO,
            )
            closing_value = sum(
                (values_by_account[account.id][closing_date] for account in fidelity_accounts),
                ZERO,
            )
            performance_periods.append(
                _performance_window(
                    session=session,
                    account_ids=fidelity_ids,
                    opening_date=opening_date,
                    closing_date=closing_date,
                    opening_value=money(opening_value),
                    closing_value=money(closing_value),
                    required_days=required_days,
                    label=label,
                    key=key,
                )
            )

    recent_observation: dict[str, Any] | None = None
    recent_start: date | None = None
    recent_end: date | None = None
    if len(common_dates) >= 2:
        recent_start, recent_end = common_dates[-2], common_dates[-1]
        recent_opening = money(
            sum(
                (values_by_account[account.id][recent_start] for account in fidelity_accounts),
                ZERO,
            )
        )
        recent_closing = money(
            sum(
                (values_by_account[account.id][recent_end] for account in fidelity_accounts),
                ZERO,
            )
        )
        recent_change = money(recent_closing - recent_opening)
        recent_observation = {
            "period_start": recent_start,
            "period_end": recent_end,
            "opening_value": amount(recent_opening),
            "closing_value": amount(recent_closing),
            "change": amount(recent_change),
            "change_pct": amount(
                recent_change / recent_opening * Decimal("100") if recent_opening else ZERO
            ),
            "message": "Observed balance movement; not yet a contribution-adjusted return.",
        }

    account_rows: list[dict[str, Any]] = []
    observed_period = next(
        (period for period in performance_periods if period["key"] == "observed"),
        None,
    )
    for account in fidelity_accounts:
        accessible_value, excluded_value, access_status, access_reason = account_access[account.id]
        account_recent_change: Decimal | None = None
        if recent_start is not None and recent_end is not None:
            account_recent_change = money(
                values_by_account[account.id][recent_end]
                - values_by_account[account.id][recent_start]
            )
        account_performance: dict[str, Any] | None = None
        if observed_period is not None:
            account_opening_date = observed_period["period_start"]
            account_closing_date = observed_period["period_end"]
            if (
                account_opening_date in values_by_account[account.id]
                and account_closing_date in values_by_account[account.id]
            ):
                account_performance = _performance_window(
                    session=session,
                    account_ids=[account.id],
                    opening_date=account_opening_date,
                    closing_date=account_closing_date,
                    opening_value=values_by_account[account.id][account_opening_date],
                    closing_value=values_by_account[account.id][account_closing_date],
                    required_days=observed_period["required_days"],
                    label="Observed",
                    key="observed",
                )
        account_rows.append(
            {
                "id": account.id,
                "name": account.display_name,
                "type": account.account_type,
                "current_value": amount(current_by_account[account.id]),
                "accessible_value": amount(accessible_value),
                "excluded_value": amount(excluded_value),
                "access_status": access_status,
                "access_reason": access_reason,
                "recent_change": amount(account_recent_change),
                "performance_status": (
                    account_performance["status"] if account_performance else "tracking"
                ),
                "investment_result": (
                    account_performance["investment_result"] if account_performance else None
                ),
                "return_pct": account_performance["return_pct"] if account_performance else None,
                "performance_message": (
                    account_performance["message"]
                    if account_performance
                    else "More balance history is needed."
                ),
            }
        )

    latest_paycheck = session.scalar(
        select(PayrollScheduleEntry)
        .order_by(PayrollScheduleEntry.observed_deposit_date.desc())
        .limit(1)
    )
    paycheck: dict[str, Any] | None = None
    if latest_paycheck is not None:
        allocations = list(
            session.scalars(
                select(PayrollAllocation).where(
                    PayrollAllocation.schedule_entry_id == latest_paycheck.id
                )
            )
        )

        def allocated(category: str) -> Decimal:
            return money(sum((row.amount for row in allocations if row.category == category), ZERO))

        stock = allocated("after_tax.employee_stock_purchase")
        locked = money(
            allocated("pretax.employee_retirement")
            + allocated("pretax.employee_hsa")
            + allocated("employer_benefit.employer_retirement")
            + allocated("employer_benefit.employer_hsa")
        )
        paycheck = {
            "spendable_cash": amount(latest_paycheck.net_payment),
            "accessible_stock_funding": amount(stock),
            "accessible_value_before_spending": amount(latest_paycheck.net_payment + stock),
            "locked_account_funding": amount(locked),
            "total_paycheck_value": amount(latest_paycheck.net_payment + stock + locked),
        }

    fidelity_current = money(sum(current_by_account.values(), ZERO))
    funding_end = closing_date or date.today()
    funding = period_investments(session, funding_end - timedelta(days=365), funding_end)
    return {
        "as_of": closing_date,
        "accessible": {
            "total": amount(money(cash + sellable_investments)),
            "cash": amount(money(cash)),
            "sellable_investments": amount(money(sellable_investments)),
            "accounts": accessible_accounts,
        },
        "excluded": {
            "total": amount(money(excluded_investments)),
            "message": "Tracked for performance, excluded from accessible wealth.",
        },
        "fidelity": {
            "current_value": amount(fidelity_current),
            "accounts": account_rows,
            "history": history,
            "recent_observation": recent_observation,
            "performance_periods": performance_periods,
            "funding": {
                "period_start": funding_end - timedelta(days=365),
                "period_end": funding_end,
                "you_contributed": funding["employee_fidelity_contributions"],
                "employer_contributed": funding["employer_contributions"],
                "total_payroll_funding": funding["total_payroll_fidelity_contributions"],
            },
        },
        "paycheck": paycheck,
    }
