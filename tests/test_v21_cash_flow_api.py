from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

import paycheck_map.api_v2 as api_module
from paycheck_map.app import app
from paycheck_map.db import get_session
from paycheck_map.v21_contracts import CashFlowPeriodResult

from .v21_cash_flow_support import (
    synthetic_cash_flow_accounts,
    synthetic_transaction,
    synthetic_transfer_match,
)

NOW = datetime(2026, 8, 11, 14, 15, tzinfo=UTC)


def _get(session: Session, path: str) -> httpx.Response:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:

        async def request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
            ) as client:
                return await client.get(path)

        return asyncio.run(request())
    finally:
        app.dependency_overrides.clear()


def _seed_endpoint_period(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount="1000.25",
        role="external_inflow",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 11),
        amount="-400.10",
        role="external_outflow",
        source_row=2,
    )


def test_endpoint_returns_contract_valid_exact_period_result(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_endpoint_period(session)
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    response = _get(session, "/api/v2/cash-flow?period_kind=all_imported_history")

    assert response.status_code == 200
    result = CashFlowPeriodResult.model_validate(response.json())
    assert result.period.start_date == date(2026, 8, 1)
    assert result.period.end_date == date(2026, 8, 11)
    assert response.json()["totals"]["money_in"]["amount"] == "1000.25"
    assert response.json()["totals"]["money_out"]["amount"] == "400.10"
    assert response.json()["totals"]["net_cash_flow"]["amount"] == "600.15"


def test_endpoint_query_validation_and_unavailable_conflict_are_explicit(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)
    missing_custom = _get(session, "/api/v2/cash-flow?period_kind=custom_range")
    start_after_end = _get(
        session,
        "/api/v2/cash-flow?period_kind=custom_range&start_date=2026-08-02&end_date=2026-08-01",
    )
    future_end = _get(
        session,
        "/api/v2/cash-flow?period_kind=custom_range&start_date=2026-08-01&end_date=2026-08-12",
    )
    conflicting_preset = _get(
        session,
        "/api/v2/cash-flow?period_kind=year_to_date&start_date=2026-02-01",
    )
    unavailable = _get(session, "/api/v2/cash-flow?period_kind=all_imported_history")
    invalid_kind = _get(session, "/api/v2/cash-flow?period_kind=quarter_to_date")

    assert missing_custom.status_code == 422
    assert start_after_end.status_code == 422
    assert future_end.status_code == 422
    assert conflicting_preset.status_code == 422
    assert invalid_kind.status_code == 422
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["state"] == "unavailable"
    assert "no bank transaction coverage" in unavailable.json()["detail"]["reason"]


def test_endpoint_get_executes_no_database_writes(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_endpoint_period(session)
    session.commit()
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)
    writes: list[str] = []

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
        if operation in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            writes.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        response = _get(session, "/api/v2/cash-flow?period_kind=all_imported_history")
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert writes == []


def test_legacy_overview_and_timeline_shapes_remain_compatible(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    transfer_out = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount="-100.00",
        role="internal_transfer",
        source_row=1,
    )
    transfer_in = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 2),
        amount="100.00",
        role="external_inflow",
        source_row=1,
        account=accounts.savings,
    )
    synthetic_transfer_match(session, transfer_out, transfer_in)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 5),
        amount="5.00",
        role="interest",
        source_row=2,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 11),
        amount="-2.00",
        role="fee",
        source_row=3,
    )
    monkeypatch.setattr(api_module, "_cash_flow_api_now", lambda: NOW)

    overview = _get(
        session,
        "/api/overview?start_date=2026-08-01&end_date=2026-08-11",
    )
    timeline = _get(
        session,
        "/api/timeline?start_date=2026-08-01&end_date=2026-08-11",
    )

    assert overview.status_code == 200
    assert timeline.status_code == 200
    assert set(overview.json()["cashflow"]) == {
        "coverage",
        "external_inflows",
        "external_outflows",
        "transfer_in",
        "transfer_out",
        "interest",
        "fees",
        "net_external",
        "matched_transfer_transactions",
    }
    assert set(timeline.json()[0]) == {
        "month",
        "gross_pay",
        "taxes",
        "pretax",
        "after_tax",
        "employer_contributions",
        "net_pay",
        "cash_inflows",
        "cash_outflows",
        "transfers",
        "investment_contributions",
        "investment_result",
        "status",
    }
    assert timeline.json()[0]["cash_inflows"] == "5.00"
    assert timeline.json()[0]["cash_outflows"] == "2.00"
    assert timeline.json()[0]["transfers"] == "200.00"
