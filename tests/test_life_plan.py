from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from paycheck_map.config import Settings
from paycheck_map.ingestion import import_private_inbox
from paycheck_map.life_plan import (
    PATHS,
    LifePlanProfileInput,
    ScenarioSaveInput,
    _additional_income_needed,
    _retirement_capital_needed,
    _simulate,
    _take_retirement,
    current_fingerprint,
    load_benchmarks,
    save_scenario,
    scenario_dict,
    source_fingerprint,
    starting_point,
    upsert_profile,
)
from paycheck_map.models import Account, LifeGoal, LifePlanProfile


def _profile(**overrides: object) -> LifePlanProfile:
    values: dict[str, object] = {
        "id": 1,
        "birth_date": date(1990, 1, 1),
        "state": "NJ",
        "end_age": 38,
        "current_monthly_outflow": Decimal("0"),
        "essential_monthly_spend": Decimal("1000"),
        "flexible_monthly_spend": Decimal("0"),
        "cash_floor": Decimal("0"),
        "retirement_tax_rate_pct": Decimal("20"),
        "target_ages": [37],
        "notes": "",
    }
    values.update(overrides)
    return LifePlanProfile(**values)


def _start(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "cash": "0.00",
        "accessible_investments": "0.00",
        "pretax_retirement": "0.00",
        "hsa": "0.00",
        "restricted_assets": "0.00",
        "debt": "0.00",
        "payroll": None,
    }
    values.update(overrides)
    return values


def test_starting_point_keeps_401k_out_of_accessible_money(
    session: Session,
    runtime_settings: Settings,
    populated_inbox: Path,
) -> None:
    del populated_inbox
    import_private_inbox(session, runtime_settings)
    retirement = session.scalar(
        select(Account).where(Account.display_name == "Synthetic retirement")
    )
    assert retirement is not None
    retirement.account_type = "401k"
    session.commit()

    result = starting_point(session, as_of=date(2026, 8, 3))

    assert result["cash"] == "2802.00"
    assert result["accessible_investments"] == "0.00"
    assert result["pretax_retirement"] == "11000.00"
    retirement_row = next(
        row for row in result["accounts"] if row["name"] == "Synthetic retirement"
    )
    assert retirement_row["access_status"] == "retirement"


def test_zero_return_path_is_exact_and_monthly(monkeypatch: object) -> None:
    # The model includes the plan-end month, so 13 post-work months require exactly $13,000.
    monkeypatch.setitem(PATHS["middle"], "annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    result = _simulate(
        _profile(),
        [],
        _start(cash="13000.00"),
        target_age=37,
        path_key="middle",
        as_of=date(2026, 1, 1),
    )

    assert result["status"] == "works"
    assert result["end_assets"]["cash"] == "0.00"
    assert result["periods"][-1]["month"] == date(2028, 1, 1)


def test_required_goal_is_funded_before_flexible_lifestyle(monkeypatch: object) -> None:
    monkeypatch.setitem(PATHS["middle"], "annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    goal = LifeGoal(
        id=1,
        profile_id=1,
        name="Dated life goal",
        target_date=date(2027, 1, 1),
        target_amount=Decimal("1000"),
        reserved_amount=Decimal("0"),
        annual_cost=Decimal("0"),
        priority="required",
        enabled=True,
        notes="",
    )
    result = _simulate(
        _profile(end_age=37, flexible_monthly_spend=Decimal("1000")),
        [goal],
        _start(cash="2000.00"),
        target_age=37,
        path_key="middle",
        as_of=date(2026, 1, 1),
    )

    assert result["status"] == "works_essentials_only"
    assert result["goal_results"]["1"] == {"funded": True, "shortfall": "0.00"}
    stop_period = result["periods"][-1]
    assert stop_period["essential_spend"] == "1000.00"
    assert stop_period["goal_spend"] == "1000.00"
    assert stop_period["flexible_spend"] == "0.00"


