from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command

from .conftest import PROJECT_ROOT


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite3"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    names = set(inspect(engine).get_table_names())
    assert {
        "import_artifacts",
        "payroll_statements",
        "forecast_periods",
        "plaid_connections",
        "plaid_sync_runs",
        "investment_holdings",
        "payroll_schedule_entries",
        "payroll_transaction_matches",
        "payroll_allocations",
        "account_balance_points",
        "application_settings",
    } <= names
    payroll_columns = {
        column["name"] for column in inspect(engine).get_columns("payroll_statements")
    }
    assert {"job_title", "observed_deposit_date"} <= payroll_columns
    forecast_columns = {
        column["name"] for column in inspect(engine).get_columns("forecast_periods")
    }
    assert {"employee_hsa", "employer_hsa", "cash_redirect_to_investments"} <= forecast_columns
    command.downgrade(config, "base")
    remaining = set(inspect(engine).get_table_names())
    assert "payroll_statements" not in remaining
    engine.dispose()


def test_refresh_timestamp_migration_repairs_only_invalid_ordering(tmp_path: Path) -> None:
    database = tmp_path / "timestamp-repair.sqlite3"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0006_daily_data_refresh")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(id, created_at, status, requested_source, artifact_count, imported_count, "
                "duplicate_count, error_count) VALUES "
                "(1, '2026-07-31 19:00:00', 'complete', 'synthetic', 0, 0, 0, 0), "
                "(2, '2026-07-31 19:01:00', 'complete', 'synthetic', 0, 0, 0, 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO plaid_connections "
                "(id, environment, target, item_id, institution_name, status, products, "
                "created_at, updated_at) VALUES "
                "(1, 'sandbox', 'sofi', 'synthetic-item', 'Synthetic Bank', 'active', '[]', "
                "'2026-07-31 18:00:00', '2026-07-31 18:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO plaid_sync_runs "
                "(id, connection_id, batch_id, started_at, finished_at, status, account_count, "
                "transaction_count, holding_count) VALUES "
                "(1, 1, 1, '2026-07-31 19:00:05', '2026-07-31 19:00:01', "
                "'complete', 1, 0, 0), "
                "(2, 1, 2, '2026-07-31 19:01:00', '2026-07-31 19:01:03', "
                "'complete', 1, 0, 0)"
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, started_at, finished_at FROM plaid_sync_runs ORDER BY id")
        ).all()
    assert rows[0].started_at == rows[0].finished_at
    assert rows[1].finished_at == "2026-07-31 19:01:03"
    engine.dispose()
