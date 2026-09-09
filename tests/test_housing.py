from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
from paycheck_map.app import app
from paycheck_map.db import get_session
from paycheck_map.housing import HousingInput, evaluate
from paycheck_map.models import HousingPlan

from .conftest import PROJECT_ROOT


def fixture() -> dict[str, Any]:
    return {
        "name": "Synthetic coastal move",
        "destination": "Synthetic coast",
        "target_date": "2027-02-01",
        "as_of": "2027-01-01",
        "end_date": "2027-03-01",
        "baseline_complete": True,
        "baseline_notes": "Synthetic statements, January 1; all included.",
        "cash": "20000",
        "dedicated_cash": "1000",
        "other_net_assets": "50000",
        "income": "6000",
        "nonhousing": "1000",
        "other_savings": "500",
        "home_value": "200000",
        "mortgage_balance": "100000",
        "mortgage_payment": "1200",
        "principal_interest": "1000",
        "annual_rate": "0",
        "owner_extras": "300",
        "reserve": "1000",
        "monthly_set_aside": "1000",
        "housing_costs_complete": True,
        "scenarios": [
            {
                "name": "Main",
                "sale_price": "210000",
                "payoff": "99000",
                "selling_fees": "11000",
                "sale_date": "2027-02-01",
                "funds_date": "2027-02-05",
                "move_date": "2027-02-01",
                "rent": "2000",
                "rental_extras": "100",
                "costs_complete": True,
                "costs": [
                    {"name": "Moving", "amount": "3000", "due": "2027-02-01"},
                    {"name": "Deposit", "amount": "2000", "due": "2027-01-15", "kind": "deposit"},
                ],
            }
        ],
    }


def result(raw: dict[str, Any]) -> dict[str, Any]:
    return dict(evaluate(HousingInput.model_validate(raw))["scenarios"][0])


def test_hand_calculated_two_month_ledger() -> None:
    r = result(fixture())
    assert r["unknown"] == []
    assert r["proceeds"] == "100000.00"  # 210k price - 99k debt - 11k expenses, not profit.
    assert r["monthly"]["stay_capacity"] == "3000.00"
    assert r["monthly"]["move_capacity"] == "2400.00"
    end = r["comparison"]["ending"]
    # Stay: 20k cash + 12k income - 3k housing - 2k living - 1k saved elsewhere.
    assert end["stay_cash"] == "26000.00"
    # Move: 20k + 12k - 1.5k ownership - 2.1k rent - 2k living - 1k other savings
    # + 100k sale - 3k expense - 2k refundable deposit.
    assert end["move_cash"] == "120400.00"
    assert end["stay_debt"] == "98000.00"
    assert end["stay_net_worth"] == "179000.00"
    assert end["move_net_worth"] == "173400.00"
    assert end["net_worth_difference"] == "-5600.00"
    transition = r["transition"]
    assert transition["needed_now"] == "2000.00"
    assert transition["required_monthly"] == "5000.00"
    assert transition["timeline"][2]["shortfall"] == "4000.00"


def test_deposit_return_changes_liquidity_not_net_worth() -> None:
    raw = fixture()
    before = result(raw)["comparison"]["ending"]
    raw["scenarios"][0]["costs"][1]["returned"] = "2027-02-20"
    after = result(raw)["comparison"]["ending"]
    assert Decimal(after["move_cash"]) - Decimal(before["move_cash"]) == 2000
    assert after["move_net_worth"] == before["move_net_worth"]
    assert after["refundable_deposits"] == "0.00"


def test_escrow_and_equity_not_added_to_spending_twice() -> None:
    raw = fixture()
    raw["principal_interest"] = "800"
    r = result(raw)
    assert r["monthly"]["stay_housing"] == "1500.00"
    assert r["comparison"]["ending"]["stay_cash"] == "26000.00"
    assert r["comparison"]["ending"]["stay_debt"] == "98400.00"
    raw["principal_interest"] = "1201"
    with pytest.raises(ValidationError):
        HousingInput.model_validate(raw)


def test_overlap_is_in_timeline_and_counted_once_in_comparison() -> None:
    raw = fixture()
    raw["scenarios"][0]["move_date"] = "2027-01-01"
    r = result(raw)
    assert r["comparison"]["ending"]["move_cash"] == "118300.00"
    overlap = [
        item
        for row in r["transition"]["timeline"]
        for item in row["items"]
        if item["kind"] == "overlap"
    ]
    assert overlap[0]["amount"] == "-2100.00"
    assert r["transition"]["needed_now"] == "4100.00"


def test_delayed_receipts_do_not_fund_early_costs_and_negative_proceeds_due_at_closing() -> None:
    raw = fixture()
    raw["scenarios"][0]["funds_date"] = "2027-03-15"
    r = result(raw)
    assert r["transition"]["required_monthly"] == "5000.00"
    assert r["comparison"]["ending"]["move_cash"] == "20400.00"
    assert r["comparison"]["ending"]["move_net_worth"] == "173400.00"  # receivable
    raw["scenarios"][0]["sale_price"] = "90000"
    r = result(raw)
    assert r["proceeds"] == "-20000.00"
    sale = next(
        row for row in r["transition"]["timeline"] if any(i["kind"] == "sale" for i in row["items"])
    )
    assert sale["date"] == date(2027, 2, 1)
    assert r["comparison"]["ending"]["move_cash"] == "400.00"


