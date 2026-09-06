"""Planning snapshot storage; callers own validation and commit or rollback."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .models import LifeProjectionPeriod, LifeScenario
from .v2_contracts import PlanningSnapshotContext


def persist_snapshot(
    session: Session, scenario: LifeScenario, periods: list[dict[str, Any]]
) -> dict[str, Any]:
    """Flush the snapshot and periods together without committing the caller's transaction."""
    session.add(scenario)
    session.flush()
    _persist_projection_periods(scenario, periods)
    session.flush()
    return planning_snapshot_dict(scenario, current_legacy_fingerprint=None)


def _persist_projection_periods(scenario: LifeScenario, periods: list[dict[str, Any]]) -> None:
    for period in periods:
        scenario.periods.append(
            LifeProjectionPeriod(
                scenario_id=scenario.id,
                month=date.fromisoformat(str(period["month"])[:10]),
                age_months=int(period["age_months"]),
                working=bool(period["working"]),
                gross_income=Decimal(str(period["gross_income"])),
                net_income=Decimal(str(period["net_income"])),
                employee_retirement=Decimal(str(period["employee_retirement"])),
                employer_retirement=Decimal(str(period["employer_retirement"])),
                stock_plan=Decimal(str(period["stock_plan"])),
                essential_spend=Decimal(str(period["essential_spend"])),
                flexible_spend=Decimal(str(period["flexible_spend"])),
                goal_spend=Decimal(str(period["goal_spend"])),
                cash=Decimal(str(period["cash"])),
                accessible_investments=Decimal(str(period["accessible_investments"])),
                pretax_retirement=Decimal(str(period["pretax_retirement"])),
                hsa=Decimal(str(period["hsa"])),
                restricted_assets=Decimal(str(period["restricted_assets"])),
                debt=Decimal(str(period["debt"])),
                investment_result=Decimal(str(period["investment_result"])),
                total_spendable=Decimal(str(period["total_spendable"])),
            )
        )


def snapshot_context(scenario: LifeScenario) -> PlanningSnapshotContext:
    raw = scenario.input_snapshot.get("snapshot_context")
    try:
        return PlanningSnapshotContext(str(raw))
    except ValueError:
        return PlanningSnapshotContext.LEGACY_COMBINED


def planning_snapshot_dict(
    scenario: LifeScenario, *, current_legacy_fingerprint: str | None
) -> dict[str, Any]:
    context = snapshot_context(scenario)
    legacy = context is PlanningSnapshotContext.LEGACY_COMBINED
    return {
        "id": scenario.id,
        "name": scenario.name,
        "snapshot_context": context.value,
        "context_label": (
            "Legacy combined plan · v1.2.1 inputs" if legacy else context.value.replace("_", " ")
        ),
        "legacy": legacy,
        "target_age": scenario.target_age,
        "path_key": scenario.path_key,
        "status": scenario.status,
        "summary": scenario.summary,
        "input_snapshot": scenario.input_snapshot,
        "warnings": scenario.warnings,
        "engine_version": scenario.engine_version,
        "assumption_version": scenario.assumption_version,
        "benchmark_version": scenario.benchmark_version,
        "source_fingerprint": scenario.source_fingerprint,
        "stale": (
            scenario.source_fingerprint != current_legacy_fingerprint
            if legacy and current_legacy_fingerprint is not None
            else False
        ),
        "created_at": scenario.created_at,
        "periods": [
            {
                "month": period.month,
                "age_months": period.age_months,
                "working": period.working,
                "gross_income": str(period.gross_income),
                "net_income": str(period.net_income),
                "employee_retirement": str(period.employee_retirement),
                "employer_retirement": str(period.employer_retirement),
                "stock_plan": str(period.stock_plan),
                "essential_spend": str(period.essential_spend),
                "flexible_spend": str(period.flexible_spend),
                "goal_spend": str(period.goal_spend),
                "cash": str(period.cash),
                "accessible_investments": str(period.accessible_investments),
                "pretax_retirement": str(period.pretax_retirement),
                "hsa": str(period.hsa),
                "restricted_assets": str(period.restricted_assets),
                "debt": str(period.debt),
                "investment_result": str(period.investment_result),
                "total_spendable": str(period.total_spendable),
            }
            for period in sorted(scenario.periods, key=lambda row: row.month)
        ],
    }
