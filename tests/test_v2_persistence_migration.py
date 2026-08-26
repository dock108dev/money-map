from __future__ import annotations

import copy
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from alembic import command
from paycheck_map.goal_service import edit_goal, program_edit_token
from paycheck_map.logical_manifest import build_logical_manifest, logical_tables
from paycheck_map.models import GoalProgram
from paycheck_map.v2_contracts import GoalEditRequest

from .v2_migration_support import (
    V2_TABLES,
    assert_sqlite_health,
    database_revision,
    materialize_state,
    migration_config,
    online_copy,
    stable_v2_manifest,
    synthetic_states,
)

STATES = synthetic_states()


def _upgrade_to_v1(database: Path, state: dict[str, Any] | None = None) -> None:
    command.upgrade(migration_config(database), "0008_life_lab_v01")
    if state is not None:
        materialize_state(database, state)


def _programs(database: Path) -> list[GoalProgram]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            return list(
                session.scalars(select(GoalProgram).order_by(GoalProgram.source_life_goal_id)).all()
            )
    finally:
        engine.dispose()


def _assert_expected_mapping(database: Path, state: dict[str, Any]) -> None:
    goals = [goal for goal in state["tables"]["life_goals"] if goal["enabled"]]
    profiles = {profile["id"]: profile for profile in state["tables"]["life_plan_profiles"]}
    programs = _programs(database)
    assert len(programs) == len(goals)
    assert sum(program.is_primary for program in programs) == (1 if len(goals) == 1 else 0)
    assert {program.source_life_goal_id for program in programs} == {goal["id"] for goal in goals}
    expected_primary = state["expected_slice_1"]["primary_goal_source_id"]
    actual_primary = next(
        (program.source_life_goal_id for program in programs if program.is_primary), None
    )
    assert actual_primary == expected_primary
    goals_by_id = {goal["id"]: goal for goal in goals}
    expected_provenance = {
        "public_key",
        "name",
        "target_date",
        "target_amount",
        "protected_cash_floor",
        "reserved_amount",
        "is_primary",
        "status",
        "tracking_mode",
        "reservation_policy",
    }
    for program in programs:
        goal = goals_by_id[program.source_life_goal_id]
        profile = profiles[goal["profile_id"]]
        assert program.public_key == f"goal_life_{goal['id']}"
        assert program.name == goal["name"]
        assert program.target_date.isoformat() == goal["target_date"]
        assert program.target_amount == Decimal(goal["target_amount"])
        assert program.protected_cash_floor == Decimal(profile["cash_floor"])
        assert program.reserved_amount == Decimal(goal["reserved_amount"])
        assert program.status == (
            "complete"
            if Decimal(goal["reserved_amount"]) >= Decimal(goal["target_amount"])
            else "active"
        )
        assert program.tracking_mode == "explicit_reservation"
        assert program.reservation_policy == "exclusive_primary_goal"
        assert program.contract_version == "money-map-v2-contract-v1"
        assert program.migration_version == "0009_goal_persistence"
        assert program.created_at.tzinfo is not None
        assert program.created_at.utcoffset() is not None
        assert program.updated_at.tzinfo is not None
        assert program.updated_at.utcoffset() is not None
        assert set(program.field_provenance) == expected_provenance
        for provenance in program.field_provenance.values():
            assert provenance["evidence"] in {"user_entered", "derived", "assumed"}
            assert provenance["source_refs"]
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM goal_check_ins").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM goal_check_in_components").fetchone() == (
            0,
        )


@pytest.mark.parametrize("state", STATES, ids=[state["id"] for state in STATES])
def test_all_synthetic_states_upgrade_downgrade_reupgrade_losslessly(
    state: dict[str, Any], tmp_path: Path
) -> None:
    database = tmp_path / f"{state['id']}.sqlite3"
    config = migration_config(database)
    _upgrade_to_v1(database, state)
    before = build_logical_manifest(database)
    pre_v2_tables = set(before["tables"])

    command.upgrade(config, "head")
    assert database_revision(database) == "0009_goal_persistence"
    after_upgrade = build_logical_manifest(database, include_tables=pre_v2_tables)
    assert logical_tables(after_upgrade) == logical_tables(before)
    _assert_expected_mapping(database, state)
    first_v2 = stable_v2_manifest(database)

    command.upgrade(config, "head")
    assert stable_v2_manifest(database) == first_v2
    _assert_expected_mapping(database, state)

    command.downgrade(config, "0008_life_lab_v01")
    assert database_revision(database) == "0008_life_lab_v01"
    after_downgrade = build_logical_manifest(database)
    assert after_downgrade == before
    assert V2_TABLES.isdisjoint(after_downgrade["tables"])

    command.upgrade(config, "head")
    assert database_revision(database) == "0009_goal_persistence"
    assert stable_v2_manifest(database) == first_v2
    _assert_expected_mapping(database, state)
    assert_sqlite_health(database)


