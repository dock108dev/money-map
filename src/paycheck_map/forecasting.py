from __future__ import annotations

import calendar
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings, settings
from .models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    ForecastPeriod,
    ForecastScenario,
    Institution,
    PayrollLineItem,
    PayrollStatement,
)
from .money import ZERO, money

FORECAST_VERSION = "money-map-v1.0.5"


class ScenarioInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    additional_401k_pct: Decimal = Field(default=ZERO, ge=0, le=100)
    stock_plan_pct: Decimal = Field(default=ZERO, ge=0, le=100)
    hsa_per_paycheck: Decimal | None = Field(default=None, ge=0)
    checking_split_pct: Decimal | None = Field(default=None, ge=0, le=100)
    monthly_outflow: Decimal | None = Field(default=None, ge=0)
    cash_floor: Decimal = Field(default=ZERO, ge=0)
    redirect_cash_above_floor: bool = False
    annual_return_pct: Decimal = Field(default=ZERO, ge=-100, le=100)
    opening_checking: Decimal | None = Field(default=None, ge=0)
    opening_savings: Decimal | None = Field(default=None, ge=0)
    employer_match_pct: Decimal = Field(default=ZERO, ge=0, le=100)
    bonus_amount: Decimal = Field(default=ZERO, ge=0)
    bonus_month: date | None = None

    @field_validator(
        "additional_401k_pct",
        "stock_plan_pct",
        "hsa_per_paycheck",
        "checking_split_pct",
        "monthly_outflow",
        "cash_floor",
        "annual_return_pct",
        "opening_checking",
        "opening_savings",
        "employer_match_pct",
        "bonus_amount",
        mode="before",
    )
    @classmethod
    def decimal_from_text(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return Decimal(str(value))


class ForecastSummary(BaseModel):
    scenario_id: int
    name: str
    start_month: date
    end_month: date
    annual_salary: Decimal
    additional_fidelity_funding: Decimal
    lowest_projected_cash: Decimal
    contribution_limit_warnings: list[str]
    assumption_warnings: list[str]


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_sequence(start: date, count: int = 12) -> list[date]:
    months = [start]
    for _ in range(count - 1):
        months.append(_next_month(months[-1]))
    return months


def _serialize_input(value: object) -> str | int | float | bool | None:
    if isinstance(value, (Decimal, date)):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _latest_cash_balance(session: Session, account_type: str) -> Decimal:
    snapshot = session.scalar(
        select(BalanceSnapshot)
        .join(Account)
        .join(Institution)
        .where(
            Institution.canonical_name == "SoFi",
            Account.account_type == account_type,
            BalanceSnapshot.kind.in_(["closing", "current"]),
        )
        .order_by(BalanceSnapshot.snapshot_date.desc())
        .limit(1)
    )
    return snapshot.amount if snapshot is not None else ZERO


def _latest_investment_balance(session: Session) -> Decimal:
    accounts = list(
        session.scalars(select(Account).join(Institution).where(Institution.kind == "investment"))
    )
    total = ZERO
    for account in accounts:
        snapshot = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account.id)
            .order_by(BalanceSnapshot.snapshot_date.desc(), BalanceSnapshot.id.desc())
            .limit(1)
        )
        if snapshot is not None:
            total += snapshot.amount
    return money(total)


