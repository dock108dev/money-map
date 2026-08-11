from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forecasting import ensure_baseline
from .goal_observation import (
    CompletedOperationState,
    SourceCurrentnessUpdate,
    coordinate_goal_observation,
    operation_evidence_ref,
    plaid_source_key,
)
from .goal_service import GoalCheckInTrigger
from .keychain import SecretStore, SecretStoreError, keychain
from .models import ApplicationSetting, PlaidConnection, PlaidSyncRun
from .plaid_client import PlaidAPIError, PlaidClient
from .plaid_service import sync_plaid_connection

LOCAL_TIMEZONE = ZoneInfo("America/New_York")
AUTO_REFRESH_KEY = "plaid.auto_refresh_enabled"
AUTO_ATTEMPT_KEY = "plaid.last_auto_refresh_attempt_date"
RETRYABLE_STATUSES = {"active", "temporarily_unavailable"}
Clock = Callable[[], datetime]

_refresh_lock = Lock()


class RefreshAlreadyRunningError(RuntimeError):
    pass


@contextmanager
def refresh_guard() -> Iterator[None]:
    if not _refresh_lock.acquire(blocking=False):
        raise RefreshAlreadyRunningError("Account data is already updating")
    try:
        yield
    finally:
        _refresh_lock.release()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _clock_timestamp(clock: Clock, *, not_before: datetime | None = None) -> datetime:
    value = _as_utc(clock())
    floor = _as_utc(not_before) if not_before is not None else None
    return floor if floor is not None and value < floor else value


def local_business_date(value: datetime | None = None) -> date:
    instant = value or datetime.now(UTC)
    return _as_utc(instant).astimezone(LOCAL_TIMEZONE).date()


def _setting(session: Session, key: str) -> str | None:
    row = session.get(ApplicationSetting, key)
    return row.value if row is not None else None


def _set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(ApplicationSetting, key)
    if row is None:
        session.add(ApplicationSetting(key=key, value=value))
    else:
        row.value = value


def auto_refresh_enabled(session: Session) -> bool:
    return _setting(session, AUTO_REFRESH_KEY) != "false"


def set_auto_refresh_enabled(session: Session, enabled: bool) -> None:
    _set_setting(session, AUTO_REFRESH_KEY, "true" if enabled else "false")
    session.commit()


def refresh_status(
    session: Session,
    *,
    now: datetime | None = None,
    in_progress: bool | None = None,
) -> dict[str, Any]:
    today = local_business_date(now)
    active = list(
        session.scalars(
            select(PlaidConnection)
            .where(PlaidConnection.status.in_(RETRYABLE_STATUSES))
            .order_by(PlaidConnection.id)
        )
    )
    current = [
        connection
        for connection in active
        if connection.last_synced_at is not None
        and local_business_date(_as_utc(connection.last_synced_at)) == today
    ]
    completed = [
        _as_utc(connection.last_synced_at) for connection in active if connection.last_synced_at
    ]
    last_successful = min(completed) if len(completed) == len(active) and completed else None
    last_attempt = _setting(session, AUTO_ATTEMPT_KEY)
    enabled = auto_refresh_enabled(session)
    needed = bool(active) and len(current) != len(active)
    return {
        "last_successful_refresh": last_successful,
        "local_refresh_date": today,
        "refresh_needed": needed,
        "automatic_refresh_due": enabled and needed and last_attempt != today.isoformat(),
        "refresh_in_progress": _refresh_lock.locked() if in_progress is None else in_progress,
        "active_connections": len(active),
        "connections_current": len(current),
        "connections_needing_attention": session.scalar(
            select(PlaidConnection.id).where(PlaidConnection.status == "needs_attention").limit(1)
        )
        is not None,
        "auto_refresh_enabled": enabled,
        "last_auto_refresh_attempt_date": last_attempt,
    }


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, PlaidAPIError):
        return exc.code, exc.safe_message
    if isinstance(exc, SecretStoreError):
        return "SECRET_STORE_ERROR", "The local credential store could not be read."
    if isinstance(exc, ValueError):
        return "CONNECTION_ERROR", str(exc)[:300]
    return "LOCAL_SYNC_ERROR", "Local synchronization failed; existing data was preserved."


