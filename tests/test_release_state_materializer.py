from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from paycheck_map.cash_flow_service import build_cash_flow_period_result
from paycheck_map.v21_contracts import CoverageCompleteness, PeriodKind

from .release_state_materializer import materialize_release_state

STATE_IDS = (
    "empty",
    "loading",
    "unavailable",
    "partial_coverage",
    "recoverable_failure",
    "stale_evidence",
    "complete_current",
    "large_history",
    "negative_recurring_cash_flow",
    "cash_below_protected_floor",
    "missing_source_coverage",
    "no_life_lab_profile",
    "profile_without_goals",
    "one_enabled_goal_with_floor",
    "multiple_enabled_goals_ambiguous",
    "stale_saved_scenario",
    "completed_goal",
)


@pytest.mark.parametrize("state_id", STATE_IDS)
def test_every_release_state_materializes_with_exact_declared_counts(
    tmp_path: Path, state_id: str
) -> None:
    database = tmp_path / state_id / "paycheck-map.sqlite3"
    result = materialize_release_state(database, state_id)
    assert result["state"] == state_id
    assert result["revision"] == "0009_goal_persistence"
    assert result["integrity"] == "ok"
    assert result["foreign_keys"] == "ok"
    assert database.stat().st_mode & 0o777 == 0o600
    assert database.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    ("state_id", "expected_in", "expected_out"),
    [
        ("partial_coverage", "100.00", "40.00"),
        ("complete_current", "4200.00", "3900.00"),
        ("large_history", "134400.00", "99200.00"),
    ],
)
def test_cash_flow_seed_aggregates_are_independently_exact(
    tmp_path: Path, state_id: str, expected_in: str, expected_out: str
) -> None:
    database = tmp_path / state_id / "paycheck-map.sqlite3"
    materialize_release_state(database, state_id)
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT role, amount FROM account_transactions "
            "WHERE role IN ('external_inflow', 'external_outflow')"
        ).fetchall()
    money_in = sum(
        (Decimal(str(amount)) for role, amount in rows if role == "external_inflow"),
        Decimal("0.00"),
    )
    money_out = -sum(
        (Decimal(str(amount)) for role, amount in rows if role == "external_outflow"),
        Decimal("0.00"),
    )
    assert money_in == Decimal(expected_in)
    assert money_out == Decimal(expected_out)


def test_large_history_respects_its_sealed_date_boundaries(tmp_path: Path) -> None:
    database = tmp_path / "large_history" / "paycheck-map.sqlite3"
    materialize_release_state(database, "large_history")
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        transaction_bounds = connection.execute(
            "SELECT MIN(posted_date), MAX(posted_date) FROM account_transactions"
        ).fetchone()
        latest_snapshot = connection.execute(
            "SELECT MAX(snapshot_date) FROM balance_snapshots"
        ).fetchone()
    assert transaction_bounds == ("2024-01-01", "2026-08-10")
    assert latest_snapshot == ("2026-08-10",)


def test_negative_recurring_state_materializes_its_source_summary(tmp_path: Path) -> None:
    database = tmp_path / "negative_recurring_cash_flow" / "paycheck-map.sqlite3"
    materialize_release_state(database, "negative_recurring_cash_flow")
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        transactions = connection.execute(
            "SELECT role, amount FROM account_transactions ORDER BY id"
        ).fetchall()
        balances = connection.execute(
            "SELECT amount FROM balance_snapshots ORDER BY account_id"
        ).fetchall()
        payroll = connection.execute("SELECT net_payment FROM payroll_schedule_entries").fetchall()
    assert transactions == [("external_inflow", 4200), ("external_outflow", -4700)]
    assert balances == [(6100,), (1400,), (18000,)]
    assert payroll == [(4200,)]


def test_missing_source_state_materializes_only_incomplete_bank_marker_and_retirement(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing_source_coverage" / "paycheck-map.sqlite3"
    materialize_release_state(database, "missing_source_coverage")
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        transactions = connection.execute(
            "SELECT role, amount FROM account_transactions ORDER BY id"
        ).fetchall()
        balances = connection.execute(
            "SELECT amount FROM balance_snapshots ORDER BY account_id"
        ).fetchall()
        payroll_count = connection.execute(
            "SELECT COUNT(*) FROM payroll_schedule_entries"
        ).fetchone()
    assert transactions == [("interest", 0)]
    assert balances == [(18000,)]
    assert payroll_count == (0,)
    with Session(create_engine(f"sqlite:///{database}")) as session:
        result = build_cash_flow_period_result(
            session,
            period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
            as_of_date=datetime(2026, 8, 26, tzinfo=UTC).date(),
            now=datetime(2026, 8, 26, tzinfo=UTC),
        )
    assert result.coverage.completeness is CoverageCompleteness.INCOMPLETE
    assert result.coverage.incomplete_reasons == ("unexpected_interest_sign",)
    assert result.totals.money_in.amount == Decimal("0.00")
    assert result.totals.money_out.amount == Decimal("0.00")


def test_materializer_has_no_candidate_observation_or_expected_update_mode() -> None:
    source = Path(__file__).with_name("release_state_materializer.py").read_text(encoding="utf-8")
    assert "candidate_output" not in source
    assert "record_expected" not in source
    assert "update_snapshot" not in source
    assert "subprocess" not in source