def _observed_monthly_outflow(session: Session, as_of: date) -> tuple[Decimal, list[str]]:
    cash_accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(
                Institution.kind == "bank",
                Account.account_type.in_(["checking", "savings"]),
            )
        )
    )
    if not cash_accounts:
        return ZERO, []
    complete_by_account: list[set[tuple[int, int]]] = []
    for account in cash_accounts:
        snapshots = list(
            session.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id))
        )
        snapshot_openings = {
            (row.snapshot_date.year, row.snapshot_date.month)
            for row in snapshots
            if row.kind == "opening" and row.snapshot_date.day == 1
        }
        snapshot_closings = {
            (row.snapshot_date.year, row.snapshot_date.month)
            for row in snapshots
            if row.kind in {"closing", "current"}
            and row.snapshot_date.day
            == calendar.monthrange(row.snapshot_date.year, row.snapshot_date.month)[1]
        }
        points = list(
            session.scalars(
                select(AccountBalancePoint).where(AccountBalancePoint.account_id == account.id)
            )
        )
        openings = {
            (row.balance_date.year, row.balance_date.month)
            for row in points
            if row.kind == "month_open"
        }
        closings = {
            (row.balance_date.year, row.balance_date.month)
            for row in points
            if row.kind == "month_close"
            or (
                row.source_kind == "observed"
                and row.balance_date.day
                == calendar.monthrange(row.balance_date.year, row.balance_date.month)[1]
            )
        }
        complete_by_account.append((snapshot_openings & snapshot_closings) | (openings & closings))
    complete_months = set.intersection(*complete_by_account) if complete_by_account else set()
    current_month = (as_of.year, as_of.month)
    complete_months.discard(current_month)
    by_month: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    account_ids = [account.id for account in cash_accounts]
    transactions = list(
        session.scalars(
            select(AccountTransaction).where(
                AccountTransaction.account_id.in_(account_ids),
                AccountTransaction.amount < ZERO,
                AccountTransaction.role.in_(["external_outflow", "fee"]),
            )
        )
    )
    for transaction in transactions:
        key = (transaction.posted_date.year, transaction.posted_date.month)
        if key in complete_months:
            by_month[key] += abs(transaction.amount)
    if not by_month:
        return ZERO, []
    labels = [f"{year:04d}-{month:02d}" for year, month in sorted(by_month)]
    return money(sum(by_month.values(), ZERO) / len(by_month)), labels


def _observed_checking_split(session: Session, latest: PayrollStatement) -> tuple[Decimal, str]:
    distributions = list(
        session.scalars(
            select(PayrollLineItem).where(
                PayrollLineItem.statement_id == latest.id,
                PayrollLineItem.category.like("net_distribution.%"),
            )
        )
    )
    total = money(sum((line.amount for line in distributions), ZERO))
    if total <= ZERO:
        return Decimal("100"), "fallback because payroll has no net distribution detail"
    checking_accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(
                Institution.kind == "bank",
                Account.account_type == "checking",
            )
        )
    )
    checking_markers = {
        marker
        for account in checking_accounts
        for marker in [
            "".join(character for character in account.display_name if character.isdigit())[-4:]
        ]
        if marker
    }
    checking = money(
        sum(
            (
                line.amount
                for line in distributions
                if "checking" in line.original_label.lower()
                or any(marker in line.original_label for marker in checking_markers)
            ),
            ZERO,
        )
    )
    if checking <= ZERO:
        return Decimal("100"), "fallback because the checking destination could not be matched"
    return money(checking / total * Decimal("100")), "latest detailed payroll distribution"


