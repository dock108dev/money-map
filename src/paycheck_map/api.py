from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import __product_version__
from .api_inputs import (
    CorrectionInput,
    ManualValueInput,
)
from .api_plaid import get_secret_store
from .balances import add_manual_value_observation
from .config import settings
from .db import get_session
from .forecasting import ScenarioInput, build_forecast, ensure_baseline
from .goal_operations import (
    import_inbox_with_goal_observation,
    regenerate_payroll_with_goal_observation,
)
from .ingestion import rollback_import_batch
from .models import ManualCorrection, PayrollStatement
from .payroll import RECEIVED_END, RECEIVED_START
from .reconciliation import reconcile_all
from .refresh import (
    local_business_date,
)
from .reporting import REPORT_FILENAME, REPORT_ID, approved_report, generate_trailing_report
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
)

router = APIRouter(prefix="/api")

__all__ = ["get_secret_store", "router"]


@router.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "privacy": "local-first",
        "server": "127.0.0.1-only",
        "provider_connections": "opt-in-read-only",
        "money_movement": False,
        "version": __product_version__,
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
