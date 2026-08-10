from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from alembic.config import Config

from paycheck_map.logical_manifest import build_logical_manifest

from .conftest import PROJECT_ROOT

V2_TABLES = {"goal_programs", "goal_check_ins", "goal_check_in_components"}
V2_TIMESTAMP_OMISSIONS = {
    "goal_programs": {"created_at", "updated_at"},
}


def migration_config(database: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def synthetic_states() -> list[dict[str, Any]]:
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "synthetic" / "v1_2_1" / "states.json"
    payload: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    states = payload["states"]
    if not isinstance(states, list):
        raise ValueError("Synthetic states fixture must contain a list")
    return states


def materialize_state(database: Path, state: dict[str, Any]) -> None:
    tables = state["tables"]
    if not isinstance(tables, dict):
        raise ValueError("Synthetic state tables must be a mapping")
    allowed = {
        "life_plan_profiles",
        "life_goals",
        "life_scenarios",
        "life_projection_periods",
    }
    if set(tables) != allowed:
        raise ValueError("Synthetic state contains an unexpected table set")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table_name in (
            "life_plan_profiles",
            "life_goals",
            "life_scenarios",
            "life_projection_periods",
        ):
            rows = tables[table_name]
            if not isinstance(rows, list):
                raise ValueError(f"Synthetic table {table_name} must be a list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"Synthetic row for {table_name} must be a mapping")
                columns = list(row)
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                values = tuple(_database_value(row[column]) for column in columns)
                connection.execute(
                    f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
                    values,
                )


def online_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as source_connection,
        sqlite3.connect(destination) as destination_connection,
    ):
        source_connection.backup(destination_connection)


def database_revision(database: Path) -> str:
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise ValueError("Database has no Alembic revision")
    return str(row[0])


def assert_sqlite_health(database: Path) -> None:
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert integrity == [("ok",)]
    assert foreign_keys == []


def stable_v2_manifest(database: Path) -> dict[str, Any]:
    return build_logical_manifest(
        database,
        include_tables=V2_TABLES,
        omit_row_columns=V2_TIMESTAMP_OMISSIONS,
    )


def _database_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if isinstance(value, bool):
        return int(value)
    return value