def _baseline_fingerprint(session: Session, as_of: date) -> str:
    latest = session.scalar(
        select(PayrollStatement).order_by(PayrollStatement.payment_date.desc()).limit(1)
    )
    cash_accounts = list(
        session.scalars(
            select(Account)
            .join(Institution)
            .where(
                Institution.kind == "bank",
                Account.account_type.in_(["checking", "savings"]),
            )
            .order_by(Account.id)
        )
    )
    account_ids = [account.id for account in cash_accounts]
    snapshots = (
        list(
            session.scalars(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.account_id.in_(account_ids))
                .order_by(
                    BalanceSnapshot.account_id, BalanceSnapshot.snapshot_date, BalanceSnapshot.id
                )
            )
        )
        if account_ids
        else []
    )
    transactions = (
        list(
            session.scalars(
                select(AccountTransaction)
                .where(AccountTransaction.account_id.in_(account_ids))
                .order_by(
                    AccountTransaction.account_id,
                    AccountTransaction.posted_date,
                    AccountTransaction.id,
                )
            )
        )
        if account_ids
        else []
    )
    lines = (
        list(
            session.scalars(
                select(PayrollLineItem)
                .where(PayrollLineItem.statement_id == latest.id)
                .order_by(PayrollLineItem.category, PayrollLineItem.id)
            )
        )
        if latest
        else []
    )
    payload = {
        "forecast_month": str(_next_month(_month_start(as_of))),
        "payroll": (
            [
                latest.id,
                str(latest.payment_date),
                str(latest.base_salary),
                str(latest.gross_earnings),
                str(latest.net_payment),
                str(latest.observed_deposit_date),
            ]
            if latest
            else None
        ),
        "payroll_lines": [
            [line.category, line.original_label, str(line.amount), str(line.ytd_amount)]
            for line in lines
        ],
        "cash_accounts": [[account.id, account.account_type] for account in cash_accounts],
        "cash_snapshots": [
            [row.account_id, str(row.snapshot_date), row.kind, str(row.amount)] for row in snapshots
        ],
        "cash_activity": [
            [row.account_id, str(row.posted_date), row.role, str(row.amount)]
            for row in transactions
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contribution_limits(runtime_settings: Settings) -> dict[str, dict[str, str]]:
    path = runtime_settings.config_dir / "contribution_limits.json"
    if not path.exists():
        return {}
    return cast(dict[str, dict[str, str]], json.loads(path.read_text(encoding="utf-8")))


def build_forecast(
    session: Session,
    scenario_input: ScenarioInput,
    runtime_settings: Settings = settings,
    *,
    is_baseline: bool = False,
    as_of: date | None = None,
) -> ForecastSummary:
    latest = session.scalar(
        select(PayrollStatement).order_by(PayrollStatement.payment_date.desc()).limit(1)
    )
    if latest is None:
        raise ValueError("Import at least one payroll statement before forecasting")

    # The latest statement remains the baseline even when its payment month is partial;
    # this captures a newly effective salary or deduction change.
    today = as_of or date.today()
    first_forecast_month = _next_month(_month_start(today))
    months = _month_sequence(first_forecast_month)
    last_month = months[-1]
    days_in_last_month = calendar.monthrange(last_month.year, last_month.month)[1]
    last_day = date(last_month.year, last_month.month, days_in_last_month)

    pay_dates: list[date] = []
    pay_schedule_anchor = latest.observed_deposit_date or latest.payment_date
    next_pay = pay_schedule_anchor + timedelta(days=14)
    while next_pay <= last_day:
        if next_pay >= first_forecast_month:
            pay_dates.append(next_pay)
        next_pay += timedelta(days=14)
    pays_by_month: dict[date, int] = defaultdict(int)
    for pay_date in pay_dates:
        pays_by_month[_month_start(pay_date)] += 1

    gross_per_paycheck = money(latest.base_salary / Decimal("26"))
    observed_gross = latest.gross_earnings
    tax_rate = latest.tax_withholdings / observed_gross if observed_gross else ZERO

    def latest_line_total(*categories: str) -> Decimal:
        values = list(
            session.scalars(
                select(PayrollLineItem.amount).where(
                    PayrollLineItem.statement_id == latest.id,
                    PayrollLineItem.category.in_(categories),
                )
            )
        )
        return money(sum(values, ZERO))

    def latest_line_ytd(*categories: str) -> Decimal:
        values = list(
            session.scalars(
                select(PayrollLineItem.ytd_amount).where(
                    PayrollLineItem.statement_id == latest.id,
                    PayrollLineItem.category.in_(categories),
                    PayrollLineItem.ytd_amount.is_not(None),
                )
            )
        )
        return money(sum((value for value in values if value is not None), ZERO))

    observed_retirement = latest_line_total("pretax.employee_retirement")
    observed_hsa = latest_line_total("pretax.employee_hsa")
    observed_stock_plan = latest_line_total("after_tax.employee_stock_purchase")
    observed_employer_retirement = latest_line_total("employer_benefit.employer_retirement")
    retirement_rate = observed_retirement / observed_gross if observed_gross else ZERO
    stock_plan_rate = observed_stock_plan / observed_gross if observed_gross else ZERO
    employer_gross_rate = observed_employer_retirement / observed_gross if observed_gross else ZERO
    incremental_employer_rate = scenario_input.employer_match_pct / Decimal("100")
    aggregate_other_per_paycheck = money(
        latest.pretax_deductions
        + latest.after_tax_deductions
        + latest.imputed_earnings
        - observed_retirement
        - observed_hsa
        - observed_stock_plan
    )
    observed_outflow, outflow_months = _observed_monthly_outflow(session, today)
    monthly_outflow = (
        scenario_input.monthly_outflow
        if scenario_input.monthly_outflow is not None
        else observed_outflow
    )
    observed_checking_split, checking_split_source = _observed_checking_split(session, latest)
    checking_split_pct = (
        scenario_input.checking_split_pct
        if scenario_input.checking_split_pct is not None
        else observed_checking_split
    )
    employer_hsa_per_paycheck = latest_line_total("employer_benefit.employer_hsa")
    hsa_per_paycheck = (
        scenario_input.hsa_per_paycheck
        if scenario_input.hsa_per_paycheck is not None
        else observed_hsa
    )
    checking_balance = (
        scenario_input.opening_checking
        if scenario_input.opening_checking is not None
        else _latest_cash_balance(session, "checking")
    )
    savings_balance = (
        scenario_input.opening_savings
        if scenario_input.opening_savings is not None
        else _latest_cash_balance(session, "savings")
    )

    existing_scenarios = list(
        session.scalars(
            select(ForecastScenario).where(ForecastScenario.name == scenario_input.name)
        )
    )
    for existing_scenario in existing_scenarios:
        session.delete(existing_scenario)
    session.flush()
    scenario = ForecastScenario(
        name=scenario_input.name,
        is_baseline=is_baseline,
        inputs={key: _serialize_input(value) for key, value in scenario_input.model_dump().items()}
        | {
            "annual_salary": str(latest.base_salary),
            "pay_schedule_anchor": str(pay_schedule_anchor),
            "observed_retirement_pct": str(money(retirement_rate * Decimal("100"))),
            "observed_stock_plan_pct": str(money(stock_plan_rate * Decimal("100"))),
            "forecast_version": FORECAST_VERSION,
            "baseline_fingerprint": _baseline_fingerprint(session, today) if is_baseline else None,
            "outflow_months": outflow_months,
            "monthly_outflow_effective": str(monthly_outflow),
            "monthly_outflow_source": (
                "manual scenario input"
                if scenario_input.monthly_outflow is not None
                else "complete observed cash months"
            ),
            "checking_split_pct_effective": str(checking_split_pct),
            "checking_split_source": (
                "manual scenario input"
                if scenario_input.checking_split_pct is not None
                else checking_split_source
            ),
        },
    )
    session.add(scenario)
    session.flush()

    annual_contributions: dict[int, Decimal] = defaultdict(lambda: ZERO)
    annual_total_additions: dict[int, Decimal] = defaultdict(lambda: ZERO)
    if first_forecast_month.year == latest.payment_date.year:
        annual_contributions[first_forecast_month.year] = latest_line_ytd(
            "pretax.employee_retirement"
        )
        annual_total_additions[first_forecast_month.year] = money(
            annual_contributions[first_forecast_month.year]
            + latest_line_ytd("employer_benefit.employer_retirement")
        )
    initial_cash = checking_balance + savings_balance
    lowest_cash = initial_cash
    total_additional_fidelity = ZERO
    annual_return = scenario_input.annual_return_pct / Decimal("100")
    monthly_return = annual_return / Decimal("12")
    projected_investment_value = _latest_investment_balance(session)

    for month in months:
        pay_count = pays_by_month[month]
        gross = money(gross_per_paycheck * pay_count)
        if scenario_input.bonus_month and _month_start(scenario_input.bonus_month) == month:
            gross = money(gross + scenario_input.bonus_amount)
        baseline_retirement = money(gross * retirement_rate)
        additional_retirement = money(gross * scenario_input.additional_401k_pct / Decimal("100"))
        retirement = money(baseline_retirement + additional_retirement)
        baseline_stock_plan = money(gross * stock_plan_rate)
        additional_stock_plan = money(gross * scenario_input.stock_plan_pct / Decimal("100"))
        stock_plan = money(baseline_stock_plan + additional_stock_plan)
        baseline_employer = money(gross * employer_gross_rate)
        additional_employer = money(additional_retirement * incremental_employer_rate)
        employer = money(baseline_employer + additional_employer)
        employee_hsa = money(hsa_per_paycheck * pay_count)
        employer_hsa = money(employer_hsa_per_paycheck * pay_count)
        benefits_and_other = money(aggregate_other_per_paycheck * pay_count)
        baseline_taxes = money(gross * tax_rate)
        estimated_tax_reduction = money(additional_retirement * tax_rate)
        taxes = max(ZERO, money(baseline_taxes - estimated_tax_reduction))
        net_to_sofi = max(
            ZERO,
            money(gross - benefits_and_other - taxes - retirement - employee_hsa - stock_plan),
        )
        checking_deposit = money(net_to_sofi * checking_split_pct / Decimal("100"))
        savings_deposit = money(net_to_sofi - checking_deposit)
        checking_balance = money(checking_balance + checking_deposit - monthly_outflow)
        savings_balance = money(savings_balance + savings_deposit)
        ending_cash = money(checking_balance + savings_balance)
        cash_redirect = ZERO
        if (
            scenario_input.redirect_cash_above_floor
            and scenario_input.cash_floor > ZERO
            and ending_cash > scenario_input.cash_floor
        ):
            cash_redirect = money(ending_cash - scenario_input.cash_floor)
            from_savings = min(savings_balance, cash_redirect)
            savings_balance = money(savings_balance - from_savings)
            checking_balance = money(checking_balance - (cash_redirect - from_savings))
            ending_cash = money(checking_balance + savings_balance)
        lowest_cash = min(lowest_cash, ending_cash)
        new_investment_funding = money(retirement + stock_plan + employer + cash_redirect)
        assumed_result = money(
            (projected_investment_value + new_investment_funding / Decimal("2")) * monthly_return
        )
        projected_investment_value = money(
            projected_investment_value + new_investment_funding + assumed_result
        )
        annual_contributions[month.year] += retirement
        annual_total_additions[month.year] += retirement + employer
        total_additional_fidelity += (
            additional_retirement + additional_stock_plan + additional_employer + cash_redirect
        )
        scenario.periods.append(
            ForecastPeriod(
                month=month,
                gross_pay=gross,
                taxes=taxes,
                benefits_and_other=benefits_and_other,
                employee_retirement=retirement,
                employee_hsa=employee_hsa,
                stock_plan=stock_plan,
                employer_retirement=employer,
                employer_hsa=employer_hsa,
                sofi_checking=checking_deposit,
                sofi_savings=savings_deposit,
                external_outflow=monthly_outflow,
                ending_checking=checking_balance,
                ending_savings=savings_balance,
                ending_cash=ending_cash,
                cash_redirect_to_investments=cash_redirect,
                assumed_investment_result=assumed_result,
            )
        )

    limit_warnings: list[str] = []
    limits = _contribution_limits(runtime_settings)
    for year, contribution in annual_contributions.items():
        year_config = limits.get(str(year))
        if year_config is None:
            limit_warnings.append(
                f"No contribution-limit configuration is stored for {year}; verify before use."
            )
            continue
        if contribution > Decimal(year_config["employee_401k"]):
            limit_warnings.append(
                f"{year} modeled employee 401(k) contributions exceed the configured limit."
            )
        if annual_total_additions[year] > Decimal(year_config["defined_contribution_total"]):
            limit_warnings.append(
                f"{year} modeled employee plus employer additions exceed the configured limit."
            )

    assumption_warnings = [
        "Tax changes use the latest observed withholding ratio; this is not a tax-return estimate.",
        "Investment returns are optional scenarios, not predictions, and remain separate "
        "from contributions.",
    ]
    if latest.detail_complete:
        assumption_warnings.insert(
            0,
            "Current 401(k), stock-plan, employer contribution, benefit, and "
            "early-deposit cadence "
            "use the latest detailed payslip as the forecast baseline.",
        )
    else:
        assumption_warnings.insert(
            0,
            "Page 2 payroll detail is missing, so current 401(k), stock-plan, and benefit "
            "components are not inferred from aggregate deductions.",
        )
    if (
        scenario_input.opening_checking is None
        and scenario_input.opening_savings is None
        and initial_cash == ZERO
    ):
        assumption_warnings.append(
            "No SoFi closing or connected current balances are available; cash starts from "
            "the supplied/default zero."
        )
    if monthly_outflow == ZERO:
        assumption_warnings.append(
            "No SoFi outflow history or manual outflow was supplied; projected outflow is zero."
        )
    elif scenario_input.monthly_outflow is None:
        assumption_warnings.append(
            f"Monthly outflow is {monthly_outflow:,.2f}, averaged from {len(outflow_months)} "
            f"complete observed cash month{'s' if len(outflow_months) != 1 else ''}: "
            f"{', '.join(outflow_months)}."
        )
    if scenario_input.checking_split_pct is None:
        assumption_warnings.append(
            f"Net SoFi deposits use {checking_split_pct:.2f}% checking and "
            f"{Decimal('100') - checking_split_pct:.2f}% savings from the "
            f"{checking_split_source}."
        )
    if lowest_cash < ZERO:
        assumption_warnings.append(
            "Projected cash falls below zero; this baseline is a warning, not a viable plan."
        )
    if scenario_input.cash_floor and lowest_cash < scenario_input.cash_floor:
        assumption_warnings.append("Projected cash falls below the selected cash floor.")
    if scenario_input.additional_401k_pct and not scenario_input.employer_match_pct:
        assumption_warnings.append(
            "Employer contributions stay at the observed baseline because no incremental "
            "match formula was supplied."
        )

    scenario.inputs = scenario.inputs | {
        "assumption_warnings": assumption_warnings,
        "contribution_limit_warnings": limit_warnings,
    }
    session.commit()
    return ForecastSummary(
        scenario_id=scenario.id,
        name=scenario.name,
        start_month=months[0],
        end_month=months[-1],
        annual_salary=latest.base_salary,
        additional_fidelity_funding=money(total_additional_fidelity),
        lowest_projected_cash=money(lowest_cash),
        contribution_limit_warnings=limit_warnings,
        assumption_warnings=assumption_warnings,
    )


def ensure_baseline(
    session: Session,
    runtime_settings: Settings = settings,
    *,
    as_of: date | None = None,
) -> ForecastSummary:
    today = as_of or date.today()
    current_fingerprint = _baseline_fingerprint(session, today)
    baseline = session.scalar(
        select(ForecastScenario).where(ForecastScenario.is_baseline.is_(True)).limit(1)
    )
    if (
        baseline is not None
        and baseline.inputs.get("forecast_version") == FORECAST_VERSION
        and baseline.inputs.get("baseline_fingerprint") == current_fingerprint
        and "assumption_warnings" in baseline.inputs
        and baseline.periods
    ):
        periods = sorted(baseline.periods, key=lambda item: item.month)
        return ForecastSummary(
            scenario_id=baseline.id,
            name=baseline.name,
            start_month=periods[0].month,
            end_month=periods[-1].month,
            annual_salary=Decimal(str(baseline.inputs.get("annual_salary", "0"))),
            additional_fidelity_funding=sum(
                (
                    period.employee_retirement + period.employer_retirement + period.stock_plan
                    for period in periods
                ),
                ZERO,
            ),
            lowest_projected_cash=min(period.ending_cash for period in periods),
            contribution_limit_warnings=list(
                baseline.inputs.get("contribution_limit_warnings", [])
            ),
            assumption_warnings=list(baseline.inputs.get("assumption_warnings", [])),
        )
    session.execute(delete(ForecastScenario))
    session.flush()
    session.expunge_all()
    return build_forecast(
        session,
        ScenarioInput(name="No-change baseline"),
        runtime_settings,
        is_baseline=True,
        as_of=today,
    )
