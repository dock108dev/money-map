from __future__ import annotations

import asyncio
import copy
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.app import app
from paycheck_map.db import get_session
from paycheck_map.goal_service import calculate_primary_goal_position, program_edit_token
from paycheck_map.models import (
    ApplicationSetting,
    GoalCheckIn,
    GoalProgram,
    LifePlanProfile,
    LifeScenario,
)
from paycheck_map.retirement_lab import (
    PlanningStaleError,
    PlanningValidationError,
    confirm_lab_promotion,
    edit_retirement_profile,
    experiment_fingerprint,
    list_lab_snapshots,
    open_lab_snapshot,
    preview_lab_promotion,
    project_lab_experiment,
    retirement_profile_token,
    run_retirement_projection,
    save_lab_snapshot,
    save_retirement_snapshot,
    seed_lab_experiment,
)
from paycheck_map.v2_contracts import (
    GoalObservationResult,
    LabExperimentSeedKind,
    LifeLabExperimentCreateRequest,
    LifeLabExperimentProjectRequest,
    LifeLabPromotionCandidate,
    LifeLabPromotionConfirmationRequest,
    LifeLabPromotionPreviewRequest,
    PromotionField,
    PromotionTarget,
    RetirementPath,
    RetirementProfileEditRequest,
    RetirementProjectionRequest,
)

from .test_goal_service import _seed


def _program(session: Session) -> GoalProgram:
    program = session.scalar(select(GoalProgram).where(GoalProgram.is_primary.is_(True)))
    assert program is not None
    return program


def _profile(session: Session) -> LifePlanProfile:
    profile = session.scalar(select(LifePlanProfile).order_by(LifePlanProfile.id))
    assert profile is not None
    return profile


def _retirement_edit(token: str, **changes: object) -> RetirementProfileEditRequest:
    return RetirementProfileEditRequest.model_validate({"expected_edit_token": token, **changes})


def _promotion_candidate(field: PromotionField, after: str) -> LifeLabPromotionCandidate:
    return LifeLabPromotionCandidate.model_validate({"field": field, "after": after})


