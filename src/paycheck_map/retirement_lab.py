"""Money Map v2 Retirement and isolated Lab product boundaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .goal_observation import CompletedOperationState, coordinate_goal_observation
from .goal_service import (
    GoalCheckInTrigger,
    GoalValidationError,
    StaleGoalWriteError,
    calculate_goal_position,
    edit_goal,
    program_edit_token,
    program_view,
)
from .life_plan import (
    LifePlanProfileInput,
    ProjectionGoal,
    ProjectionInputs,
    ProjectionProfile,
    ProjectionStartingPoint,
    current_fingerprint,
    get_profile,
    list_goals,
    project_projection_inputs,
    projection_profile,
    starting_point,
)
from .models import (
    ApplicationSetting,
    GoalProgram,
    LifePlanProfile,
    LifeProjectionPeriod,
    LifeScenario,
    utcnow,
)
from .money import ZERO, money
from .refresh import local_business_date
from .v2_contracts import (
    EvidenceClass,
    EvidencedMoney,
    GoalEditRequest,
    LabExperimentSeedKind,
    LifeLabExperimentCreateRequest,
    LifeLabExperimentProjectRequest,
    LifeLabExperimentResult,
    LifeLabExperimentSeed,
    LifeLabPromotionApplied,
    LifeLabPromotionCandidate,
    LifeLabPromotionChange,
    LifeLabPromotionConfirmationRequest,
    LifeLabPromotionPreview,
    LifeLabPromotionPreviewRequest,
    MoneyDerivation,
    PlanningSnapshotContext,
    PromotionField,
    PromotionTarget,
    RetirementGoalInclusion,
    RetirementProfileEditRequest,
    RetirementProfileView,
    RetirementProjectionRequest,
    RetirementProjectionResult,
    RetirementRunSelection,
)

RETIREMENT_PROVENANCE_KEY = "retirement.profile.provenance.v1"
RETIREMENT_PROFILE_TOKEN_VERSION = "retirement-profile-token-v1"
RETIREMENT_RUN_FINGERPRINT_VERSION = "retirement-run-fingerprint-v1"
LAB_EXPERIMENT_FINGERPRINT_VERSION = "lab-experiment-fingerprint-v1"
PROMOTION_PREVIEW_VERSION = "lab-promotion-preview-v1"


class PlanningBoundaryError(ValueError):
    pass


class PlanningNotFoundError(PlanningBoundaryError):
    pass


class PlanningStaleError(PlanningBoundaryError):
    pass


class PlanningValidationError(PlanningBoundaryError):
    pass


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True, default=str))


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _entered(value: Decimal, refs: tuple[str, ...]) -> EvidencedMoney:
    return EvidencedMoney(
        amount=money(value),
        evidence=EvidenceClass.USER_ENTERED,
        source_refs=refs,
    )


def _retirement_default_refs(profile: LifePlanProfile) -> dict[str, tuple[str, ...]]:
    return {
        field: (f"life_plan_profiles:{profile.id}:{column}",)
        for field, column in {
            "current_monthly_outflow": "current_monthly_outflow",
            "retirement_essential_monthly_spend": "essential_monthly_spend",
            "retirement_flexible_monthly_spend": "flexible_monthly_spend",
            "protected_cash_floor": "cash_floor",
        }.items()
    }


def _retirement_provenance(
    session: Session, profile: LifePlanProfile
) -> dict[str, tuple[str, ...]]:
    result = _retirement_default_refs(profile)
    row = session.get(ApplicationSetting, RETIREMENT_PROVENANCE_KEY)
    if row is None:
        return result
    try:
        payload = json.loads(row.value)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict) or payload.get("version") != "retirement-provenance-v1":
        return result
    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        return result
    for field, raw in fields.items():
        if field not in result or not isinstance(raw, dict):
            continue
        refs = raw.get("source_refs", [])
        if isinstance(refs, list) and refs:
            result[field] = tuple(sorted({str(ref) for ref in refs if str(ref)}))
    return result


def _persist_retirement_provenance(
    session: Session,
    *,
    changed_fields: set[str],
    source_ref: str,
    origin: str,
) -> None:
    row = session.get(ApplicationSetting, RETIREMENT_PROVENANCE_KEY)
    if row is None:
        payload: dict[str, Any] = {"version": "retirement-provenance-v1", "fields": {}}
        row = ApplicationSetting(key=RETIREMENT_PROVENANCE_KEY, value="")
        session.add(row)
    else:
        try:
            payload = cast(dict[str, Any], json.loads(row.value))
        except json.JSONDecodeError:
            payload = {"version": "retirement-provenance-v1", "fields": {}}
    fields = payload.setdefault("fields", {})
    if not isinstance(fields, dict):
        fields = {}
        payload["fields"] = fields
    for field in changed_fields:
        fields[field] = {
            "evidence": "user_entered",
            "source_refs": [source_ref],
            "edit_origin": origin,
        }
    row.value = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    row.updated_at = utcnow()


def retirement_profile_token(profile: LifePlanProfile) -> str:
    return _canonical_hash(
        {
            "version": RETIREMENT_PROFILE_TOKEN_VERSION,
            "profile_id": profile.id,
            "birth_date": profile.birth_date,
            "state": profile.state,
            "plan_through_age": profile.end_age,
            "current_monthly_outflow": format(money(profile.current_monthly_outflow), ".2f"),
            "retirement_essential_monthly_spend": format(
                money(profile.essential_monthly_spend), ".2f"
            ),
            "retirement_flexible_monthly_spend": format(
                money(profile.flexible_monthly_spend), ".2f"
            ),
            "protected_cash_floor": format(money(profile.cash_floor), ".2f"),
            "retirement_tax_haircut_pct": format(Decimal(profile.retirement_tax_rate_pct), ".4f"),
            "work_optional_ages": list(profile.target_ages),
            "notes": profile.notes,
            "updated_at": _aware_utc(profile.updated_at).isoformat(timespec="microseconds"),
        }
    )


def retirement_profile_view(session: Session, profile: LifePlanProfile) -> RetirementProfileView:
    refs = _retirement_provenance(session, profile)
    return RetirementProfileView(
        profile_id=profile.id,
        birth_date=profile.birth_date,
        state=profile.state,
        plan_through_age=profile.end_age,
        current_monthly_outflow=_entered(
            profile.current_monthly_outflow, refs["current_monthly_outflow"]
        ),
        retirement_essential_monthly_spend=_entered(
            profile.essential_monthly_spend,
            refs["retirement_essential_monthly_spend"],
        ),
        retirement_flexible_monthly_spend=_entered(
            profile.flexible_monthly_spend,
            refs["retirement_flexible_monthly_spend"],
        ),
        protected_cash_floor=_entered(profile.cash_floor, refs["protected_cash_floor"]),
        retirement_tax_haircut_pct=profile.retirement_tax_rate_pct,
        work_optional_ages=tuple(profile.target_ages),
        notes=profile.notes,
        edit_token=retirement_profile_token(profile),
        updated_at=_aware_utc(profile.updated_at),
    )


def edit_retirement_profile(
    session: Session,
    *,
    request: RetirementProfileEditRequest,
    provenance_origin: str = "v2_owner_edit",
    provenance_source_ref: str | None = None,
) -> RetirementProfileView:
    profile = get_profile(session)
    if profile is None:
        raise PlanningNotFoundError("A Retirement profile has not been created")
    if request.expected_edit_token != retirement_profile_token(profile):
        raise PlanningStaleError("Retirement assumptions changed after this edit was loaded")

    values: dict[str, Any] = {
        "birth_date": request.birth_date or profile.birth_date,
        "state": (request.state or profile.state).upper(),
        "end_age": request.plan_through_age or profile.end_age,
        "current_monthly_outflow": (
            request.current_monthly_outflow
            if request.current_monthly_outflow is not None
            else profile.current_monthly_outflow
        ),
        "essential_monthly_spend": (
            request.retirement_essential_monthly_spend
            if request.retirement_essential_monthly_spend is not None
            else profile.essential_monthly_spend
        ),
        "flexible_monthly_spend": (
            request.retirement_flexible_monthly_spend
            if request.retirement_flexible_monthly_spend is not None
            else profile.flexible_monthly_spend
        ),
        "cash_floor": (
            request.protected_cash_floor
            if request.protected_cash_floor is not None
            else profile.cash_floor
        ),
        "retirement_tax_rate_pct": (
            request.retirement_tax_haircut_pct
            if request.retirement_tax_haircut_pct is not None
            else profile.retirement_tax_rate_pct
        ),
        "target_ages": list(request.work_optional_ages or profile.target_ages),
        "notes": request.notes if request.notes is not None else profile.notes,
    }
    validated = LifePlanProfileInput.model_validate(values)
    stored_values = validated.model_dump()
    changed_columns = {
        column
        for column, current in {
            "birth_date": profile.birth_date,
            "state": profile.state,
            "end_age": profile.end_age,
            "current_monthly_outflow": profile.current_monthly_outflow,
            "essential_monthly_spend": profile.essential_monthly_spend,
            "flexible_monthly_spend": profile.flexible_monthly_spend,
            "cash_floor": profile.cash_floor,
            "retirement_tax_rate_pct": profile.retirement_tax_rate_pct,
            "target_ages": profile.target_ages,
            "notes": profile.notes,
        }.items()
        if stored_values[column] != current
    }
    if not changed_columns:
        raise PlanningValidationError("The submitted Retirement edit does not change any value")
    changed_at = utcnow()
    result = session.execute(
        update(LifePlanProfile)
        .where(
            LifePlanProfile.id == profile.id,
            LifePlanProfile.updated_at == profile.updated_at,
        )
        .values(**stored_values, updated_at=changed_at)
    )
    if cast(Any, result).rowcount != 1:
        raise PlanningStaleError("Retirement assumptions changed during this edit")
    provenance_fields = {
        {
            "current_monthly_outflow": "current_monthly_outflow",
            "essential_monthly_spend": "retirement_essential_monthly_spend",
            "flexible_monthly_spend": "retirement_flexible_monthly_spend",
            "cash_floor": "protected_cash_floor",
        }[column]
        for column in changed_columns
        if column
        in {
            "current_monthly_outflow",
            "essential_monthly_spend",
            "flexible_monthly_spend",
            "cash_floor",
        }
    }
    if provenance_fields:
        source_ref = provenance_source_ref or (
            f"retirement_profile:{profile.id}:{provenance_origin}:"
            f"{changed_at.isoformat(timespec='microseconds')}"
        )
        _persist_retirement_provenance(
            session,
            changed_fields=provenance_fields,
            source_ref=source_ref,
            origin=provenance_origin,
        )
    session.flush()
    session.expire(profile)
    session.refresh(profile)
    return retirement_profile_view(session, profile)


def retirement_starting_evidence(session: Session) -> dict[str, Any]:
    evidence = starting_point(session)
    return {
        **evidence,
        "evidence_classification": {
            "cash": "observed",
            "accessible_investments": "observed",
            "pretax_retirement": "observed",
            "hsa": "observed",
            "restricted_assets": "observed",
            "debt": "observed",
            "observed_monthly_outflow": "observed",
            "payroll": "observed" if evidence.get("payroll") else "unavailable",
        },
        "read_only": True,
    }


def eligible_retirement_goals(session: Session) -> tuple[Any, ...]:
    return tuple(
        program_view(program)
        for program in session.scalars(select(GoalProgram).order_by(GoalProgram.target_date))
    )


def _retirement_goal_snapshot(
    session: Session, program: GoalProgram, *, observed_on: date
) -> RetirementGoalInclusion:
    calculated = calculate_goal_position(session, program=program, observed_on=observed_on)
    view = program_view(program)
    target = cast(Decimal, view.target_amount.amount)
    reserved = cast(Decimal, view.reserved_for_goal.amount)
    refs = tuple(sorted({*view.target_amount.source_refs, *view.reserved_for_goal.source_refs}))
    return RetirementGoalInclusion(
        goal_program_id=program.public_key,
        name=program.name,
        target_date=program.target_date,
        goal_source_fingerprint=calculated.source_fingerprint,
        target_amount=view.target_amount,
        reserved_for_goal=view.reserved_for_goal,
        remaining_target=EvidencedMoney(
            amount=money(max(target - reserved, ZERO)),
            evidence=EvidenceClass.DERIVED,
            source_refs=refs,
            derivation=MoneyDerivation.RETIREMENT_GOAL_SNAPSHOT,
        ),
        evidence_refs=refs,
    )


def _goal_projection_input(
    profile: LifePlanProfile, program: GoalProgram, snapshot: RetirementGoalInclusion
) -> ProjectionGoal:
    return ProjectionGoal(
        id=program.id,
        profile_id=profile.id,
        name=snapshot.name,
        target_date=snapshot.target_date,
        target_amount=cast(Decimal, snapshot.remaining_target.amount),
        reserved_amount=ZERO,
        annual_cost=ZERO,
        priority="required",
        enabled=True,
        notes=(
            "Immutable operational-goal snapshot included only in this Retirement run; "
            f"source {snapshot.goal_source_fingerprint}."
        ),
        provenance="copied_operational_goal_snapshot",
    )


def run_retirement_projection(
    session: Session,
    *,
    request: RetirementProjectionRequest,
    observed_on: date | None = None,
) -> RetirementProjectionResult:
    profile = get_profile(session)
    if profile is None:
        raise PlanningNotFoundError("A Retirement profile has not been created")
    today = observed_on or date.today()
    included: RetirementGoalInclusion | None = None
    projection_goals: tuple[ProjectionGoal, ...] = ()
    if request.goal_program_id is not None:
        program = session.scalar(
            select(GoalProgram).where(GoalProgram.public_key == request.goal_program_id).limit(1)
        )
        if program is None:
            raise PlanningNotFoundError("The selected operational goal was not found")
        included = _retirement_goal_snapshot(session, program, observed_on=today)
        projection_goals = (_goal_projection_input(profile, program, included),)
    start = ProjectionStartingPoint.from_dict(starting_point(session, as_of=today))
    inputs = ProjectionInputs(
        profile=projection_profile(profile),
        goals=projection_goals,
        starting_point=start,
        input_context=("retirement_with_goal" if included else "retirement_default"),
    )
    projection = project_projection_inputs(
        inputs, target_ages=[request.work_optional_age], as_of=today
    )
    target = cast(list[dict[str, Any]], projection["results"])[0]
    selected = next(
        row
        for row in cast(list[dict[str, Any]], target["paths"])
        if row["path_key"] == request.path.value
    )
    run_fingerprint = _canonical_hash(
        {
            "version": RETIREMENT_RUN_FINGERPRINT_VERSION,
            "projection_source_fingerprint": projection["source_fingerprint"],
            "work_optional_age": request.work_optional_age,
            "path": request.path.value,
            "included_goal": (included.model_dump(mode="json") if included is not None else None),
        }
    )
    selection = RetirementRunSelection(
        run_selection_id=f"retirement_{run_fingerprint[:16]}",
        work_optional_age=request.work_optional_age,
        path=request.path,
        include_operational_goal=included is not None,
        included_goal=included,
    )
    work_stop = cast(dict[str, str], selected["work_stop_assets"])
    end_assets = cast(dict[str, str], selected["end_assets"])
    return RetirementProjectionResult(
        run_selection=selection,
        run_fingerprint=run_fingerprint,
        profile=retirement_profile_view(session, profile),
        snapshot_context=("retirement_with_goal" if included else "retirement_default"),
        bridge_verdict=cast(
            Literal[
                "works",
                "works_essentials_only",
                "shortfall",
                "insufficient_accessible_bridge",
            ],
            selected["status"],
        ),
        accessible_assets_at_work_stop=Decimal(
            work_stop.get("accessible_total", work_stop["accessible_investments"])
        ),
        retirement_assets_at_work_stop=Decimal(work_stop["pretax_retirement"]),
        end_spendable_assets=Decimal(end_assets["total_spendable"]),
        required_money_runway_months=_runway_months(
            cast(date, selected["work_stop_month"]),
            cast(date | None, selected["first_shortfall_month"]),
        ),
        warnings=tuple(cast(list[str], projection["warnings"])),
        selected_result=_json_safe(selected),
        projection=_json_safe(projection),
    )


def _runway_months(work_stop: date, shortfall: date | None) -> int | None:
    if shortfall is None:
        return None
    return max(0, (shortfall.year - work_stop.year) * 12 + shortfall.month - work_stop.month)


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


def save_retirement_snapshot(
    session: Session, *, name: str, run: RetirementProjectionResult
) -> dict[str, Any]:
    profile = get_profile(session)
    if profile is None or profile.id != run.profile.profile_id:
        raise PlanningStaleError("The Retirement profile changed before the snapshot was saved")
    if retirement_profile_token(profile) != run.profile.edit_token:
        raise PlanningStaleError("The Retirement profile changed before the snapshot was saved")
    selected = cast(dict[str, Any], run.selected_result)
    projection = cast(dict[str, Any], run.projection)
    scenario = LifeScenario(
        profile_id=profile.id,
        name=name,
        target_age=run.run_selection.work_optional_age,
        path_key=run.run_selection.path.value,
        input_snapshot=_json_safe(
            {
                "snapshot_context": run.snapshot_context,
                "run_fingerprint": run.run_fingerprint,
                "run_selection": run.run_selection.model_dump(mode="json"),
                "profile": run.profile.model_dump(mode="json"),
                "projection": projection,
                "selected_result": selected,
            }
        ),
        source_fingerprint=run.run_fingerprint,
        engine_version=str(projection["engine_version"]),
        assumption_version=str(cast(dict[str, Any], projection["assumptions"])["version"]),
        benchmark_version=str(
            cast(dict[str, Any], projection["benchmarks"]).get("version", "unavailable")
        ),
        status=str(selected["status"]),
        warnings=list(run.warnings),
        summary=_json_safe(
            {
                **{key: value for key, value in selected.items() if key != "periods"},
                "snapshot_context": run.snapshot_context,
                "run_fingerprint": run.run_fingerprint,
            }
        ),
    )
    session.add(scenario)
    session.flush()
    _persist_projection_periods(scenario, cast(list[dict[str, Any]], selected["periods"]))
    session.flush()
    return planning_snapshot_dict(scenario, current_legacy_fingerprint=None)


def _snapshot_context(scenario: LifeScenario) -> PlanningSnapshotContext:
    raw = scenario.input_snapshot.get("snapshot_context")
    try:
        return PlanningSnapshotContext(str(raw))
    except ValueError:
        return PlanningSnapshotContext.LEGACY_COMBINED


def planning_snapshot_dict(
    scenario: LifeScenario, *, current_legacy_fingerprint: str | None
) -> dict[str, Any]:
    context = _snapshot_context(scenario)
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


def _legacy_fingerprint(session: Session, profile: LifePlanProfile | None) -> str | None:
    if profile is None:
        return None
    return current_fingerprint(session, profile, list_goals(session, profile.id))


def list_retirement_snapshots(session: Session) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(LifeScenario).order_by(LifeScenario.created_at.desc())))
    return [
        planning_snapshot_dict(row, current_legacy_fingerprint=None)
        for row in rows
        if _snapshot_context(row)
        in {
            PlanningSnapshotContext.RETIREMENT_DEFAULT,
            PlanningSnapshotContext.RETIREMENT_WITH_GOAL,
        }
    ]


def open_retirement_snapshot(session: Session, snapshot_id: int) -> dict[str, Any]:
    row = session.get(LifeScenario, snapshot_id)
    if row is None or _snapshot_context(row) not in {
        PlanningSnapshotContext.RETIREMENT_DEFAULT,
        PlanningSnapshotContext.RETIREMENT_WITH_GOAL,
    }:
        raise PlanningNotFoundError("The Retirement snapshot was not found")
    return planning_snapshot_dict(row, current_legacy_fingerprint=None)


def _blank_profile(today: date) -> dict[str, Any]:
    return {
        "id": 0,
        "birth_date": date(today.year - 35, 1, 1).isoformat(),
        "state": "NJ",
        "end_age": 95,
        "current_monthly_outflow": "0.00",
        "essential_monthly_spend": "0.00",
        "flexible_monthly_spend": "0.00",
        "cash_floor": "0.00",
        "retirement_tax_rate_pct": "20.0000",
        "target_ages": [65],
        "notes": "",
    }


def _blank_start(today: date) -> dict[str, Any]:
    return {
        "as_of": today.isoformat(),
        "cash": "0.00",
        "accessible_investments": "0.00",
        "pretax_retirement": "0.00",
        "hsa": "0.00",
        "restricted_assets": "0.00",
        "debt": "0.00",
        "accessible_total": "0.00",
        "tracked_total": "0.00",
        "observed_monthly_outflow": "0.00",
        "outflow_months": [],
        "payroll": None,
        "accounts": [],
        "warnings": ["Blank experiment uses no copied Goal or Retirement money."],
    }


def _default_mission(today: date) -> dict[str, Any]:
    return {
        "target_amount": "0.00",
        "target_date": date(today.year + 1, today.month, min(today.day, 28)).isoformat(),
        "selected_age": 65,
        "path": "middle",
        "starting_stake": "5000.00",
        "weekly_compound_pct": "0.9000",
        "take_home_pct": "60.0000",
        "ownership_pct": "20.0000",
        "exit_tax_pct": "30.0000",
        "revenue_multiple": "6.0000",
        "eligible_vested_balance": "0.00",
        "loan_rate_pct": "8.5000",
        "loan_years": "5.0000",
        "current_loan": "0.00",
        "highest_prior_loan": "0.00",
    }


def experiment_fingerprint(experiment_id: str, draft: dict[str, object]) -> str:
    return _canonical_hash(
        {
            "version": LAB_EXPERIMENT_FINGERPRINT_VERSION,
            "experiment_id": experiment_id,
            "draft": draft,
        }
    )


def seed_lab_experiment(
    session: Session,
    *,
    request: LifeLabExperimentCreateRequest,
    today: date | None = None,
) -> LifeLabExperimentSeed:
    current = today or date.today()
    experiment_id = f"lab_{uuid.uuid4().hex}"
    profile = _blank_profile(current)
    start = _blank_start(current)
    mission = _default_mission(current)
    goals: list[dict[str, Any]] = []
    seeded_money: dict[str, EvidencedMoney] = {}
    source_fingerprint: str | None = None
    source_label: str | None = None
    promotable: dict[str, str] = {}

    if request.seed_kind is LabExperimentSeedKind.CURRENT_GOAL:
        program = session.scalar(
            select(GoalProgram)
            .where(GoalProgram.is_primary.is_(True))
            .order_by(GoalProgram.id)
            .limit(1)
        )
        if program is None:
            raise PlanningNotFoundError("A current primary goal is required for this seed")
        calculated = calculate_goal_position(session, program=program, observed_on=current)
        view = program_view(program)
        target = cast(Decimal, view.target_amount.amount)
        reserved = cast(Decimal, view.reserved_for_goal.amount)
        remaining = money(max(target - reserved, ZERO))
        source_fingerprint = calculated.source_fingerprint
        source_label = program.name
        seeded_money = {
            "goal_target": view.target_amount,
            "reserved_for_goal": view.reserved_for_goal,
            "protected_cash_floor": view.protected_cash_floor,
            "remaining_target": EvidencedMoney(
                amount=remaining,
                evidence=EvidenceClass.DERIVED,
                source_refs=tuple(
                    sorted(
                        {
                            *view.target_amount.source_refs,
                            *view.reserved_for_goal.source_refs,
                        }
                    )
                ),
                derivation=MoneyDerivation.REMAINING_TARGET,
            ),
        }
        mission["target_amount"] = format(remaining, ".2f")
        mission["target_date"] = program.target_date.isoformat()
        profile["cash_floor"] = format(program.protected_cash_floor, ".2f")
        goals = [
            {
                "id": program.id,
                "profile_id": 0,
                "name": program.name,
                "target_date": program.target_date.isoformat(),
                "target_amount": format(remaining, ".2f"),
                "reserved_amount": "0.00",
                "annual_cost": "0.00",
                "priority": "required",
                "enabled": True,
                "notes": "Copied current GoalProgram snapshot",
            }
        ]
        promotable = {
            "goal_target": format(target, ".2f"),
            "reserved_for_goal": format(reserved, ".2f"),
            "protected_cash_floor": format(program.protected_cash_floor, ".2f"),
        }
    elif request.seed_kind is LabExperimentSeedKind.RETIREMENT_RESULT:
        row = session.get(LifeScenario, cast(int, request.retirement_snapshot_id))
        if row is None or _snapshot_context(row) not in {
            PlanningSnapshotContext.RETIREMENT_DEFAULT,
            PlanningSnapshotContext.RETIREMENT_WITH_GOAL,
        }:
            raise PlanningNotFoundError("The selected Retirement snapshot was not found")
        stored = row.input_snapshot
        projection = cast(dict[str, Any], stored.get("projection", {}))
        selected = cast(dict[str, Any], stored.get("selected_result", row.summary))
        copied_profile = cast(dict[str, Any], projection.get("profile", {}))
        copied_start = cast(dict[str, Any], projection.get("starting_point", {}))
        if not copied_profile or not copied_start:
            raise PlanningValidationError("The Retirement snapshot lacks reproducible inputs")
        profile = _json_safe(copied_profile)
        start = _json_safe(copied_start)
        goals = _json_safe(projection.get("goals", []))
        source_fingerprint = row.source_fingerprint
        source_label = row.name
        make_it_happen = cast(dict[str, Any], selected.get("make_it_happen", {}))
        capital = str(make_it_happen.get("retirement_capital_needed") or "0.00")
        mission["target_amount"] = capital
        mission["target_date"] = str(
            make_it_happen.get("retirement_deadline")
            or selected.get("work_stop_month")
            or mission["target_date"]
        )[:10]
        mission["selected_age"] = row.target_age
        mission["path"] = row.path_key
        seeded_money = {
            "retirement_capital_needed": _entered(
                Decimal(capital), (f"retirement_run:{row.source_fingerprint}:capital",)
            ),
            "retirement_essential_monthly_spend": _entered(
                Decimal(str(profile["essential_monthly_spend"])),
                (f"retirement_run:{row.source_fingerprint}:essential_spend",),
            ),
            "retirement_flexible_monthly_spend": _entered(
                Decimal(str(profile["flexible_monthly_spend"])),
                (f"retirement_run:{row.source_fingerprint}:flexible_spend",),
            ),
        }
        promotable = {
            "retirement_essential_monthly_spend": str(profile["essential_monthly_spend"]),
            "retirement_flexible_monthly_spend": str(profile["flexible_monthly_spend"]),
        }

    draft: dict[str, object] = {
        "seed": {
            "kind": request.seed_kind.value,
            "source_fingerprint": source_fingerprint,
            "source_label": source_label,
        },
        "profile": profile,
        "starting_point": start,
        "goals": goals,
        "mission": mission,
        "promotable_values": promotable,
    }
    fingerprint = experiment_fingerprint(experiment_id, draft)
    return LifeLabExperimentSeed(
        experiment_id=experiment_id,
        seed_kind=request.seed_kind,
        source_fingerprint=source_fingerprint,
        seeded_money=seeded_money,
        source_label=source_label,
        draft=draft,
        experiment_fingerprint=fingerprint,
    )


def _draft_profile(raw: dict[str, Any]) -> ProjectionProfile:
    validated = LifePlanProfileInput.model_validate(
        {
            "birth_date": raw["birth_date"],
            "state": raw["state"],
            "end_age": raw["end_age"],
            "current_monthly_outflow": raw["current_monthly_outflow"],
            "essential_monthly_spend": raw["essential_monthly_spend"],
            "flexible_monthly_spend": raw["flexible_monthly_spend"],
            "cash_floor": raw["cash_floor"],
            "retirement_tax_rate_pct": raw["retirement_tax_rate_pct"],
            "target_ages": raw["target_ages"],
            "notes": raw.get("notes", ""),
        }
    )
    return ProjectionProfile(
        id=int(raw.get("id", 0)),
        birth_date=validated.birth_date,
        state=validated.state,
        end_age=validated.end_age,
        current_monthly_outflow=money(validated.current_monthly_outflow),
        essential_monthly_spend=money(validated.essential_monthly_spend),
        flexible_monthly_spend=money(validated.flexible_monthly_spend),
        cash_floor=money(validated.cash_floor),
        retirement_tax_rate_pct=validated.retirement_tax_rate_pct,
        target_ages=tuple(validated.target_ages),
        notes=validated.notes,
    )


def _draft_goals(rows: list[dict[str, Any]]) -> tuple[ProjectionGoal, ...]:
    goals: list[ProjectionGoal] = []
    for index, row in enumerate(rows, start=1):
        priority = str(row.get("priority", "required"))
        if priority not in {"required", "flexible"}:
            raise PlanningValidationError("Lab goal priority is unsupported")
        goals.append(
            ProjectionGoal(
                id=int(row.get("id", index)),
                profile_id=int(row.get("profile_id", 0)),
                name=str(row["name"]),
                target_date=date.fromisoformat(str(row["target_date"])),
                target_amount=money(Decimal(str(row["target_amount"]))),
                reserved_amount=money(Decimal(str(row.get("reserved_amount", ZERO)))),
                annual_cost=money(Decimal(str(row.get("annual_cost", ZERO)))),
                priority=cast(Literal["required", "flexible"], priority),
                enabled=bool(row.get("enabled", True)),
                notes=str(row.get("notes", "")),
                provenance="isolated_lab_draft",
            )
        )
    return tuple(goals)


def project_lab_experiment(*, request: LifeLabExperimentProjectRequest) -> LifeLabExperimentResult:
    draft = request.draft
    seed = cast(dict[str, Any], draft.get("seed"))
    if not isinstance(seed, dict):
        raise PlanningValidationError("The Lab draft has no seed context")
    try:
        seed_kind = LabExperimentSeedKind(str(seed["kind"]))
    except (KeyError, ValueError) as exc:
        raise PlanningValidationError("The Lab draft seed context is invalid") from exc
    profile_raw = cast(dict[str, Any], draft.get("profile"))
    start_raw = cast(dict[str, Any], draft.get("starting_point"))
    goals_raw = cast(list[dict[str, Any]], draft.get("goals", []))
    mission = cast(dict[str, Any], draft.get("mission"))
    if (
        not isinstance(profile_raw, dict)
        or not isinstance(start_raw, dict)
        or not isinstance(mission, dict)
    ):
        raise PlanningValidationError("The Lab draft is incomplete")
    profile = _draft_profile(profile_raw)
    start = ProjectionStartingPoint.from_dict(start_raw)
    age = int(mission.get("selected_age", profile.target_ages[0]))
    path = str(mission.get("path", "middle"))
    if path not in {"middle", "rough", "early_crash"}:
        raise PlanningValidationError("The selected Lab path is unsupported")
    projection = project_projection_inputs(
        ProjectionInputs(
            profile=profile,
            goals=_draft_goals(goals_raw),
            starting_point=start,
            input_context=f"lab_{seed_kind.value}",
        ),
        target_ages=[age],
        as_of=start.as_of,
    )
    target = cast(list[dict[str, Any]], projection["results"])[0]
    selected = next(
        row for row in cast(list[dict[str, Any]], target["paths"]) if row["path_key"] == path
    )
    fingerprint = experiment_fingerprint(request.experiment_id, draft)
    context = {
        LabExperimentSeedKind.BLANK: "lab_blank",
        LabExperimentSeedKind.CURRENT_GOAL: "lab_current_goal",
        LabExperimentSeedKind.RETIREMENT_RESULT: "lab_retirement_result",
    }[seed_kind]
    return LifeLabExperimentResult(
        experiment_id=request.experiment_id,
        experiment_fingerprint=fingerprint,
        seed_kind=seed_kind,
        snapshot_context=cast(
            Literal["lab_blank", "lab_current_goal", "lab_retirement_result"], context
        ),
        draft=draft,
        projection=_json_safe(projection),
        reverse_solver={
            "mission_capital": cast(dict[str, Any], selected["make_it_happen"])[
                "retirement_capital_needed"
            ],
            "additional_monthly_after_tax_income": cast(dict[str, Any], selected["make_it_happen"])[
                "additional_monthly_after_tax_income"
            ],
            "selected_result": _json_safe(selected),
            "paths": {
                "linear_income": {"promotable": False},
                "compound_sprint": {"promotable": False},
                "business_exit": {"promotable": False},
                "401k_loan_arithmetic": {
                    "promotable": False,
                    "advice": False,
                    "eligibility": False,
                    "money_movement": False,
                },
            },
        },
        snapshot_context_evidence={
            "source_fingerprint": seed.get("source_fingerprint"),
            "source_label": seed.get("source_label"),
            "copied_once": seed_kind is not LabExperimentSeedKind.BLANK,
        },
    )


def save_lab_snapshot(
    session: Session, *, name: str, result: LifeLabExperimentResult
) -> dict[str, Any]:
    if experiment_fingerprint(result.experiment_id, result.draft) != result.experiment_fingerprint:
        raise PlanningStaleError("The Lab draft changed before the snapshot was saved")
    profile = get_profile(session)
    if profile is None:
        raise PlanningValidationError(
            "A durable local profile container is required to save this experiment"
        )
    projection = cast(dict[str, Any], result.projection)
    selected = cast(dict[str, Any], cast(dict[str, Any], result.reverse_solver)["selected_result"])
    mission = cast(dict[str, Any], result.draft["mission"])
    scenario = LifeScenario(
        profile_id=profile.id,
        name=name,
        target_age=int(mission["selected_age"]),
        path_key=str(mission["path"]),
        input_snapshot=_json_safe(
            {
                "snapshot_context": result.snapshot_context,
                "experiment_id": result.experiment_id,
                "experiment_fingerprint": result.experiment_fingerprint,
                "draft": result.draft,
                "projection": projection,
                "selected_result": selected,
                "snapshot_context_evidence": result.snapshot_context_evidence,
            }
        ),
        source_fingerprint=result.experiment_fingerprint,
        engine_version=str(projection["engine_version"]),
        assumption_version=str(cast(dict[str, Any], projection["assumptions"])["version"]),
        benchmark_version=str(
            cast(dict[str, Any], projection["benchmarks"]).get("version", "unavailable")
        ),
        status=str(selected["status"]),
        warnings=cast(list[str], projection["warnings"]),
        summary=_json_safe(
            {
                **{key: value for key, value in selected.items() if key != "periods"},
                "snapshot_context": result.snapshot_context,
                "experiment_id": result.experiment_id,
                "experiment_fingerprint": result.experiment_fingerprint,
            }
        ),
    )
    session.add(scenario)
    session.flush()
    _persist_projection_periods(scenario, cast(list[dict[str, Any]], selected["periods"]))
    session.flush()
    return planning_snapshot_dict(scenario, current_legacy_fingerprint=None)


def list_lab_snapshots(session: Session) -> list[dict[str, Any]]:
    profile = get_profile(session)
    legacy_fingerprint = _legacy_fingerprint(session, profile)
    rows = list(session.scalars(select(LifeScenario).order_by(LifeScenario.created_at.desc())))
    return [
        planning_snapshot_dict(row, current_legacy_fingerprint=legacy_fingerprint)
        for row in rows
        if _snapshot_context(row)
        in {
            PlanningSnapshotContext.LAB_BLANK,
            PlanningSnapshotContext.LAB_CURRENT_GOAL,
            PlanningSnapshotContext.LAB_RETIREMENT_RESULT,
            PlanningSnapshotContext.LEGACY_COMBINED,
        }
    ]


def open_lab_snapshot(session: Session, snapshot_id: int) -> dict[str, Any]:
    row = session.get(LifeScenario, snapshot_id)
    allowed = {
        PlanningSnapshotContext.LAB_BLANK,
        PlanningSnapshotContext.LAB_CURRENT_GOAL,
        PlanningSnapshotContext.LAB_RETIREMENT_RESULT,
        PlanningSnapshotContext.LEGACY_COMBINED,
    }
    if row is None or _snapshot_context(row) not in allowed:
        raise PlanningNotFoundError("The Lab snapshot was not found")
    profile = get_profile(session)
    return planning_snapshot_dict(
        row, current_legacy_fingerprint=_legacy_fingerprint(session, profile)
    )


GOAL_FIELD_MAP = {
    PromotionField.GOAL_TARGET: "goal_programs.target_amount",
    PromotionField.RESERVED_FOR_GOAL: "goal_programs.reserved_amount",
    PromotionField.PROTECTED_CASH_FLOOR: "goal_programs.protected_cash_floor",
}
RETIREMENT_FIELD_MAP = {
    PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND: "life_plan_profiles.essential_monthly_spend",
    PromotionField.RETIREMENT_FLEXIBLE_MONTHLY_SPEND: "life_plan_profiles.flexible_monthly_spend",
}


def _draft_promotable_value(draft: dict[str, object], field: PromotionField) -> Decimal:
    values = draft.get("promotable_values")
    if not isinstance(values, dict) or field.value not in values:
        raise PlanningValidationError(f"{field.value} is not supported by this Lab draft")
    try:
        return money(Decimal(str(values[field.value])))
    except Exception as exc:
        raise PlanningValidationError("The Lab promotion value is invalid") from exc


def preview_lab_promotion(
    session: Session, *, request: LifeLabPromotionPreviewRequest
) -> LifeLabPromotionPreview:
    actual_fingerprint = experiment_fingerprint(request.experiment_id, request.draft)
    if actual_fingerprint != request.expected_experiment_fingerprint:
        raise PlanningStaleError("The Lab experiment changed before promotion preview")
    if len({change.field for change in request.changes}) != len(request.changes):
        raise PlanningValidationError("Promotion fields must be unique")

    before_values: dict[PromotionField, tuple[Decimal, tuple[str, ...]]] = {}
    if request.target_surface is PromotionTarget.GOALS:
        if any(change.field not in GOAL_FIELD_MAP for change in request.changes):
            raise PlanningValidationError("The Lab result is not promotable to Goals")
        program = session.scalar(
            select(GoalProgram).where(GoalProgram.public_key == request.target_id).limit(1)
        )
        if program is None:
            raise PlanningNotFoundError("The promotion target Goal was not found")
        target_token = program_edit_token(program)
        target_id = program.public_key
        goal_view = program_view(program)
        by_field = {
            PromotionField.GOAL_TARGET: goal_view.target_amount,
            PromotionField.RESERVED_FOR_GOAL: goal_view.reserved_for_goal,
            PromotionField.PROTECTED_CASH_FLOOR: goal_view.protected_cash_floor,
        }
        for field, value in by_field.items():
            before_values[field] = (cast(Decimal, value.amount), value.source_refs)
    else:
        if any(change.field not in RETIREMENT_FIELD_MAP for change in request.changes):
            raise PlanningValidationError("The Lab result is not promotable to Retirement")
        profile = get_profile(session)
        if profile is None or request.target_id != f"retirement_profile_{profile.id}":
            raise PlanningNotFoundError("The promotion target Retirement profile was not found")
        target_token = retirement_profile_token(profile)
        target_id = request.target_id
        profile_view = retirement_profile_view(session, profile)
        before_values = {
            PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND: (
                cast(Decimal, profile_view.retirement_essential_monthly_spend.amount),
                profile_view.retirement_essential_monthly_spend.source_refs,
            ),
            PromotionField.RETIREMENT_FLEXIBLE_MONTHLY_SPEND: (
                cast(Decimal, profile_view.retirement_flexible_monthly_spend.amount),
                profile_view.retirement_flexible_monthly_spend.source_refs,
            ),
        }

    changes: list[LifeLabPromotionChange] = []
    for candidate in request.changes:
        draft_value = _draft_promotable_value(request.draft, candidate.field)
        if candidate.after != draft_value:
            raise PlanningStaleError(
                f"{candidate.field.value} no longer matches the submitted Lab experiment"
            )
        before, target_refs = before_values[candidate.field]
        if candidate.after == before:
            raise PlanningValidationError(
                f"{candidate.field.value} does not change the stored target"
            )
        source_ref = f"lab_experiment:{actual_fingerprint}:promotion:{candidate.field.value}"
        field_map = (
            GOAL_FIELD_MAP
            if request.target_surface is PromotionTarget.GOALS
            else RETIREMENT_FIELD_MAP
        )
        changes.append(
            LifeLabPromotionChange(
                field=candidate.field,
                stored_target_field=field_map[candidate.field],
                before=_entered(before, target_refs),
                after=_entered(candidate.after, (source_ref,)),
                source_provenance=(source_ref,),
                target_provenance=target_refs,
            )
        )
    if request.target_surface is PromotionTarget.GOALS:
        current_target = before_values[PromotionField.GOAL_TARGET][0]
        current_reserved = before_values[PromotionField.RESERVED_FOR_GOAL][0]
        next_target = next(
            (
                cast(Decimal, change.after.amount)
                for change in changes
                if change.field is PromotionField.GOAL_TARGET
            ),
            current_target,
        )
        next_reserved = next(
            (
                cast(Decimal, change.after.amount)
                for change in changes
                if change.field is PromotionField.RESERVED_FOR_GOAL
            ),
            current_reserved,
        )
        if next_reserved > next_target:
            raise PlanningValidationError("Reserved amount cannot exceed the goal target")
    preview_payload = {
        "version": PROMOTION_PREVIEW_VERSION,
        "experiment_id": request.experiment_id,
        "experiment_fingerprint": actual_fingerprint,
        "target_surface": request.target_surface.value,
        "target_id": target_id,
        "target_stale_write_token": target_token,
        "changes": [change.model_dump(mode="json") for change in changes],
    }
    return LifeLabPromotionPreview(
        preview_id=_canonical_hash(preview_payload),
        experiment_id=request.experiment_id,
        experiment_fingerprint=actual_fingerprint,
        target_surface=request.target_surface,
        target_id=target_id,
        target_stale_write_token=target_token,
        changes=tuple(changes),
    )


def confirm_lab_promotion(
    session: Session, *, request: LifeLabPromotionConfirmationRequest
) -> LifeLabPromotionApplied:
    preview = request.preview
    candidates = tuple(
        LifeLabPromotionCandidate.model_validate(
            {
                "field": change.field,
                "after": format(cast(Decimal, change.after.amount), ".2f"),
            }
        )
        for change in preview.changes
    )
    current_preview = preview_lab_promotion(
        session,
        request=LifeLabPromotionPreviewRequest(
            experiment_id=preview.experiment_id,
            expected_experiment_fingerprint=preview.experiment_fingerprint,
            draft=request.draft,
            target_surface=preview.target_surface,
            target_id=preview.target_id,
            changes=candidates,
        ),
    )
    if current_preview.model_dump(mode="json") != preview.model_dump(mode="json"):
        raise PlanningStaleError("The promotion preview or target changed before confirmation")
    source_ref = f"lab_experiment:{preview.experiment_fingerprint}:confirmed_promotion"
    observation = None
    if preview.target_surface is PromotionTarget.GOALS:
        edit_values: dict[str, Any] = {"expected_edit_token": preview.target_stale_write_token}
        for change in preview.changes:
            if change.field is PromotionField.GOAL_TARGET:
                edit_values["target_amount"] = format(cast(Decimal, change.after.amount), ".2f")
            elif change.field is PromotionField.RESERVED_FOR_GOAL:
                edit_values["reserved_for_goal"] = format(cast(Decimal, change.after.amount), ".2f")
            elif change.field is PromotionField.PROTECTED_CASH_FLOOR:
                edit_values["protected_cash_floor"] = format(
                    cast(Decimal, change.after.amount), ".2f"
                )
        try:
            applied_view = edit_goal(
                session,
                goal_program_id=preview.target_id,
                request=GoalEditRequest.model_validate(edit_values),
                provenance_origin="lab_promotion",
                provenance_source_ref=source_ref,
            )
        except StaleGoalWriteError as exc:
            raise PlanningStaleError(str(exc)) from exc
        except GoalValidationError as exc:
            raise PlanningValidationError(str(exc)) from exc
        session.commit()
        observation = coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.LAB_PROMOTION,
            observed_on=local_business_date(),
            operation_state=CompletedOperationState.COMPLETE,
        )
        next_token = applied_view.edit_token
    else:
        edit_values = {"expected_edit_token": preview.target_stale_write_token}
        for change in preview.changes:
            if change.field is PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND:
                edit_values["retirement_essential_monthly_spend"] = format(
                    cast(Decimal, change.after.amount), ".2f"
                )
            elif change.field is PromotionField.RETIREMENT_FLEXIBLE_MONTHLY_SPEND:
                edit_values["retirement_flexible_monthly_spend"] = format(
                    cast(Decimal, change.after.amount), ".2f"
                )
        applied_profile = edit_retirement_profile(
            session,
            request=RetirementProfileEditRequest.model_validate(edit_values),
            provenance_origin="lab_promotion",
            provenance_source_ref=source_ref,
        )
        session.commit()
        next_token = applied_profile.edit_token
    return LifeLabPromotionApplied(
        preview_id=preview.preview_id,
        experiment_id=preview.experiment_id,
        experiment_fingerprint=preview.experiment_fingerprint,
        target_surface=preview.target_surface,
        target_id=preview.target_id,
        changes=preview.changes,
        target_stale_write_token=next_token,
        goal_observation=observation,
    )
