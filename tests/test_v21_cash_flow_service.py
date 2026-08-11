from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from paycheck_map.business_time import local_business_date
from paycheck_map.cash_flow_service import (
    CashFlowClassification,
    CashFlowUnavailableError,
    CashFlowValidationError,
    ImportedBankCoverage,
    build_cash_flow_period_result,
    classify_bank_transaction,
    resolve_period,
)
from paycheck_map.v21_contracts import (
    CashFlowPeriodResult,
    CoverageCompleteness,
    FreshnessState,
    PeriodKind,
)

from .v21_cash_flow_support import (
    synthetic_cash_flow_accounts,
    synthetic_transaction,
    synthetic_transfer_match,
)

AS_OF = date(2026, 8, 11)
NOW = datetime(2026, 8, 11, 14, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "start", "end"),
    [
        (PeriodKind.ALL_IMPORTED_HISTORY, date(2025, 6, 15), date(2026, 8, 10)),
        (PeriodKind.TRAILING_12_MONTHS, date(2025, 9, 1), AS_OF),
        (PeriodKind.YEAR_TO_DATE, date(2026, 1, 1), AS_OF),
        (PeriodKind.CUSTOM_RANGE, date(2026, 2, 3), date(2026, 5, 17)),
    ],
)
def test_period_resolution_is_deterministic(
    kind: PeriodKind,
    start: date,
    end: date,
) -> None:
    result = resolve_period(
        period_kind=kind,
        as_of_date=AS_OF,
        imported_coverage=ImportedBankCoverage(date(2025, 6, 15), date(2026, 8, 10)),
        start_date=start if kind is PeriodKind.CUSTOM_RANGE else None,
        end_date=end if kind is PeriodKind.CUSTOM_RANGE else None,
    )
    assert (result.start_date, result.end_date) == (start, end)


def test_partial_boundaries_and_zero_activity_months_are_explicit(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 1, 15),
        amount="100.00",
        role="external_inflow",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 3, 10),
        amount="-40.00",
        role="external_outflow",
        source_row=2,
    )

    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.CUSTOM_RANGE,
        start_date=date(2026, 1, 15),
        end_date=date(2026, 3, 10),
        as_of_date=AS_OF,
        now=NOW,
    )

    assert result.coverage.opening_month.value == "partial"
    assert result.coverage.closing_month.value == "partial"
    assert [point.month for point in result.monthly_points] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    assert result.monthly_points[1].transaction_count == 0
    assert result.monthly_points[1].amounts.net_cash_flow.amount == Decimal("0.00")


def test_no_activity_inside_established_coverage_is_an_evidenced_zero(
    session: Session,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 1, 1),
        amount="25.00",
        role="external_inflow",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 3, 31),
        amount="-25.00",
        role="external_outflow",
        source_row=2,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.CUSTOM_RANGE,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.coverage.completeness is CoverageCompleteness.COMPLETE
    assert result.coverage.transaction_count == 0
    assert result.totals.net_cash_flow.amount == Decimal("0.00")


def test_all_history_without_bank_coverage_is_explicitly_unavailable(session: Session) -> None:
    synthetic_cash_flow_accounts(session)
    with pytest.raises(CashFlowUnavailableError, match="no bank transaction coverage"):
        build_cash_flow_period_result(
            session,
            period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
            as_of_date=AS_OF,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("inflow", "outflow", "expected_net"),
    [("500.00", "-125.00", "375.00"), ("50.00", "-725.00", "-675.00")],
)
def test_positive_and_negative_period_net(
    session: Session,
    inflow: str,
    outflow: str,
    expected_net: str,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 1),
        amount=inflow,
        role="external_inflow",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 31),
        amount=outflow,
        role="external_outflow",
        source_row=2,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.totals.net_cash_flow.amount == Decimal(expected_net)