def test_retirement_tax_haircut_and_access_bridge_are_explicit(monkeypatch: object) -> None:
    remaining, retirement = _take_retirement(Decimal("1000"), Decimal("1250"), Decimal("20"))
    assert remaining == Decimal("0.00")
    assert retirement == Decimal("0.00")

    monkeypatch.setitem(PATHS["middle"], "annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    result = _simulate(
        _profile(end_age=37),
        [],
        _start(pretax_retirement="100000.00"),
        target_age=37,
        path_key="middle",
        as_of=date(2026, 1, 1),
    )
    assert result["status"] == "insufficient_accessible_bridge"
    assert result["first_shortfall_month"] == date(2027, 1, 1)
    assert result["end_assets"]["pretax_retirement"] == "100000.00"


def test_reverse_solvers_never_stop_at_the_current_budget(monkeypatch: object) -> None:
    monkeypatch.setitem(PATHS["middle"], "annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    profile = _profile()
    start = _start()

    monthly_income = _additional_income_needed(profile, [], start, 37, "middle", date(2026, 1, 1))
    stop_event = _retirement_capital_needed(profile, [], start, 37, "middle", date(2026, 1, 1))

    assert monthly_income == Decimal("1083.34")
    assert monthly_income > profile.current_monthly_outflow
    assert stop_event == Decimal("13000.00")


def test_early_crash_reverse_solver_prices_the_crash(monkeypatch: object) -> None:
    monkeypatch.setitem(PATHS["early_crash"], "pre_stop_annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    monkeypatch.setitem(PATHS["early_crash"], "later_annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    stop_event = _retirement_capital_needed(
        _profile(), [], _start(), 37, "early_crash", date(2026, 1, 1)
    )
    assert stop_event == Decimal("20000.00")


def test_retirement_capital_solver_ignores_an_earlier_liquidity_hole(
    monkeypatch: object,
) -> None:
    monkeypatch.setitem(PATHS["middle"], "annual_real_return_pct", Decimal("0"))  # type: ignore[attr-defined]
    profile = _profile(current_monthly_outflow=Decimal("1000"))
    start = _start()
    as_of = date(2026, 1, 1)
    base = _simulate(profile, [], start, target_age=37, path_key="middle", as_of=as_of)

    capital = _retirement_capital_needed(profile, [], start, 37, "middle", as_of)

    assert base["first_shortfall_month"] == as_of
    assert base["work_stop_month"] == date(2027, 1, 1)
    assert capital == Decimal("13000.00")


def test_benchmarks_are_versioned_state_agi_context() -> None:
    result = load_benchmarks("NJ", Decimal("190000"))

    assert result["available"] is True
    assert result["source_year"] == 2022
    assert result["normalized_dollar_basis"] == "June 2026"
    assert set(result["thresholds"]) == {"top_50", "top_25", "top_10", "top_5", "top_1"}
    assert "definitions differ" in result["warning"]


def test_saved_scenario_becomes_stale_when_profile_changes(session: Session) -> None:
    profile = upsert_profile(
        session,
        LifePlanProfileInput(
            birth_date=date(1991, 1, 1),
            state="NJ",
            end_age=41,
            current_monthly_outflow=Decimal("0"),
            essential_monthly_spend=Decimal("0"),
            flexible_monthly_spend=Decimal("0"),
            cash_floor=Decimal("0"),
            retirement_tax_rate_pct=Decimal("20"),
            target_ages=[40],
            notes="",
        ),
    )
    scenario = save_scenario(
        session,
        profile,
        [],
        ScenarioSaveInput(name="Before assumptions move", target_age=40, path_key="middle"),
        as_of=date(2026, 8, 3),
    )
    original_fingerprint = source_fingerprint(
        profile,
        [],
        starting_point(session, as_of=date(2026, 8, 3)),
        str(load_benchmarks("NJ")["version"]),
    )
    assert scenario_dict(scenario, original_fingerprint)["stale"] is False

    profile.flexible_monthly_spend = Decimal("1")
    session.commit()
    changed_fingerprint = current_fingerprint(session, profile, [])
    assert scenario_dict(scenario, changed_fingerprint)["stale"] is True
