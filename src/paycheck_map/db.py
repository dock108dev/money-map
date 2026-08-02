from __future__ import annotations

from collections.abc import Generator

from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

from .config import Settings, settings


def make_engine(runtime_settings: Settings = settings) -> Engine:
    runtime_settings.ensure_private_dirs()
    engine = create_engine(
        f"sqlite:///{runtime_settings.database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(db_engine: Engine = engine) -> None:
    """Upgrade a new or existing local database to the current schema."""

    config = Config()
    config.set_main_option("script_location", str(settings.migration_dir))
    config.set_main_option(
        "sqlalchemy.url",
        db_engine.url.render_as_string(hide_password=False),
    )
    tables = set(inspect(db_engine).get_table_names())
    if "payroll_statements" in tables and "alembic_version" not in tables:
        command.stamp(config, "0001_local_v01")
    command.upgrade(config, "head")


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