def test_interest_and_fees_are_included_exactly_once(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 1),
        amount="3.25",
        role="interest",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 31),
        amount="-7.50",
        role="fee",
        source_row=2,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.totals.interest_received.amount == Decimal("3.25")
    assert result.totals.fees_paid.amount == Decimal("7.50")
    assert result.totals.external_cash_inflows.amount == Decimal("0.00")
    assert result.totals.external_cash_outflows.amount == Decimal("0.00")
    assert result.totals.net_cash_flow.amount == Decimal("-4.25")


def test_matched_and_unmatched_internal_transfers_are_separate_exclusions(
    session: Session,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    left = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 1),
        amount="-200.00",
        role="internal_transfer",
        source_row=1,
    )
    right = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 2),
        amount="200.00",
        role="external_inflow",
        source_row=1,
        account=accounts.savings,
    )
    synthetic_transfer_match(session, left, right)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 31),
        amount="-75.00",
        role="internal_transfer",
        source_row=2,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.totals.money_in.amount == Decimal("0.00")
    assert result.totals.money_out.amount == Decimal("0.00")
    assert result.transfers_excluded.matched_owned_account_amount.amount == Decimal("400.00")
    assert result.transfers_excluded.matched_owned_account_count == 2
    assert result.transfers_excluded.internal_transfer_amount.amount == Decimal("75.00")
    assert result.transfers_excluded.internal_transfer_count == 1

    classified = classify_bank_transaction(left, matched_transaction_ids={left.id, right.id})
    assert classified.classification is CashFlowClassification.MATCHED_OWNED_TRANSFER


def test_investment_activity_and_zero_rows_never_become_cash_flow(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 1),
        amount="0.00",
        role="adjustment",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 31),
        amount="900.00",
        role="employer_contribution",
        source_row=1,
        account=accounts.investment,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.coverage.transaction_count == 1
    assert result.totals.net_cash_flow.amount == Decimal("0.00")


def test_monthly_amounts_transfers_and_transaction_counts_reconcile_exactly(
    session: Session,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    first = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 6, 1),
        amount="100.10",
        role="external_inflow",
        source_row=1,
    )
    second = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 6, 2),
        amount="-20.10",
        role="internal_transfer",
        source_row=2,
    )
    third = synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 7, 2),
        amount="20.10",
        role="internal_transfer",
        source_row=1,
        account=accounts.savings,
    )
    synthetic_transfer_match(session, second, third)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 11),
        amount="-55.05",
        role="external_outflow",
        source_row=3,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert isinstance(first.id, int)
    assert sum(point.transaction_count for point in result.monthly_points) == 4
    assert result.coverage.transaction_count == 4
    assert (
        sum(point.transfers_excluded.matched_owned_account_count for point in result.monthly_points)
        == result.transfers_excluded.matched_owned_account_count
    )
    assert (
        sum(
            (point.amounts.net_cash_flow.amount or Decimal("0.00"))
            for point in result.monthly_points
        )
        == result.totals.net_cash_flow.amount
    )


def test_future_dated_imported_bank_source_fails_closed(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 12),
        amount="10.00",
        role="external_inflow",
        source_row=1,
    )
    with pytest.raises(CashFlowValidationError, match="source date 2026-08-12"):
        build_cash_flow_period_result(
            session,
            period_kind=PeriodKind.YEAR_TO_DATE,
            as_of_date=AS_OF,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (None, date(2026, 7, 31), "require both"),
        (date(2026, 8, 2), date(2026, 8, 1), "must not follow"),
        (date(2026, 8, 1), date(2026, 8, 12), "must not exceed"),
    ],
)
def test_invalid_custom_dates_are_rejected(
    start: date | None,
    end: date,
    message: str,
) -> None:
    with pytest.raises(CashFlowValidationError, match=message):
        resolve_period(
            period_kind=PeriodKind.CUSTOM_RANGE,
            as_of_date=AS_OF,
            imported_coverage=ImportedBankCoverage(date(2026, 1, 1), AS_OF),
            start_date=start,
            end_date=end,
        )


