from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.keychain import MemorySecretStore
from paycheck_map.models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    ImportArtifact,
    InvestmentHolding,
    InvestmentValueBridge,
    PlaidConnection,
    PlaidEndpointEvidence,
    PlaidSyncRun,
    ReconciliationResult,
)
from paycheck_map.plaid_client import JsonObject, PlaidAPIError, PlaidClient
from paycheck_map.plaid_service import (
    CONFIG_NAMESPACE,
    ITEM_NAMESPACE,
    _fidelity_role,
    _sofi_role,
    configure_plaid,
    create_plaid_link_session,
    exchange_plaid_public_token,
    plaid_configuration_status,
    revoke_plaid_connection,
    sync_plaid_connection,
)
from paycheck_map.refresh import (
    RefreshAlreadyRunningError,
    refresh_guard,
    refresh_status,
    set_auto_refresh_enabled,
    sync_all_connections,
)
from paycheck_map.services import accounts_dashboard, fidelity_summary


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> datetime:
        if self.index >= len(self.values):
            raise AssertionError("The refresh read the clock more times than expected")
        value = self.values[self.index]
        self.index += 1
        return value


class FakeSofiPlaidClient(PlaidClient):
    removed = False

    def __init__(self) -> None:
        pass

    def create_link_token(self, *, target: str, client_user_id: str) -> JsonObject:
        assert target == "sofi"
        assert client_user_id
        return {
            "link_token": "link-sandbox-sofi",
            "expiration": "2027-01-01T00:00:00Z",
        }

    def exchange_public_token(self, public_token: str) -> JsonObject:
        assert public_token == "public-sandbox-sofi"
        return {"access_token": "access-sandbox-sofi", "item_id": "item-sofi"}

    def item_get(self, access_token: str) -> JsonObject:
        assert access_token == "access-sandbox-sofi"
        return {
            "item": {
                "institution_id": "ins_sandbox",
                "consent_expiration_time": "2027-07-25T00:00:00Z",
            }
        }

    def institution_get(self, institution_id: str) -> JsonObject:
        assert institution_id == "ins_sandbox"
        return {"institution": {"name": "First Platypus Bank"}}

    def transactions_sync(self, access_token: str, cursor: str | None) -> list[JsonObject]:
        assert access_token == "access-sandbox-sofi"
        assert cursor in {None, "cursor-sofi"}
        return [
            {
                "accounts": [_sofi_account()],
                "added": [
                    {
                        "account_id": "acct-sofi",
                        "transaction_id": "txn-payroll",
                        "date": "2026-07-03",
                        "name": "UnitedHealth Payroll",
                        "merchant_name": None,
                        "original_description": "PAYROLL DIRECT DEP",
                        "amount": -3765.83,
                        "pending": False,
                        "personal_finance_category": {
                            "primary": "INCOME",
                            "detailed": "INCOME_WAGES",
                        },
                    }
                ],
                "modified": [],
                "removed": [],
                "has_more": False,
                "next_cursor": "cursor-sofi",
                "request_id": "request-transactions",
            }
        ]

    def transactions_get(
        self,
        access_token: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[JsonObject]:
        assert access_token == "access-sandbox-sofi"
        assert start_date is None
        assert end_date is not None
        page = self.transactions_sync(access_token, None)[0]
        return [
            {
                "accounts": page["accounts"],
                "transactions": page["added"],
                "total_transactions": 1,
                "request_id": "request-history",
            }
        ]

    def accounts_balance_get(self, access_token: str) -> JsonObject:
        assert access_token == "access-sandbox-sofi"
        return {
            "accounts": [_sofi_account()],
            "request_id": "request-balances",
        }

    def remove_item(self, access_token: str) -> JsonObject:
        assert access_token == "access-sandbox-sofi"
        self.removed = True
        return {"request_id": "request-remove"}


class FakeFidelityPlaidClient(PlaidClient):
    def __init__(self) -> None:
        pass

    def create_link_token(self, *, target: str, client_user_id: str) -> JsonObject:
        assert target == "fidelity"
        assert client_user_id
        return {
            "link_token": "link-sandbox-fidelity",
            "expiration": "2027-01-01T00:00:00Z",
        }

    def exchange_public_token(self, public_token: str) -> JsonObject:
        assert public_token == "public-sandbox-fidelity"
        return {"access_token": "access-sandbox-fidelity", "item_id": "item-fidelity"}

    def item_get(self, access_token: str) -> JsonObject:
        assert access_token == "access-sandbox-fidelity"
        return {"item": {"institution_id": "ins_sandbox"}}

    def institution_get(self, institution_id: str) -> JsonObject:
        assert institution_id == "ins_sandbox"
        return {"institution": {"name": "First Platypus Bank"}}

    def investments_holdings_get(self, access_token: str) -> JsonObject:
        assert access_token == "access-sandbox-fidelity"
        return {
            "accounts": [_fidelity_account()],
            "securities": [
                {
                    "security_id": "security-index",
                    "name": "Synthetic Index Fund",
                    "ticker_symbol": "SIF",
                    "type": "mutual fund",
                    "close_price_as_of": "2026-07-25",
                }
            ],
            "holdings": [
                {
                    "account_id": "acct-fidelity",
                    "security_id": "security-index",
                    "quantity": 100,
                    "institution_price": 250,
                    "institution_value": 25000,
                    "cost_basis": 20000,
                }
            ],
            "request_id": "request-holdings",
        }

    def investments_transactions_get(
        self,
        access_token: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[JsonObject]:
        assert access_token == "access-sandbox-fidelity"
        assert start_date is None
        assert end_date is not None
        return [
            {
                "accounts": [_fidelity_account()],
                "investment_transactions": [
                    {
                        "account_id": "acct-fidelity",
                        "investment_transaction_id": "investment-contribution",
                        "date": "2026-07-03",
                        "name": "EMPLOYEE CONTRIBUTION",
                        "type": "cash",
                        "subtype": "contribution",
                        "amount": -500,
                    }
                ],
                "total_investment_transactions": 1,
                "request_id": "request-investments",
            }
        ]


class FailingFidelityPlaidClient(FakeFidelityPlaidClient):
    def investments_holdings_get(self, access_token: str) -> JsonObject:
        del access_token
        raise PlaidAPIError(code="NETWORK_ERROR", message="Provider is temporarily unavailable")


def _sofi_account() -> JsonObject:
    return {
        "account_id": "acct-sofi",
        "name": "Plaid Checking",
        "official_name": "Plaid Gold Checking",
        "mask": "1111",
        "type": "depository",
        "subtype": "checking",
        "balances": {"current": 5000, "available": 4800},
    }


def _fidelity_account() -> JsonObject:
    return {
        "account_id": "acct-fidelity",
        "name": "Plaid 401k",
        "official_name": "Plaid Retirement Plan",
        "mask": "6666",
        "type": "investment",
        "subtype": "401k",
        "balances": {"current": 25000, "available": None},
    }


def _configured_store() -> MemorySecretStore:
    store = MemorySecretStore()
    configure_plaid(
        environment="sandbox",
        client_id="client-sandbox",
        secret="secret-sandbox",
        store=store,
    )
    return store


def test_plaid_client_uses_headers_without_putting_secrets_in_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["PLAID-CLIENT-ID"] == "client-id"
        assert request.headers["PLAID-SECRET"] == "secret-value"
        assert b"secret-value" not in request.content
        return httpx.Response(200, json={"item": {"institution_id": "ins_test"}})

    client = PlaidClient(
        environment="sandbox",
        client_id="client-id",
        secret="secret-value",
        transport=httpx.MockTransport(handler),
    )
    assert client.item_get("access-token")["item"]["institution_id"] == "ins_test"


def test_configuration_is_stored_outside_the_database() -> None:
    store = _configured_store()
    configure_plaid(
        environment="sandbox",
        client_id="",
        secret="rotated-secret",
        store=store,
    )
    status = plaid_configuration_status(store)
    assert status["sandbox"] == {
        "configured": True,
        "client_id_hint": "••••dbox",
    }
    assert store.get(CONFIG_NAMESPACE, "sandbox.client_id") == "client-sandbox"
    assert store.get(CONFIG_NAMESPACE, "sandbox.secret") == "rotated-secret"


def test_production_secret_reuses_the_shared_client_id() -> None:
    store = _configured_store()
    configure_plaid(
        environment="production",
        client_id="",
        secret="production-secret",
        store=store,
    )
    assert plaid_configuration_status(store)["production"] == {
        "configured": True,
        "client_id_hint": "••••dbox",
    }
    assert store.get(CONFIG_NAMESPACE, "production.client_id") == "client-sandbox"


def test_realized_gain_loss_is_not_counted_as_an_investment_deposit() -> None:
    role, confidence = _fidelity_role(
        {"type": "cash", "subtype": "deposit"},
        "VANG INST 500 IDX TR - realizedGainLoss",
    )
    assert (role, confidence) == ("adjustment", "high")


def test_fidelity_internal_transfers_and_stock_plan_credits_keep_their_roles() -> None:
    assert _fidelity_role(
        {"type": "cash", "subtype": "withdrawal"},
        "TRANSFERRED TO VS X00-000000-1",
    ) == ("internal_transfer", "medium")
    assert _fidelity_role(
        {"type": "cash", "subtype": "deposit"},
        "JOURNALED SPP PURCHASE CREDIT",
    ) == ("stock_plan_contribution", "medium")


def test_plaid_transfer_category_is_external_without_an_owned_account_marker() -> None:
    assert (
        _sofi_role(
            {
                "name": "PAYPAL",
                "personal_finance_category": {"primary": "TRANSFER_OUT", "detailed": ""},
            },
            Decimal("-25.00"),
        )
        == "external_outflow"
    )
    assert (
        _sofi_role(
            {
                "name": "To Savings - 0002",
                "personal_finance_category": {"primary": "TRANSFER_OUT", "detailed": ""},
            },
            Decimal("-25.00"),
        )
        == "internal_transfer"
    )


def test_sofi_link_sync_is_idempotent_and_revocable(session: Session) -> None:
    store = _configured_store()
    client = FakeSofiPlaidClient()
    link = create_plaid_link_session(
        session,
        environment="sandbox",
        target="sofi",
        store=store,
        client=client,
    )
    connection = exchange_plaid_public_token(
        session,
        link_session_id=link["session_id"],
        public_token="public-sandbox-sofi",
        store=store,
        client=client,
    )
    transaction = session.scalar(select(AccountTransaction))
    assert transaction is not None
    assert transaction.role == "payroll_deposit"
    assert transaction.amount == Decimal("3765.83")
    assert transaction.provider_transaction_id is not None
    assert transaction.provider_transaction_id.startswith("plaid:")
    assert "txn-payroll" not in transaction.provider_transaction_id
    assert session.scalar(select(func.count(BalanceSnapshot.id))) == 1
    assert session.scalar(select(func.count(PlaidEndpointEvidence.id))) == 3
    assert store.get(ITEM_NAMESPACE, "sandbox.item-sofi") == "access-sandbox-sofi"
    bank = session.scalar(select(Account))
    assert bank is not None
    assert bank.institution.canonical_name == "First Platypus Bank"
    assert not list(
        session.scalars(
            select(ReconciliationResult).where(ReconciliationResult.status == "unresolved")
        )
    )

    sync_plaid_connection(session, connection.id, store=store, client=client)
    assert session.scalar(select(func.count(AccountTransaction.id))) == 1
    assert session.scalar(select(func.count(BalanceSnapshot.id))) == 1
    assert session.scalar(select(func.count(ImportArtifact.id))) == 3

    revoke_plaid_connection(
        session,
        connection.id,
        delete_local_data=True,
        store=store,
        client=client,
    )
    assert client.removed
    assert session.get(PlaidConnection, connection.id) is None
    assert session.scalar(select(func.count(Account.id))) == 0
    assert store.get(ITEM_NAMESPACE, "sandbox.item-sofi") is None


def test_fidelity_link_stores_current_holdings_without_inventing_return(
    session: Session,
) -> None:
    store = _configured_store()
    client = FakeFidelityPlaidClient()
    link = create_plaid_link_session(
        session,
        environment="sandbox",
        target="fidelity",
        store=store,
        client=client,
    )
    connection = exchange_plaid_public_token(
        session,
        link_session_id=link["session_id"],
        public_token="public-sandbox-fidelity",
        store=store,
        client=client,
    )
    assert connection.status == "active"
    holding = session.scalar(select(InvestmentHolding))
    assert holding is not None
    assert holding.security_name == "Synthetic Index Fund"
    transaction = session.scalar(select(AccountTransaction))
    assert transaction is not None
    assert transaction.role == "employee_contribution"
    assert transaction.amount == Decimal("500.00")
    summary = fidelity_summary(session)
    assert summary["accounts"][0]["current_value"] == "25000.00"
    assert summary["accounts"][0]["investment_result"] is None
    assert summary["accounts"][0]["holdings"][0]["ticker"] == "SIF"
    assert summary["warnings"] == []
    dashboard = accounts_dashboard(session)
    assert dashboard["totals"]["investments"] == "25000.00"
    assert dashboard["accounts"][0]["starting_balance"] == "25000.00"
    assert dashboard["accounts"][0]["change"] is None
    assert dashboard["accounts"][0]["institution"] == "First Platypus Bank"


def _connect_synthetic_items(
    session: Session,
) -> tuple[MemorySecretStore, FakeSofiPlaidClient, FakeFidelityPlaidClient, int, int]:
    store = _configured_store()
    sofi_client = FakeSofiPlaidClient()
    sofi_link = create_plaid_link_session(
        session,
        environment="sandbox",
        target="sofi",
        store=store,
        client=sofi_client,
    )
    sofi = exchange_plaid_public_token(
        session,
        link_session_id=sofi_link["session_id"],
        public_token="public-sandbox-sofi",
        store=store,
        client=sofi_client,
    )
    fidelity_client = FakeFidelityPlaidClient()
    fidelity_link = create_plaid_link_session(
        session,
        environment="sandbox",
        target="fidelity",
        store=store,
        client=fidelity_client,
    )
    fidelity = exchange_plaid_public_token(
        session,
        link_session_id=fidelity_link["session_id"],
        public_token="public-sandbox-fidelity",
        store=store,
        client=fidelity_client,
    )
    return store, sofi_client, fidelity_client, sofi.id, fidelity.id


def test_global_refresh_updates_all_connections_and_appends_one_snapshot_per_day(
    session: Session,
) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    initial_snapshots = session.scalar(select(func.count(BalanceSnapshot.id))) or 0
    initial_transactions = session.scalar(select(func.count(AccountTransaction.id))) or 0
    next_day = datetime(2026, 8, 1, 16, tzinfo=UTC)

    result = sync_all_connections(
        session,
        store=store,
        now=next_day,
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )

    assert result["status"] == "complete"
    assert result["requested"] == result["succeeded"] == 2
    assert result["failed"] == 0
    assert session.scalar(select(func.count(BalanceSnapshot.id))) == initial_snapshots + 2
    assert session.scalar(select(func.count(AccountTransaction.id))) == initial_transactions
    assert session.scalar(select(func.count(InvestmentValueBridge.id))) == 1
    assert refresh_status(session, now=next_day)["connections_current"] == 2
    assert not list(
        session.scalars(
            select(ReconciliationResult).where(
                ReconciliationResult.rule == "account_balance",
                ReconciliationResult.status != "reconciled",
            )
        )
    )

    repeated = sync_all_connections(
        session,
        store=store,
        now=next_day,
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )
    assert repeated["succeeded"] == 2
    assert session.scalar(select(func.count(BalanceSnapshot.id))) == initial_snapshots + 2
    assert session.scalar(select(func.count(AccountTransaction.id))) == initial_transactions


def test_global_refresh_records_truthful_sequential_operation_times(session: Session) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    global_start = datetime(2026, 8, 4, 14, 0, 0, tzinfo=UTC)
    sofi_start = datetime(2026, 8, 4, 14, 0, 1, tzinfo=UTC)
    sofi_finish = datetime(2026, 8, 4, 14, 0, 2, tzinfo=UTC)
    fidelity_start = datetime(2026, 8, 4, 14, 0, 3, tzinfo=UTC)
    fidelity_finish = datetime(2026, 8, 4, 14, 0, 5, tzinfo=UTC)
    global_finish = datetime(2026, 8, 4, 14, 0, 6, tzinfo=UTC)

    result = sync_all_connections(
        session,
        store=store,
        clock=SequenceClock(
            global_start,
            sofi_start,
            sofi_finish,
            fidelity_start,
            fidelity_finish,
            global_finish,
        ),
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )

    assert result["started_at"] == global_start
    assert result["finished_at"] == global_finish
    assert result["connections"][0]["started_at"] == sofi_start
    assert result["connections"][0]["finished_at"] == sofi_finish
    assert result["connections"][1]["started_at"] == fidelity_start
    assert result["connections"][1]["finished_at"] == fidelity_finish
    latest_runs = list(
        session.scalars(
            select(PlaidSyncRun)
            .where(PlaidSyncRun.connection_id.in_([sofi_id, fidelity_id]))
            .order_by(PlaidSyncRun.id.desc())
            .limit(2)
        )
    )
    assert all(
        run.finished_at is not None and run.started_at <= run.finished_at for run in latest_runs
    )
    for row in result["connections"]:
        connection = session.get(PlaidConnection, row["connection_id"])
        assert connection is not None
        assert connection.last_synced_at is not None
        assert connection.last_synced_at.replace(tzinfo=UTC) == row["finished_at"]


def test_clock_is_clamped_when_the_system_clock_moves_backward(session: Session) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 5, 13, 59, 59, tzinfo=UTC)
    result = sync_all_connections(
        session,
        store=store,
        clock=SequenceClock(start, earlier, earlier, earlier, earlier, earlier),
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )
    assert result["finished_at"] == start
    assert all(row["started_at"] == row["finished_at"] == start for row in result["connections"])


def test_automatic_refresh_runs_once_per_local_day(session: Session) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    connections = [
        session.get(PlaidConnection, connection_id) for connection_id in (sofi_id, fidelity_id)
    ]
    last_synced = [
        connection.last_synced_at
        for connection in connections
        if connection is not None and connection.last_synced_at is not None
    ]
    assert len(last_synced) == 2
    latest_sync = max(last_synced)
    latest_sync_utc = (
        latest_sync.replace(tzinfo=UTC)
        if latest_sync.tzinfo is None
        else latest_sync.astimezone(UTC)
    )
    next_day = latest_sync_utc + timedelta(days=1)
    first = sync_all_connections(
        session,
        store=store,
        automatic=True,
        now=next_day,
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )
    second = sync_all_connections(
        session,
        store=store,
        automatic=True,
        now=next_day,
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )
    assert first["status"] == "complete"
    assert second["status"] == "skipped"
    assert second["requested"] == 0
    set_auto_refresh_enabled(session, False)
    assert (
        refresh_status(session, now=next_day + timedelta(days=1))["automatic_refresh_due"] is False
    )


def test_automatic_refresh_skips_provider_calls_when_connections_are_current(
    session: Session,
) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    current = datetime(2026, 8, 6, 15, tzinfo=UTC)
    for connection_id in (sofi_id, fidelity_id):
        connection = session.get(PlaidConnection, connection_id)
        assert connection is not None
        connection.last_synced_at = current
    session.commit()
    run_count = session.scalar(select(func.count(PlaidSyncRun.id)))

    result = sync_all_connections(
        session,
        store=store,
        automatic=True,
        clock=SequenceClock(current, current),
        clients={sofi_id: sofi_client, fidelity_id: fidelity_client},
    )

    assert result["status"] == "skipped"
    assert result["requested"] == 0
    assert session.scalar(select(func.count(PlaidSyncRun.id))) == run_count


def test_global_refresh_isolates_connection_failure_and_preserves_previous_data(
    session: Session,
) -> None:
    store, sofi_client, fidelity_client, sofi_id, fidelity_id = _connect_synthetic_items(session)
    del fidelity_client
    transaction_count = session.scalar(select(func.count(AccountTransaction.id)))
    snapshot_count = session.scalar(select(func.count(BalanceSnapshot.id))) or 0
    sofi = session.get(PlaidConnection, sofi_id)
    assert sofi is not None
    assert sofi.last_synced_at is not None
    latest_sync = sofi.last_synced_at
    latest_sync_utc = (
        latest_sync.replace(tzinfo=UTC)
        if latest_sync.tzinfo is None
        else latest_sync.astimezone(UTC)
    )
    result = sync_all_connections(
        session,
        store=store,
        now=latest_sync_utc + timedelta(days=1),
        clients={sofi_id: sofi_client, fidelity_id: FailingFidelityPlaidClient()},
    )
    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["connections"][1]["error_code"] == "NETWORK_ERROR"
    fidelity = session.get(PlaidConnection, fidelity_id)
    assert fidelity is not None
    assert fidelity.status == "temporarily_unavailable"
    assert result["connections"][1]["started_at"] <= result["connections"][1]["finished_at"]
    assert fidelity.last_synced_at is not None
    assert result["connections"][1]["last_synced_at"] == fidelity.last_synced_at.replace(tzinfo=UTC)
    assert session.scalar(select(func.count(AccountTransaction.id))) == transaction_count
    assert session.scalar(select(func.count(BalanceSnapshot.id))) == snapshot_count + 1


def test_refresh_lock_rejects_overlapping_global_refresh(session: Session) -> None:
    with refresh_guard(), pytest.raises(RefreshAlreadyRunningError):
        sync_all_connections(session)
