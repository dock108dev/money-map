"""Digest-only SQLite logical manifests for migration and recovery evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import Numeric

MANIFEST_FORMAT = "money-map-logical-manifest-v1"


def build_logical_manifest(
    database_path: Path,
    *,
    include_tables: Iterable[str] | None = None,
    omit_row_columns: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Return schema, counts, and ordered row digests without returning row content."""

    engine = _read_only_engine(database_path)
    try:
        inspector = inspect(engine)
        available = sorted(
            name
            for name in inspector.get_table_names()
            if not name.startswith("sqlite_") and name != "alembic_version"
        )
        selected = available if include_tables is None else sorted(set(include_tables))
        missing = sorted(set(selected) - set(available))
        if missing:
            raise ValueError(f"Manifest tables do not exist: {', '.join(missing)}")
        return {
            "format": MANIFEST_FORMAT,
            "alembic_revision": _alembic_revision(engine),
            "tables": {
                name: _table_manifest(
                    engine,
                    name,
                    omitted_columns=set((omit_row_columns or {}).get(name, ())),
                )
                for name in selected
            },
        }
    finally:
        engine.dispose()


def logical_tables(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the revision-independent logical/schema portion of a manifest."""

    tables = manifest.get("tables")
    if not isinstance(tables, Mapping):
        raise ValueError("Manifest has no table mapping")
    return tables


def manifest_digest(manifest: Mapping[str, Any], *, include_revision: bool = True) -> str:
    """Hash a manifest canonically; callers can explicitly exclude the revision."""

    material = dict(manifest)
    if not include_revision:
        material.pop("alembic_revision", None)
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _read_only_engine(database_path: Path) -> Engine:
    path = database_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True),
    )


def _alembic_revision(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        revisions = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).scalars()
        values = [str(value) for value in revisions]
    if not values:
        return None
    return ",".join(values)


def _table_manifest(
    engine: Engine, table_name: str, *, omitted_columns: set[str]
) -> dict[str, Any]:
    inspector = inspect(engine)
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    primary_key = [column.name for column in table.primary_key.columns]
    ordering = primary_key or [column.name for column in table.columns]
    unknown_omissions = omitted_columns - set(table.columns.keys())
    if unknown_omissions:
        raise ValueError(
            f"Manifest columns do not exist on {table_name}: {', '.join(sorted(unknown_omissions))}"
        )
    digest_columns = [column for column in table.columns if column.name not in omitted_columns]
    digest_indexes = [
        index for index, column in enumerate(table.columns) if column.name not in omitted_columns
    ]
    statement = select(table)
    if ordering:
        statement = statement.order_by(*(table.c[name] for name in ordering))
    with engine.connect() as connection:
        rows = connection.execute(statement)
        row_digests = [
            _row_digest(digest_columns, [row[index] for index in digest_indexes]) for row in rows
        ]
    indexes = [_normalize_index(item) for item in inspector.get_indexes(table_name)]
    unique_constraints = [
        _normalize_constraint(item) for item in inspector.get_unique_constraints(table_name)
    ]
    foreign_keys = [_normalize_foreign_key(item) for item in inspector.get_foreign_keys(table_name)]
    checks = [_normalize_check(item) for item in inspector.get_check_constraints(table_name)]
    return {
        "columns": [_normalize_column(column) for column in inspector.get_columns(table_name)],
        "primary_key": primary_key,
        "row_order": ordering,
        "row_digest_columns": [column.name for column in digest_columns],
        "omitted_row_columns": sorted(omitted_columns),
        "indexes": sorted(indexes, key=_canonical_json),
        "unique_constraints": sorted(unique_constraints, key=_canonical_json),
        "foreign_keys": sorted(foreign_keys, key=_canonical_json),
        "check_constraints": sorted(checks, key=_canonical_json),
        "row_count": len(row_digests),
        "row_digests": row_digests,
        "rows_digest": hashlib.sha256("\n".join(row_digests).encode("ascii")).hexdigest(),
    }


def _row_digest(columns: Sequence[Column[Any]], values: Sequence[Any]) -> str:
    material = [
        {"column": column.name, "value": _typed_value(column, value)}
        for column, value in zip(columns, values, strict=True)
    ]
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _typed_value(column: Column[Any], value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, Decimal):
        scale = column.type.scale if isinstance(column.type, Numeric) else None
        text = format(value, f".{scale}f") if scale is not None else format(value, "f")
        return {"type": "decimal", "value": text}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, (dict, list)):
        return {"type": "json", "value": _canonical_json(value)}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": "text", "value": str(value)}


def _normalize_column(column: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(column["name"]),
        "type": str(column["type"]),
        "nullable": bool(column["nullable"]),
        "default": None if column.get("default") is None else str(column["default"]),
        "primary_key": int(column.get("primary_key", 0)),
    }


def _normalize_index(index: Mapping[str, Any]) -> dict[str, Any]:
    dialect_options = index.get("dialect_options", {})
    return {
        "name": None if index.get("name") is None else str(index["name"]),
        "columns": [str(value) for value in index.get("column_names", [])],
        "unique": bool(index.get("unique", False)),
        "sqlite_where": (
            None
            if not isinstance(dialect_options, Mapping)
            or dialect_options.get("sqlite_where") is None
            else str(dialect_options["sqlite_where"])
        ),
    }


def _normalize_constraint(constraint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": None if constraint.get("name") is None else str(constraint["name"]),
        "columns": [str(value) for value in constraint.get("column_names", [])],
    }


def _normalize_foreign_key(foreign_key: Mapping[str, Any]) -> dict[str, Any]:
    options = foreign_key.get("options", {})
    return {
        "name": None if foreign_key.get("name") is None else str(foreign_key["name"]),
        "columns": [str(value) for value in foreign_key.get("constrained_columns", [])],
        "referred_table": str(foreign_key["referred_table"]),
        "referred_columns": [str(value) for value in foreign_key.get("referred_columns", [])],
        "ondelete": options.get("ondelete") if isinstance(options, Mapping) else None,
    }


def _normalize_check(check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": None if check.get("name") is None else str(check["name"]),
        "sqltext": str(check["sqltext"]),
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
