"""Optional read-only Plaid configuration and synchronization routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .api_inputs import (
    AutoRefreshPreferenceInput,
    PlaidConfigurationInput,
    PlaidExchangeInput,
    PlaidLinkInput,
    PlaidSyncAllInput,
)
from .config import settings
from .db import get_session
from .desktop_policy import uses_memory_secret_store
from .goal_operations import (
    exchange_token_with_goal_observation,
    sync_connection_with_goal_observation,
)
from .keychain import MemorySecretStore, SecretStore, SecretStoreError, keychain
from .plaid_client import PlaidAPIError
from .plaid_service import (
    clear_plaid_configuration,
    configure_plaid,
    create_plaid_link_session,
    create_plaid_update_session,
    plaid_configuration_status,
    plaid_status,
    revoke_plaid_connection,
)
from .refresh import (
    RefreshAlreadyRunningError,
    local_business_date,
    refresh_guard,
    refresh_status,
    set_auto_refresh_enabled,
    sync_all_connections,
)

router = APIRouter(prefix="/api")
_acceptance_secret_store = MemorySecretStore()


def get_secret_store() -> SecretStore:
    if settings.desktop_mode and uses_memory_secret_store(settings.desktop_data_mode):
        return _acceptance_secret_store
    return keychain


@router.get("/plaid/status")
def get_plaid_status(
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        status = plaid_status(session, store)
        status["refresh"] = refresh_status(session)
        return status
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/plaid/sync-all")
def sync_all_plaid(
    payload: PlaidSyncAllInput,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        return sync_all_connections(session, store=store, automatic=payload.automatic)
    except RefreshAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/plaid/refresh-preference")
def update_refresh_preference(
    payload: AutoRefreshPreferenceInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    set_auto_refresh_enabled(session, payload.enabled)
    return refresh_status(session)


@router.post("/plaid/configuration")
def set_plaid_configuration(
    payload: PlaidConfigurationInput,
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        from .native_secrets import request_plaid_credentials

        client_id, secret = request_plaid_credentials()
        configure_plaid(
            environment=payload.environment,
            client_id=client_id,
            secret=secret,
            store=store,
        )
        return plaid_configuration_status(store)
    except (ValueError, SecretStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail="Plaid setup did not complete.") from exc


@router.delete("/plaid/configuration/{environment}")
def delete_plaid_configuration(
    environment: Literal["sandbox", "production"],
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, bool]:
    try:
        clear_plaid_configuration(environment, store)
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"cleared": True}


@router.post("/plaid/link-token")
def create_link_token(
    payload: PlaidLinkInput,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        return create_plaid_link_session(
            session,
            environment=payload.environment,
            target=payload.target,
            store=store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlaidAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Plaid {exc.code}: {exc.safe_message}",
        ) from exc


@router.post("/plaid/exchange")
def exchange_link_token(
    payload: PlaidExchangeInput,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        connection, observation = exchange_token_with_goal_observation(
            session,
            link_session_id=payload.session_id,
            public_token=payload.public_token.get_secret_value(),
            observed_on=local_business_date(),
            store=store,
        )
        return {
            "connection_id": connection.id,
            "status": connection.status,
            "target": connection.target,
            "goal_observation": observation.model_dump(mode="json"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlaidAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Plaid {exc.code}: {exc.safe_message}",
        ) from exc


@router.post("/plaid/connections/{connection_id}/sync")
def sync_connection(
    connection_id: int,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        with refresh_guard():
            connection, observation = sync_connection_with_goal_observation(
                session,
                connection_id,
                observed_on=local_business_date(),
                store=store,
            )
        return {
            "connection_id": connection.id,
            "status": connection.status,
            "last_synced_at": connection.last_synced_at,
            "goal_observation": observation.model_dump(mode="json"),
        }
    except RefreshAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlaidAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Plaid {exc.code}: {exc.safe_message}",
        ) from exc


@router.post("/plaid/connections/{connection_id}/update-token")
def create_update_token(
    connection_id: int,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, Any]:
    try:
        return create_plaid_update_session(
            session,
            connection_id,
            store=store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SecretStoreError, PlaidAPIError) as exc:
        detail = (
            f"Plaid {exc.code}: {exc.safe_message}" if isinstance(exc, PlaidAPIError) else str(exc)
        )
        raise HTTPException(status_code=502, detail=detail) from exc


@router.delete("/plaid/connections/{connection_id}")
def disconnect_plaid(
    connection_id: int,
    delete_local_data: bool = True,
    session: Session = Depends(get_session),
    store: SecretStore = Depends(get_secret_store),
) -> dict[str, bool]:
    try:
        revoke_plaid_connection(
            session,
            connection_id,
            delete_local_data=delete_local_data,
            store=store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PlaidAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Plaid {exc.code}: {exc.safe_message}",
        ) from exc
    return {"disconnected": True, "local_data_deleted": delete_local_data}
