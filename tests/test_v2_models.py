from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint, create_engine, inspect
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from alembic import command
from paycheck_map.models import GoalCheckIn, GoalCheckInComponent, GoalProgram
from paycheck_map.money import Money

from .v2_migration_support import migration_config


def _program(*, created_at: datetime) -> GoalProgram:
    return GoalProgram(
        public_key="goal_test_model",
        source_life_goal_id=None,
        name="Synthetic model goal",
        target_date=date(2027, 8, 10),
        target_amount=Decimal("1000.00"),
        protected_cash_floor=Decimal("500.00"),
        reserved_amount=Decimal("100.00"),
        is_primary=True,
        status="active",
        tracking_mode="explicit_reservation",
        reservation_policy="exclusive_primary_goal",
        field_provenance={"target_amount": {"evidence": "user_entered"}},
        contract_version="money-map-v2-contract-v1",
        migration_version="0009_goal_persistence",
        created_at=created_at,
        updated_at=created_at,
    )


def test_v2_model_shape_relationships_and_exact_money() -> None:
    program_columns = GoalProgram.__table__.c
    check_in_columns = GoalCheckIn.__table__.c
    component_columns = GoalCheckInComponent.__table__.c

    for name in ("target_amount", "protected_cash_floor", "reserved_amount"):
        assert isinstance(program_columns[name].type, Money)
    for name in (
        "accessible_cash",
        "accessible_investments",
        "retirement_assets_excluded",
        "tracked_debt",
        "goal_target",
        "protected_cash_floor",
        "reserved_amount",
    ):
        assert isinstance(check_in_columns[name].type, Money)
    assert isinstance(component_columns.amount.type, Money)

    assert set(inspect(GoalProgram).relationships.keys()) == {
        "source_life_goal",
        "check_ins",
    }
    assert set(inspect(GoalCheckIn).relationships.keys()) == {"goal_program", "components"}
    assert set(inspect(GoalCheckInComponent).relationships.keys()) == {"check_in"}
    program_table = cast(Table, GoalProgram.__table__)
    primary_index = next(
        index for index in program_table.indexes if index.name == "uq_goal_programs_single_primary"
    )
    assert primary_index.unique
    assert str(primary_index.dialect_options["sqlite"]["where"]) == "is_primary = 1"


def test_v2_copy_timestamps_round_trip_as_timezone_aware(db_engine: object) -> None:
    now = datetime(2026, 8, 10, 19, 30, tzinfo=UTC)
    with Session(db_engine) as session:  # type: ignore[arg-type]
        session.add(_program(created_at=now))
        session.commit()
        session.expire_all()
        stored = session.get(GoalProgram, 1)
        assert stored is not None
        assert stored.created_at.tzinfo is not None
        assert stored.created_at.utcoffset() is not None
        assert stored.created_at == now


def test_v2_copy_timestamps_reject_naive_values(db_engine: object) -> None:
    with Session(db_engine) as session:  # type: ignore[arg-type]
        session.add(_program(created_at=datetime(2026, 8, 10, 19, 30)))
        with pytest.raises(StatementError, match="Timestamp must be timezone-aware"):
            session.commit()


@pytest.mark.parametrize(
    ("table_name", "model"),
    [
        ("goal_programs", GoalProgram),
        ("goal_check_ins", GoalCheckIn),
        ("goal_check_in_components", GoalCheckInComponent),
    ],
)
def test_v2_migration_schema_matches_sqlalchemy_models(
    table_name: str, model: type[object], tmp_path: Path
) -> None:
    database = tmp_path / f"{table_name}.sqlite3"
    command.upgrade(migration_config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    try:
        database_inspector = inspect(engine)
        model_table = cast(Table, model.__table__)  # type: ignore[attr-defined]
        migrated_columns = {
            column["name"]: (
                str(column["type"]),
                bool(column["nullable"]),
            )
            for column in database_inspector.get_columns(table_name)
        }
        model_columns = {
            column.name: (str(column.type), bool(column.nullable)) for column in model_table.columns
        }
        assert migrated_columns == model_columns
        assert set(database_inspector.get_pk_constraint(table_name)["constrained_columns"]) == {
            column.name for column in model_table.primary_key.columns
        }
        assert {index["name"] for index in database_inspector.get_indexes(table_name)} == {
            index.name for index in model_table.indexes
        }
        assert {
            constraint["name"]
            for constraint in database_inspector.get_check_constraints(table_name)
        } == {
            constraint.name
            for constraint in model_table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert {
            tuple(constraint["column_names"])
            for constraint in database_inspector.get_unique_constraints(table_name)
        } == {
            tuple(column.name for column in constraint.columns)
            for constraint in model_table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
    finally:
        engine.dispose()
