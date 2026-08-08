from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .forecasting import _observed_monthly_outflow
from .models import (
    Account,
    BalanceSnapshot,
    Institution,
    InvestmentHolding,
    LifeGoal,
    LifePlanProfile,
    LifeProjectionPeriod,
    LifeScenario,
    PayrollAllocation,
    PayrollScheduleEntry,
    utcnow,
)
from .money import ZERO, money
from .services import _account_category, _investment_access

ENGINE_VERSION = "life-lab-v0.3.0"
ASSUMPTION_VERSION = "life-lab-drive-paths-v3"
RETIREMENT_ACCESS_AGE_MONTHS = 59 * 12 + 6
PAYCHECKS_PER_YEAR = Decimal("26")
MONTHS_PER_YEAR = Decimal("12")
BENCHMARK_PATH = Path(__file__).resolve().parent / "data" / "income_benchmarks.json"

PATHS: dict[str, dict[str, Decimal | int | str]] = {
    "middle": {
        "label": "Middle path",
        "annual_real_return_pct": Decimal("4.00"),
    },
    "rough": {
        "label": "Rough path",
        "annual_real_return_pct": Decimal("2.00"),
    },
    "early_crash": {
        "label": "Early-crash path",
        "pre_stop_annual_real_return_pct": Decimal("4.00"),
        "crash_pct": Decimal("-35.00"),
        "flat_months": 24,
        "later_annual_real_return_pct": Decimal("3.00"),
    },
}


def _decimal_fields(*names: str) -> Any:
    return field_validator(*names, mode="before")(_decimal_from_text)


def _decimal_from_text(value: object) -> object:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


class LifePlanProfileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    birth_date: date
    state: str = Field(min_length=2, max_length=2)
    end_age: int = Field(default=95, ge=40, le=120)
    current_monthly_outflow: Decimal = Field(default=ZERO, ge=0)
    essential_monthly_spend: Decimal = Field(default=ZERO, ge=0)
    flexible_monthly_spend: Decimal = Field(default=ZERO, ge=0)
    cash_floor: Decimal = Field(default=ZERO, ge=0)
    retirement_tax_rate_pct: Decimal = Field(default=Decimal("20"), ge=0, le=60)
    target_ages: list[int] = Field(min_length=1, max_length=8)
    notes: str = Field(default="", max_length=500)

    _money_values = _decimal_fields(
        "current_monthly_outflow",
        "essential_monthly_spend",
        "flexible_monthly_spend",
        "cash_floor",
        "retirement_tax_rate_pct",
    )

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("State must be a two-letter postal abbreviation")
        return normalized

    @field_validator("target_ages")
    @classmethod
    def unique_target_ages(cls, value: list[int]) -> list[int]:
        if any(age < 18 or age > 110 for age in value):
            raise ValueError("Target ages must be between 18 and 110")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_age_ordering(self) -> LifePlanProfileInput:
        current_age = _age_months(self.birth_date, date.today()) // 12
        if current_age < 18 or current_age > 100:
            raise ValueError("Birth date must produce a current age between 18 and 100")
        if self.end_age <= current_age:
            raise ValueError("Plan end age must be after the current age")
        if any(age <= current_age or age >= self.end_age for age in self.target_ages):
            raise ValueError("Target ages must be after the current age and before the end age")
        return self


class LifeGoalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    target_date: date
    target_amount: Decimal = Field(ge=0)
    reserved_amount: Decimal = Field(default=ZERO, ge=0)
    annual_cost: Decimal = Field(default=ZERO, ge=0)
    priority: Literal["required", "flexible"] = "required"
    enabled: bool = True
    notes: str = Field(default="", max_length=500)

    _money_values = _decimal_fields("target_amount", "reserved_amount", "annual_cost")


class ProjectionRequest(BaseModel):
    target_ages: list[int] | None = Field(default=None, max_length=8)

    @field_validator("target_ages")
    @classmethod
    def normalize_target_ages(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("Select at least one target age")
        if any(age < 18 or age > 110 for age in value):
            raise ValueError("Target ages must be between 18 and 110")
        return sorted(set(value))


class ScenarioSaveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    target_age: int = Field(ge=18, le=110)
    path_key: Literal["middle", "rough", "early_crash"] = "middle"


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _age_months(birth_date: date, value: date) -> int:
    months = (value.year - birth_date.year) * 12 + value.month - birth_date.month
    if value.day < birth_date.day:
        months -= 1
    return months


def _month_for_age(birth_date: date, age: int) -> date:
    return date(birth_date.year + age, birth_date.month, 1)


def _monthly_rate(annual_pct: Decimal) -> Decimal:
    annual = float(annual_pct / Decimal("100"))
    return Decimal(str((1.0 + annual) ** (1.0 / 12.0) - 1.0))


def _latest_balance(session: Session, account_id: int) -> BalanceSnapshot | None:
    return session.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.snapshot_date.desc(), BalanceSnapshot.id.desc())
        .limit(1)
    )


def _allocation_total(allocations: list[PayrollAllocation], category: str) -> Decimal:
    return money(sum((row.amount for row in allocations if row.category == category), ZERO))