def sync_all_connections(
    session: Session,
    *,
    store: SecretStore = keychain,
    automatic: bool = False,
    now: datetime | None = None,
    clock: Clock | None = None,
    clients: dict[int, PlaidClient] | None = None,
) -> dict[str, Any]:
    if now is not None and clock is not None:
        raise ValueError("Provide either a fixed time or a clock, not both")
    operation_clock = clock or ((lambda: now) if now is not None else _system_clock)
    started = _clock_timestamp(operation_clock)
    business_date = local_business_date(started)
    with refresh_guard():
        status_before = refresh_status(session, now=started, in_progress=True)
        if automatic:
            if not status_before["automatic_refresh_due"]:
                freshness = refresh_status(session, now=started, in_progress=False)
                finished = _clock_timestamp(operation_clock, not_before=started)
                observation = coordinate_goal_observation(
                    session,
                    trigger=GoalCheckInTrigger.POST_REFRESH,
                    observed_on=business_date,
                    operation_state=CompletedOperationState.SKIPPED,
                )
                return {
                    "status": "skipped",
                    "reason": "already_current_or_attempted",
                    "started_at": started,
                    "finished_at": finished,
                    "requested": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "connections": [],
                    "freshness": freshness,
                    "goal_observation": observation.model_dump(mode="json"),
                }
            _set_setting(session, AUTO_ATTEMPT_KEY, business_date.isoformat())
            session.commit()

        connection_ids = list(
            session.scalars(
                select(PlaidConnection.id)
                .where(PlaidConnection.status.in_(RETRYABLE_STATUSES))
                .order_by(PlaidConnection.id)
            )
        )
        results: list[dict[str, Any]] = []
        currentness_updates: list[SourceCurrentnessUpdate] = []
        succeeded = 0
        last_event = started
        for connection_id in connection_ids:
            connection = session.get(PlaidConnection, connection_id)
            institution = connection.institution_name if connection is not None else "Connection"
            prior_run_id = session.scalar(
                select(PlaidSyncRun.id)
                .where(PlaidSyncRun.connection_id == connection_id)
                .order_by(PlaidSyncRun.id.desc())
                .limit(1)
            )
            attempt_started = _clock_timestamp(operation_clock, not_before=last_event)
            try:
                refreshed = sync_plaid_connection(
                    session,
                    connection_id,
                    store=store,
                    client=(clients or {}).get(connection_id),
                    business_date=business_date,
                    started_at=attempt_started,
                    clock=operation_clock,
                )
                latest_run = session.scalar(
                    select(PlaidSyncRun)
                    .where(PlaidSyncRun.connection_id == connection_id)
                    .order_by(PlaidSyncRun.id.desc())
                    .limit(1)
                )
                current_run = (
                    latest_run
                    if latest_run is not None
                    and (prior_run_id is None or latest_run.id > prior_run_id)
                    else None
                )
                run_started = _as_utc(current_run.started_at) if current_run else attempt_started
                run_finished = (
                    _as_utc(current_run.finished_at)
                    if current_run and current_run.finished_at is not None
                    else _clock_timestamp(operation_clock, not_before=run_started)
                )
                last_event = _as_utc(run_finished)
                results.append(
                    {
                        "connection_id": refreshed.id,
                        "institution": refreshed.institution_name,
                        "status": "complete",
                        "accounts": current_run.account_count if current_run else 0,
                        "transactions": current_run.transaction_count if current_run else 0,
                        "holdings": current_run.holding_count if current_run else 0,
                        "balance_snapshot_date": business_date,
                        "started_at": run_started,
                        "finished_at": run_finished,
                        "last_synced_at": (
                            _as_utc(refreshed.last_synced_at)
                            if refreshed.last_synced_at is not None
                            else None
                        ),
                        "error_code": None,
                        "message": None,
                    }
                )
                currentness_updates.append(
                    SourceCurrentnessUpdate(
                        source_key=plaid_source_key(connection_id),
                        state="complete",
                        evidence_ref=(
                            operation_evidence_ref(
                                "plaid_sync_run",
                                current_run.id,
                                current_run.finished_at,
                            )
                            if current_run is not None
                            else operation_evidence_ref("plaid_sync_attempt", connection_id)
                        ),
                    )
                )
                succeeded += 1
            except Exception as exc:  # connection failures are isolated and safely summarized
                code, message = _safe_failure(exc)
                session.expire_all()
                latest_run = session.scalar(
                    select(PlaidSyncRun)
                    .where(PlaidSyncRun.connection_id == connection_id)
                    .order_by(PlaidSyncRun.id.desc())
                    .limit(1)
                )
                current_run = (
                    latest_run
                    if latest_run is not None
                    and (prior_run_id is None or latest_run.id > prior_run_id)
                    else None
                )
                run_started = _as_utc(current_run.started_at) if current_run else attempt_started
                run_finished = (
                    _as_utc(current_run.finished_at)
                    if current_run and current_run.finished_at is not None
                    else _clock_timestamp(operation_clock, not_before=run_started)
                )
                last_event = _as_utc(run_finished)
                failed_connection = session.get(PlaidConnection, connection_id)
                results.append(
                    {
                        "connection_id": connection_id,
                        "institution": institution,
                        "status": "failed",
                        "accounts": 0,
                        "transactions": 0,
                        "holdings": 0,
                        "balance_snapshot_date": None,
                        "started_at": run_started,
                        "finished_at": run_finished,
                        "last_synced_at": (
                            _as_utc(failed_connection.last_synced_at)
                            if failed_connection is not None
                            and failed_connection.last_synced_at is not None
                            else None
                        ),
                        "error_code": code,
                        "message": message,
                    }
                )
                currentness_updates.append(
                    SourceCurrentnessUpdate(
                        source_key=plaid_source_key(connection_id),
                        state="failed",
                        evidence_ref=(
                            operation_evidence_ref(
                                "plaid_sync_run",
                                current_run.id,
                                current_run.finished_at,
                            )
                            if current_run is not None
                            else operation_evidence_ref("plaid_sync_attempt", connection_id)
                        ),
                    )
                )

        if succeeded:
            with suppress(ValueError):
                ensure_baseline(session)
        finished = _clock_timestamp(operation_clock, not_before=last_event)
        failed = len(connection_ids) - succeeded
        operation_state = (
            CompletedOperationState.COMPLETE if failed == 0 else CompletedOperationState.PARTIAL
        )
        observation = coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_REFRESH,
            observed_on=business_date,
            operation_state=operation_state,
            source_updates=tuple(currentness_updates),
        )
        return {
            "status": "complete" if failed == 0 else "partial",
            "started_at": started,
            "finished_at": finished,
            "requested": len(connection_ids),
            "succeeded": succeeded,
            "failed": failed,
            "connections": results,
            "freshness": refresh_status(session, now=finished, in_progress=False),
            "goal_observation": observation.model_dump(mode="json"),
        }
