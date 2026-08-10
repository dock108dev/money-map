from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import create_engine, text

from paycheck_map.logical_manifest import (
    build_logical_manifest,
    logical_tables,
    manifest_digest,
)


def test_logical_manifest_is_copy_stable_and_revision_separate(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    copied = tmp_path / "copied.sqlite3"
    engine = create_engine(f"sqlite:///{source}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('revision_a')"))
        connection.execute(
            text(
                "CREATE TABLE sample ("
                "id INTEGER PRIMARY KEY, amount NUMERIC(20, 2) NOT NULL, "
                "observed_on DATE NOT NULL, created_at DATETIME NOT NULL, payload JSON, "
                "UNIQUE (amount, observed_on))"
            )
        )
        connection.exec_driver_sql(
            "INSERT INTO sample VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)",
            (
                2,
                2.1,
                "2026-08-10",
                "2026-08-10 13:01:02",
                '{"z":null,"a":"value"}',
                1,
                1,
                "2026-08-09",
                "2026-08-09 01:02:03",
                '{"a":"value","z":null}',
            ),
        )
    engine.dispose()
    shutil.copy2(source, copied)

    source_manifest = build_logical_manifest(source)
    copied_manifest = build_logical_manifest(copied)

    assert source_manifest == copied_manifest
    assert source_manifest["alembic_revision"] == "revision_a"
    assert logical_tables(source_manifest) == logical_tables(copied_manifest)
    assert manifest_digest(source_manifest) == manifest_digest(copied_manifest)
    sample = source_manifest["tables"]["sample"]
    assert sample["row_count"] == 2
    assert sample["row_order"] == ["id"]
    assert len(sample["row_digests"]) == 2


def test_logical_manifest_detects_schema_rows_and_revision_independently(tmp_path: Path) -> None:
    database = tmp_path / "database.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('revision_a')"))
        connection.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)"))
        connection.execute(text("INSERT INTO sample VALUES (1, 'first')"))
    before = build_logical_manifest(database)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'revision_b'"))
    revision_only = build_logical_manifest(database)
    assert logical_tables(before) == logical_tables(revision_only)
    assert manifest_digest(before, include_revision=False) == manifest_digest(
        revision_only, include_revision=False
    )
    assert manifest_digest(before) != manifest_digest(revision_only)

    with engine.begin() as connection:
        connection.execute(text("UPDATE sample SET value = 'second' WHERE id = 1"))
    changed = build_logical_manifest(database)
    assert logical_tables(before) != logical_tables(changed)
    engine.dispose()


def test_logical_manifest_can_exclude_allowed_timestamp_changes(tmp_path: Path) -> None:
    database = tmp_path / "database.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT, created_at DATETIME)")
        )
        connection.execute(text("INSERT INTO sample VALUES (1, 'stable', '2026-08-10 01:00:00')"))
    before = build_logical_manifest(database, omit_row_columns={"sample": {"created_at"}})
    with engine.begin() as connection:
        connection.execute(text("UPDATE sample SET created_at = '2026-08-10 02:00:00'"))
    after = build_logical_manifest(database, omit_row_columns={"sample": {"created_at"}})

    assert before == after
    assert before["tables"]["sample"]["omitted_row_columns"] == ["created_at"]
    engine.dispose()
