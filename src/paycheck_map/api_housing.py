"""Housing plan persistence. API owns transactions and optimistic revision checks."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import get_session
from .housing import HousingInput, evaluate
from .models import HousingPlan

router = APIRouter(prefix="/api/v2/housing")
Database = Annotated[Session, Depends(get_session)]


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    plan: HousingInput


def serialize(row: HousingPlan) -> dict[str, Any]:
    return {
        "id": row.id,
        "revision": row.revision,
        "plan": row.payload,
        "updated_at": row.updated_at,
        "result": evaluate(HousingInput.model_validate(row.payload)),
    }


@router.get("")
def list_plans(session: Database) -> list[dict[str, Any]]:
    return [serialize(row) for row in session.scalars(select(HousingPlan).order_by(HousingPlan.id))]


@router.post("/preview")
def preview(plan: HousingInput) -> dict[str, Any]:
    return evaluate(plan)


@router.post("")
def create_plan(request: SaveRequest, session: Database) -> dict[str, Any]:
    if request.revision != 0:
        raise HTTPException(409, "New plans must start with revision zero.")
    row = HousingPlan(payload=request.plan.model_dump(mode="json"), revision=1)
    session.add(row)
    session.commit()
    session.refresh(row)
    return serialize(row)


@router.put("/{plan_id}")
def edit_plan(plan_id: int, request: SaveRequest, session: Database) -> dict[str, Any]:
    result = session.execute(
        update(HousingPlan)
        .where(HousingPlan.id == plan_id, HousingPlan.revision == request.revision)
        .values(
            payload=request.plan.model_dump(mode="json"),
            revision=request.revision + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(HousingPlan.id)
    )
    if result.scalar_one_or_none() is None:
        session.rollback()
        raise HTTPException(
            409, "This plan changed elsewhere. Reopen it before saving your changes."
        )
    session.commit()
    row = session.get(HousingPlan, plan_id)
    assert row is not None
    return serialize(row)