def test_empty_database_upgrade_downgrade_reupgrade(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite3"
    config = migration_config(database)
    _upgrade_to_v1(database)
    before = build_logical_manifest(database)

    command.upgrade(config, "head")
    assert _programs(database) == []
    first_v2 = stable_v2_manifest(database)
    command.downgrade(config, "0008_life_lab_v01")
    assert build_logical_manifest(database) == before
    command.upgrade(config, "head")
    assert stable_v2_manifest(database) == first_v2
    assert_sqlite_health(database)


def test_goal_cas_accepts_exact_token_for_migrated_sqlite_timestamp(tmp_path: Path) -> None:
    state = next(state for state in STATES if state["id"] == "one_enabled_goal_with_floor")
    database = tmp_path / "migrated-goal-edit.sqlite3"
    _upgrade_to_v1(database, state)
    command.upgrade(migration_config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine, expire_on_commit=False) as session:
            program = session.scalar(select(GoalProgram).where(GoalProgram.is_primary.is_(True)))
            assert program is not None
            updated = edit_goal(
                session,
                goal_program_id=program.public_key,
                request=GoalEditRequest.model_validate(
                    {
                        "expected_edit_token": program_edit_token(program),
                        "target_amount": "15555.00",
                    }
                ),
            )
            session.commit()
            assert updated.target_amount.amount == Decimal("15555.00")
    finally:
        engine.dispose()


def test_profile_with_only_disabled_goal_creates_no_program(tmp_path: Path) -> None:
    state = copy.deepcopy(
        next(state for state in STATES if state["id"] == "one_enabled_goal_with_floor")
    )
    state["tables"]["life_goals"][0]["enabled"] = False
    state["expected_slice_1"] = {
        "primary_goal_source_id": None,
        "requires_primary_selection": False,
    }
    database = tmp_path / "disabled.sqlite3"
    _upgrade_to_v1(database, state)

    command.upgrade(migration_config(database), "head")

    _assert_expected_mapping(database, state)


def _insert_program(
    connection: sqlite3.Connection,
    *,
    public_key: str,
    source_life_goal_id: int | None = None,
    target: str = "1000.00",
    floor: str = "500.00",
    reserved: str = "100.00",
    primary: bool = False,
) -> None:
    connection.execute(
        """
        INSERT INTO goal_programs (
            public_key, source_life_goal_id, name, target_date, target_amount,
            protected_cash_floor, reserved_amount, is_primary, status, tracking_mode,
            reservation_policy, field_provenance, contract_version, migration_version,
            created_at, updated_at
        ) VALUES (?, ?, 'Synthetic constraint goal', '2027-08-10', ?, ?, ?, ?, 'active',
            'explicit_reservation', 'exclusive_primary_goal', '{}',
            'money-map-v2-contract-v1', '0009_goal_persistence',
            '2026-08-10 19:30:00', '2026-08-10 19:30:00')
        """,
        (public_key, source_life_goal_id, target, floor, reserved, int(primary)),
    )


@pytest.mark.parametrize(
    ("target", "floor", "reserved"),
    [
        ("-0.01", "500.00", "0.00"),
        ("1000.00", "-0.01", "0.00"),
        ("1000.00", "500.00", "-0.01"),
        ("1000.00", "500.00", "1000.01"),
    ],
)
def test_goal_program_money_constraints(
    target: str, floor: str, reserved: str, tmp_path: Path
) -> None:
    database = tmp_path / "money-constraint.sqlite3"
    command.upgrade(migration_config(database), "head")
    with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
        _insert_program(
            connection,
            public_key="goal_invalid",
            target=target,
            floor=floor,
            reserved=reserved,
        )


def _insert_check_in(
    connection: sqlite3.Connection,
    program_id: int,
    *,
    check_in_id: str = "a" * 64,
    fingerprint: str = "b" * 64,
) -> None:
    connection.execute(
        """
        INSERT INTO goal_check_ins (
            check_in_id, goal_program_id, source_fingerprint, effective_observation_date,
            accessible_cash, accessible_investments, retirement_assets_excluded,
            tracked_debt, accessible_now, protected_cash_floor, available_above_floor,
            reserved_amount, goal_target, remaining_target, effective_recurring_take_home,
            observed_recurring_outflow, recurring_cash_flow_gap, funding_months, pace_status,
            required_funding_pace, position_evidence, canonical_position_payload,
            position_payload_version, contract_version, calculation_version,
            fingerprint_version, trigger, created_at
        ) VALUES (?, ?, ?, '2026-08-10', '4000.00', '1000.00', '9000.00', '500.00',
            '5000.00', '3000.00', '2000.00', '100.00', '1000.00', '900.00',
            '4200.00', '3000.00', '0.00', '12.000000000000', 'active', '75.00',
            '{}', '{}', 'goal-position-payload-v1', 'money-map-v2-contract-v1',
            'goal-arithmetic-v1', 'goal-source-fingerprint-v1', 'test',
            '2026-08-10 19:30:00')
        """,
        (check_in_id, program_id, fingerprint),
    )


def test_primary_source_foreign_key_and_check_in_component_constraints(tmp_path: Path) -> None:
    state = next(state for state in STATES if state["id"] == "one_enabled_goal_with_floor")
    database = tmp_path / "constraints.sqlite3"
    _upgrade_to_v1(database, state)
    command.upgrade(migration_config(database), "head")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        program_id = int(
            connection.execute("SELECT id FROM goal_programs WHERE is_primary = 1").fetchone()[0]
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_program(connection, public_key="goal_second_primary", primary=True)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_program(
                connection,
                public_key="goal_duplicate_source",
                source_life_goal_id=10,
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_program(connection, public_key="goal_life_10")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM life_goals WHERE id = 10")

        _insert_check_in(connection, program_id)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_check_in(connection, program_id, check_in_id="c" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_check_in(
                connection,
                program_id,
                check_in_id="not-hex",
                fingerprint="d" * 64,
            )
        connection.execute(
            """
            INSERT INTO goal_check_in_components (
                check_in_id, component_key, component_version, amount,
                evidence_class, derivation, supporting_source_refs
            ) VALUES (?, 'accessible_cash', 'goal-component-v1', '4000.00',
                'observed', NULL, '["source:test"]')
            """,
            ("a" * 64,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO goal_check_in_components (
                    check_in_id, component_key, component_version, amount,
                    evidence_class, derivation, supporting_source_refs
                ) VALUES (?, 'accessible_cash', 'goal-component-v1', '4000.00',
                    'observed', NULL, '[]')
                """,
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO goal_check_in_components (
                    check_in_id, component_key, component_version, amount,
                    evidence_class, derivation, supporting_source_refs
                ) VALUES (?, 'bad_evidence', 'goal-component-v1', '1.00',
                    'unsupported', NULL, '[]')
                """,
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO goal_check_in_components (
                    check_in_id, component_key, component_version, amount,
                    evidence_class, derivation, supporting_source_refs
                ) VALUES (?, 'empty_sources', 'goal-component-v1', '1.00',
                    'observed', NULL, '[]')
                """,
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE goal_check_ins SET trigger = 'changed' WHERE check_in_id = ?",
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM goal_check_in_components WHERE check_in_id = ?",
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM goal_programs WHERE id = ?", (program_id,))


@pytest.mark.parametrize("failure_stage", ["after_tables", "during_copy"])
def test_failure_injection_never_reports_partial_mapping_at_0009_and_recovers_fresh(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = next(state for state in STATES if state["id"] == "multiple_enabled_goals_ambiguous")
    failed = tmp_path / f"failed-{failure_stage}.sqlite3"
    verified_restore = tmp_path / f"verified-restore-{failure_stage}.sqlite3"
    recovered = tmp_path / f"recovered-{failure_stage}.sqlite3"
    _upgrade_to_v1(failed, state)
    online_copy(failed, verified_restore)
    monkeypatch.setenv("PAYCHECK_MAP_MIGRATION_0009_FAIL_AT", failure_stage)

    with pytest.raises(RuntimeError, match="Injected 0009 failure"):
        command.upgrade(migration_config(failed), "head")

    assert database_revision(failed) == "0008_life_lab_v01"
    monkeypatch.delenv("PAYCHECK_MAP_MIGRATION_0009_FAIL_AT")
    online_copy(verified_restore, recovered)
    command.upgrade(migration_config(recovered), "head")
    assert database_revision(recovered) == "0009_goal_persistence"
    assert len(_programs(recovered)) == 2
    assert database_revision(failed) == "0008_life_lab_v01"
    assert_sqlite_health(recovered)
