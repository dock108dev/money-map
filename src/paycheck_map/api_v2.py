"""Versioned cash-flow, goal, retirement, and experiment API routes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .cash_flow_service import (
    CashFlowUnavailableError,
    CashFlowValidationError,
    build_cash_flow_period_result,
)
from .db import get_session
from .goal_gap_service import GoalGapValidationError, build_goal_gap_preview
from .goal_observation import load_backfill_goal_observation
from .goal_service import (
    GoalValidationError,
    IneligibleGoalError,
    StaleGoalWriteError,
    UnknownGoalError,
    calculate_primary_goal_position,
    check_in_timeline,
    current_milestone,
    edit_goal,
    goal_candidates,
    latest_check_in,
    latest_comparison,
    primary_goal,
    primary_goal_state,
    select_primary_goal,
)
from .life_plan import get_profile
from .recurring_outflow_service import recurring_outflow_candidates
from .refresh import local_business_date
from .retirement_lab import (
    PlanningNotFoundError,
    PlanningStaleError,
    PlanningValidationError,
    confirm_lab_promotion,
    edit_retirement_profile,
    eligible_retirement_goals,
    list_lab_snapshots,
    list_retirement_snapshots,
    open_lab_snapshot,
    open_retirement_snapshot,
    preview_lab_promotion,
    project_lab_experiment,
    retirement_profile_view,
    retirement_starting_evidence,
    run_retirement_projection,
    save_lab_snapshot,
    save_retirement_snapshot,
    seed_lab_experiment,
)
from .services import wealth_dashboard
from .v2_contracts import (
    GoalCandidateList,
    GoalCheckInState,
    GoalCheckInTimelinePage,
    GoalComparisonState,
    GoalEditRequest,
    GoalMilestoneState,
    GoalObservationResult,
    GoalPositionState,
    GoalProgramView,
    GoalProvenanceState,
    LifeLabExperimentCreateRequest,
    LifeLabExperimentProjectRequest,
    LifeLabExperimentResult,
    LifeLabExperimentSeed,
    LifeLabPromotionApplied,
    LifeLabPromotionConfirmationRequest,
    LifeLabPromotionPreview,
    LifeLabPromotionPreviewRequest,
    LifeLabSnapshotSaveRequest,
    PrimaryGoalSelectionRequest,
    PrimaryGoalState,
    RetirementProfileEditRequest,
    RetirementProfileView,
    RetirementProjectionRequest,
    RetirementProjectionResult,
    RetirementSnapshotSaveRequest,
)
from .v21_contracts import (
    CashFlowPeriodResult,
    GoalGapPreviewRequest,
    GoalGapPreviewResponse,
    PeriodKind,
    RecurringOutflowCandidateList,
)

router = APIRouter(prefix="/api")


def _cash_flow_api_now() -> datetime:
    return datetime.now(UTC)


@router.get("/v2/cash-flow")
def get_v2_cash_flow(
    period_kind: PeriodKind,
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_session),
) -> CashFlowPeriodResult:
    now = _cash_flow_api_now()
    try:
        return build_cash_flow_period_result(
            session,
            period_kind=period_kind,
            start_date=start_date,
            end_date=end_date,
            as_of_date=local_business_date(now),
            now=now,
        )
    except CashFlowUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={"state": "unavailable", "reason": str(exc)},
        ) from exc
    except CashFlowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v2/goals/gap-preview")
def post_v2_goal_gap_preview(
    payload: GoalGapPreviewRequest,
    session: Session = Depends(get_session),
) -> GoalGapPreviewResponse:
    now = _cash_flow_api_now()
    try:
        return build_goal_gap_preview(
            session,
            request=payload,
            observed_on=local_business_date(now),
        )
    except GoalGapValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/cash-flow/recurring-outflow-candidates")
def get_v2_recurring_outflow_candidates(
    session: Session = Depends(get_session),
) -> RecurringOutflowCandidateList:
    now = _cash_flow_api_now()
    return recurring_outflow_candidates(
        session,
        observed_on=local_business_date(now),
    )


@router.get("/wealth")
def get_wealth(session: Session = Depends(get_session)) -> dict[str, Any]:
    return wealth_dashboard(session)


@router.get("/v2/goals/primary")
def get_v2_primary_goal(session: Session = Depends(get_session)) -> PrimaryGoalState:
    return primary_goal_state(session)


@router.put("/v2/goals/primary")
def put_v2_primary_goal(
    payload: PrimaryGoalSelectionRequest,
    session: Session = Depends(get_session),
) -> GoalProgramView:
    try:
        result = select_primary_goal(session, request=payload)
        session.commit()
        return result
    except UnknownGoalError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (StaleGoalWriteError, IneligibleGoalError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v2/goals/candidates")
def get_v2_goal_candidates(session: Session = Depends(get_session)) -> GoalCandidateList:
    return goal_candidates(session)


@router.get("/v2/goals/position")
def get_v2_goal_position(
    observed_on: date | None = None,
    session: Session = Depends(get_session),
) -> GoalPositionState:
    result = calculate_primary_goal_position(session, observed_on=observed_on or date.today())
    if result is None:
        return GoalPositionState(state="no_primary")
    return GoalPositionState(
        state="available",
        position=result.position,
        source_fingerprint=result.source_fingerprint,
    )


@router.get("/v2/goals/check-ins/latest")
def get_v2_latest_goal_check_in(
    session: Session = Depends(get_session),
) -> GoalCheckInState:
    program = primary_goal(session)
    if program is None:
        return GoalCheckInState(state="no_primary")
    result = latest_check_in(session, program=program)
    return GoalCheckInState(
        state="available" if result is not None else "no_check_in",
        check_in=result,
    )


@router.get("/v2/goals/check-ins")
def get_v2_goal_check_ins(
    limit: int = 20,
    cursor: str | None = None,
    session: Session = Depends(get_session),
) -> GoalCheckInTimelinePage:
    program = primary_goal(session)
    if program is None:
        return GoalCheckInTimelinePage(state="no_primary")
    try:
        result = check_in_timeline(session, program=program, limit=limit, cursor=cursor)
    except GoalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GoalCheckInTimelinePage(
        state="available",
        check_ins=result.check_ins,
        comparisons=result.comparisons,
        next_cursor=result.next_cursor,
    )


@router.post("/v2/goals/check-ins/backfill")
def post_v2_goal_check_in_backfill(
    session: Session = Depends(get_session),
) -> GoalObservationResult:
    return load_backfill_goal_observation(session, observed_on=local_business_date())


@router.get("/v2/goals/comparison")
def get_v2_goal_comparison(
    session: Session = Depends(get_session),
) -> GoalComparisonState:
    program = primary_goal(session)
    if program is None:
        return GoalComparisonState(
            state="no_primary", reason="A primary goal has not been selected"
        )
    result = latest_comparison(session, program=program)
    return GoalComparisonState(
        state=result.state,
        comparison=result.comparison,
        reason=result.reason,
    )


@router.get("/v2/goals/milestone")
def get_v2_goal_milestone(
    observed_on: date | None = None,
    session: Session = Depends(get_session),
) -> GoalMilestoneState:
    result = calculate_primary_goal_position(session, observed_on=observed_on or date.today())
    if result is None:
        return GoalMilestoneState(state="no_primary")
    return GoalMilestoneState(state="available", milestone=current_milestone(result))


@router.get("/v2/goals/provenance")
def get_v2_goal_provenance(
    observed_on: date | None = None,
    session: Session = Depends(get_session),
) -> GoalProvenanceState:
    result = calculate_primary_goal_position(session, observed_on=observed_on or date.today())
    if result is None:
        return GoalProvenanceState(state="no_primary")
    return GoalProvenanceState(
        state="available",
        source_fingerprint=result.source_fingerprint,
        source_material=result.source_material,
    )


@router.patch("/v2/goals/{goal_program_id}")
def patch_v2_goal(
    goal_program_id: str,
    payload: GoalEditRequest,
    session: Session = Depends(get_session),
) -> GoalProgramView:
    try:
        result = edit_goal(
            session,
            goal_program_id=goal_program_id,
            request=payload,
        )
        session.commit()
        return result
    except UnknownGoalError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleGoalWriteError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GoalValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/retirement/profile")
def get_v2_retirement_profile(
    session: Session = Depends(get_session),
) -> RetirementProfileView | None:
    profile = get_profile(session)
    return retirement_profile_view(session, profile) if profile is not None else None


@router.put("/v2/retirement/profile")
def put_v2_retirement_profile(
    payload: RetirementProfileEditRequest,
    session: Session = Depends(get_session),
) -> RetirementProfileView:
    try:
        result = edit_retirement_profile(session, request=payload)
        session.commit()
        return result
    except PlanningNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanningStaleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/retirement/starting-point")
def get_v2_retirement_starting_point(
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return retirement_starting_evidence(session)


@router.get("/v2/retirement/operational-goals")
def get_v2_retirement_operational_goals(
    session: Session = Depends(get_session),
) -> tuple[GoalProgramView, ...]:
    return eligible_retirement_goals(session)


@router.post("/v2/retirement/project")
def post_v2_retirement_projection(
    payload: RetirementProjectionRequest,
    session: Session = Depends(get_session),
) -> RetirementProjectionResult:
    try:
        return run_retirement_projection(session, request=payload)
    except PlanningNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PlanningValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v2/retirement/snapshots")
def post_v2_retirement_snapshot(
    payload: RetirementSnapshotSaveRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = save_retirement_snapshot(session, name=payload.name, run=payload.run)
        session.commit()
        return result
    except PlanningStaleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/retirement/snapshots")
def get_v2_retirement_snapshots(
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return list_retirement_snapshots(session)


@router.get("/v2/retirement/snapshots/{snapshot_id}")
def get_v2_retirement_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return open_retirement_snapshot(session, snapshot_id)
    except PlanningNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v2/lab/experiments")
def post_v2_lab_experiment(
    payload: LifeLabExperimentCreateRequest,
    session: Session = Depends(get_session),
) -> LifeLabExperimentSeed:
    try:
        return seed_lab_experiment(session, request=payload)
    except PlanningNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v2/lab/experiments/project")
def post_v2_lab_projection(
    payload: LifeLabExperimentProjectRequest,
) -> LifeLabExperimentResult:
    try:
        return project_lab_experiment(request=payload)
    except (PlanningValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v2/lab/snapshots")
def post_v2_lab_snapshot(
    payload: LifeLabSnapshotSaveRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = save_lab_snapshot(session, name=payload.name, result=payload.result)
        session.commit()
        return result
    except PlanningStaleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/lab/snapshots")
def get_v2_lab_snapshots(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return list_lab_snapshots(session)


@router.get("/v2/lab/snapshots/{snapshot_id}")
def get_v2_lab_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return open_lab_snapshot(session, snapshot_id)
    except PlanningNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v2/lab/promotions/preview")
def post_v2_lab_promotion_preview(
    payload: LifeLabPromotionPreviewRequest,
    session: Session = Depends(get_session),
) -> LifeLabPromotionPreview:
    try:
        return preview_lab_promotion(session, request=payload)
    except PlanningNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanningStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v2/lab/promotions/confirm")
def post_v2_lab_promotion_confirmation(
    payload: LifeLabPromotionConfirmationRequest,
    session: Session = Depends(get_session),
) -> LifeLabPromotionApplied:
    try:
        return confirm_lab_promotion(session, request=payload)
    except PlanningNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanningStaleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanningValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
