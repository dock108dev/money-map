"""Explicit post-operation goal observation coordination for Money Map v2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .goal_service import (
    GoalCheckInTrigger,
    ensure_goal_check_in_result,
    primary_goal,
)
from .models import ApplicationSetting, ImportBatch, PlaidConnection, PlaidSyncRun, utcnow
from .v2_contracts import GoalObservationResult

CURRENTNESS_KEY: Final = "goals.source_currentness_v1"
CURRENTNESS_VERSION: Final = "goal-source-currentness-v1"


class CompletedOperationState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


CurrentnessState = Literal["complete", "partial", "failed"]


@dataclass(frozen=True)
class SourceCurrentnessUpdate:
    source_key: str
    state: CurrentnessState
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.source_key or not self.evidence_ref:
            raise ValueError("Currentness updates require stable source evidence")


@dataclass(frozen=True)
class _Eligibility:
    eligible: bool
    unavailable: bool = False


def plaid_source_key(connection_id: int) -> str:
    return f"plaid_connection:{connection_id}"


def coordinate_goal_observation(
    session: Session,
    *,
    trigger: GoalCheckInTrigger,
    observed_on: date,
    operation_state: CompletedOperationState,
    source_updates: tuple[SourceCurrentnessUpdate, ...] = (),
) -> GoalObservationResult:
    """Persist operation currentness, then independently persist one goal observation.

    The caller supplies an already completed operation state. Any pending operation
    transaction is committed before currentness is recorded. Check-in insertion then
    receives its own commit/rollback boundary, so it cannot undo committed source data.
    """

    public_trigger = _public_trigger(trigger)
    try:
        session.commit()
        if source_updates:
            _persist_currentness(session, observed_on=observed_on, updates=source_updates)
            session.commit()
    except Exception:
        session.rollback()
        return GoalObservationResult(
            status="unavailable",
            trigger=public_trigger,
            retryable=True,
            message=(
                "The financial operation completed, but observation currentness could not be "
                "saved. Retry Update data."
            ),
        )

    if primary_goal(session) is None:
        session.rollback()
        return GoalObservationResult(
            status="no_primary",
            trigger=public_trigger,
            message="No primary goal is selected, so no goal observation was saved.",
        )

    if operation_state is CompletedOperationState.SKIPPED:
        session.rollback()
        return GoalObservationResult(
            status="unavailable",
            trigger=public_trigger,
            retryable=True,
            message=(
                "No goal observation was requested for the skipped operation. Retry Update data "
                "if freshness is uncertain."
            ),
        )
    if operation_state in {CompletedOperationState.PARTIAL, CompletedOperationState.FAILED}:
        session.rollback()
        return GoalObservationResult(
            status="not_current",
            trigger=public_trigger,
            retryable=True,
            message=(
                "No new goal observation was saved because the financial operation was not fully "
                "current. Retry Update data."
            ),
        )

    eligibility = _source_eligibility(session)
    if not eligibility.eligible:
        session.rollback()
        return GoalObservationResult(
            status="unavailable" if eligibility.unavailable else "not_current",
            trigger=public_trigger,
            retryable=True,
            message=(
                "Goal observation currentness is unavailable. Retry Update data."
                if eligibility.unavailable
                else (
                    "No new goal observation was saved because one or more financial sources are "
                    "not current. Retry Update data."
                )
            ),
        )

    try:
        ensured = ensure_goal_check_in_result(
            session,
            trigger=trigger,
            effective_observation_date=observed_on,
        )
        session.commit()
    except Exception:
        session.rollback()
        return GoalObservationResult(
            status="unavailable",
            trigger=public_trigger,
            retryable=True,
            message=(
                "Financial data was preserved, but the goal observation could not be saved. "
                "Retry Update data."
            ),
        )
    return GoalObservationResult(
        status="created" if ensured.created else "unchanged",
        trigger=public_trigger,
        check_in=ensured.check_in,
        message=(
            "A new financial-change observation was saved."
            if ensured.created
            else "The current financial evidence already has a saved observation."
        ),
    )


def load_backfill_goal_observation(
    session: Session,
    *,
    observed_on: date,
) -> GoalObservationResult:
    return coordinate_goal_observation(
        session,
        trigger=GoalCheckInTrigger.LOAD_BACKFILL,
        observed_on=observed_on,
        operation_state=CompletedOperationState.COMPLETE,
    )


def _public_trigger(
    trigger: GoalCheckInTrigger,
) -> Literal["post_refresh", "post_import", "post_payroll", "load_backfill"]:
    if trigger is GoalCheckInTrigger.SYNTHETIC_TEST:
        raise ValueError("Synthetic test triggers cannot cross the operation coordinator")
    return trigger.value  # type: ignore[return-value]


def _persist_currentness(
    session: Session,
    *,
    observed_on: date,
    updates: tuple[SourceCurrentnessUpdate, ...],
) -> None:
    payload = _currentness_payload(session)
    sources = payload.setdefault("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("Stored goal source currentness is invalid")
    recorded_at = utcnow().isoformat(timespec="microseconds")
    for update in updates:
        sources[update.source_key] = {
            "state": update.state,
            "evidence_ref": update.evidence_ref,
            "observed_on": observed_on.isoformat(),
            "recorded_at": recorded_at,
        }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    row = session.get(ApplicationSetting, CURRENTNESS_KEY)
    if row is None:
        session.add(ApplicationSetting(key=CURRENTNESS_KEY, value=encoded))
    else:
        row.value = encoded
        row.updated_at = utcnow()


def _currentness_payload(session: Session) -> dict[str, Any]:
    row = session.get(ApplicationSetting, CURRENTNESS_KEY)
    if row is None:
        return {"version": CURRENTNESS_VERSION, "sources": {}}
    try:
        payload = json.loads(row.value)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored goal source currentness is invalid") from exc
    if not isinstance(payload, dict) or payload.get("version") != CURRENTNESS_VERSION:
        raise ValueError("Stored goal source currentness is invalid")
    return payload


def _source_eligibility(session: Session) -> _Eligibility:
    try:
        payload = _currentness_payload(session)
    except ValueError:
        return _Eligibility(eligible=False, unavailable=True)
    sources = payload.get("sources", {})
    if not isinstance(sources, dict):
        return _Eligibility(eligible=False, unavailable=True)

    manual = sources.get("manual_import")
    if isinstance(manual, dict):
        if manual.get("state") != "complete":
            return _Eligibility(eligible=False)
    else:
        latest_manual = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.requested_source == "local_inbox")
            .order_by(ImportBatch.id.desc())
            .limit(1)
        )
        if latest_manual is not None and latest_manual.status != "complete":
            return _Eligibility(eligible=False)

    payroll = sources.get("payroll")
    if isinstance(payroll, dict) and payroll.get("state") != "complete":
        return _Eligibility(eligible=False)

    connections = list(
        session.scalars(
            select(PlaidConnection)
            .where(PlaidConnection.status != "revoked")
            .order_by(PlaidConnection.id)
        )
    )
    for connection in connections:
        marker = sources.get(plaid_source_key(connection.id))
        if isinstance(marker, dict) and marker.get("state") != "complete":
            return _Eligibility(eligible=False)
        latest_run = session.scalar(
            select(PlaidSyncRun)
            .where(PlaidSyncRun.connection_id == connection.id)
            .order_by(PlaidSyncRun.id.desc())
            .limit(1)
        )
        if marker is None and (latest_run is None or latest_run.status != "complete"):
            return _Eligibility(eligible=False)
        if latest_run is not None and latest_run.status != "complete":
            return _Eligibility(eligible=False)
        if connection.status not in {"active"}:
            return _Eligibility(eligible=False)
    return _Eligibility(eligible=True)


def operation_evidence_ref(prefix: str, value: object, completed_at: datetime | None = None) -> str:
    """Build a stable, sanitized persisted-operation reference."""

    suffix = f":{completed_at.isoformat(timespec='microseconds')}" if completed_at else ""
    return f"{prefix}:{value}{suffix}"
