from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.balances import add_manual_value_observation
from paycheck_map.models import (
    Account,
    AccountBalancePoint,
    AccountTransaction,
    BalanceSnapshot,
    ImportArtifact,
    ImportBatch,
    Institution,
    InvestmentValueBridge,
)
from paycheck_map.reconciliation import reconcile_all
from paycheck_map.services import account_detail, accounts_dashboard, timeline


def _artifact(session: Session) -> ImportArtifact:
    batch = ImportBatch(status="complete", requested_source="synthetic")
    session.add(batch)
    session.flush()
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256="a" * 64,
        original_filename="synthetic-money-map.json",
        source_kind="synthetic",
        adapter="synthetic",
        parser_version="test-v1",
    )
    session.add(artifact)
    session.flush()
    return artifact


def test_balance_history_transfer_cancellation_and_investment_bridge(session: Session) -> None:
    artifact = _artifact(session)
    bank = Institution(canonical_name="Synthetic Bank", kind="bank")
    investment = Institution(canonical_name="Synthetic Investments", kind="investment")
    session.add_all([bank, investment])
    session.flush()
    checking = Account(
        institution_id=bank.id,
        external_key="checking",
        display_name="Checking ••0001",
        account_type="checking",
    )
    savings = Account(
        institution_id=bank.id,
        external_key="savings",
        display_name="Savings ••0002",
        account_type="savings",
    )
    retirement = Account(
        institution_id=investment.id,
        external_key="retirement",
        display_name="Retirement ••0003",
        account_type="401k",
    )
    session.add_all([checking, savings, retirement])
    session.flush()
    session.add_all(
        [
            BalanceSnapshot(
                account_id=checking.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 3, 15),
                kind="current",
                amount=Decimal("1500.00"),
            ),
            BalanceSnapshot(
                account_id=savings.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 3, 15),
                kind="current",
                amount=Decimal("700.00"),
            ),
            BalanceSnapshot(
                account_id=retirement.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 3, 15),
                kind="current",
                amount=Decimal("12000.00"),
            ),
        ]
    )
    session.add_all(
        [
            AccountTransaction(
                account_id=checking.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 2, 1),
                original_description="Pay",
                role="external_inflow",
                amount=Decimal("1000.00"),
                source_row=1,
            ),
            AccountTransaction(
                account_id=checking.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 2, 15),
                original_description="Aggregate outflow",
                role="external_outflow",
                amount=Decimal("-200.00"),
                source_row=2,
            ),
            AccountTransaction(
                account_id=checking.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 3, 1),
                original_description="Move to savings",
                role="internal_transfer",
                amount=Decimal("-300.00"),
                source_row=3,
            ),
            AccountTransaction(
                account_id=savings.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 3, 2),
                original_description="Deposit from checking",
                role="external_deposit",
                amount=Decimal("300.00"),
                source_row=4,
            ),
            AccountTransaction(
                account_id=retirement.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 2, 15),
                original_description="Employee contribution",
                role="employee_contribution",
                amount=Decimal("500.00"),
                source_row=5,
            ),
            AccountTransaction(
                account_id=retirement.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 3, 1),
                original_description="Employer contribution",
                role="employer_contribution",
                amount=Decimal("250.00"),
                source_row=6,
            ),
            AccountTransaction(
                account_id=retirement.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 3, 10),
                original_description="Withdrawal",
                role="external_withdrawal",
                amount=Decimal("-100.00"),
                source_row=7,
            ),
        ]
    )
    add_manual_value_observation(
        session,
        account_id=retirement.id,
        observation_date=date(2026, 1, 31),
        value=Decimal("10000.00"),
        source_note="Synthetic statement",
    )
    reconcile_all(session)
    session.flush()

    checking_points = list(
        session.scalars(
            select(AccountBalancePoint)
            .where(AccountBalancePoint.account_id == checking.id)
            .order_by(AccountBalancePoint.balance_date, AccountBalancePoint.kind)
        )
    )
    assert checking_points[0].amount == Decimal("1000.00")
    assert checking_points[-1].amount == Decimal("1500.00")
    dashboard = accounts_dashboard(session)
    assert dashboard["totals"]["money_in"] == "1000.00"
    assert dashboard["totals"]["money_out"] == "200.00"

    bridge = session.scalar(select(InvestmentValueBridge))
    assert bridge is not None
    assert bridge.investment_result == Decimal("1350.00")
    assert (
        bridge.opening_value
        + Decimal("500")
        + Decimal("250")
        - Decimal("100")
        + bridge.investment_result
        == bridge.closing_value
    )
    details = account_detail(
        session,
        retirement.id,
        date(2026, 1, 1),
        date(2026, 3, 31),
    )
    assert details is not None
    assert details["performance_status"] == "available"
    march = timeline(session, date(2026, 3, 1), date(2026, 3, 31))[0]
    assert march["cash_inflows"] == "0.00"
    assert march["transfers"] == "600.00"
    assert march["investment_result"] == "1350.00"

    reconcile_all(session)
    assert session.scalar(select(func.count(InvestmentValueBridge.id))) == 1


def test_manual_value_observation_is_idempotent(session: Session) -> None:
    artifact = _artifact(session)
    institution = Institution(canonical_name="Synthetic Investments", kind="investment")
    session.add(institution)
    session.flush()
    account = Account(
        institution_id=institution.id,
        external_key="investment",
        display_name="Investment ••0001",
        account_type="brokerage",
    )
    session.add(account)
    session.flush()
    session.add(
        BalanceSnapshot(
            account_id=account.id,
            artifact_id=artifact.id,
            snapshot_date=date(2026, 3, 31),
            kind="current",
            amount=Decimal("1100.00"),
        )
    )
    first = add_manual_value_observation(
        session,
        account_id=account.id,
        observation_date=date(2026, 2, 28),
        value=Decimal("1000.00"),
        source_note="Synthetic statement",
    )
    second = add_manual_value_observation(
        session,
        account_id=account.id,
        observation_date=date(2026, 2, 28),
        value=Decimal("1000.00"),
        source_note="Synthetic statement",
    )
    assert first.id == second.id
