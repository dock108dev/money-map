from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from paycheck_map.api import get_secret_store
from paycheck_map.app import app
from paycheck_map.config import Settings
from paycheck_map.db import get_session
from paycheck_map.ingestion import import_private_inbox
from paycheck_map.keychain import MemorySecretStore


def test_local_api_workflow(
    session: Session,
    runtime_settings: Settings,
    populated_inbox: Path,
) -> None:
    del populated_inbox
    import_private_inbox(session, runtime_settings)

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    secret_store = MemorySecretStore()
    app.dependency_overrides[get_secret_store] = lambda: secret_store
    try:

        async def exercise_api() -> tuple[
            httpx.Response,
            httpx.Response,
            httpx.Response,
            httpx.Response,
            httpx.Response,
            httpx.Response,
            httpx.Response,
        ]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test.local"
            ) as client:
                health = await client.get("/api/health")
                overview = await client.get("/api/overview")
                accounts = await client.get("/api/accounts")
                scenario = await client.post(
                    "/api/scenarios",
                    json={"name": "API comparison", "additional_401k_pct": "1"},
                )
                plaid = await client.get("/api/plaid/status")
                preference = await client.put(
                    "/api/plaid/refresh-preference", json={"enabled": False}
                )
                sync_all = await client.post("/api/plaid/sync-all", json={"automatic": False})
            return health, overview, accounts, scenario, plaid, preference, sync_all

        health, overview, accounts, scenario, plaid, preference, sync_all = asyncio.run(
            exercise_api()
        )
        assert health.json()["privacy"] == "local-first"
        assert overview.json()["coverage"]["all_imported_paychecks"] == 1
        assert accounts.json()["totals"]["net_worth"] == "13802.00"
        assert scenario.status_code == 200
        assert scenario.json()["annual_salary"] == "190000.00"
        assert plaid.json()["configuration"]["sandbox"]["configured"] is False
        assert plaid.json()["refresh"]["active_connections"] == 0
        assert preference.json()["auto_refresh_enabled"] is False
        assert sync_all.json()["requested"] == 0
    finally:
        app.dependency_overrides.clear()


def test_life_lab_api_profile_goal_projection_and_stale_snapshot(
    session: Session,
    runtime_settings: Settings,
    populated_inbox: Path,
) -> None:
    del populated_inbox
    import_private_inbox(session, runtime_settings)

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:

        async def exercise_life_lab() -> tuple[dict[str, object], ...]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test.local"
            ) as client:
                empty_profile = (await client.get("/api/life-plan/profile")).json()
                profile = (
                    await client.put(
                        "/api/life-plan/profile",
                        json={
                            "birth_date": "1991-01-01",
                            "state": "NJ",
                            "end_age": 41,
                            "current_monthly_outflow": "2500",
                            "essential_monthly_spend": "1000",
                            "flexible_monthly_spend": "500",
                            "cash_floor": "2000",
                            "retirement_tax_rate_pct": "20",
                            "target_ages": [40],
                            "notes": "API test",
                        },
                    )
                ).json()
                goal = (
                    await client.post(
                        "/api/life-plan/goals",
                        json={
                            "name": "Generic 2028 goal",
                            "target_date": "2028-06-01",
                            "target_amount": "10000",
                            "reserved_amount": "1000",
                            "annual_cost": "0",
                            "priority": "required",
                            "enabled": True,
                            "notes": "",
                        },
                    )
                ).json()
                projection = (
                    await client.post("/api/life-plan/project", json={"target_ages": [40]})
                ).json()
                saved = (
                    await client.post(
                        "/api/life-plan/scenarios",
                        json={"name": "Age 40 middle", "target_age": 40, "path_key": "middle"},
                    )
                ).json()
                await client.put(
                    "/api/life-plan/profile",
                    json={
                        "birth_date": "1991-01-01",
                        "state": "NJ",
                        "end_age": 41,
                        "current_monthly_outflow": "2600",
                        "essential_monthly_spend": "1000",
                        "flexible_monthly_spend": "500",
                        "cash_floor": "2000",
                        "retirement_tax_rate_pct": "20",
                        "target_ages": [40],
                        "notes": "API test",
                    },
                )
                scenarios = (await client.get("/api/life-plan/scenarios")).json()
                return empty_profile, profile, goal, projection, saved, scenarios[0]

        empty_profile, profile, goal, projection, saved, changed = asyncio.run(exercise_life_lab())
        assert empty_profile is None
        assert profile["provenance"]["birth_date"] == "user_entered"
        assert goal["name"] == "Generic 2028 goal"
        assert projection["engine_version"] == "life-lab-v0.3.0"
        assert projection["results"][0]["target_age"] == 40
        assert {row["path_key"] for row in projection["results"][0]["paths"]} == {
            "middle",
            "rough",
            "early_crash",
        }
        drive_answer = projection["results"][0]["paths"][0]["make_it_happen"]
        assert Decimal(drive_answer["additional_monthly_after_tax_income"]) >= 0
        assert Decimal(drive_answer["retirement_capital_needed"]) >= 0
        assert (
            drive_answer["retirement_deadline"]
            == projection["results"][0]["paths"][0]["work_stop_month"]
        )
        assert saved["stale"] is False
        assert changed["stale"] is True
        assert changed["source_fingerprint"] == saved["source_fingerprint"]
    finally:
        app.dependency_overrides.clear()
