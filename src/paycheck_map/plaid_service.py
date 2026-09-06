from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import plaid_records
from .business_time import as_utc, clock_timestamp, local_business_date
from .keychain import SecretStore, SecretStoreError, keychain
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    ForecastScenario,
    ImportArtifact,
    ImportBatch,
    Institution,
    InvestmentHolding,
    PlaidConnection,
    PlaidEndpointEvidence,
    PlaidLinkSession,
    PlaidSyncRun,
    SourceEvidence,
)
from .money import money
from .plaid_client import JsonObject, PlaidAPIError, PlaidClient
from .reconciliation import reconcile_all

PlaidEnvironment = Literal["sandbox", "production"]
PlaidTarget = Literal["sofi", "fidelity"]

PARSER_VERSION = "1.0.2"
CONFIG_NAMESPACE = "plaid.config"
ITEM_NAMESPACE = "plaid.items"
Clock = Callable[[], datetime]


def _system_clock() -> datetime:
    return datetime.now(UTC)


def configure_plaid(
    *,
    environment: PlaidEnvironment,
    client_id: str,
    secret: str,
    store: SecretStore = keychain,
) -> None:
    other_environment = "production" if environment == "sandbox" else "sandbox"
    clean_client = (
        client_id.strip()
        or store.get(CONFIG_NAMESPACE, f"{environment}.client_id")
        or store.get(CONFIG_NAMESPACE, f"{other_environment}.client_id")
        or ""
    )
    clean_secret = secret.strip()
    if len(clean_client) < 8 or len(clean_secret) < 8:
        raise ValueError("Plaid client ID and secret are required")
    client_account = f"{environment}.client_id"
    secret_account = f"{environment}.secret"
    prior_client = store.get(CONFIG_NAMESPACE, client_account)
    prior_secret = store.get(CONFIG_NAMESPACE, secret_account)
    prior_user = store.get(CONFIG_NAMESPACE, "client_user_id")
    try:
        store.set(CONFIG_NAMESPACE, client_account, clean_client)
        store.set(CONFIG_NAMESPACE, secret_account, clean_secret)
        if prior_user is None:
            store.set(CONFIG_NAMESPACE, "client_user_id", str(uuid4()))
    except Exception as setup_error:
        rollback_failed = False
        for account, value in (
            (client_account, prior_client),
            (secret_account, prior_secret),
            ("client_user_id", prior_user),
        ):
            try:
                if value is None:
                    store.delete(CONFIG_NAMESPACE, account)
                else:
                    store.set(CONFIG_NAMESPACE, account, value)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise SecretStoreError(
                "Plaid setup failed and the prior Keychain configuration could not be "
                "fully restored."
            ) from setup_error
        raise


def clear_plaid_configuration(environment: PlaidEnvironment, store: SecretStore = keychain) -> None:
    store.delete(CONFIG_NAMESPACE, f"{environment}.client_id")
    store.delete(CONFIG_NAMESPACE, f"{environment}.secret")


def plaid_configuration_status(store: SecretStore = keychain) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for environment in ("sandbox", "production"):
        other_environment = "production" if environment == "sandbox" else "sandbox"
        client_id = store.get(CONFIG_NAMESPACE, f"{environment}.client_id") or store.get(
            CONFIG_NAMESPACE, f"{other_environment}.client_id"
        )
        secret = store.get(CONFIG_NAMESPACE, f"{environment}.secret")
        output[environment] = {
            "configured": bool(client_id and secret),
            "client_id_hint": f"••••{client_id[-4:]}" if client_id else None,
        }
    return output


def _client(
    environment: PlaidEnvironment,
    store: SecretStore,
    supplied: PlaidClient | None,
) -> PlaidClient:
    if supplied is not None:
        return supplied
    other_environment = "production" if environment == "sandbox" else "sandbox"
    client_id = store.get(CONFIG_NAMESPACE, f"{environment}.client_id") or store.get(
        CONFIG_NAMESPACE, f"{other_environment}.client_id"
    )
    secret = store.get(CONFIG_NAMESPACE, f"{environment}.secret")
    if not client_id or not secret:
        raise ValueError(f"Plaid {environment} credentials are not configured")
    return PlaidClient(environment=environment, client_id=client_id, secret=secret)