@pytest.mark.parametrize(
    ("last_synced_at", "expected"),
    [
        (datetime(2026, 8, 10, 16, tzinfo=UTC), FreshnessState.STALE),
        (datetime(2026, 8, 11, 13, tzinfo=UTC), FreshnessState.CURRENT),
    ],
)
def test_applicable_bank_connection_freshness(
    session: Session,
    last_synced_at: datetime,
    expected: FreshnessState,
) -> None:
    accounts = synthetic_cash_flow_accounts(
        session,
        with_connection=True,
        last_synced_at=last_synced_at,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount="10.00",
        role="external_inflow",
        source_row=1,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=AS_OF,
        amount="-1.00",
        role="external_outflow",
        source_row=2,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.freshness.state is expected
    assert result.freshness.stale_sources == (
        ("Juniper Community Bank connection",) if expected is FreshnessState.STALE else ()
    )


def test_manual_only_cash_evidence_is_current_without_plaid(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount="20.00",
        role="external_inflow",
        source_row=1,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.freshness.state is FreshnessState.CURRENT
    assert result.freshness.stale_sources == ()


def test_eastern_business_date_changes_at_eastern_midnight(session: Session) -> None:
    last_sync = datetime(2026, 8, 11, 0, 5, tzinfo=UTC)
    accounts = synthetic_cash_flow_accounts(
        session,
        with_connection=True,
        last_synced_at=last_sync,
    )
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 10),
        amount="1.00",
        role="external_inflow",
        source_row=1,
    )
    before_midnight = datetime(2026, 8, 11, 3, 59, tzinfo=UTC)
    after_midnight = datetime(2026, 8, 11, 4, 1, tzinfo=UTC)
    current = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=local_business_date(before_midnight),
        now=before_midnight,
    )
    stale = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=local_business_date(after_midnight),
        now=after_midnight,
    )
    assert current.freshness.state is FreshnessState.CURRENT
    assert stale.freshness.state is FreshnessState.STALE


@pytest.mark.parametrize(
    ("role", "amount", "reason", "expected_in", "expected_out"),
    [
        ("interest", "-2.00", "unexpected_interest_sign", "0.00", "2.00"),
        ("fee", "3.00", "unexpected_fee_sign", "3.00", "0.00"),
    ],
)
def test_unexpected_interest_or_fee_sign_is_preserved_and_incomplete(
    session: Session,
    role: str,
    amount: str,
    reason: str,
    expected_in: str,
    expected_out: str,
) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount=amount,
        role=role,
        source_row=1,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    assert result.coverage.completeness is CoverageCompleteness.INCOMPLETE
    assert reason in result.coverage.incomplete_reasons
    assert result.totals.money_in.amount == Decimal(expected_in)
    assert result.totals.money_out.amount == Decimal(expected_out)
    assert result.freshness.state is FreshnessState.INCOMPLETE
    assert result.warnings


def test_contract_serializes_every_amount_as_exact_two_places(session: Session) -> None:
    accounts = synthetic_cash_flow_accounts(session)
    synthetic_transaction(
        session,
        accounts,
        posted_date=date(2026, 8, 1),
        amount="1.20",
        role="external_inflow",
        source_row=1,
    )
    result = build_cash_flow_period_result(
        session,
        period_kind=PeriodKind.ALL_IMPORTED_HISTORY,
        as_of_date=AS_OF,
        now=NOW,
    )
    payload = result.model_dump(mode="json")
    assert payload["totals"]["money_in"]["amount"] == "1.20"
    assert payload["totals"]["fees_paid"]["amount"] == "0.00"
    assert payload["monthly_points"][0]["amounts"]["net_cash_flow"]["amount"] == "1.20"
    assert TypeAdapter(CashFlowPeriodResult).validate_python(payload) == result
