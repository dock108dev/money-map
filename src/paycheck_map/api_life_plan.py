"""Legacy Life Plan compatibility routes backed by the current deterministic engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
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
from .models import LifeGoal, LifeScenario

router = APIRouter(prefix="/api")


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