def test_missing_brief_never_invents_payoff_value_or_profit() -> None:
    raw = fixture()
    raw.update(
        condo_amount="260000",
        condo_amount_meaning="unknown",
        mortgage_payment="1776",
        annual_rate="6.75",
        home_value=None,
        mortgage_balance=None,
        principal_interest=None,
        baseline_complete=False,
    )
    raw["scenarios"][0].update(sale_price=None, payoff=None, rent="4000")
    r = result(raw)
    assert r["proceeds"] is None
    assert r["comparison"] is None
    assert "home_value" in r["unknown"]
    assert any("Clarify" in w for w in r["warnings"])


def test_alternatives_preserve_original_and_have_independent_consequences() -> None:
    raw = fixture()
    raw["scenarios"].append({**raw["scenarios"][0], "name": "Higher rent", "rent": "2500"})
    results = evaluate(HousingInput.model_validate(raw))["scenarios"]
    assert results[0]["comparison"]["ending"]["move_cash"] == "120400.00"
    assert results[1]["comparison"]["ending"]["move_cash"] == "119900.00"


@pytest.mark.parametrize(
    "change",
    [
        {"dedicated_cash": "20001"},
        {"annual_rate": "-1"},
        {"cash": "NaN"},
        {"as_of": "2027-03-01"},
        {"end_date": "2040-01-01"},
    ],
)
def test_invalid_assumptions_rejected(change: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        HousingInput.model_validate({**fixture(), **change})


def test_mortgage_interest_is_independent_of_cash_payment() -> None:
    raw = fixture()
    raw["annual_rate"] = "12"
    # At 1% monthly, the $1000 P&I payment is all interest on $100,000.
    assert result(raw)["comparison"]["ending"]["stay_debt"] == "100000.00"


def test_api_create_edit_reload_and_stale_write(session: Session) -> None:
    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            assert (await client.get("/api/v2/housing")).json() == []
            created = await client.post("/api/v2/housing", json={"revision": 0, "plan": fixture()})
            assert created.status_code == 200, created.text
            row = created.json()
            path = f"/api/v2/housing/{row['id']}"
            raw = fixture()
            raw["scenarios"].append(
                {**raw["scenarios"][0], "name": "Later", "funds_date": "2027-03-15"}
            )
            saved = await client.put(path, json={"revision": 1, "plan": raw})
            assert saved.status_code == 200, saved.text
            assert (
                await client.put(path, json={"revision": 1, "plan": fixture()})
            ).status_code == 409
            session.expire_all()
            reopened = (await client.get("/api/v2/housing")).json()[0]
            assert reopened["revision"] == 2
            assert len(reopened["plan"]["scenarios"]) == 2
            assert reopened["result"] == saved.json()["result"]
            bad = await client.post("/api/v2/housing/preview", json={**raw, "cash": "-10"})
            assert bad.status_code == 422

    try:
        asyncio.run(exercise())
        # A different SQLAlchemy session reads the persisted document, not an identity-map cache.
        with Session(session.get_bind()) as reopened:
            saved = reopened.get(HousingPlan, 1)
            assert saved is not None and saved.revision == 2
    finally:
        app.dependency_overrides.clear()


def test_migration_from_0009_preserves_existing_data_and_repeats_safely(tmp_path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    path = tmp_path / "housing.sqlite3"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "0009_goal_persistence")
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE synthetic_preserved (value TEXT)"))
        conn.execute(text("INSERT INTO synthetic_preserved VALUES ('keep')"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM synthetic_preserved")).scalar() == "keep"
        assert conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0010_housing_plans"
        )
    assert "housing_plans" in inspect(engine).get_table_names()
    command.downgrade(config, "0009_goal_persistence")
    assert "housing_plans" not in inspect(engine).get_table_names()
    engine.dispose()


def test_final_mortgage_payment_is_capped_and_stops_when_repaid() -> None:
    raw = fixture()
    raw.update(mortgage_balance="500", principal_interest="1000")
    r = result(raw)
    # Only $500 of loan service across two months, plus $400 escrow and $600 extras.
    assert r["comparison"]["ending"]["stay_debt"] == "0.00"
    assert r["comparison"]["ending"]["stay_cash"] == "27500.00"


def test_unknown_overlap_cost_withholds_transition_and_overcommitment_is_visible() -> None:
    raw = fixture()
    raw["scenarios"][0].update(move_date="2027-01-01", rental_extras=None)
    r = result(raw)
    assert r["proceeds"] == "100000.00"
    assert r["transition"] is None
    raw["scenarios"][0]["rental_extras"] = "100"
    raw["monthly_set_aside"] = "4000"
    r = result(raw)
    assert any("planned set-aside exceeds" in warning for warning in r["warnings"])
