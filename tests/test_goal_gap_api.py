from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

import paycheck_map.api_v2 as api_module
from paycheck_map.app import app
from paycheck_map.db import get_session

from .goal_gap_support import seed_goal_gap
from .test_recurring_outflow_candidates import add_occurrences

NOW = datetime(2026, 8, 11, 14, 15, tzinfo=UTC)


def request(
    session: Session,
    method: str,
    path: str,
    payload: object | None = None,
) -> httpx.Response:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:

        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
            ) as client:
                return await client.request(method, path, json=payload)

        return asyncio.run(send())
    finally:
        app.dependency_overrides.clear()


def test_preview_endpoint_returns_exact_typed_result(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_goal_gap(session)
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    response = request(
        session,
        "POST",
        "/api/v2/goals/gap-preview",
        {
            "target_date": None,
            "additional_reservation": "0.00",
            "monthly_spending_reduction": "0.00",
            "monthly_after_tax_income": "0.00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "available"
    assert body["baseline_current_recurring_facts"]["stabilization_gap"]["amount"] == "5602.98"
    assert body["baseline_goal_pace_reference"]["required_goal_pace"]["amount"] == "39003.52"
    assert body["baseline_combined_monthly_improvement"]["amount"] == "44606.50"
    assert body["exact_funding_months"] == "48.000000000000"


def test_preview_endpoint_no_primary_and_invalid_drafts_are_explicit(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_goal_gap(session, include_goal=False)
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    no_primary = request(
        session,
        "POST",
        "/api/v2/goals/gap-preview",
        {
            "additional_reservation": "0.00",
            "monthly_spending_reduction": "0.00",
            "monthly_after_tax_income": "0.00",
        },
    )
    malformed = request(
        session,
        "POST",
        "/api/v2/goals/gap-preview",
        {
            "target_date": "2035-02-31",
            "additional_reservation": 1.25,
            "monthly_spending_reduction": "-1.00",
            "monthly_after_tax_income": "0.00",
        },
    )

    assert no_primary.status_code == 200
    assert no_primary.json()["state"] == "no_primary"
    assert malformed.status_code == 422


def test_service_validation_becomes_safe_http_422(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_goal_gap(session)
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    response = request(
        session,
        "POST",
        "/api/v2/goals/gap-preview",
        {
            "additional_reservation": "1872168.97",
            "monthly_spending_reduction": "0.00",
            "monthly_after_tax_income": "0.00",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Additional reservation cannot exceed the remaining goal target"
    )


def test_candidate_endpoint_returns_typed_high_confidence_rows(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[
            datetime(2026, 5, 5).date(),
            datetime(2026, 6, 4).date(),
            datetime(2026, 7, 4).date(),
        ],
    )
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    response = request(
        session,
        "GET",
        "/api/v2/cash-flow/recurring-outflow-candidates",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "available"
    assert body["candidates"][0]["cadence"] == "monthly"
    assert body["candidates"][0]["typical_monthly_amount"]["amount"] == "10.00"


def test_preview_and_candidate_endpoints_emit_no_write_or_persistence_sql(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[
            datetime(2026, 5, 5).date(),
            datetime(2026, 6, 4).date(),
            datetime(2026, 7, 4).date(),
        ],
    )
    session.commit()
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)
    forbidden: list[str] = []

    def capture_statement(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
            "CREATE",
            "ALTER",
            "DROP",
            "BEGIN",
            "COMMIT",
        }:
            forbidden.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        preview_response = request(
            session,
            "POST",
            "/api/v2/goals/gap-preview",
            {
                "target_date": "2035-11-18",
                "additional_reservation": "100.00",
                "monthly_spending_reduction": "50.00",
                "monthly_after_tax_income": "75.00",
            },
        )
        candidate_response = request(
            session,
            "GET",
            "/api/v2/cash-flow/recurring-outflow-candidates",
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert preview_response.status_code == 200
    assert candidate_response.status_code == 200
    assert forbidden == []
    assert not session.new
    assert not session.dirty
    assert not session.deleted
