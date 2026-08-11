"""Outer mutation workflows that coordinate durable goal observations exactly once."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, settings
from .goal_observation import (
    CompletedOperationState,
    SourceCurrentnessUpdate,
    coordinate_goal_observation,
    operation_evidence_ref,
    plaid_source_key,
)
from .goal_service import GoalCheckInTrigger
from .ingestion import ImportOutcome, import_private_inbox
from .keychain import SecretStore, keychain
from .models import PlaidConnection, PlaidSyncRun
from .payroll import generate_payroll_schedule
from .plaid_client import PlaidClient
from .plaid_service import exchange_plaid_public_token, sync_plaid_connection
from .reconciliation import reconcile_all
from .v2_contracts import GoalObservationResult


def import_inbox_with_goal_observation(
    session: Session,
    *,
    observed_on: date,
    runtime_settings: Settings = settings,
) -> tuple[ImportOutcome, GoalObservationResult]:
    try:
        outcome = import_private_inbox(session, runtime_settings)
    except Exception:
        session.rollback()
        coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            observed_on=observed_on,
            operation_state=CompletedOperationState.FAILED,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key="manual_import",
                    state="failed",
                    evidence_ref="import_operation:failed",
                ),
            ),
        )
        raise
    state = CompletedOperationState.PARTIAL if outcome.errors else CompletedOperationState.COMPLETE
    observation = coordinate_goal_observation(
        session,
        trigger=GoalCheckInTrigger.POST_IMPORT,
        observed_on=observed_on,
        operation_state=state,
        source_updates=(
            SourceCurrentnessUpdate(
                source_key="manual_import",
                state="partial" if outcome.errors else "complete",
                evidence_ref=operation_evidence_ref("import_batch", outcome.batch_id),
            ),
        ),
    )
    return outcome, observation


def regenerate_payroll_with_goal_observation(
    session: Session,
    *,
    observed_on: date,
) -> tuple[dict[str, Any], GoalObservationResult]:
    try:
        result = generate_payroll_schedule(session)
        reconcile_all(session)
        session.commit()
    except Exception:
        session.rollback()
        coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_PAYROLL,
            observed_on=observed_on,
            operation_state=CompletedOperationState.FAILED,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key="payroll",
                    state="failed",
                    evidence_ref="payroll_rebuild:failed",
                ),
            ),
        )
        raise
    digest = hashlib.sha256(
        json.dumps(
            {
                "fingerprints": result["fingerprints"],
                "allocation_fingerprints": result["allocation_fingerprints"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    observation = coordinate_goal_observation(
        session,
        trigger=GoalCheckInTrigger.POST_PAYROLL,
        observed_on=observed_on,
        operation_state=CompletedOperationState.COMPLETE,
        source_updates=(
            SourceCurrentnessUpdate(
                source_key="payroll",
                state="complete",
                evidence_ref=f"payroll_rebuild:{digest}",
            ),
        ),
    )
    return result, observation


def sync_connection_with_goal_observation(
    session: Session,
    connection_id: int,
    *,
    observed_on: date,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> tuple[PlaidConnection, GoalObservationResult]:
    prior_run_id = session.scalar(
        select(PlaidSyncRun.id)
        .where(PlaidSyncRun.connection_id == connection_id)
        .order_by(PlaidSyncRun.id.desc())
        .limit(1)
    )
    try:
        connection = sync_plaid_connection(
            session,
            connection_id,
            store=store,
            client=client,
            business_date=observed_on,
        )
    except Exception:
        session.rollback()
        latest = _new_sync_run(session, connection_id=connection_id, prior_run_id=prior_run_id)
        coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_REFRESH,
            observed_on=observed_on,
            operation_state=CompletedOperationState.FAILED,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key=plaid_source_key(connection_id),
                    state="failed",
                    evidence_ref=(
                        operation_evidence_ref("plaid_sync_run", latest.id)
                        if latest is not None
                        else operation_evidence_ref("plaid_sync_attempt", connection_id)
                    ),
                ),
            ),
        )
        raise
    latest = _new_sync_run(session, connection_id=connection_id, prior_run_id=prior_run_id)
    evidence = (
        operation_evidence_ref("plaid_sync_run", latest.id, latest.finished_at)
        if latest is not None
        else operation_evidence_ref("plaid_sync_attempt", connection_id)
    )
    observation = coordinate_goal_observation(
        session,
        trigger=GoalCheckInTrigger.POST_REFRESH,
        observed_on=observed_on,
        operation_state=CompletedOperationState.COMPLETE,
        source_updates=(
            SourceCurrentnessUpdate(
                source_key=plaid_source_key(connection_id),
                state="complete",
                evidence_ref=evidence,
            ),
        ),
    )
    return connection, observation


def exchange_token_with_goal_observation(
    session: Session,
    *,
    link_session_id: str,
    public_token: str,
    observed_on: date,
    store: SecretStore = keychain,
    client: PlaidClient | None = None,
) -> tuple[PlaidConnection, GoalObservationResult]:
    connection = exchange_plaid_public_token(
        session,
        link_session_id=link_session_id,
        public_token=public_token,
        store=store,
        client=client,
    )
    latest = session.scalar(
        select(PlaidSyncRun)
        .where(PlaidSyncRun.connection_id == connection.id)
        .order_by(PlaidSyncRun.id.desc())
        .limit(1)
    )
    complete = latest is not None and latest.status == "complete"
    observation = coordinate_goal_observation(
        session,
        trigger=GoalCheckInTrigger.POST_REFRESH,
        observed_on=observed_on,
        operation_state=(
            CompletedOperationState.COMPLETE if complete else CompletedOperationState.FAILED
        ),
        source_updates=(
            SourceCurrentnessUpdate(
                source_key=plaid_source_key(connection.id),
                state="complete" if complete else "failed",
                evidence_ref=(
                    operation_evidence_ref("plaid_sync_run", latest.id, latest.finished_at)
                    if latest is not None
                    else operation_evidence_ref("plaid_sync_attempt", connection.id)
                ),
            ),
        ),
    )
    return connection, observation


def _new_sync_run(
    session: Session,
    *,
    connection_id: int,
    prior_run_id: int | None,
) -> PlaidSyncRun | None:
    statement = (
        select(PlaidSyncRun)
        .where(PlaidSyncRun.connection_id == connection_id)
        .order_by(PlaidSyncRun.id.desc())
        .limit(1)
    )
    latest = session.scalar(statement)
    if latest is None or (prior_run_id is not None and latest.id <= prior_run_id):
        return None
    return latest