def starting_point(session: Session, *, as_of: date | None = None) -> dict[str, Any]:
    today = as_of or date.today()
    cash = ZERO
    accessible = ZERO
    retirement = ZERO
    hsa = ZERO
    restricted = ZERO
    debt = ZERO
    source_dates: list[date] = []
    warnings: list[str] = []
    account_rows: list[dict[str, Any]] = []

    pairs = list(session.execute(select(Account, Institution).join(Institution)))
    for account, institution in pairs:
        latest = _latest_balance(session, account.id)
        if latest is None:
            continue
        source_dates.append(latest.snapshot_date)
        current = latest.amount
        category = _account_category(account, institution)
        account_type = account.account_type.strip().lower().replace("_", " ")
        status = "unverified"
        value = current
        if category == "debt":
            debt += abs(current)
            status = "debt"
        elif category == "cash" and account_type in {"checking", "savings"}:
            cash += current
            status = "accessible"
        elif category == "investment":
            holdings = list(
                session.scalars(
                    select(InvestmentHolding).where(InvestmentHolding.account_id == account.id)
                )
            )
            accessible_value, excluded_value, access_status, access_reason = _investment_access(
                account, current, holdings
            )
            accessible += accessible_value
            status = access_status
            if account_type == "hsa":
                hsa += excluded_value
            elif access_status == "retirement":
                retirement += excluded_value
            else:
                restricted += excluded_value
            if access_status == "review":
                warnings.append(
                    f"{account.display_name} is excluded because accessibility is not confirmed."
                )
            account_rows.append(
                {
                    "name": account.display_name,
                    "type": account.account_type,
                    "value": str(money(value)),
                    "access_status": access_status,
                    "access_reason": access_reason,
                    "as_of": latest.snapshot_date,
                    "provenance": "observed",
                }
            )
            continue
        account_rows.append(
            {
                "name": account.display_name,
                "type": account.account_type,
                "value": str(money(value)),
                "access_status": status,
                "access_reason": "Latest connected balance",
                "as_of": latest.snapshot_date,
                "provenance": "observed",
            }
        )

    latest_paycheck = session.scalar(
        select(PayrollScheduleEntry)
        .order_by(PayrollScheduleEntry.observed_deposit_date.desc())
        .limit(1)
    )
    payroll: dict[str, Any] | None = None
    if latest_paycheck is not None:
        allocations = list(
            session.scalars(
                select(PayrollAllocation).where(
                    PayrollAllocation.schedule_entry_id == latest_paycheck.id
                )
            )
        )
        payroll = {
            "payment_date": latest_paycheck.payment_date,
            "observed_deposit_date": latest_paycheck.observed_deposit_date,
            "annual_salary": str(money(latest_paycheck.base_salary)),
            "gross_per_paycheck": str(money(latest_paycheck.gross_earnings)),
            "net_per_paycheck": str(money(latest_paycheck.net_payment)),
            "employee_retirement_per_paycheck": str(
                _allocation_total(allocations, "pretax.employee_retirement")
            ),
            "employer_retirement_per_paycheck": str(
                _allocation_total(allocations, "employer_benefit.employer_retirement")
            ),
            "employee_hsa_per_paycheck": str(_allocation_total(allocations, "pretax.employee_hsa")),
            "employer_hsa_per_paycheck": str(
                _allocation_total(allocations, "employer_benefit.employer_hsa")
            ),
            "stock_plan_per_paycheck": str(
                _allocation_total(allocations, "after_tax.employee_stock_purchase")
            ),
            "provenance": "observed",
        }
    else:
        warnings.append("No completed detailed payroll is available for recurring income.")

    observed_outflow, outflow_months = _observed_monthly_outflow(session, today)
    if observed_outflow == ZERO:
        warnings.append("No complete observed cash months are available for an outflow suggestion.")
    warnings.extend(
        [
            "All retirement accounts are modeled as pretax because tax character is not confirmed.",
            "Projected stock-plan contributions are treated as accessible and may require "
            "a vesting review.",
            "Debt payoff schedules and interest are not modeled in Life Lab v0.1.",
        ]
    )
    return {
        "as_of": max(source_dates, default=today),
        "cash": str(money(cash)),
        "accessible_investments": str(money(accessible)),
        "pretax_retirement": str(money(retirement)),
        "hsa": str(money(hsa)),
        "restricted_assets": str(money(restricted)),
        "debt": str(money(debt)),
        "accessible_total": str(money(cash + accessible)),
        "tracked_total": str(money(cash + accessible + retirement + hsa + restricted)),
        "observed_monthly_outflow": str(observed_outflow),
        "outflow_months": outflow_months,
        "payroll": payroll,
        "accounts": account_rows,
        "warnings": warnings,
    }


def load_benchmarks(
    state: str | None = None, current_income: Decimal | None = None
) -> dict[str, Any]:
    if not BENCHMARK_PATH.exists():
        return {
            "available": False,
            "state": state,
            "warning": "The public income benchmark artifact is unavailable.",
        }
    artifact = cast(dict[str, Any], json.loads(BENCHMARK_PATH.read_text(encoding="utf-8")))
    states = cast(dict[str, dict[str, Any]], artifact["states"])
    state_row = states.get(state.upper()) if state else None
    result: dict[str, Any] = {
        "available": state_row is not None,
        "version": artifact["version"],
        "definition": artifact["definition"],
        "source_year": artifact["source_year"],
        "normalized_dollar_basis": artifact["normalized_dollar_basis"],
        "sources": artifact["sources"],
        "state": state.upper() if state else None,
        "state_name": state_row.get("name") if state_row else None,
        "thresholds": state_row.get("thresholds", {}) if state_row else {},
        "current_income": str(money(current_income)) if current_income is not None else None,
        "current_income_context": None,
        "warning": (
            "Salary is compared with tax-return AGI thresholds only as context; "
            "the definitions differ."
            if state_row
            else "No benchmark is stored for the selected state."
        ),
    }
    if state_row and current_income is not None:
        thresholds = cast(dict[str, dict[str, str]], state_row["thresholds"])
        for key in ("top_1", "top_5", "top_10", "top_25", "top_50"):
            if current_income >= Decimal(thresholds[key]["normalized_amount"]):
                result["current_income_context"] = key
                break
        if result["current_income_context"] is None:
            result["current_income_context"] = "below_top_50"
    return result


