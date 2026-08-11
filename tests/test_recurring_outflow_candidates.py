from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from paycheck_map.models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    Institution,
)
from paycheck_map.recurring_outflow_service import recurring_outflow_candidates
from paycheck_map.v21_contracts import RecurringOutflowCandidateList

from .goal_gap_support import GoalGapSeed, seed_goal_gap

OBSERVED_ON = date(2026, 8, 11)


def add_occurrences(
    session: Session,
    seed: GoalGapSeed,
    *,
    dates: list[date],
    description: str = "Invented Media Plan",
    amounts: list[str] | None = None,
    role: str = "external_outflow",
    account: Account | None = None,
    source_start: int = 100,
) -> None:
    values = amounts or ["10.00"] * len(dates)
    for index, (posted, amount) in enumerate(zip(dates, values, strict=True)):
        session.add(
            AccountTransaction(
                account_id=(account or seed.cash_account).id,
                artifact_id=seed.artifact.id,
                posted_date=posted,
                original_description=description,
                role=role,
                amount=-Decimal(amount),
                source_row=source_start + index,
            )
        )
    session.flush()


def candidates(session: Session) -> RecurringOutflowCandidateList:
    return recurring_outflow_candidates(session, observed_on=OBSERVED_ON)


@pytest.mark.parametrize(
    ("dates", "cadence", "expected_typical"),
    [
        ([date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)], "monthly", "10.00"),
        (
            [
                date(2026, 5, 1),
                date(2026, 5, 15),
                date(2026, 5, 29),
                date(2026, 6, 12),
                date(2026, 6, 26),
                date(2026, 7, 10),
            ],
            "biweekly",
            "21.67",
        ),
        (
            [
                date(2026, 5, 2),
                date(2026, 5, 9),
                date(2026, 5, 16),
                date(2026, 5, 23),
                date(2026, 5, 30),
                date(2026, 6, 6),
                date(2026, 6, 13),
                date(2026, 6, 20),
                date(2026, 6, 27),
                date(2026, 7, 4),
            ],
            "weekly",
            "43.33",
        ),
    ],
)
def test_high_confidence_cadences_and_exact_monthly_conversion(
    session: Session,
    dates: list[date],
    cadence: str,
    expected_typical: str,
) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(session, seed, dates=dates)

    result = candidates(session)

    assert result.state == "available"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.cadence.value == cadence
    assert candidate.typical_monthly_amount.amount == Decimal(expected_typical)
    assert candidate.confidence == "high"


def test_too_few_occurrences_and_too_few_complete_months_are_excluded(
    session: Session,
) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4)],
    )

    result = candidates(session)

    assert result.state == "empty"
    assert result.candidates == ()


def test_too_few_complete_months_do_not_support_a_candidate(session: Session) -> None:
    seed = seed_goal_gap(session, complete_months=False)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)],
    )

    result = candidates(session)

    assert result.state == "unavailable"
    assert result.candidates == ()


def test_unstable_amounts_are_excluded(session: Session) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)],
        amounts=["10.00", "10.00", "20.01"],
    )

    assert candidates(session).state == "empty"


def test_incomplete_month_activity_is_excluded(session: Session) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 2, 5), date(2026, 3, 7), date(2026, 4, 6)],
    )

    assert candidates(session).state == "empty"


@pytest.mark.parametrize("role", ["fee", "internal_transfer"])
def test_fees_and_transfers_are_excluded(session: Session, role: str) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)],
        role=role,
    )

    assert candidates(session).state == "empty"


def test_investment_transactions_are_excluded(session: Session) -> None:
    seed = seed_goal_gap(session)
    investment = Institution(canonical_name="Invented Candidate Brokerage", kind="investment")
    session.add(investment)
    session.flush()
    account = Account(
        institution_id=investment.id,
        external_key="invented-candidate-brokerage",
        display_name="Invented candidate brokerage",
        account_type="brokerage",
    )
    session.add(account)
    session.flush()
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)],
        account=account,
    )

    assert candidates(session).state == "empty"


def test_same_description_on_different_accounts_is_not_merged(session: Session) -> None:
    seed = seed_goal_gap(session)
    second = Account(
        institution_id=seed.cash_account.institution_id,
        external_key="invented-second-checking",
        display_name="Invented second checking",
        account_type="checking",
    )
    session.add(second)
    session.flush()
    for month in (5, 6, 7):
        final_day = calendar.monthrange(2026, month)[1]
        session.add_all(
            [
                BalanceSnapshot(
                    account_id=second.id,
                    artifact_id=seed.artifact.id,
                    snapshot_date=date(2026, month, 1),
                    kind="opening",
                    amount=Decimal("1000.00"),
                ),
                BalanceSnapshot(
                    account_id=second.id,
                    artifact_id=seed.artifact.id,
                    snapshot_date=date(2026, month, final_day),
                    kind="closing",
                    amount=Decimal("1000.00"),
                ),
            ]
        )
    dates = [date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)]
    add_occurrences(session, seed, dates=dates, source_start=100)
    add_occurrences(session, seed, dates=dates, account=second, source_start=100)

    result = candidates(session)

    assert len(result.candidates) == 2
    assert {item.safe_account_label for item in result.candidates} == {
        "Checking account 1",
        "Checking account 2",
    }


def test_normalizes_only_case_and_whitespace(session: Session) -> None:
    seed = seed_goal_gap(session)
    dates = [date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)]
    for index, (posted, description) in enumerate(
        zip(dates, ["  Video   Club  ", "video club", "VIDEO CLUB"], strict=True)
    ):
        add_occurrences(
            session,
            seed,
            dates=[posted],
            description=description,
            source_start=200 + index,
        )
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 6), date(2026, 6, 5)],
        description="Video Club 001",
        source_start=300,
    )

    result = candidates(session)

    assert len(result.candidates) == 1
    assert result.candidates[0].observed_description == "Video Club"
    assert result.candidates[0].occurrence_count == 3


def test_candidate_id_is_deterministic_opaque_and_excludes_account_identifiers(
    session: Session,
) -> None:
    seed = seed_goal_gap(session)
    add_occurrences(
        session,
        seed,
        dates=[date(2026, 5, 5), date(2026, 6, 4), date(2026, 7, 4)],
    )

    first = candidates(session).candidates[0]
    second = candidates(session).candidates[0]

    assert first.candidate_id == second.candidate_id
    assert first.candidate_id != f"candidate_{seed.cash_account.id}"
    assert seed.cash_account.external_key not in first.candidate_id
    assert seed.cash_account.display_name not in first.candidate_id
    assert first.candidate_id.startswith("candidate_")


def test_empty_candidate_result_is_explicit(session: Session) -> None:
    seed_goal_gap(session)

    result = candidates(session)

    assert result.state == "empty"
    assert result.candidates == ()
