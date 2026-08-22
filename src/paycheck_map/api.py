from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .balances import add_manual_value_observation
from .cash_flow_service import (
    CashFlowUnavailableError,
    CashFlowValidationError,
    build_cash_flow_period_result,
)
from .config import settings
from .db import get_session
from .forecasting import ScenarioInput, build_forecast, ensure_baseline
from .goal_gap_service import GoalGapValidationError, build_goal_gap_preview
from .goal_observation import load_backfill_goal_observation
from .goal_operations import (
    exchange_token_with_goal_observation,
    import_inbox_with_goal_observation,
    regenerate_payroll_with_goal_observation,
    sync_connection_with_goal_observation,
)
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
from .ingestion import rollback_import_batch
from .keychain import MemorySecretStore, SecretStore, SecretStoreError, keychain
from .life_plan import (
    LifeGoalInput,
    LifePlanProfileInput,
    ProjectionRequest,
    ScenarioSaveInput,
    create_goal,
    current_fingerprint,
    delete_goal,
    get_profile,
    goal_dict,
    list_goals,
    load_benchmarks,
    profile_dict,
    project_life_plan,
    save_scenario,
    scenario_dict,
    starting_point,
    update_goal,
    upsert_profile,
)
from .models import LifeGoal, LifeScenario, ManualCorrection, PayrollStatement
from .payroll import RECEIVED_END, RECEIVED_START
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
from .reconciliation import reconcile_all
from .recurring_outflow_service import recurring_outflow_candidates
from .refresh import (
    RefreshAlreadyRunningError,
    local_business_date,
    refresh_guard,
    refresh_status,
    set_auto_refresh_enabled,
    sync_all_connections,
)
from .reporting import REPORT_FILENAME, REPORT_ID, approved_report, generate_trailing_report
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
from .services import (
    account_detail,
    accounts_dashboard,
    exceptions,
    fidelity_summary,
    imports,
    latest_complete_period,
    overview,
    paychecks,
    payroll_entry,
    payroll_history,
    payroll_reconciliation,
    scenarios,
    sofi_summary,
    timeline,
    wealth_dashboard,
)
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


class CorrectionInput(BaseModel):
    entity_type: str
    entity_id: int
    field_name: str
    new_value: Decimal
    reason: str = Field(min_length=3, max_length=500)


class PlaidConfigurationInput(BaseModel):
    environment: Literal["sandbox", "production"]
    client_id: str = Field(default="", max_length=128)
    secret: SecretStr


class PlaidLinkInput(BaseModel):
    environment: Literal["sandbox", "production"] = "sandbox"
    target: Literal["sofi", "fidelity"]


class PlaidExchangeInput(BaseModel):
    session_id: str
    public_token: SecretStr


class ManualValueInput(BaseModel):
    observation_date: date
    value: Decimal = Field(ge=0)
    source_note: str = Field(min_length=3, max_length=200)


class PlaidSyncAllInput(BaseModel):
    automatic: bool = False


class AutoRefreshPreferenceInput(BaseModel):
    enabled: bool


_acceptance_secret_store = MemorySecretStore()


def get_secret_store() -> SecretStore:
    if settings.desktop_mode and settings.desktop_data_mode == "acceptance-synthetic-v1":
        return _acceptance_secret_store
    return keychain


def _cash_flow_api_now() -> datetime:
    return datetime.now(UTC)


@router.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "privacy": "local-first",
        "server": "127.0.0.1-only",
        "provider_connections": "opt-in-read-only",
        "money_movement": False,
        "version": __version__,
    }


