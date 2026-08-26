from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

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


def test_materializer_has_no_candidate_observation_or_expected_update_mode() -> None:
    source = Path(__file__).with_name("release_state_materializer.py").read_text(encoding="utf-8")
    assert "candidate_output" not in source
    assert "record_expected" not in source
    assert "update_snapshot" not in source
    assert "subprocess" not in source