def test_default_retirement_excludes_goals_and_explicit_inclusion_is_immutable(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    default = run_retirement_projection(
        migrated_session,
        request=RetirementProjectionRequest(
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
        ),
        observed_on=date(2026, 8, 10),
    )
    included = run_retirement_projection(
        migrated_session,
        request=RetirementProjectionRequest(
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
            goal_program_id="goal_synthetic_home",
        ),
        observed_on=date(2026, 8, 10),
    )

    assert default.snapshot_context == "retirement_default"
    assert default.run_selection.included_goal is None
    assert default.projection["goals"] == []
    assert included.snapshot_context == "retirement_with_goal"
    assert included.run_selection.included_goal is not None
    assert included.run_selection.included_goal.remaining_target.amount == Decimal("12000.00")
    assert included.run_fingerprint != default.run_fingerprint
    stored_run = included.model_dump(mode="json")

    program = _program(migrated_session)
    program.target_amount = Decimal("16000.00")
    migrated_session.commit()

    assert included.model_dump(mode="json") == stored_run
    assert (
        default.run_fingerprint
        == run_retirement_projection(
            migrated_session,
            request=RetirementProjectionRequest(
                work_optional_age=50,
                path=RetirementPath.MIDDLE,
            ),
            observed_on=date(2026, 8, 10),
        ).run_fingerprint
    )


def test_retirement_edit_changes_only_retirement_fingerprint(migrated_session: Session) -> None:
    _seed(migrated_session)
    program = _program(migrated_session)
    before_goal = calculate_primary_goal_position(migrated_session, observed_on=date(2026, 8, 10))
    assert before_goal is not None
    before_retirement = run_retirement_projection(
        migrated_session,
        request=RetirementProjectionRequest(
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
        ),
        observed_on=date(2026, 8, 10),
    )
    profile = _profile(migrated_session)

    edit_retirement_profile(
        migrated_session,
        request=_retirement_edit(
            retirement_profile_token(profile),
            retirement_flexible_monthly_spend="950.00",
        ),
    )
    migrated_session.commit()

    after_retirement = run_retirement_projection(
        migrated_session,
        request=RetirementProjectionRequest(
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
        ),
        observed_on=date(2026, 8, 10),
    )
    after_goal = calculate_primary_goal_position(migrated_session, observed_on=date(2026, 8, 10))
    assert after_goal is not None
    assert after_retirement.run_fingerprint != before_retirement.run_fingerprint
    assert after_goal.source_fingerprint == before_goal.source_fingerprint
    assert program_edit_token(_program(migrated_session)) == program_edit_token(program)


def test_lab_seeds_and_snapshots_are_isolated_and_preserve_legacy_context(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(seed_kind=LabExperimentSeedKind.CURRENT_GOAL),
        today=date(2026, 8, 10),
    )
    original = seed.model_dump(mode="json")
    program = _program(migrated_session)
    program.reserved_amount = Decimal("2500.00")
    migrated_session.commit()
    assert seed.model_dump(mode="json") == original

    draft = copy.deepcopy(seed.draft)
    cast_values = draft["promotable_values"]
    assert isinstance(cast_values, dict)
    cast_values["goal_target"] = "15000.00"
    result = project_lab_experiment(
        request=LifeLabExperimentProjectRequest(
            experiment_id=seed.experiment_id,
            expected_experiment_fingerprint=seed.experiment_fingerprint,
            draft=draft,
        )
    )
    goal_token = program_edit_token(_program(migrated_session))
    retirement_token = retirement_profile_token(_profile(migrated_session))
    snapshot = save_lab_snapshot(migrated_session, name="Synthetic isolated draft", result=result)
    migrated_session.commit()

    assert snapshot["snapshot_context"] == "lab_current_goal"
    assert program_edit_token(_program(migrated_session)) == goal_token
    assert retirement_profile_token(_profile(migrated_session)) == retirement_token

    profile = _profile(migrated_session)
    legacy = LifeScenario(
        profile_id=profile.id,
        name="Synthetic legacy evidence",
        target_age=50,
        path_key="middle",
        input_snapshot={"profile": {}, "goals": [], "starting_point": {}, "assumptions": {}},
        source_fingerprint="a" * 64,
        engine_version="life-lab-v0.3.0",
        assumption_version="life-lab-drive-paths-v3",
        benchmark_version="synthetic",
        status="works",
        warnings=[],
        summary={},
    )
    migrated_session.add(legacy)
    migrated_session.commit()
    rows = list_lab_snapshots(migrated_session)
    legacy_row = next(row for row in rows if row["id"] == legacy.id)
    assert legacy_row["context_label"] == "Legacy combined plan · v1.2.1 inputs"
    assert open_lab_snapshot(migrated_session, legacy.id)["input_snapshot"] == legacy.input_snapshot


def test_promotion_preview_and_stale_confirmation_perform_zero_writes(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(seed_kind=LabExperimentSeedKind.CURRENT_GOAL),
        today=date(2026, 8, 10),
    )
    draft = copy.deepcopy(seed.draft)
    values = draft["promotable_values"]
    assert isinstance(values, dict)
    values["goal_target"] = "15000.00"
    fingerprint = experiment_fingerprint(seed.experiment_id, draft)
    before_program = _program(migrated_session).target_amount
    before_profile = _profile(migrated_session).essential_monthly_spend
    before_scenarios = migrated_session.scalar(select(func.count()).select_from(LifeScenario))
    before_check_ins = migrated_session.scalar(select(func.count()).select_from(GoalCheckIn))
    preview = preview_lab_promotion(
        migrated_session,
        request=LifeLabPromotionPreviewRequest(
            experiment_id=seed.experiment_id,
            expected_experiment_fingerprint=fingerprint,
            draft=draft,
            target_surface=PromotionTarget.GOALS,
            target_id="goal_synthetic_home",
            changes=(_promotion_candidate(PromotionField.GOAL_TARGET, "15000.00"),),
        ),
    )
    assert _program(migrated_session).target_amount == before_program
    assert _profile(migrated_session).essential_monthly_spend == before_profile
    assert (
        migrated_session.scalar(select(func.count()).select_from(LifeScenario)) == before_scenarios
    )
    assert (
        migrated_session.scalar(select(func.count()).select_from(GoalCheckIn)) == before_check_ins
    )

    _program(migrated_session).reserved_amount = Decimal("2100.00")
    migrated_session.commit()
    with pytest.raises(PlanningStaleError):
        confirm_lab_promotion(
            migrated_session,
            request=LifeLabPromotionConfirmationRequest(preview=preview, draft=draft),
        )
    migrated_session.rollback()
    assert _program(migrated_session).target_amount == before_program
    assert (
        migrated_session.scalar(select(func.count()).select_from(GoalCheckIn)) == before_check_ins
    )


def test_confirmed_promotions_apply_only_previewed_fields_and_record_provenance(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(seed_kind=LabExperimentSeedKind.CURRENT_GOAL),
        today=date(2026, 8, 10),
    )
    draft = copy.deepcopy(seed.draft)
    values = draft["promotable_values"]
    assert isinstance(values, dict)
    values["goal_target"] = "15000.00"
    fingerprint = experiment_fingerprint(seed.experiment_id, draft)
    preview = preview_lab_promotion(
        migrated_session,
        request=LifeLabPromotionPreviewRequest(
            experiment_id=seed.experiment_id,
            expected_experiment_fingerprint=fingerprint,
            draft=draft,
            target_surface=PromotionTarget.GOALS,
            target_id="goal_synthetic_home",
            changes=(_promotion_candidate(PromotionField.GOAL_TARGET, "15000.00"),),
        ),
    )
    before = _program(migrated_session)
    reserved = before.reserved_amount
    floor = before.protected_cash_floor
    applied = confirm_lab_promotion(
        migrated_session,
        request=LifeLabPromotionConfirmationRequest(preview=preview, draft=draft),
    )

    after = _program(migrated_session)
    assert after.target_amount == Decimal("15000.00")
    assert after.reserved_amount == reserved
    assert after.protected_cash_floor == floor
    assert after.field_provenance["target_amount"]["edit_origin"] == "lab_promotion"
    assert fingerprint in after.field_provenance["target_amount"]["source_refs"][0]
    assert applied.goal_observation is not None
    assert applied.goal_observation.status in {"created", "unchanged"}
    assert migrated_session.scalar(select(func.count()).select_from(GoalCheckIn)) == 1


def test_retirement_result_seed_survives_profile_change_and_promotes_one_spend_field(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    run = run_retirement_projection(
        migrated_session,
        request=RetirementProjectionRequest(
            work_optional_age=50,
            path=RetirementPath.MIDDLE,
        ),
        observed_on=date(2026, 8, 10),
    )
    saved = save_retirement_snapshot(migrated_session, name="Synthetic Retirement", run=run)
    migrated_session.commit()
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(
            seed_kind=LabExperimentSeedKind.RETIREMENT_RESULT,
            retirement_snapshot_id=int(saved["id"]),
        ),
        today=date(2026, 8, 10),
    )
    immutable_seed = seed.model_dump(mode="json")
    profile = _profile(migrated_session)
    edit_retirement_profile(
        migrated_session,
        request=_retirement_edit(
            retirement_profile_token(profile),
            retirement_flexible_monthly_spend="950.00",
        ),
    )
    migrated_session.commit()
    assert seed.model_dump(mode="json") == immutable_seed

    draft = copy.deepcopy(seed.draft)
    values = draft["promotable_values"]
    assert isinstance(values, dict)
    values["retirement_essential_monthly_spend"] = "3200.00"
    fingerprint = experiment_fingerprint(seed.experiment_id, draft)
    preview = preview_lab_promotion(
        migrated_session,
        request=LifeLabPromotionPreviewRequest(
            experiment_id=seed.experiment_id,
            expected_experiment_fingerprint=fingerprint,
            draft=draft,
            target_surface=PromotionTarget.RETIREMENT,
            target_id=f"retirement_profile_{profile.id}",
            changes=(
                _promotion_candidate(
                    PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND,
                    "3200.00",
                ),
            ),
        ),
    )
    before_flexible = _profile(migrated_session).flexible_monthly_spend
    confirm_lab_promotion(
        migrated_session,
        request=LifeLabPromotionConfirmationRequest(preview=preview, draft=draft),
    )
    after = _profile(migrated_session)
    assert after.essential_monthly_spend == Decimal("3200.00")
    assert after.flexible_monthly_spend == before_flexible

    values["retirement_essential_monthly_spend"] = "3200.00"
    with pytest.raises(PlanningValidationError, match="does not change"):
        preview_lab_promotion(
            migrated_session,
            request=LifeLabPromotionPreviewRequest(
                experiment_id=seed.experiment_id,
                expected_experiment_fingerprint=fingerprint,
                draft=draft,
                target_surface=PromotionTarget.RETIREMENT,
                target_id=f"retirement_profile_{profile.id}",
                changes=(
                    _promotion_candidate(
                        PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND,
                        "3200.00",
                    ),
                ),
            ),
        )


def test_lab_draft_fingerprint_and_unsupported_promotion_are_write_free(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(seed_kind=LabExperimentSeedKind.CURRENT_GOAL),
        today=date(2026, 8, 10),
    )
    program_token = program_edit_token(_program(migrated_session))
    profile_token = retirement_profile_token(_profile(migrated_session))
    scenario_count = migrated_session.scalar(select(func.count()).select_from(LifeScenario))
    draft = copy.deepcopy(seed.draft)
    mission = draft["mission"]
    assert isinstance(mission, dict)
    mission["target_amount"] = "999999.00"
    assert experiment_fingerprint(seed.experiment_id, draft) != seed.experiment_fingerprint

    values = draft["promotable_values"]
    assert isinstance(values, dict)
    values["retirement_essential_monthly_spend"] = "3200.00"
    fingerprint = experiment_fingerprint(seed.experiment_id, draft)
    with pytest.raises(PlanningValidationError, match="not promotable to Goals"):
        preview_lab_promotion(
            migrated_session,
            request=LifeLabPromotionPreviewRequest(
                experiment_id=seed.experiment_id,
                expected_experiment_fingerprint=fingerprint,
                draft=draft,
                target_surface=PromotionTarget.GOALS,
                target_id="goal_synthetic_home",
                changes=(
                    _promotion_candidate(
                        PromotionField.RETIREMENT_ESSENTIAL_MONTHLY_SPEND,
                        "3200.00",
                    ),
                ),
            ),
        )
    assert program_edit_token(_program(migrated_session)) == program_token
    assert retirement_profile_token(_profile(migrated_session)) == profile_token
    assert migrated_session.scalar(select(func.count()).select_from(LifeScenario)) == scenario_count


def test_goal_promotion_observation_failure_does_not_rollback_and_is_requested_once(
    migrated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(migrated_session)
    seed = seed_lab_experiment(
        migrated_session,
        request=LifeLabExperimentCreateRequest(seed_kind=LabExperimentSeedKind.CURRENT_GOAL),
        today=date(2026, 8, 10),
    )
    draft = copy.deepcopy(seed.draft)
    values = draft["promotable_values"]
    assert isinstance(values, dict)
    values["goal_target"] = "15000.00"
    fingerprint = experiment_fingerprint(seed.experiment_id, draft)
    preview = preview_lab_promotion(
        migrated_session,
        request=LifeLabPromotionPreviewRequest(
            experiment_id=seed.experiment_id,
            expected_experiment_fingerprint=fingerprint,
            draft=draft,
            target_surface=PromotionTarget.GOALS,
            target_id="goal_synthetic_home",
            changes=(_promotion_candidate(PromotionField.GOAL_TARGET, "15000.00"),),
        ),
    )
    calls: list[str] = []

    def unavailable_observation(*args: object, **kwargs: object) -> GoalObservationResult:
        del args, kwargs
        calls.append("requested")
        return GoalObservationResult(
            status="unavailable",
            trigger="lab_promotion",
            retryable=True,
            message="Synthetic observation failure",
        )

    monkeypatch.setattr(
        "paycheck_map.retirement_lab.coordinate_goal_observation",
        unavailable_observation,
    )
    applied = confirm_lab_promotion(
        migrated_session,
        request=LifeLabPromotionConfirmationRequest(preview=preview, draft=draft),
    )
    assert calls == ["requested"]
    assert applied.goal_observation is not None
    assert applied.goal_observation.status == "unavailable"
    assert _program(migrated_session).target_amount == Decimal("15000.00")


def test_retirement_and_lab_api_reads_and_pure_commands_perform_no_writes(
    migrated_session: Session,
) -> None:
    _seed(migrated_session)
    before_program = program_edit_token(_program(migrated_session))
    before_profile = retirement_profile_token(_profile(migrated_session))
    before_scenarios = migrated_session.scalar(select(func.count()).select_from(LifeScenario))
    before_settings = migrated_session.scalar(select(func.count()).select_from(ApplicationSetting))
    before_check_ins = migrated_session.scalar(select(func.count()).select_from(GoalCheckIn))

    def override_session() -> Iterator[Session]:
        yield migrated_session

    app.dependency_overrides[get_session] = override_session
    try:

        async def exercise() -> tuple[list[httpx.Response], httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
            ) as client:
                responses = [
                    await client.get("/api/v2/retirement/profile"),
                    await client.get("/api/v2/retirement/starting-point"),
                    await client.get("/api/v2/retirement/operational-goals"),
                    await client.get("/api/v2/retirement/snapshots"),
                    await client.get("/api/v2/lab/snapshots"),
                    await client.post(
                        "/api/v2/retirement/project",
                        json={"work_optional_age": 50, "path": "middle", "goal_program_id": None},
                    ),
                    await client.post("/api/v2/lab/experiments", json={"seed_kind": "blank"}),
                ]
                telemetry = await client.post(
                    "/api/v2/lab/experiments",
                    json={"seed_kind": "blank", "browser_opened_at": "2026-08-10T12:00:00Z"},
                )
            return responses, telemetry

        responses, telemetry = asyncio.run(exercise())
    finally:
        app.dependency_overrides.clear()

    assert all(response.status_code == 200 for response in responses)
    assert responses[5].json()["snapshot_context"] == "retirement_default"
    assert responses[5].json()["projection"]["goals"] == []
    assert responses[6].json()["edit_scope"] == "isolated_draft"
    assert telemetry.status_code == 422
    assert program_edit_token(_program(migrated_session)) == before_program
    assert retirement_profile_token(_profile(migrated_session)) == before_profile
    assert (
        migrated_session.scalar(select(func.count()).select_from(LifeScenario)) == before_scenarios
    )
    assert (
        migrated_session.scalar(select(func.count()).select_from(ApplicationSetting))
        == before_settings
    )
    assert (
        migrated_session.scalar(select(func.count()).select_from(GoalCheckIn)) == before_check_ins
    )
    assert not migrated_session.new and not migrated_session.dirty and not migrated_session.deleted