def get_profile(session: Session) -> LifePlanProfile | None:
    return session.scalar(select(LifePlanProfile).order_by(LifePlanProfile.id).limit(1))


def profile_dict(profile: LifePlanProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "birth_date": profile.birth_date,
        "state": profile.state,
        "end_age": profile.end_age,
        "current_monthly_outflow": str(profile.current_monthly_outflow),
        "essential_monthly_spend": str(profile.essential_monthly_spend),
        "flexible_monthly_spend": str(profile.flexible_monthly_spend),
        "cash_floor": str(profile.cash_floor),
        "retirement_tax_rate_pct": str(profile.retirement_tax_rate_pct),
        "target_ages": profile.target_ages,
        "notes": profile.notes,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "provenance": {
            "birth_date": "user_entered",
            "state": "user_entered",
            "end_age": "assumed",
            "current_monthly_outflow": "user_entered",
            "essential_monthly_spend": "user_entered",
            "flexible_monthly_spend": "user_entered",
            "cash_floor": "user_entered",
            "retirement_tax_rate_pct": "assumed",
            "target_ages": "user_entered",
        },
    }


def upsert_profile(session: Session, payload: LifePlanProfileInput) -> LifePlanProfile:
    profile = get_profile(session)
    values = payload.model_dump()
    if profile is None:
        profile = LifePlanProfile(**values)
        session.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
        profile.updated_at = utcnow()
    session.commit()
    session.refresh(profile)
    return profile


def goal_dict(goal: LifeGoal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "profile_id": goal.profile_id,
        "name": goal.name,
        "target_date": goal.target_date,
        "target_amount": str(goal.target_amount),
        "reserved_amount": str(goal.reserved_amount),
        "annual_cost": str(goal.annual_cost),
        "priority": goal.priority,
        "enabled": goal.enabled,
        "notes": goal.notes,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
        "provenance": "user_entered",
    }


def list_goals(session: Session, profile_id: int) -> list[LifeGoal]:
    return list(
        session.scalars(
            select(LifeGoal)
            .where(LifeGoal.profile_id == profile_id)
            .order_by(LifeGoal.target_date, LifeGoal.id)
        )
    )


def create_goal(session: Session, profile: LifePlanProfile, payload: LifeGoalInput) -> LifeGoal:
    goal = LifeGoal(profile_id=profile.id, **payload.model_dump())
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def update_goal(session: Session, goal: LifeGoal, payload: LifeGoalInput) -> LifeGoal:
    for key, value in payload.model_dump().items():
        setattr(goal, key, value)
    goal.updated_at = utcnow()
    session.commit()
    session.refresh(goal)
    return goal


def _profile_snapshot(profile: LifePlanProfile) -> dict[str, Any]:
    return {
        "birth_date": str(profile.birth_date),
        "state": profile.state,
        "end_age": profile.end_age,
        "current_monthly_outflow": str(profile.current_monthly_outflow),
        "essential_monthly_spend": str(profile.essential_monthly_spend),
        "flexible_monthly_spend": str(profile.flexible_monthly_spend),
        "cash_floor": str(profile.cash_floor),
        "retirement_tax_rate_pct": str(profile.retirement_tax_rate_pct),
        "target_ages": profile.target_ages,
        "notes": profile.notes,
    }


def _goal_snapshot(goal: LifeGoal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "name": goal.name,
        "target_date": str(goal.target_date),
        "target_amount": str(goal.target_amount),
        "reserved_amount": str(goal.reserved_amount),
        "annual_cost": str(goal.annual_cost),
        "priority": goal.priority,
        "enabled": goal.enabled,
        "notes": goal.notes,
    }


def _json_safe(value: Any) -> Any:
    """Round-trip projection snapshots into SQLite JSON-compatible primitives."""

    return json.loads(json.dumps(value, default=str))