@router.get("/overview")
def get_overview(
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return overview(session, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/accounts")
def get_accounts(session: Session = Depends(get_session)) -> dict[str, Any]:
    return accounts_dashboard(session)


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


@router.get("/life-plan/profile")
def get_life_plan_profile(session: Session = Depends(get_session)) -> dict[str, Any] | None:
    profile = get_profile(session)
    return profile_dict(profile) if profile else None


@router.put("/life-plan/profile")
def put_life_plan_profile(
    payload: LifePlanProfileInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = upsert_profile(session, payload)
    return profile_dict(profile)


@router.get("/life-plan/starting-point")
def get_life_plan_starting_point(session: Session = Depends(get_session)) -> dict[str, Any]:
    return starting_point(session)


@router.get("/life-plan/benchmarks")
def get_life_plan_benchmarks(
    state: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    selected_state = state or (profile.state if profile else None)
    start = starting_point(session)
    payroll = start.get("payroll")
    income = Decimal(str(payroll["annual_salary"])) if payroll else None
    return load_benchmarks(selected_state, income)


@router.get("/life-plan/goals")
def get_life_plan_goals(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    profile = get_profile(session)
    if profile is None:
        return []
    return [goal_dict(goal) for goal in list_goals(session, profile.id)]


@router.post("/life-plan/goals")
def post_life_plan_goal(
    payload: LifeGoalInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    if profile is None:
        raise HTTPException(status_code=409, detail="Create the Life Lab profile first")
    if payload.target_date < date.today():
        raise HTTPException(status_code=422, detail="Goal date cannot be in the past")
    return goal_dict(create_goal(session, profile, payload))


@router.put("/life-plan/goals/{goal_id}")
def put_life_plan_goal(
    goal_id: int,
    payload: LifeGoalInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    goal = session.get(LifeGoal, goal_id)
    if profile is None or goal is None or goal.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Life goal was not found")
    if payload.target_date < date.today():
        raise HTTPException(status_code=422, detail="Goal date cannot be in the past")
    return goal_dict(update_goal(session, goal, payload))


@router.delete("/life-plan/goals/{goal_id}")
def remove_life_plan_goal(
    goal_id: int,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    profile = get_profile(session)
    goal = session.get(LifeGoal, goal_id)
    if profile is None or goal is None or goal.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Life goal was not found")
    delete_goal(session, goal)
    return {"deleted": True}


@router.post("/life-plan/project")
def post_life_plan_projection(
    payload: ProjectionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    if profile is None:
        raise HTTPException(status_code=409, detail="Create the Life Lab profile first")
    try:
        return project_life_plan(
            session,
            profile,
            list_goals(session, profile.id),
            target_ages=payload.target_ages,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/life-plan/scenarios")
def get_life_plan_scenarios(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    profile = get_profile(session)
    if profile is None:
        return []
    goals = list_goals(session, profile.id)
    fingerprint = current_fingerprint(session, profile, goals)
    rows = list(
        session.scalars(
            select(LifeScenario)
            .where(LifeScenario.profile_id == profile.id)
            .order_by(LifeScenario.created_at.desc())
        )
    )
    return [scenario_dict(row, fingerprint) for row in rows]


@router.post("/life-plan/scenarios")
def post_life_plan_scenario(
    payload: ScenarioSaveInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    if profile is None:
        raise HTTPException(status_code=409, detail="Create the Life Lab profile first")
    try:
        goals = list_goals(session, profile.id)
        scenario = save_scenario(session, profile, goals, payload)
        return scenario_dict(scenario, current_fingerprint(session, profile, goals))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/life-plan/scenarios/{scenario_id}")
def get_life_plan_scenario(
    scenario_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    profile = get_profile(session)
    scenario = session.get(LifeScenario, scenario_id)
    if profile is None or scenario is None or scenario.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Life scenario was not found")
    goals = list_goals(session, profile.id)
    return scenario_dict(scenario, current_fingerprint(session, profile, goals))


@router.get("/accounts/{account_id}")
def get_account_detail(
    account_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    default_start, default_end = latest_complete_period()
    try:
        row = account_detail(
            session,
            account_id,
            start_date or default_start,
            end_date or default_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    return row


@router.post("/accounts/{account_id}/values")
def add_account_value(
    account_id: int,
    payload: ManualValueInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        snapshot = add_manual_value_observation(
            session,
            account_id=account_id,
            observation_date=payload.observation_date,
            value=payload.value,
            source_note=payload.source_note,
        )
        reconcile_all(session)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "account_id": account_id,
        "observation_date": snapshot.snapshot_date,
        "value": str(snapshot.amount),
    }


@router.get("/paychecks")
def get_paychecks(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return paychecks(session)


def _payroll_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date")
    if start_date < RECEIVED_START or end_date > RECEIVED_END:
        raise HTTPException(
            status_code=422,
            detail=f"Payroll history is available from {RECEIVED_START} through {RECEIVED_END}",
        )


@router.get("/payroll")
def get_payroll_history(
    start_date: date = RECEIVED_START,
    end_date: date = RECEIVED_END,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _payroll_range(start_date, end_date)
    return payroll_history(session, start_date, end_date)


@router.get("/payroll/summary")
def get_payroll_summary(
    start_date: date = RECEIVED_START,
    end_date: date = RECEIVED_END,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _payroll_range(start_date, end_date)
    history = payroll_history(session, start_date, end_date)
    return {key: value for key, value in history.items() if key != "rows"}


@router.get("/payroll/reconciliation")
def get_payroll_reconciliation(session: Session = Depends(get_session)) -> dict[str, Any]:
    return payroll_reconciliation(session)


@router.post("/payroll/regenerate")
def regenerate_payroll(session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        result, observation = regenerate_payroll_with_goal_observation(
            session,
            observed_on=local_business_date(),
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **result,
        "reconciliation": payroll_reconciliation(session),
        "goal_observation": observation.model_dump(mode="json"),
    }


@router.get("/payroll/{entry_id}")
def get_payroll_entry(entry_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = payroll_entry(session, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Payroll entry was not found")
    return row


@router.get("/sofi")
def get_sofi(session: Session = Depends(get_session)) -> dict[str, Any]:
    return sofi_summary(session)


@router.get("/fidelity")
def get_fidelity(session: Session = Depends(get_session)) -> dict[str, Any]:
    return fidelity_summary(session)


@router.get("/timeline")
def get_timeline(
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    default_start, default_end = latest_complete_period()
    try:
        return timeline(session, start_date or default_start, end_date or default_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/exceptions")
def get_exceptions(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return exceptions(session)


@router.get("/imports")
def get_imports(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return imports(session)


@router.post("/imports/scan")
def scan_inbox(session: Session = Depends(get_session)) -> dict[str, Any]:
    outcome, observation = import_inbox_with_goal_observation(
        session,
        observed_on=local_business_date(),
    )
    return {
        "batch_id": outcome.batch_id,
        "discovered": outcome.discovered,
        "imported": outcome.imported,
        "duplicates": outcome.duplicates,
        "errors": outcome.errors,
        "goal_observation": observation.model_dump(mode="json"),
    }


@router.delete("/imports/{batch_id}")
def rollback_batch(batch_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    if not rollback_import_batch(session, batch_id):
        raise HTTPException(status_code=404, detail="Import batch was not found")
    return {"rolled_back": True}


@router.get("/scenarios")
def get_scenarios(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    try:
        ensure_baseline(session)
    except ValueError:
        return []
    return scenarios(session)


@router.post("/scenarios")
def create_scenario(
    payload: ScenarioInput, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        summary = build_forecast(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return summary.model_dump()


@router.post("/corrections")
def create_correction(
    payload: CorrectionInput, session: Session = Depends(get_session)
) -> dict[str, Any]:
    if payload.entity_type != "payroll_statement":
        raise HTTPException(
            status_code=422, detail="Only payroll summary corrections are supported"
        )
    statement = session.get(PayrollStatement, payload.entity_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="Payroll statement was not found")
    allowed = {
        "base_salary",
        "gross_earnings",
        "imputed_earnings",
        "pretax_deductions",
        "tax_withholdings",
        "after_tax_deductions",
        "federal_taxable_gross",
        "net_payment",
    }
    if payload.field_name not in allowed:
        raise HTTPException(status_code=422, detail="This field cannot be corrected")
    old_value = getattr(statement, payload.field_name)
    setattr(statement, payload.field_name, payload.new_value)
    session.add(
        ManualCorrection(
            entity_type=payload.entity_type,
            entity_id=str(payload.entity_id),
            field_name=payload.field_name,
            old_value=str(old_value),
            new_value=str(payload.new_value),
            reason=payload.reason,
        )
    )
    reconcile_all(session)
    session.commit()
    return {"corrected": True, "old_value": str(old_value), "new_value": str(payload.new_value)}


@router.post("/reports/trailing-12")
def create_report(session: Session = Depends(get_session)) -> dict[str, str]:
    generate_trailing_report(session, settings)
    return {"report_id": REPORT_ID, "filename": REPORT_FILENAME}


@router.get("/reports/{report_id}/approved")
def get_approved_report(report_id: str) -> dict[str, str | bool]:
    try:
        path = approved_report(report_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"report_id": report_id, "filename": path.name, "approved": True}


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
        configure_plaid(
            environment=payload.environment,
            client_id=payload.client_id,
            secret=payload.secret.get_secret_value(),
            store=store,
        )
        return plaid_configuration_status(store)
    except (ValueError, SecretStoreError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