def _client_user_id(store: SecretStore) -> str:
    existing = store.get(CONFIG_NAMESPACE, "client_user_id")
    if existing:
        return existing
    generated = str(uuid4())
    store.set(CONFIG_NAMESPACE, "client_user_id", generated)
    return generated


def create_plaid_link_session(
    session: Session,
    *,
    environment: PlaidEnvironment,
    target: PlaidTarget,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> dict[str, Any]:
    api = _client(environment, store, client)
    response = api.create_link_token(
        target=target,
        client_user_id=_client_user_id(store),
    )
    link_token = plaid_records.required_text(response, "link_token")
    expires_at = plaid_records.parse_datetime(plaid_records.required_text(response, "expiration"))
    local_session = PlaidLinkSession(
        id=str(uuid4()),
        environment=environment,
        target=target,
        expires_at=expires_at,
    )
    session.add(local_session)
    session.commit()
    return {
        "session_id": local_session.id,
        "link_token": link_token,
        "expiration": expires_at,
        "environment": environment,
        "target": target,
    }


def create_plaid_update_session(
    session: Session,
    connection_id: int,
    *,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> dict[str, Any]:
    connection = session.get(PlaidConnection, connection_id)
    if connection is None:
        raise ValueError("Plaid connection was not found")
    environment = _environment(connection.environment)
    access_token = _access_token(connection, store)
    response = _client(environment, store, client).create_update_link_token(
        access_token=access_token,
        client_user_id=_client_user_id(store),
    )
    return {
        "connection_id": connection.id,
        "link_token": plaid_records.required_text(response, "link_token"),
        "expiration": plaid_records.parse_datetime(
            plaid_records.required_text(response, "expiration")
        ),
        "environment": connection.environment,
        "target": connection.target,
    }


def exchange_plaid_public_token(
    session: Session,
    *,
    link_session_id: str,
    public_token: str,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> PlaidConnection:
    link_session = session.get(PlaidLinkSession, link_session_id)
    if link_session is None:
        raise ValueError("Plaid link session was not found")
    now = datetime.now(UTC)
    if link_session.used_at is not None:
        raise ValueError("Plaid link session has already been used")
    if as_utc(link_session.expires_at) <= now:
        raise ValueError("Plaid link session has expired")
    environment = _environment(link_session.environment)
    target = _target(link_session.target)
    api = _client(environment, store, client)
    exchange = api.exchange_public_token(public_token)
    access_token = plaid_records.required_text(exchange, "access_token")
    item_id = plaid_records.required_text(exchange, "item_id")
    item_response = api.item_get(access_token)
    item = plaid_records.object_fields(item_response.get("item"))
    institution_id = plaid_records.optional_text(item.get("institution_id"))
    institution_name = "Sandbox institution" if environment == "sandbox" else "Institution"
    if institution_id:
        institution_response = api.institution_get(institution_id)
        institution = plaid_records.object_fields(institution_response.get("institution"))
        institution_name = plaid_records.optional_text(institution.get("name")) or institution_name
    consent_expires_at = plaid_records.optional_datetime(item.get("consent_expiration_time"))

    existing = session.scalar(select(PlaidConnection).where(PlaidConnection.item_id == item_id))
    if existing is not None:
        raise ValueError("This Plaid item is already connected")

    connection = PlaidConnection(
        environment=environment,
        target=target,
        item_id=item_id,
        institution_id=institution_id,
        institution_name=institution_name,
        products=["transactions"] if target == "sofi" else ["investments"],
        consent_expires_at=consent_expires_at,
    )
    session.add(connection)
    link_session.used_at = now
    session.flush()
    store.set(ITEM_NAMESPACE, _item_key(environment, item_id), access_token)
    try:
        session.commit()
    except Exception:
        store.delete(ITEM_NAMESPACE, _item_key(environment, item_id))
        raise
    try:
        sync_plaid_connection(session, connection.id, store=store, client=api)
    except PlaidAPIError:
        session.refresh(connection)
    return connection


def sync_plaid_connection(
    session: Session,
    connection_id: int,
    *,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
    business_date: date | None = None,
    started_at: datetime | None = None,
    clock: Clock | None = None,
) -> PlaidConnection:
    operation_clock = clock or _system_clock
    operation_started_at = as_utc(started_at or operation_clock())
    connection = session.get(PlaidConnection, connection_id)
    if connection is None:
        raise ValueError("Plaid connection was not found")
    if connection.status == "revoked":
        raise ValueError("Plaid connection has been revoked")
    environment = _environment(connection.environment)
    target = _target(connection.target)
    api = _client(environment, store, client)
    access_token = _access_token(connection, store)
    snapshot_date = business_date or local_business_date(operation_started_at)
    batch = ImportBatch(
        requested_source=f"plaid_{environment}",
        status="running",
    )
    session.add(batch)
    session.flush()
    run = PlaidSyncRun(
        connection_id=connection.id,
        batch_id=batch.id,
        started_at=operation_started_at,
    )
    session.add(run)
    session.flush()

    endpoint_count = 0
    new_artifacts = 0
    duplicate_artifacts = 0
    account_ids: set[int] = set()
    transaction_count = 0
    holding_count = 0
    next_cursor = connection.transactions_cursor
    savepoint = session.begin_nested()
    try:
        if target == "sofi":
            pages = _transactions_pages(api, access_token, connection.transactions_cursor)
            for page_number, response in enumerate(pages, start=1):
                artifact, created = _record_endpoint(
                    session,
                    run=run,
                    batch=batch,
                    connection=connection,
                    endpoint=f"/transactions/sync?page={page_number}",
                    response=response,
                    record_count=plaid_records.list_count(response, "added")
                    + plaid_records.list_count(response, "modified")
                    + plaid_records.list_count(response, "removed"),
                )
                endpoint_count += 1
                new_artifacts += int(created)
                duplicate_artifacts += int(not created)
                changed, seen_accounts = _store_sofi_transactions(
                    session, connection, artifact, response
                )
                transaction_count += changed
                account_ids.update(seen_accounts)
                next_cursor = (
                    plaid_records.optional_text(response.get("next_cursor")) or next_cursor
                )
            history_pages = api.transactions_get(access_token, end_date=snapshot_date)
            for page_number, response in enumerate(history_pages, start=1):
                artifact, created = _record_endpoint(
                    session,
                    run=run,
                    batch=batch,
                    connection=connection,
                    endpoint=f"/transactions/get?page={page_number}",
                    response=response,
                    record_count=plaid_records.list_count(response, "transactions"),
                )
                endpoint_count += 1
                new_artifacts += int(created)
                duplicate_artifacts += int(not created)
                normalized: JsonObject = {
                    "accounts": response.get("accounts", []),
                    "added": response.get("transactions", []),
                    "modified": [],
                    "removed": [],
                }
                changed, seen_accounts = _store_sofi_transactions(
                    session, connection, artifact, normalized
                )
                transaction_count += changed
                account_ids.update(seen_accounts)
            balances = api.accounts_balance_get(access_token)
            balance_artifact, created = _record_endpoint(
                session,
                run=run,
                batch=batch,
                connection=connection,
                endpoint="/accounts/balance/get",
                response=balances,
                record_count=plaid_records.list_count(balances, "accounts"),
            )
            endpoint_count += 1
            new_artifacts += int(created)
            duplicate_artifacts += int(not created)
            account_ids.update(
                _store_current_balances(
                    session,
                    connection,
                    balance_artifact,
                    balances,
                    snapshot_date=snapshot_date,
                )
            )
        else:
            holdings = api.investments_holdings_get(access_token)
            holdings_artifact, created = _record_endpoint(
                session,
                run=run,
                batch=batch,
                connection=connection,
                endpoint="/investments/holdings/get",
                response=holdings,
                record_count=plaid_records.list_count(holdings, "holdings"),
            )
            endpoint_count += 1
            new_artifacts += int(created)
            duplicate_artifacts += int(not created)
            seen_accounts, holding_count = _store_fidelity_holdings(
                session,
                connection,
                holdings_artifact,
                holdings,
                snapshot_date=snapshot_date,
            )
            account_ids.update(seen_accounts)
            investment_pages = api.investments_transactions_get(
                access_token, end_date=snapshot_date
            )
            for page_number, response in enumerate(investment_pages, start=1):
                artifact, created = _record_endpoint(
                    session,
                    run=run,
                    batch=batch,
                    connection=connection,
                    endpoint=f"/investments/transactions/get?page={page_number}",
                    response=response,
                    record_count=plaid_records.list_count(response, "investment_transactions"),
                )
                endpoint_count += 1
                new_artifacts += int(created)
                duplicate_artifacts += int(not created)
                changed, seen_accounts = _store_fidelity_transactions(
                    session, connection, artifact, response
                )
                transaction_count += changed
                account_ids.update(seen_accounts)

        session.execute(delete(ForecastScenario))
        reconcile_all(session)
        savepoint.commit()
    except PlaidAPIError as exc:
        savepoint.rollback()
        run.status = "failed"
        run.finished_at = clock_timestamp(operation_clock, not_before=operation_started_at)
        run.error_code = exc.code
        run.error_message = exc.safe_message
        batch.status = "complete_with_errors"
        batch.error_count = 1
        connection.status = (
            "temporarily_unavailable"
            if exc.code
            in {
                "INSTITUTION_DOWN",
                "INSTITUTION_NOT_RESPONDING",
                "INTERNAL_SERVER_ERROR",
                "NETWORK_ERROR",
                "PRODUCT_NOT_READY",
                "RATE_LIMIT_EXCEEDED",
            }
            else "needs_attention"
        )
        connection.last_error = f"{exc.code}: {exc.safe_message}"[:500]
        session.commit()
        raise
    except Exception:
        savepoint.rollback()
        run.status = "failed"
        run.finished_at = clock_timestamp(operation_clock, not_before=operation_started_at)
        run.error_code = "LOCAL_SYNC_ERROR"
        run.error_message = "Local normalization failed; no partial sync was committed."
        batch.status = "complete_with_errors"
        batch.error_count = 1
        connection.status = "needs_attention"
        connection.last_error = run.error_message
        session.commit()
        raise

    now = clock_timestamp(operation_clock, not_before=operation_started_at)
    run.status = "complete"
    run.finished_at = now
    run.account_count = len(account_ids)
    run.transaction_count = transaction_count
    run.holding_count = holding_count
    batch.artifact_count = endpoint_count
    batch.imported_count = new_artifacts
    batch.duplicate_count = duplicate_artifacts
    batch.status = "complete"
    connection.transactions_cursor = next_cursor
    connection.last_synced_at = now
    connection.last_error = None
    connection.status = "active"
    connection.updated_at = now
    session.commit()
    return connection


def revoke_plaid_connection(
    session: Session,
    connection_id: int,
    *,
    delete_local_data: bool,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> None:
    connection = session.get(PlaidConnection, connection_id)
    if connection is None:
        raise ValueError("Plaid connection was not found")
    environment = _environment(connection.environment)
    access_token = store.get(ITEM_NAMESPACE, _item_key(environment, connection.item_id))
    if access_token and connection.status != "revoked":
        _client(environment, store, client).remove_item(access_token)
    store.delete(ITEM_NAMESPACE, _item_key(environment, connection.item_id))
    if delete_local_data:
        account_ids = list(
            session.scalars(select(Account.id).where(Account.plaid_connection_id == connection.id))
        )
        transaction_ids = list(
            session.scalars(
                select(AccountTransaction.id).where(AccountTransaction.account_id.in_(account_ids))
            )
        )
        balance_ids = list(
            session.scalars(
                select(BalanceSnapshot.id).where(BalanceSnapshot.account_id.in_(account_ids))
            )
        )
        if transaction_ids:
            session.execute(
                delete(SourceEvidence).where(
                    SourceEvidence.entity_type == "account_transaction",
                    SourceEvidence.entity_id.in_([str(value) for value in transaction_ids]),
                )
            )
        if balance_ids:
            session.execute(
                delete(SourceEvidence).where(
                    SourceEvidence.entity_type == "balance_snapshot",
                    SourceEvidence.entity_id.in_([str(value) for value in balance_ids]),
                )
            )
        session.delete(connection)
    else:
        connection.status = "revoked"
        connection.last_error = None
        connection.updated_at = datetime.now(UTC)
    session.execute(delete(ForecastScenario))
    reconcile_all(session)
    session.commit()


def plaid_status(session: Session, store: SecretStore = keychain) -> dict[str, Any]:
    connections = list(
        session.scalars(select(PlaidConnection).order_by(PlaidConnection.created_at))
    )
    connection_rows: list[dict[str, Any]] = []
    for connection in connections:
        account_count = session.scalar(
            select(func.count(Account.id)).where(Account.plaid_connection_id == connection.id)
        )
        latest_run = session.scalar(
            select(PlaidSyncRun)
            .where(PlaidSyncRun.connection_id == connection.id)
            .order_by(PlaidSyncRun.started_at.desc())
            .limit(1)
        )
        coverage = session.execute(
            select(
                func.min(AccountTransaction.posted_date),
                func.max(AccountTransaction.posted_date),
            )
            .join(Account, AccountTransaction.account_id == Account.id)
            .where(Account.plaid_connection_id == connection.id)
        ).one()
        connection_rows.append(
            {
                "id": connection.id,
                "environment": connection.environment,
                "target": connection.target,
                "institution_name": connection.institution_name,
                "status": connection.status,
                "products": connection.products,
                "consent_expires_at": connection.consent_expires_at,
                "last_synced_at": (
                    as_utc(connection.last_synced_at)
                    if connection.last_synced_at is not None
                    else None
                ),
                "last_error": connection.last_error,
                "account_count": int(account_count or 0),
                "history_start": coverage[0],
                "history_end": coverage[1],
                "latest_sync": (
                    None
                    if latest_run is None
                    else {
                        "status": latest_run.status,
                        "accounts": latest_run.account_count,
                        "transactions": latest_run.transaction_count,
                        "holdings": latest_run.holding_count,
                        "started_at": as_utc(latest_run.started_at),
                        "finished_at": (
                            as_utc(latest_run.finished_at)
                            if latest_run.finished_at is not None
                            else None
                        ),
                    }
                ),
            }
        )
    return {
        "configuration": plaid_configuration_status(store),
        "connections": connection_rows,
        "security": {
            "credentials": "macOS Keychain",
            "bank_passwords_stored": False,
            "money_movement_enabled": False,
            "data_transit": "Plaid receives user-authorized account data during sync.",
        },
    }


def _transactions_pages(
    client: PlaidClient, access_token: str, cursor: str | None
) -> list[JsonObject]:
    try:
        return client.transactions_sync(access_token, cursor)
    except PlaidAPIError as exc:
        if exc.code != "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
            raise
        return client.transactions_sync(access_token, None)


def _record_endpoint(
    session: Session,
    *,
    run: PlaidSyncRun,
    batch: ImportBatch,
    connection: PlaidConnection,
    endpoint: str,
    response: JsonObject,
    record_count: int,
) -> tuple[ImportArtifact, bool]:
    serialized = json.dumps(
        response,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    digest = hashlib.sha256(serialized).hexdigest()
    artifact = session.scalar(select(ImportArtifact).where(ImportArtifact.sha256 == digest))
    created = artifact is None
    if artifact is None:
        safe_endpoint = endpoint.split("?")[0].strip("/").replace("/", "-")
        artifact = ImportArtifact(
            batch_id=batch.id,
            sha256=digest,
            original_filename=(f"plaid-{connection.target}-{safe_endpoint}-{digest[:12]}.json"),
            source_kind=f"plaid_{connection.environment}",
            adapter=f"plaid_{connection.target}",
            parser_version=PARSER_VERSION,
        )
        session.add(artifact)
        session.flush()
    session.add(
        PlaidEndpointEvidence(
            sync_run_id=run.id,
            artifact_id=artifact.id,
            endpoint=endpoint,
            request_id=plaid_records.optional_text(response.get("request_id")),
            response_sha256=digest,
            record_count=record_count,
            parser_version=PARSER_VERSION,
        )
    )
    return artifact, created


def _institution(session: Session, connection: PlaidConnection) -> Institution:
    target = _target(connection.target)
    name = connection.institution_name.strip() or "Connected institution"
    institution = session.scalar(select(Institution).where(Institution.canonical_name == name))
    if institution is None:
        institution = Institution(
            canonical_name=name,
            kind="bank" if target == "sofi" else "investment",
        )
        session.add(institution)
        session.flush()
    return institution


def _store_accounts(
    session: Session,
    connection: PlaidConnection,
    rows: list[object],
) -> dict[str, Account]:
    institution = _institution(session, connection)
    accounts: dict[str, Account] = {}
    for raw in rows:
        row = plaid_records.object_fields(raw)
        provider_account_id = plaid_records.required_text(row, "account_id")
        external_key = _provider_key(
            connection.item_id,
            "account",
            provider_account_id,
        )
        account = session.scalar(
            select(Account).where(
                Account.plaid_connection_id == connection.id,
                Account.external_key == external_key,
            )
        )
        if account is None:
            account = Account(
                institution_id=institution.id,
                plaid_connection_id=connection.id,
                external_key=external_key,
                display_name=plaid_records.account_display_name(row),
                account_type=plaid_records.optional_text(row.get("subtype"))
                or plaid_records.optional_text(row.get("type"))
                or "other",
            )
            session.add(account)
            session.flush()
        else:
            account.display_name = plaid_records.account_display_name(row)
            account.account_type = (
                plaid_records.optional_text(row.get("subtype"))
                or plaid_records.optional_text(row.get("type"))
                or account.account_type
            )
        accounts[provider_account_id] = account
    return accounts


def _store_current_balances(
    session: Session,
    connection: PlaidConnection,
    artifact: ImportArtifact,
    response: JsonObject,
    *,
    snapshot_date: date,
) -> set[int]:
    account_rows = plaid_records.object_records(response.get("accounts"))
    accounts = _store_accounts(session, connection, list(account_rows))
    for row in account_rows:
        external_key = plaid_records.required_text(row, "account_id")
        account = accounts[external_key]
        balances = plaid_records.object_fields(row.get("balances"))
        raw_amount = balances.get("current")
        if raw_amount is None:
            raw_amount = balances.get("available")
        if raw_amount is None:
            raise ValueError("Plaid returned an account without an available balance")
        value = plaid_records.money_amount(raw_amount)
        snapshot = session.scalar(
            select(BalanceSnapshot).where(
                BalanceSnapshot.account_id == account.id,
                BalanceSnapshot.snapshot_date == snapshot_date,
                BalanceSnapshot.kind == "current",
            )
        )
        if snapshot is None:
            snapshot = BalanceSnapshot(
                account_id=account.id,
                artifact_id=artifact.id,
                snapshot_date=snapshot_date,
                kind="current",
                amount=value,
            )
            session.add(snapshot)
        else:
            snapshot.artifact_id = artifact.id
            snapshot.amount = value
    session.flush()
    return {account.id for account in accounts.values()}


def _store_sofi_transactions(
    session: Session,
    connection: PlaidConnection,
    artifact: ImportArtifact,
    response: JsonObject,
) -> tuple[int, set[int]]:
    accounts = _store_accounts(
        session, connection, list(plaid_records.object_records(response.get("accounts")))
    )
    for removed in plaid_records.object_records(response.get("removed")):
        transaction_id = plaid_records.optional_text(removed.get("transaction_id"))
        if transaction_id:
            _delete_provider_transaction(
                session,
                _provider_key(connection.item_id, "transaction", transaction_id),
            )
    changed = 0
    for source_row, row in enumerate(
        [
            *plaid_records.object_records(response.get("added")),
            *plaid_records.object_records(response.get("modified")),
        ],
        start=1,
    ):
        if bool(row.get("pending")):
            continue
        account = accounts.get(plaid_records.required_text(row, "account_id"))
        if account is None:
            raise ValueError("Plaid returned a record without a matching account")
        provider_id = _provider_key(
            connection.item_id,
            "transaction",
            plaid_records.required_text(row, "transaction_id"),
        )
        normalized_amount = money(-plaid_records.decimal_amount(row.get("amount")))
        role = plaid_records.sofi_role(row, normalized_amount)
        description = (
            plaid_records.optional_text(row.get("merchant_name"))
            or plaid_records.optional_text(row.get("name"))
            or plaid_records.optional_text(row.get("original_description"))
            or ""
        )
        _upsert_transaction(
            session,
            artifact=artifact,
            account=account,
            provider_id=provider_id,
            posted_date=plaid_records.parse_date(plaid_records.required_text(row, "date")),
            description=description,
            role=role,
            amount=normalized_amount,
            source_row=source_row,
            confidence="high" if role != "internal_transfer" else "medium",
        )
        changed += 1
    return changed, {account.id for account in accounts.values()}


def _store_fidelity_holdings(
    session: Session,
    connection: PlaidConnection,
    artifact: ImportArtifact,
    response: JsonObject,
    *,
    snapshot_date: date,
) -> tuple[set[int], int]:
    account_rows = plaid_records.object_records(response.get("accounts"))
    accounts = _store_accounts(session, connection, list(account_rows))
    _store_current_balances(
        session,
        connection,
        artifact,
        response,
        snapshot_date=snapshot_date,
    )
    account_ids = {account.id for account in accounts.values()}
    if account_ids:
        session.execute(
            delete(InvestmentHolding).where(InvestmentHolding.account_id.in_(account_ids))
        )
    securities = {
        plaid_records.required_text(row, "security_id"): row
        for row in plaid_records.object_records(response.get("securities"))
    }
    holding_count = 0
    for row in plaid_records.object_records(response.get("holdings")):
        account = accounts.get(plaid_records.required_text(row, "account_id"))
        if account is None:
            raise ValueError("Plaid returned a record without a matching account")
        security_id = plaid_records.required_text(row, "security_id")
        security = securities.get(security_id, {})
        raw_as_of = security.get("close_price_as_of")
        holding = InvestmentHolding(
            account_id=account.id,
            artifact_id=artifact.id,
            security_id=security_id,
            security_name=(
                plaid_records.optional_text(security.get("name"))
                or plaid_records.optional_text(security.get("ticker_symbol"))
                or "Unidentified security"
            ),
            ticker_symbol=plaid_records.optional_text(security.get("ticker_symbol")),
            security_type=plaid_records.optional_text(security.get("type")) or "other",
            quantity=plaid_records.decimal_amount(row.get("quantity")),
            institution_price=plaid_records.optional_money(row.get("institution_price")),
            institution_value=plaid_records.money_amount(row.get("institution_value")),
            cost_basis=plaid_records.optional_money(row.get("cost_basis")),
            as_of=plaid_records.parse_date(str(raw_as_of)) if raw_as_of else snapshot_date,
        )
        session.add(holding)
        holding_count += 1
    session.flush()
    return account_ids, holding_count


def _store_fidelity_transactions(
    session: Session,
    connection: PlaidConnection,
    artifact: ImportArtifact,
    response: JsonObject,
) -> tuple[int, set[int]]:
    accounts = _store_accounts(
        session, connection, list(plaid_records.object_records(response.get("accounts")))
    )
    changed = 0
    for source_row, row in enumerate(
        plaid_records.object_records(response.get("investment_transactions")), start=1
    ):
        account = accounts.get(plaid_records.required_text(row, "account_id"))
        if account is None:
            raise ValueError("Plaid returned a record without a matching account")
        provider_id = _provider_key(
            connection.item_id,
            "investment",
            plaid_records.required_text(row, "investment_transaction_id"),
        )
        normalized_amount = money(-plaid_records.decimal_amount(row.get("amount")))
        description = plaid_records.optional_text(row.get("name")) or ""
        role, confidence = plaid_records.fidelity_role(row, description)
        _upsert_transaction(
            session,
            artifact=artifact,
            account=account,
            provider_id=provider_id,
            posted_date=plaid_records.parse_date(plaid_records.required_text(row, "date")),
            description=description,
            role=role,
            amount=normalized_amount,
            source_row=source_row,
            confidence=confidence,
        )
        changed += 1
    return changed, {account.id for account in accounts.values()}


def _upsert_transaction(
    session: Session,
    *,
    artifact: ImportArtifact,
    account: Account,
    provider_id: str,
    posted_date: date,
    description: str,
    role: str,
    amount: Decimal,
    source_row: int,
    confidence: str,
) -> None:
    transaction = session.scalar(
        select(AccountTransaction).where(AccountTransaction.provider_transaction_id == provider_id)
    )
    if transaction is None:
        transaction = AccountTransaction(
            account_id=account.id,
            artifact_id=artifact.id,
            posted_date=posted_date,
            original_description=description,
            role=role,
            amount=amount,
            balance_after=None,
            source_row=source_row,
            provider_transaction_id=provider_id,
        )
        session.add(transaction)
        session.flush()
    else:
        transaction.account_id = account.id
        transaction.artifact_id = artifact.id
        transaction.posted_date = posted_date
        transaction.original_description = description
        transaction.role = role
        transaction.amount = amount
        transaction.source_row = source_row
        session.flush()
        session.execute(
            delete(SourceEvidence).where(
                SourceEvidence.entity_type == "account_transaction",
                SourceEvidence.entity_id == str(transaction.id),
            )
        )
    session.add(
        SourceEvidence(
            artifact_id=artifact.id,
            entity_type="account_transaction",
            entity_id=str(transaction.id),
            field_name="amount",
            location="Plaid API normalized record",
            original_label=role,
            extraction_method="plaid_api",
            confidence=confidence,
        )
    )


def _delete_provider_transaction(session: Session, provider_id: str) -> None:
    transaction = session.scalar(
        select(AccountTransaction).where(AccountTransaction.provider_transaction_id == provider_id)
    )
    if transaction is None:
        return
    session.execute(
        delete(SourceEvidence).where(
            SourceEvidence.entity_type == "account_transaction",
            SourceEvidence.entity_id == str(transaction.id),
        )
    )
    session.delete(transaction)


def _access_token(connection: PlaidConnection, store: SecretStore) -> str:
    environment = _environment(connection.environment)
    token = store.get(ITEM_NAMESPACE, _item_key(environment, connection.item_id))
    if not token:
        raise ValueError("Plaid access token is missing from macOS Keychain; reconnect the account")
    return token


def _item_key(environment: PlaidEnvironment, item_id: str) -> str:
    return f"{environment}.{item_id}"


def _provider_key(item_id: str, record_kind: str, provider_id: str) -> str:
    digest = hashlib.sha256(f"{item_id}:{record_kind}:{provider_id}".encode()).hexdigest()
    return f"plaid:{digest}"


def _environment(value: str) -> PlaidEnvironment:
    if value == "sandbox":
        return "sandbox"
    if value == "production":
        return "production"
    raise ValueError("Stored Plaid environment is invalid")


def _target(value: str) -> PlaidTarget:
    if value == "sofi":
        return "sofi"
    if value == "fidelity":
        return "fidelity"
    raise ValueError("Stored Plaid target is invalid")