def source_fingerprint(
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    start: dict[str, Any],
    benchmark_version: str,
) -> str:
    payload = {
        "engine_version": ENGINE_VERSION,
        "assumption_version": ASSUMPTION_VERSION,
        "benchmark_version": benchmark_version,
        "paths": {
            key: {inner_key: str(value) for inner_key, value in values.items()}
            for key, values in PATHS.items()
        },
        "profile": _profile_snapshot(profile),
        "goals": [_goal_snapshot(goal) for goal in goals],
        "starting_point": {
            key: start.get(key)
            for key in (
                "as_of",
                "cash",
                "accessible_investments",
                "pretax_retirement",
                "hsa",
                "restricted_assets",
                "debt",
                "observed_monthly_outflow",
                "payroll",
            )
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _path_monthly_rate(path_key: str, working: bool, months_after_stop: int) -> Decimal:
    config = PATHS[path_key]
    if path_key != "early_crash":
        return _monthly_rate(Decimal(str(config["annual_real_return_pct"])))
    if working:
        return _monthly_rate(Decimal(str(config["pre_stop_annual_real_return_pct"])))
    if months_after_stop <= int(config["flat_months"]):
        return ZERO
    return _monthly_rate(Decimal(str(config["later_annual_real_return_pct"])))


def _take_accessible(
    requested: Decimal,
    cash: Decimal,
    accessible: Decimal,
    cash_floor: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    remaining = money(requested)
    spendable_cash = max(ZERO, money(cash - cash_floor))
    from_cash = min(spendable_cash, remaining)
    cash = money(cash - from_cash)
    remaining = money(remaining - from_cash)
    from_accessible = min(accessible, remaining)
    accessible = money(accessible - from_accessible)
    remaining = money(remaining - from_accessible)
    return remaining, cash, accessible


def _take_retirement(
    requested: Decimal,
    retirement: Decimal,
    tax_rate_pct: Decimal,
) -> tuple[Decimal, Decimal]:
    if requested <= ZERO:
        return ZERO, retirement
    spendable_rate = Decimal("1") - tax_rate_pct / Decimal("100")
    if spendable_rate <= ZERO:
        return requested, retirement
    gross_needed = money(requested / spendable_rate)
    gross_taken = min(retirement, gross_needed)
    retirement = money(retirement - gross_taken)
    remaining = money(requested - money(gross_taken * spendable_rate))
    return max(ZERO, remaining), retirement


def _withdraw(
    requested: Decimal,
    *,
    cash: Decimal,
    accessible: Decimal,
    retirement: Decimal,
    cash_floor: Decimal,
    age_months: int,
    tax_rate_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    remaining, cash, accessible = _take_accessible(requested, cash, accessible, cash_floor)
    if remaining > ZERO and age_months >= RETIREMENT_ACCESS_AGE_MONTHS:
        remaining, retirement = _take_retirement(remaining, retirement, tax_rate_pct)
    return remaining, cash, accessible, retirement


def _period_dict(period: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Decimal) else value for key, value in period.items()
    }


def _simulate(
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    start: dict[str, Any],
    *,
    target_age: int,
    path_key: str,
    as_of: date,
    extra_monthly_saving: Decimal = ZERO,
    additional_monthly_income: Decimal = ZERO,
    liquidity_event: Decimal = ZERO,
    liquidity_event_month: date | None = None,
    flexible_spend_override: Decimal | None = None,
    include_periods: bool = True,
    assessment_start_month: date | None = None,
) -> dict[str, Any]:
    cash = Decimal(str(start["cash"]))
    accessible = Decimal(str(start["accessible_investments"]))
    retirement = Decimal(str(start["pretax_retirement"]))
    hsa = Decimal(str(start["hsa"]))
    restricted = Decimal(str(start["restricted_assets"]))
    debt = Decimal(str(start["debt"]))
    payroll = cast(dict[str, Any] | None, start["payroll"])
    if payroll is None:
        monthly_gross = ZERO
        monthly_net = ZERO
        employee_retirement = ZERO
        employer_retirement = ZERO
        employee_hsa = ZERO
        employer_hsa = ZERO
        stock_plan = ZERO
    else:
        monthly_gross = money(Decimal(str(payroll["annual_salary"])) / MONTHS_PER_YEAR)
        monthly_net = money(
            Decimal(str(payroll["net_per_paycheck"])) * PAYCHECKS_PER_YEAR / MONTHS_PER_YEAR
        )
        employee_retirement = money(
            Decimal(str(payroll["employee_retirement_per_paycheck"]))
            * PAYCHECKS_PER_YEAR
            / MONTHS_PER_YEAR
        )
        employer_retirement = money(
            Decimal(str(payroll["employer_retirement_per_paycheck"]))
            * PAYCHECKS_PER_YEAR
            / MONTHS_PER_YEAR
        )
        employee_hsa = money(
            Decimal(str(payroll["employee_hsa_per_paycheck"]))
            * PAYCHECKS_PER_YEAR
            / MONTHS_PER_YEAR
        )
        employer_hsa = money(
            Decimal(str(payroll["employer_hsa_per_paycheck"]))
            * PAYCHECKS_PER_YEAR
            / MONTHS_PER_YEAR
        )
        stock_plan = money(
            Decimal(str(payroll["stock_plan_per_paycheck"])) * PAYCHECKS_PER_YEAR / MONTHS_PER_YEAR
        )

    enabled_goals = [goal for goal in goals if goal.enabled]
    first_month = _month_start(as_of)
    end_month = _month_for_age(profile.birth_date, profile.end_age)
    stop_month = _month_for_age(profile.birth_date, target_age)
    month = first_month
    periods: list[dict[str, Any]] = []
    last_period: dict[str, Any] | None = None
    required_failed = False
    flexible_failed = False
    bridge_failed = False
    first_shortfall: date | None = None
    goal_results: dict[int, dict[str, Any]] = {
        goal.id: {"funded": True, "shortfall": ZERO} for goal in enabled_goals
    }
    months_after_stop = 0
    crash_applied = False
    work_stop_assets: dict[str, Decimal] | None = None

    def fund_due_goals(
        priority: str,
        rows: list[LifeGoal],
        age: int,
        current_month: date,
        current_cash: Decimal,
        current_accessible: Decimal,
        current_retirement: Decimal,
        current_goal_spend: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal, bool, bool, bool, date | None]:
        required_failure = False
        flexible_failure = False
        bridge_failure = False
        failure_month: date | None = None
        for goal in (row for row in rows if row.priority == priority):
            remaining, current_cash, current_accessible, current_retirement = _withdraw(
                goal.target_amount,
                cash=current_cash,
                accessible=current_accessible,
                retirement=current_retirement,
                cash_floor=profile.cash_floor,
                age_months=age,
                tax_rate_pct=profile.retirement_tax_rate_pct,
            )
            funded = money(goal.target_amount - remaining)
            current_goal_spend += funded
            goal_results[goal.id] = {"funded": remaining == ZERO, "shortfall": remaining}
            counts_toward_result = (
                assessment_start_month is None or current_month >= assessment_start_month
            )
            if remaining > ZERO and priority == "required" and counts_toward_result:
                required_failure = True
                failure_month = current_month
                if age < RETIREMENT_ACCESS_AGE_MONTHS and current_retirement > ZERO:
                    bridge_failure = True
            elif remaining > ZERO and counts_toward_result:
                flexible_failure = True
        return (
            current_cash,
            current_accessible,
            current_retirement,
            current_goal_spend,
            required_failure,
            flexible_failure,
            bridge_failure,
            failure_month,
        )

    while month <= end_month:
        age_months = _age_months(profile.birth_date, month)
        working = month < stop_month
        if month == (liquidity_event_month or stop_month):
            accessible = money(accessible + liquidity_event)
        if not working:
            months_after_stop += 1
            if work_stop_assets is None:
                work_stop_assets = {
                    "cash": cash,
                    "accessible_investments": accessible,
                    "accessible_total": money(cash + accessible),
                    "pretax_retirement": retirement,
                    "hsa": hsa,
                    "restricted_assets": restricted,
                }

        investment_result = ZERO
        if path_key == "early_crash" and not working and not crash_applied:
            crash_rate = Decimal(str(PATHS[path_key]["crash_pct"])) / Decimal("100")
            for bucket_name, value in (
                ("accessible", accessible),
                ("retirement", retirement),
                ("hsa", hsa),
                ("restricted", restricted),
            ):
                result = money(value * crash_rate)
                investment_result += result
                if bucket_name == "accessible":
                    accessible = money(accessible + result)
                elif bucket_name == "retirement":
                    retirement = money(retirement + result)
                elif bucket_name == "hsa":
                    hsa = money(hsa + result)
                else:
                    restricted = money(restricted + result)
            crash_applied = True

        gross_income = monthly_gross if working else ZERO
        net_income = monthly_net if working else ZERO
        retirement_added = employee_retirement if working else ZERO
        employer_added = employer_retirement if working else ZERO
        stock_added = stock_plan if working else ZERO
        hsa_added = money(employee_hsa + employer_hsa) if working else ZERO
        retirement = money(retirement + retirement_added + employer_added)
        hsa = money(hsa + hsa_added)
        accessible = money(accessible + stock_added)

        essential_spend = ZERO
        flexible_spend = ZERO
        goal_spend = ZERO
        due_goals = [goal for goal in enabled_goals if _month_start(goal.target_date) == month]

        if working:
            effective_outflow = max(
                ZERO, money(profile.current_monthly_outflow - extra_monthly_saving)
            )
            cash = money(cash + net_income + additional_monthly_income)
            remaining, cash, accessible, retirement = _withdraw(
                effective_outflow,
                cash=cash,
                accessible=accessible,
                retirement=retirement,
                cash_floor=profile.cash_floor,
                age_months=age_months,
                tax_rate_pct=profile.retirement_tax_rate_pct,
            )
            essential_spend = money(effective_outflow - remaining)
            counts_toward_result = assessment_start_month is None or month >= assessment_start_month
            if remaining > ZERO and counts_toward_result:
                required_failed = True
                first_shortfall = first_shortfall or month
            if cash > profile.cash_floor:
                accessible = money(accessible + cash - profile.cash_floor)
                cash = money(profile.cash_floor)
            for priority in ("required", "flexible"):
                (
                    cash,
                    accessible,
                    retirement,
                    goal_spend,
                    required_failure,
                    flexible_failure,
                    bridge_failure,
                    failure_month,
                ) = fund_due_goals(
                    priority,
                    due_goals,
                    age_months,
                    month,
                    cash,
                    accessible,
                    retirement,
                    goal_spend,
                )
                required_failed = required_failed or required_failure
                flexible_failed = flexible_failed or flexible_failure
                bridge_failed = bridge_failed or bridge_failure
                first_shortfall = first_shortfall or failure_month
        else:
            continuing_required = money(
                sum(
                    (
                        goal.annual_cost / MONTHS_PER_YEAR
                        for goal in enabled_goals
                        if goal.priority == "required" and month >= _month_start(goal.target_date)
                    ),
                    ZERO,
                )
            )
            continuing_flexible = money(
                sum(
                    (
                        goal.annual_cost / MONTHS_PER_YEAR
                        for goal in enabled_goals
                        if goal.priority == "flexible" and month >= _month_start(goal.target_date)
                    ),
                    ZERO,
                )
            )
            requested_essential = money(profile.essential_monthly_spend + continuing_required)
            remaining, cash, accessible, retirement = _withdraw(
                requested_essential,
                cash=cash,
                accessible=accessible,
                retirement=retirement,
                cash_floor=profile.cash_floor,
                age_months=age_months,
                tax_rate_pct=profile.retirement_tax_rate_pct,
            )
            essential_spend = money(requested_essential - remaining)
            if remaining > ZERO:
                required_failed = True
                first_shortfall = first_shortfall or month
                if age_months < RETIREMENT_ACCESS_AGE_MONTHS and retirement > ZERO:
                    bridge_failed = True

            # Required dated goals are funded before optional lifestyle spending.
            (
                cash,
                accessible,
                retirement,
                goal_spend,
                required_failure,
                flexible_failure,
                bridge_failure,
                failure_month,
            ) = fund_due_goals(
                "required",
                due_goals,
                age_months,
                month,
                cash,
                accessible,
                retirement,
                goal_spend,
            )
            required_failed = required_failed or required_failure
            flexible_failed = flexible_failed or flexible_failure
            bridge_failed = bridge_failed or bridge_failure
            first_shortfall = first_shortfall or failure_month
            requested_flexible = money(
                (
                    flexible_spend_override
                    if flexible_spend_override is not None
                    else profile.flexible_monthly_spend
                )
                + continuing_flexible
            )
            remaining, cash, accessible, retirement = _withdraw(
                requested_flexible,
                cash=cash,
                accessible=accessible,
                retirement=retirement,
                cash_floor=profile.cash_floor,
                age_months=age_months,
                tax_rate_pct=profile.retirement_tax_rate_pct,
            )
            flexible_spend = money(requested_flexible - remaining)
            if remaining > ZERO:
                flexible_failed = True
            (
                cash,
                accessible,
                retirement,
                goal_spend,
                required_failure,
                flexible_failure,
                bridge_failure,
                failure_month,
            ) = fund_due_goals(
                "flexible",
                due_goals,
                age_months,
                month,
                cash,
                accessible,
                retirement,
                goal_spend,
            )
            required_failed = required_failed or required_failure
            flexible_failed = flexible_failed or flexible_failure
            bridge_failed = bridge_failed or bridge_failure
            first_shortfall = first_shortfall or failure_month

        monthly_rate = _path_monthly_rate(path_key, working, months_after_stop)
        if monthly_rate != ZERO:
            for bucket_name, value in (
                ("accessible", accessible),
                ("retirement", retirement),
                ("hsa", hsa),
                ("restricted", restricted),
            ):
                result = money(value * monthly_rate)
                investment_result += result
                if bucket_name == "accessible":
                    accessible = money(accessible + result)
                elif bucket_name == "retirement":
                    retirement = money(retirement + result)
                elif bucket_name == "hsa":
                    hsa = money(hsa + result)
                else:
                    restricted = money(restricted + result)

        spendable_retirement = money(
            retirement * (Decimal("1") - profile.retirement_tax_rate_pct / Decimal("100"))
        )
        total_spendable = money(cash + accessible + spendable_retirement)
        last_period = {
            "month": month,
            "age_months": age_months,
            "working": working,
            "gross_income": gross_income,
            "net_income": net_income,
            "additional_income": additional_monthly_income if working else ZERO,
            "employee_retirement": retirement_added,
            "employer_retirement": employer_added,
            "stock_plan": stock_added,
            "essential_spend": essential_spend,
            "flexible_spend": flexible_spend,
            "goal_spend": money(goal_spend),
            "cash": cash,
            "accessible_investments": accessible,
            "pretax_retirement": retirement,
            "hsa": hsa,
            "restricted_assets": restricted,
            "debt": debt,
            "investment_result": money(investment_result),
            "total_spendable": total_spendable,
        }
        if include_periods:
            periods.append(last_period)
        month = _next_month(month)

    if required_failed:
        status = "insufficient_accessible_bridge" if bridge_failed else "shortfall"
    elif flexible_failed:
        status = "works_essentials_only"
    else:
        status = "works"
    if last_period is None:
        raise RuntimeError("Life Lab projection did not generate any monthly periods")
    last = last_period
    work_stop_assets = work_stop_assets or {
        "cash": cash,
        "accessible_investments": accessible,
        "accessible_total": money(cash + accessible),
        "pretax_retirement": retirement,
        "hsa": hsa,
        "restricted_assets": restricted,
    }
    return {
        "target_age": target_age,
        "path_key": path_key,
        "path_label": PATHS[path_key]["label"],
        "status": status,
        "first_shortfall_month": first_shortfall,
        "work_stop_month": stop_month,
        "work_stop_assets": {key: str(money(value)) for key, value in work_stop_assets.items()},
        "end_assets": {
            "cash": str(last["cash"]),
            "accessible_investments": str(last["accessible_investments"]),
            "pretax_retirement": str(last["pretax_retirement"]),
            "hsa": str(last["hsa"]),
            "restricted_assets": str(last["restricted_assets"]),
            "debt": str(last["debt"]),
            "total_spendable": str(last["total_spendable"]),
        },
        "goal_results": {
            str(goal_id): {
                "funded": result["funded"],
                "shortfall": str(result["shortfall"]),
            }
            for goal_id, result in goal_results.items()
        },
        "periods": [_period_dict(period) for period in periods],
    }


def _works(result: dict[str, Any]) -> bool:
    return str(result["status"]) == "works"


def _minimum_change(
    evaluate: Callable[[Decimal], dict[str, Any]],
    *,
    initial_high: Decimal = Decimal("1000"),
    max_doublings: int = 64,
) -> Decimal | None:
    """Reverse-solve a positive lever without imposing a user-facing plausibility cap."""

    if _works(evaluate(ZERO)):
        return ZERO
    low = ZERO
    high = money(initial_high)
    for _ in range(max_doublings):
        if _works(evaluate(high)):
            break
        low = high
        high = money(high * Decimal("2"))
    else:
        return None
    for _ in range(40):
        midpoint = money((low + high) / Decimal("2"))
        if _works(evaluate(midpoint)):
            high = midpoint
        else:
            low = midpoint
        if high - low <= Decimal("0.01"):
            break
    return money(high)


def _additional_income_needed(
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    start: dict[str, Any],
    target_age: int,
    path_key: str,
    as_of: date,
) -> Decimal | None:
    return _minimum_change(
        lambda amount: _simulate(
            profile,
            goals,
            start,
            target_age=target_age,
            path_key=path_key,
            as_of=as_of,
            additional_monthly_income=amount,
            include_periods=False,
        )
    )


def _retirement_capital_needed(
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    start: dict[str, Any],
    target_age: int,
    path_key: str,
    as_of: date,
) -> Decimal | None:
    stop_month = _month_for_age(profile.birth_date, target_age)
    return _minimum_change(
        lambda amount: _simulate(
            profile,
            goals,
            start,
            target_age=target_age,
            path_key=path_key,
            as_of=as_of,
            liquidity_event=amount,
            liquidity_event_month=stop_month,
            assessment_start_month=stop_month,
            include_periods=False,
        ),
        initial_high=Decimal("10000"),
    )


def _earliest_viable_age(
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    start: dict[str, Any],
    target_age: int,
    as_of: date,
) -> int | None:
    for age in range(target_age, profile.end_age):
        result = _simulate(
            profile,
            goals,
            start,
            target_age=age,
            path_key="middle",
            as_of=as_of,
            include_periods=False,
        )
        if _works(result):
            return age
    return None


def _assumptions() -> dict[str, Any]:
    return {
        "version": ASSUMPTION_VERSION,
        "today_dollars": True,
        "cash_real_return_pct": "0.00",
        "retirement_access_age": "59.5",
        "paths": {
            key: {inner: str(value) for inner, value in config.items()}
            for key, config in PATHS.items()
        },
        "omissions": [
            "Social Security",
            "Medicare and healthcare",
            "pensions",
            "required minimum distributions",
            "Roth conversions",
            "home equity",
            "debt payoff schedules",
            "early-withdrawal exceptions",
            "probability of success",
        ],
    }


def project_life_plan(
    session: Session,
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    *,
    target_ages: list[int] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    today = as_of or date.today()
    current_age = _age_months(profile.birth_date, today) // 12
    ages = target_ages or profile.target_ages
    if any(age <= current_age or age >= profile.end_age for age in ages):
        raise ValueError("Target ages must be after the current age and before the end age")
    start = starting_point(session, as_of=today)
    payroll = cast(dict[str, Any] | None, start["payroll"])
    current_income = Decimal(str(payroll["annual_salary"])) if payroll else None
    benchmarks = load_benchmarks(profile.state, current_income)
    benchmark_version = str(benchmarks.get("version", "unavailable"))
    fingerprint = source_fingerprint(profile, goals, start, benchmark_version)
    results: list[dict[str, Any]] = []
    middle_by_age: dict[int, dict[str, Any]] = {}
    for age in ages:
        path_results: list[dict[str, Any]] = []
        for path_key in PATHS:
            result = _simulate(
                profile,
                goals,
                start,
                target_age=age,
                path_key=path_key,
                as_of=today,
            )
            additional_income = _additional_income_needed(
                profile, goals, start, age, path_key, today
            )
            retirement_capital = _retirement_capital_needed(
                profile, goals, start, age, path_key, today
            )
            stop_month = cast(date, result["work_stop_month"])
            first_shortfall = cast(date | None, result["first_shortfall_month"])
            result["make_it_happen"] = {
                "additional_monthly_after_tax_income": (
                    str(additional_income) if additional_income is not None else None
                ),
                "retirement_capital_needed": (
                    str(retirement_capital) if retirement_capital is not None else None
                ),
                "retirement_deadline": stop_month,
                "pre_retirement_shortfall_month": (
                    first_shortfall
                    if first_shortfall is not None and first_shortfall < stop_month
                    else None
                ),
            }
            path_results.append(result)
            if path_key == "middle":
                middle_by_age[age] = result
        results.append(
            {
                "target_age": age,
                "paths": path_results,
            }
        )

    goal_impacts: dict[str, list[dict[str, Any]]] = {}
    for age in ages:
        with_goals = middle_by_age[age]
        impacts: list[dict[str, Any]] = []
        with_viable = _earliest_viable_age(profile, goals, start, age, today)
        for goal in (row for row in goals if row.enabled):
            without = [row for row in goals if row.id != goal.id]
            without_result = _simulate(
                profile,
                without,
                start,
                target_age=age,
                path_key="middle",
                as_of=today,
                include_periods=False,
            )
            without_viable = _earliest_viable_age(profile, without, start, age, today)
            months_until = max(
                1,
                (goal.target_date.year - today.year) * 12 + goal.target_date.month - today.month,
            )
            remaining_target = max(ZERO, money(goal.target_amount - goal.reserved_amount))
            impacts.append(
                {
                    "goal_id": goal.id,
                    "name": goal.name,
                    "required_monthly_saving": str(money(remaining_target / Decimal(months_until))),
                    "cash_funded": with_goals["goal_results"]
                    .get(str(goal.id), {})
                    .get("funded", False),
                    "end_asset_change": str(
                        money(
                            Decimal(with_goals["end_assets"]["total_spendable"])
                            - Decimal(without_result["end_assets"]["total_spendable"])
                        )
                    ),
                    "first_shortfall_with_goal": with_goals["first_shortfall_month"],
                    "first_shortfall_without_goal": without_result["first_shortfall_month"],
                    "creates_bridge_failure": (
                        with_goals["status"] == "insufficient_accessible_bridge"
                        and without_result["status"] != "insufficient_accessible_bridge"
                    ),
                    "work_optional_delay_years": (
                        max(0, with_viable - without_viable)
                        if with_viable is not None and without_viable is not None
                        else None
                    ),
                }
            )
        goal_impacts[str(age)] = impacts

    warnings = list(cast(list[str], start["warnings"]))
    if profile.current_monthly_outflow == ZERO:
        warnings.append("Current monthly outflow is zero; pre-work surplus may be overstated.")
    if profile.essential_monthly_spend == ZERO:
        warnings.append("Essential post-work spending is zero; success is not meaningful yet.")
    if Decimal(str(start["cash"])) < profile.cash_floor:
        warnings.append("Observed cash is currently below the protected cash floor.")
    warnings.append(
        "Life Lab is an assumption-driven planning model, not a tax return or investment forecast."
    )
    return {
        "engine_version": ENGINE_VERSION,
        "source_fingerprint": fingerprint,
        "generated_at": datetime.now(UTC),
        "as_of": today,
        "profile": profile_dict(profile),
        "starting_point": start,
        "benchmarks": benchmarks,
        "goals": [goal_dict(goal) for goal in goals],
        "assumptions": _assumptions(),
        "results": results,
        "goal_impacts": goal_impacts,
        "warnings": warnings,
    }


def save_scenario(
    session: Session,
    profile: LifePlanProfile,
    goals: list[LifeGoal],
    payload: ScenarioSaveInput,
    *,
    as_of: date | None = None,
) -> LifeScenario:
    projection = project_life_plan(
        session, profile, goals, target_ages=[payload.target_age], as_of=as_of
    )
    target = cast(dict[str, Any], projection["results"][0])
    selected = next(
        row
        for row in cast(list[dict[str, Any]], target["paths"])
        if row["path_key"] == payload.path_key
    )
    scenario = LifeScenario(
        profile_id=profile.id,
        name=payload.name,
        target_age=payload.target_age,
        path_key=payload.path_key,
        input_snapshot=_json_safe(
            {
                "profile": _profile_snapshot(profile),
                "goals": [_goal_snapshot(goal) for goal in goals],
                "starting_point": projection["starting_point"],
                "assumptions": projection["assumptions"],
            }
        ),
        source_fingerprint=str(projection["source_fingerprint"]),
        engine_version=ENGINE_VERSION,
        assumption_version=ASSUMPTION_VERSION,
        benchmark_version=str(projection["benchmarks"].get("version", "unavailable")),
        status=str(selected["status"]),
        warnings=cast(list[str], projection["warnings"]),
        summary=_json_safe({key: value for key, value in selected.items() if key != "periods"}),
    )
    session.add(scenario)
    session.flush()
    for period in cast(list[dict[str, Any]], selected["periods"]):
        scenario.periods.append(
            LifeProjectionPeriod(
                scenario_id=scenario.id,
                month=date.fromisoformat(str(period["month"])),
                age_months=int(period["age_months"]),
                working=bool(period["working"]),
                gross_income=Decimal(str(period["gross_income"])),
                net_income=Decimal(str(period["net_income"])),
                employee_retirement=Decimal(str(period["employee_retirement"])),
                employer_retirement=Decimal(str(period["employer_retirement"])),
                stock_plan=Decimal(str(period["stock_plan"])),
                essential_spend=Decimal(str(period["essential_spend"])),
                flexible_spend=Decimal(str(period["flexible_spend"])),
                goal_spend=Decimal(str(period["goal_spend"])),
                cash=Decimal(str(period["cash"])),
                accessible_investments=Decimal(str(period["accessible_investments"])),
                pretax_retirement=Decimal(str(period["pretax_retirement"])),
                hsa=Decimal(str(period["hsa"])),
                restricted_assets=Decimal(str(period["restricted_assets"])),
                debt=Decimal(str(period["debt"])),
                investment_result=Decimal(str(period["investment_result"])),
                total_spendable=Decimal(str(period["total_spendable"])),
            )
        )
    session.commit()
    session.refresh(scenario)
    return scenario


def scenario_dict(scenario: LifeScenario, current_fingerprint: str) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "target_age": scenario.target_age,
        "path_key": scenario.path_key,
        "status": scenario.status,
        "summary": scenario.summary,
        "warnings": scenario.warnings,
        "engine_version": scenario.engine_version,
        "assumption_version": scenario.assumption_version,
        "benchmark_version": scenario.benchmark_version,
        "source_fingerprint": scenario.source_fingerprint,
        "stale": scenario.source_fingerprint != current_fingerprint,
        "created_at": scenario.created_at,
        "periods": [
            {
                "month": period.month,
                "age_months": period.age_months,
                "working": period.working,
                "cash": str(period.cash),
                "accessible_investments": str(period.accessible_investments),
                "pretax_retirement": str(period.pretax_retirement),
                "total_spendable": str(period.total_spendable),
            }
            for period in sorted(scenario.periods, key=lambda row: row.month)
        ],
    }


def current_fingerprint(session: Session, profile: LifePlanProfile, goals: list[LifeGoal]) -> str:
    start = starting_point(session)
    benchmarks = load_benchmarks(profile.state)
    return source_fingerprint(profile, goals, start, str(benchmarks.get("version", "unavailable")))


def delete_goal(session: Session, goal: LifeGoal) -> None:
    session.delete(goal)
    session.commit()


def delete_scenario(session: Session, scenario: LifeScenario) -> None:
    session.delete(scenario)
    session.commit()


def clear_life_plan(session: Session) -> None:
    """Test helper for removing only Life Lab state."""

    session.execute(delete(LifePlanProfile))
    session.commit()
