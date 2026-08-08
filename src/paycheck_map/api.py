from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .balances import add_manual_value_observation
from .config import settings
from .db import get_session
from .forecasting import ScenarioInput, build_forecast, ensure_baseline
from .ingestion import import_private_inbox, rollback_import_batch
from .keychain import SecretStore, SecretStoreError, keychain
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
from .payroll import RECEIVED_END, RECEIVED_START, generate_payroll_schedule
from .plaid_client import PlaidAPIError
from .plaid_service import (
    clear_plaid_configuration,
    configure_plaid,
    create_plaid_link_session,
    create_plaid_update_session,
    exchange_plaid_public_token,
    plaid_configuration_status,
    plaid_status,
    revoke_plaid_connection,
    sync_plaid_connection,
)
from .reconciliation import reconcile_all
from .refresh import (
    RefreshAlreadyRunningError,
    refresh_guard,
    refresh_status,
    set_auto_refresh_enabled,
    sync_all_connections,
)
from .reporting import generate_trailing_report
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


def get_secret_store() -> SecretStore:
    return keychain


@router.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "privacy": "local-first",
        "server": "127.0.0.1-only",
        "provider_connections": "opt-in-read-only",
        "money_movement": False,
        "version": "1.2.1",
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


@router.get("/wealth")
def get_wealth(session: Session = Depends(get_session)) -> dict[str, Any]:
    return wealth_dashboard(session)


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
        result = generate_payroll_schedule(session)
        reconcile_all(session)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "reconciliation": payroll_reconciliation(session)}


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
    outcome = import_private_inbox(session)
    return {
        "batch_id": outcome.batch_id,
        "discovered": outcome.discovered,
        "imported": outcome.imported,
        "duplicates": outcome.duplicates,
        "errors": outcome.errors,
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
    path = generate_trailing_report(session, settings)
    return {"path": str(path)}


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
        connection = exchange_plaid_public_token(
            session,
            link_session_id=payload.session_id,
            public_token=payload.public_token.get_secret_value(),
            store=store,
        )
        return {
            "connection_id": connection.id,
            "status": connection.status,
            "target": connection.target,
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
            connection = sync_plaid_connection(session, connection_id, store=store)
        return {
            "connection_id": connection.id,
            "status": connection.status,
            "last_synced_at": connection.last_synced_at,
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
