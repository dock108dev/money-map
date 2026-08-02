from __future__ import annotations

import asyncio
from collections.abc import Iterator
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
