from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from paycheck_map import business_time, plaid_service, refresh, retirement_lab
from paycheck_map.app import app
from paycheck_map.desktop_policy import (
    ACCEPTANCE_DATA_MODE,
    DISPOSABLE_DATA_MODE,
    KEYCHAIN_ACCEPTANCE_DATA_MODE,
    MANAGED_DATA_MODES,
    PRODUCTION_DATA_MODE,
    uses_managed_data_home,
    uses_memory_secret_store,
)
from paycheck_map.product_metadata import (
    PUBLIC_VERSION,
    PYTHON_PACKAGE_VERSION,
    SCHEMA_HEAD,
    desktop_artifact_name,
)

from .conftest import PROJECT_ROOT


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/life-plan/profile"),
        ("PUT", "/api/life-plan/profile"),
        ("GET", "/api/life-plan/starting-point"),
        ("GET", "/api/life-plan/benchmarks"),
        ("GET", "/api/life-plan/goals"),
        ("POST", "/api/life-plan/goals"),
        ("PUT", "/api/life-plan/goals/1"),
        ("DELETE", "/api/life-plan/goals/1"),
        ("POST", "/api/life-plan/project"),
        ("GET", "/api/life-plan/scenarios"),
        ("POST", "/api/life-plan/scenarios"),
        ("GET", "/api/life-plan/scenarios/1"),
    ],
)
def test_combined_planning_endpoints_are_unavailable(method: str, path: str) -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            response = await client.request(
                method, path, headers={"Content-Type": "application/json"}
            )
        assert response.status_code in {404, 405}

    asyncio.run(exercise())


def test_lab_qualification_observes_current_mounted_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "tests/fixtures/synthetic/v1_2_1/release-state-contract.json").read_text()
    )
    # Check the actual mounted operations rather than a second endpoint allowlist.
    operations = {
        f"{method.upper()} {path}"
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    lab = contract["routes"]["lab"]["combination_defaults"]["expected_api_endpoints"]
    assert set(lab) <= operations
    native = (root / "desktop/src-tauri/src/main.rs").read_text()
    lab_observer = native.split('"lab" => &[', 1)[1].split("],", 1)[0]
    assert all(f'"{operation.split(" ", 1)[1]}"' in lab_observer for operation in lab)
    assert "/api/life-plan" not in native


def test_provider_refresh_and_planning_use_shared_clock_policy() -> None:
    assert (
        vars(plaid_service)["as_utc"]
        is vars(refresh)["as_utc"]
        is vars(retirement_lab)["as_utc"]
        is business_time.as_utc
    )
    assert (
        vars(plaid_service)["clock_timestamp"]
        is vars(refresh)["clock_timestamp"]
        is business_time.clock_timestamp
    )
    assert vars(plaid_service)["local_business_date"] is vars(refresh)["local_business_date"]
    # Both sides of midnight and DST use the same Eastern calendar policy.
    assert business_time.local_business_date(
        datetime(2026, 9, 6, 3, 59, tzinfo=UTC)
    ).isoformat() == ("2026-09-05")
    assert business_time.local_business_date(datetime(2026, 9, 6, 4, 0)).isoformat() == "2026-09-06"
    assert business_time.local_business_date(
        datetime(2026, 1, 6, 4, 59, tzinfo=UTC)
    ).isoformat() == ("2026-01-05")
    floor = datetime(2026, 9, 6, 12, tzinfo=timezone(timedelta(hours=-4)))
    assert business_time.clock_timestamp(
        lambda: datetime(2026, 9, 6, 15), not_before=floor
    ) == datetime(2026, 9, 6, 16, tzinfo=UTC)
    assert business_time.clock_timestamp(lambda: datetime(2026, 9, 6, 17)) == datetime(
        2026, 9, 6, 17, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "mode",
    [PRODUCTION_DATA_MODE, ACCEPTANCE_DATA_MODE, KEYCHAIN_ACCEPTANCE_DATA_MODE],
)
def test_managed_desktop_modes_share_one_policy(mode: str) -> None:
    assert mode in MANAGED_DATA_MODES
    assert uses_managed_data_home(mode)


def test_unsupported_and_disposable_modes_do_not_enter_managed_data_home() -> None:
    assert not uses_managed_data_home(DISPOSABLE_DATA_MODE)
    assert not uses_managed_data_home("production")
    assert not uses_managed_data_home(None)
    assert uses_memory_secret_store(ACCEPTANCE_DATA_MODE)
    assert uses_memory_secret_store(KEYCHAIN_ACCEPTANCE_DATA_MODE)
    assert not uses_memory_secret_store(PRODUCTION_DATA_MODE)


def test_product_identity_is_derived_from_authoritative_metadata() -> None:
    assert PUBLIC_VERSION == "3.0.0-beta.1"
    assert PYTHON_PACKAGE_VERSION == "3.0.0b1"
    assert SCHEMA_HEAD == "0010_housing_plans"
    assert desktop_artifact_name() == f"Money Map-{PUBLIC_VERSION}-arm64.dmg"


def test_policy_callers_do_not_reintroduce_mode_lists() -> None:
    callers = (
        "src/paycheck_map/app.py",
        "src/paycheck_map/api.py",
        "src/paycheck_map/config.py",
        "src/paycheck_map/data_home.py",
        "src/paycheck_map/desktop_sidecar.py",
    )
    managed_literals = tuple(MANAGED_DATA_MODES)
    for relative in callers:
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert sum(literal in source for literal in managed_literals) <= 1, relative


def test_frontend_does_not_invent_the_backend_schema() -> None:
    source = (PROJECT_ROOT / "web/src/data-home.tsx").read_text(encoding="utf-8")
    assert SCHEMA_HEAD not in source
    assert 'status.schema_revision ?? "unavailable"' in source


def test_release_scripts_source_python_identity_from_product_metadata() -> None:
    for relative in (
        "scripts/package_desktop_release.py",
        "scripts/qualify_desktop_release.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert 'VERSION = "3.0.0-beta.1"' not in source
        assert 'SCHEMA = "0009_goal_persistence"' not in source
