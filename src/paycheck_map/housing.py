"""Versioned, assumption-only housing planning. Decimal arithmetic; no source mutations."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=14, decimal_places=2)]
ZERO = Decimal(0)
CENT = Decimal(".01")


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Cost(InputModel):
    name: str = Field(min_length=1, max_length=100)
    amount: Money | None = None
    due: date
    kind: Literal["expense", "deposit"] = "expense"
    returned: date | None = None

    @model_validator(mode="after")
    def valid_return(self) -> Cost:
        if self.returned and (self.kind != "deposit" or self.returned < self.due):
            raise ValueError("Only a refundable deposit can have a later return date.")
        return self


class HousingScenario(InputModel):
    name: str = Field(min_length=1, max_length=100)
    sale_price: Money | None = None
    payoff: Money | None = None
    selling_fees: Money | None = None
    sale_date: date
    funds_date: date
    move_date: date
    rent: Money | None = None
    rental_extras: Money | None = None
    costs: list[Cost] = Field(default_factory=list, max_length=40)
    costs_complete: bool = False
    notes: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def ordered(self) -> HousingScenario:
        if self.funds_date < self.sale_date:
            raise ValueError("Sale funds cannot be available before closing.")
        return self


class HousingInput(InputModel):
    contract_version: Literal["housing-input-v1"] = "housing-input-v1"
    name: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    target_date: date
    as_of: date
    end_date: date
    baseline_complete: bool = False
    baseline_notes: str = Field(default="", max_length=3000)
    condo_amount_meaning: Literal[
        "unknown", "purchase_price", "estimated_value", "mortgage_balance"
    ] = "unknown"
    condo_amount: Money | None = None
    cash: Money | None = None
    dedicated_cash: Money | None = None
    other_net_assets: (
        Annotated[Decimal, Field(ge=-1_000_000_000, le=1_000_000_000, decimal_places=2)] | None
    ) = None
    income: Money | None = None
    nonhousing: Money | None = None
    other_savings: Money | None = None
    home_value: Money | None = None
    mortgage_balance: Money | None = None
    mortgage_payment: Money | None = None
    principal_interest: Money | None = None
    annual_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | None = None
    owner_extras: Money | None = None
    reserve: Money | None = None
    monthly_set_aside: Money | None = None
    housing_costs_complete: bool = False
    scenarios: list[HousingScenario] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def consistent(self) -> HousingInput:
        if not self.as_of < self.end_date or (self.end_date - self.as_of).days > 3660:
            raise ValueError(
                "Choose a comparison period of up to ten years after the baseline date."
            )
        if (
            self.principal_interest is not None
            and self.mortgage_payment is not None
            and self.principal_interest > self.mortgage_payment
        ):
            raise ValueError("Principal and interest cannot exceed the total mortgage payment.")
        if (
            self.dedicated_cash is not None
            and self.cash is not None
            and self.dedicated_cash > self.cash
        ):
            raise ValueError("Dedicated cash must be part of current liquid cash.")
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Give each alternative a different name.")
        for s in self.scenarios:
            event_dates = [
                s.sale_date,
                s.move_date,
                s.funds_date,
                *(c.due for c in s.costs),
                *(c.returned for c in s.costs if c.returned),
            ]
            if any((day - self.as_of).days > 3660 for day in event_dates):
                raise ValueError("Keep scenario events within ten years of the baseline.")
            if min(s.sale_date, s.move_date, *(c.due for c in s.costs)) < self.as_of:
                raise ValueError("Future events must be on or after the baseline date.")
        return self


def amount(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def anniversary(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(start.day, calendar.monthrange(year, month + 1)[1]))


def evaluate(plan: HousingInput) -> dict[str, Any]:
    """Partial results remain available; all projections are conditional estimates."""
    return {
        "engine_version": "housing-v1",
        "as_of": plan.as_of,
        "end_date": plan.end_date,
        "scenarios": [evaluate_scenario(plan, s) for s in plan.scenarios],
    }


def evaluate_scenario(p: HousingInput, s: HousingScenario) -> dict[str, Any]:
    unknown = [
        key
        for key in (
            "cash",
            "dedicated_cash",
            "other_net_assets",
            "income",
            "nonhousing",
            "other_savings",
            "home_value",
            "mortgage_balance",
            "mortgage_payment",
            "principal_interest",
            "annual_rate",
            "owner_extras",
            "reserve",
            "monthly_set_aside",
        )
        if getattr(p, key) is None
    ]
    unknown += [
        key
        for key in ("sale_price", "payoff", "selling_fees", "rent", "rental_extras")
        if getattr(s, key) is None
    ]
    unknown += [f"cost: {c.name}" for c in s.costs if c.amount is None]
    warnings = []
    if not p.baseline_complete:
        warnings.append(
            "Baseline coverage has not been confirmed. Review Accounts, Income and Cash Flow."
        )
    if not p.housing_costs_complete:
        warnings.append("Housing costs and included expenses have not been confirmed.")
    if not s.costs_complete:
        warnings.append("Transition cost list has not been confirmed complete.")
    if p.condo_amount_meaning == "unknown" and p.condo_amount is not None:
        warnings.append(
            "Clarify what the condo amount represents; it is not used as value or debt."
        )
    if max(s.sale_date, s.move_date) > p.target_date:
        warnings.append("This alternative misses the goal date.")
    if max(s.funds_date, s.move_date, *(c.due for c in s.costs)) > p.end_date:
        warnings.append(
            "Some events are beyond the comparison period; extend it to see their full effect."
        )
    if s.sale_date < s.move_date:
        warnings.append(
            "There is a gap between sale and move. Include temporary accommodation in dated costs."
        )
    result: dict[str, Any] = {
        "name": s.name,
        "unknown": unknown,
        "warnings": warnings,
        "conditional": True,
        "proceeds": None,
        "monthly": None,
        "transition": None,
        "comparison": None,
    }
    proceeds = None
    if s.sale_price is not None and s.payoff is not None and s.selling_fees is not None:
        proceeds = s.sale_price - s.payoff - s.selling_fees
        result["proceeds"] = amount(proceeds)
        if proceeds < 0:
            warnings.append("Sale proceeds are negative: cash is required at closing.")
    owner = rent = None
    if p.mortgage_payment is not None and p.owner_extras is not None:
        owner = p.mortgage_payment + p.owner_extras
    if s.rent is not None and s.rental_extras is not None:
        rent = s.rent + s.rental_extras
    if (
        owner is not None
        and rent is not None
        and p.income is not None
        and p.nonhousing is not None
        and p.other_savings is not None
    ):
        available = p.income - p.nonhousing - p.other_savings
        result["monthly"] = {
            "stay_housing": amount(owner),
            "move_housing": amount(rent),
            "stay_spending": amount(owner + p.nonhousing),
            "move_spending": amount(rent + p.nonhousing),
            "stay_capacity": amount(available - owner),
            "move_capacity": amount(available - rent),
        }
    if (
        proceeds is not None
        and all(c.amount is not None for c in s.costs)
        and (s.move_date >= s.sale_date or rent is not None)
    ):
        # Negative proceeds are payable at closing, never delayed until disbursement.
        events: dict[date, list[tuple[str, Decimal, str]]] = {}

        def event(day: date, name: str, value: Decimal, kind: str) -> None:
            events.setdefault(day, []).append((name, value, kind))

        event(p.as_of, "Starting reserve check", ZERO, "reserve")
        if rent is not None and s.move_date < s.sale_date:
            due = s.move_date
            count = 1
            while due < s.sale_date:
                until = min(anniversary(s.move_date, count), s.sale_date)
                overlap = ZERO
                day = due
                while day < until:
                    overlap += rent / calendar.monthrange(day.year, day.month)[1]
                    day += timedelta(days=1)
                event(due, "Rental costs during housing overlap", -overlap, "overlap")
                due = until
                count += 1
        event(
            s.funds_date if proceeds >= 0 else s.sale_date,
            "Sale cash after payoff and selling expenses",
            proceeds,
            "sale",
        )
        for c in s.costs:
            assert c.amount is not None
            event(c.due, c.name, -c.amount, c.kind)
            if c.returned:
                event(c.returned, f"{c.name} returned", c.amount, "return")
        event(
            max(s.move_date, s.funds_date), "Reserve checkpoint (not an expense)", ZERO, "reserve"
        )
        if (
            p.dedicated_cash is not None
            and p.reserve is not None
            and p.monthly_set_aside is not None
        ):
            base = p.dedicated_cash
            required = ZERO
            immediate = ZERO
            timeline = []
            for day in sorted(events):
                # Savings arrive on completed monthly anniversaries, never before the first one.
                months = (day.year - p.as_of.year) * 12 + day.month - p.as_of.month
                if anniversary(p.as_of, months) > day:
                    months -= 1
                for _name, delta, _kind in events[day]:
                    base += delta
                deficit = max(ZERO, p.reserve - base)
                if months:
                    required = max(required, deficit / months)
                else:
                    immediate = max(immediate, deficit)
                funded = base + p.monthly_set_aside * months
                timeline.append(
                    {
                        "date": day,
                        "items": [
                            {"name": n, "amount": amount(v), "kind": k} for n, v, k in events[day]
                        ],
                        "cash": amount(funded),
                        "shortfall": amount(max(ZERO, p.reserve - funded)),
                    }
                )
            result["transition"] = {
                "timeline": timeline,
                "required_monthly": str(required.quantize(CENT, rounding=ROUND_UP)),
                "needed_now": amount(immediate),
                "reserve": amount(p.reserve),
            }
            if result["monthly"] and required > Decimal(result["monthly"]["stay_capacity"]):
                warnings.append(
                    "Required saving exceeds the estimated monthly capacity while staying."
                )
        if p.monthly_set_aside is not None and result["monthly"]:
            if p.monthly_set_aside > Decimal(result["monthly"]["stay_capacity"]):
                warnings.append(
                    "Your planned set-aside exceeds the monthly capacity while staying."
                )
            if max(events) > s.move_date and p.monthly_set_aside > Decimal(
                result["monthly"]["move_capacity"]
            ):
                warnings.append("Your planned set-aside exceeds the monthly capacity after moving.")
        if not unknown and owner is not None and rent is not None:
            result["comparison"] = compare(p, s, events, owner, rent)
    return result


def compare(
    p: HousingInput,
    s: HousingScenario,
    events: dict[date, list[tuple[str, Decimal, str]]],
    owner: Decimal,
    rent: Decimal,
) -> dict[str, Any]:
    # Inputs are checked by the caller. No appreciation, returns or tax benefits.
    assert p.cash is not None and p.mortgage_balance is not None and p.home_value is not None
    assert p.income is not None and p.nonhousing is not None and p.other_savings is not None
    assert (
        p.other_net_assets is not None
        and p.principal_interest is not None
        and p.annual_rate is not None
    )
    stay = move = p.cash
    debt = p.mortgage_balance
    moved_debt = debt
    deposit = ZERO
    saved_elsewhere = ZERO
    low_cash = move
    low_date = p.as_of
    rows = []
    day = p.as_of
    payment_number = 1
    next_payment = anniversary(p.as_of, payment_number)
    while day <= p.end_date:
        if day == next_payment:
            principal = min(debt, p.principal_interest - debt * p.annual_rate / 1200)
            debt -= principal
            if day < s.sale_date:
                moved_debt = debt
            payment_number += 1
            next_payment = anniversary(p.as_of, payment_number)
        for _name, delta, kind in events.get(day, []):
            if kind != "overlap":
                move += delta
            if kind == "deposit" or kind == "return":
                deposit -= delta
        if day == s.sale_date:
            moved_debt = ZERO
        if move < low_cash:
            low_cash, low_date = move, day
        if day == p.end_date or day.day == 1:
            # Positive proceeds pending after closing are a receivable, not spendable cash.
            receivable = ZERO
            if s.sale_date <= day < s.funds_date:
                assert (
                    s.sale_price is not None and s.payoff is not None and s.selling_fees is not None
                )
                receivable = max(ZERO, s.sale_price - s.payoff - s.selling_fees)
            common = p.other_net_assets + saved_elsewhere
            stay_worth = stay + p.home_value - debt + common
            move_worth = (
                move
                + (p.home_value if day < s.sale_date else ZERO)
                - moved_debt
                + deposit
                + receivable
                + common
            )
            rows.append(
                {
                    "date": day,
                    "stay_cash": amount(stay),
                    "move_cash": amount(move),
                    "stay_net_worth": amount(stay_worth),
                    "move_net_worth": amount(move_worth),
                    "cash_difference": amount(move - stay),
                    "net_worth_difference": amount(move_worth - stay_worth),
                    "stay_debt": amount(debt),
                    "refundable_deposits": amount(deposit),
                }
            )
        if day == p.end_date:
            break
        fraction = Decimal(1) / calendar.monthrange(day.year, day.month)[1]
        common_flow = p.income - p.nonhousing - p.other_savings
        loan_payment = min(p.principal_interest, debt + debt * p.annual_rate / 1200)
        actual_owner = owner - p.principal_interest + loan_payment
        stay += (common_flow - actual_owner) * fraction
        move_cost = (actual_owner if day < s.sale_date else ZERO) + (
            rent if day >= s.move_date else ZERO
        )
        move += (common_flow - move_cost) * fraction
        saved_elsewhere += p.other_savings * fraction
        day += timedelta(days=1)
    return {
        "periods": rows,
        "ending": rows[-1],
        "lowest_move_cash": amount(low_cash),
        "lowest_cash_date": low_date,
    }
