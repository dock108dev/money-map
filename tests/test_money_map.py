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
    InvestmentHolding,
    InvestmentValueBridge,
    ReconciliationResult,
)
from paycheck_map.reconciliation import reconcile_all
from paycheck_map.services import (
    account_detail,
    accounts_dashboard,
    exceptions,
    fidelity_summary,
    timeline,
    wealth_dashboard,
)


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


def test_bank_review_distinguishes_same_day_timing_from_loan_accrual(
    session: Session,
) -> None:
    artifact = _artifact(session)
    institution = Institution(canonical_name="Synthetic Bank", kind="bank")
    session.add(institution)
    session.flush()
    checking = Account(
        institution_id=institution.id,
        external_key="timing-checking",
        display_name="Checking ••1206",
        account_type="checking",
    )
    loan = Account(
        institution_id=institution.id,
        external_key="loan",
        display_name="Personal loan",
        account_type="loan",
    )
    session.add_all([checking, loan])
    session.flush()
    session.add_all(
        [
            BalanceSnapshot(
                account_id=checking.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 29),
                kind="opening",
                amount=Decimal("20000.00"),
            ),
            BalanceSnapshot(
                account_id=checking.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 31),
                kind="closing",
                amount=Decimal("6895.07"),
            ),
            BalanceSnapshot(
                account_id=loan.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 1),
                kind="opening",
                amount=Decimal("10000.00"),
            ),
            BalanceSnapshot(
                account_id=loan.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 31),
                kind="closing",
                amount=Decimal("10014.41"),
            ),
            AccountTransaction(
                account_id=checking.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 7, 29),
                original_description="Opening-day posted purchases",
                role="external_outflow",
                amount=Decimal("-13104.93"),
                source_row=1,
            ),
        ]
    )
    reconcile_all(session)

    checking_result = session.scalar(
        select(ReconciliationResult).where(
            ReconciliationResult.entity_type == "account",
            ReconciliationResult.entity_id == str(checking.id),
            ReconciliationResult.rule == "account_balance",
        )
    )
    assert checking_result is not None
    assert checking_result.status == "reconciled"
    assert checking_result.residual == Decimal("0.00")
    assert checking_result.details["likely_cause"] == "same_day_posting_boundary"
    assert checking_result.details["strict_residual"] == "13104.93"

    review = exceptions(session)
    assert len(review) == 1
    assert review[0]["entity_id"] == str(loan.id)
    assert review[0]["residual"] == "-14.41"
    assert review[0]["details"]["likely_cause"] == "interest_or_balance_adjustment"
    assert len(review[0]["details"]["next_steps"]) == 3


def test_short_investment_interval_keeps_audit_bridge_but_hides_performance(
    session: Session,
) -> None:
    artifact = _artifact(session)
    institution = Institution(canonical_name="Synthetic Fidelity", kind="investment")
    session.add(institution)
    session.flush()
    account = Account(
        institution_id=institution.id,
        external_key="short-window",
        display_name="Brokerage ••0004",
        account_type="brokerage",
    )
    session.add(account)
    session.flush()
    session.add_all(
        [
            BalanceSnapshot(
                account_id=account.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 29),
                kind="opening",
                amount=Decimal("20000.00"),
            ),
            BalanceSnapshot(
                account_id=account.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 31),
                kind="closing",
                amount=Decimal("6500.00"),
            ),
            AccountTransaction(
                account_id=account.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 7, 29),
                original_description="Withdrawal",
                role="external_withdrawal",
                amount=Decimal("-10000.00"),
                source_row=1,
            ),
        ]
    )
    reconcile_all(session)

    bridge = session.scalar(select(InvestmentValueBridge))
    assert bridge is not None
    assert bridge.investment_result == Decimal("-13500.00")
    assert bridge.return_method == "tracking_short_window"
    dashboard = accounts_dashboard(session)
    assert dashboard["accounts"][0]["performance_status"] == "tracking"
    assert dashboard["accounts"][0]["investment_result"] is None
    detail = account_detail(session, account.id, date(2026, 7, 1), date(2026, 7, 31))
    assert detail is not None
    assert detail["bridges"][0]["investment_result"] is None
    assert detail["bridges"][0]["performance_status"] == "tracking"
    assert timeline(session, date(2026, 7, 1), date(2026, 7, 31))[0]["investment_result"] is None
    assert fidelity_summary(session)["consolidated"] == {}
    assert fidelity_summary(session)["warnings"]


def test_wealth_dashboard_separates_access_and_removes_deposits_from_performance(
    session: Session,
) -> None:
    artifact = _artifact(session)
    bank = Institution(canonical_name="Synthetic Bank", kind="bank")
    fidelity = Institution(canonical_name="Synthetic Fidelity", kind="investment")
    session.add_all([bank, fidelity])
    session.flush()
    cash = Account(
        institution_id=bank.id,
        external_key="cash",
        display_name="Checking ••0001",
        account_type="checking",
    )
    brokerage = Account(
        institution_id=fidelity.id,
        external_key="brokerage",
        display_name="Brokerage ••0002",
        account_type="brokerage",
    )
    retirement = Account(
        institution_id=fidelity.id,
        external_key="401k",
        display_name="401(k) ••0003",
        account_type="401k",
    )
    restricted = Account(
        institution_id=fidelity.id,
        external_key="rsu",
        display_name="Stock plan ••0004",
        account_type="stock plan",
    )
    session.add_all([cash, brokerage, retirement, restricted])
    session.flush()
    session.add(
        BalanceSnapshot(
            account_id=cash.id,
            artifact_id=artifact.id,
            snapshot_date=date(2026, 1, 10),
            kind="current",
            amount=Decimal("1000.00"),
        )
    )
    for account, opening, closing in (
        (brokerage, "10000.00", "11500.00"),
        (retirement, "20000.00", "20000.00"),
        (restricted, "5000.00", "5000.00"),
    ):
        session.add_all(
            [
                BalanceSnapshot(
                    account_id=account.id,
                    artifact_id=artifact.id,
                    snapshot_date=date(2026, 1, 1),
                    kind="current",
                    amount=Decimal(opening),
                ),
                BalanceSnapshot(
                    account_id=account.id,
                    artifact_id=artifact.id,
                    snapshot_date=date(2026, 1, 10),
                    kind="current",
                    amount=Decimal(closing),
                ),
            ]
        )
    session.add_all(
        [
            InvestmentHolding(
                account_id=restricted.id,
                artifact_id=artifact.id,
                security_id="synthetic-rsu",
                security_name="Synthetic RSU",
                ticker_symbol="SYNTHETIC.RSU",
                security_type="equity",
                quantity=Decimal("10"),
                institution_price=Decimal("500.00"),
                institution_value=Decimal("5000.00"),
                cost_basis=None,
                as_of=date(2026, 1, 10),
            ),
            AccountTransaction(
                account_id=brokerage.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 1, 5),
                original_description="Brokerage deposit",
                role="external_deposit",
                amount=Decimal("1000.00"),
                source_row=1,
            ),
        ]
    )
    session.flush()

    wealth = wealth_dashboard(session)

    assert wealth["accessible"]["cash"] == "1000.00"
    assert wealth["accessible"]["sellable_investments"] == "11500.00"
    assert wealth["accessible"]["total"] == "12500.00"
    assert wealth["excluded"]["total"] == "25000.00"
    observed = wealth["fidelity"]["performance_periods"][0]
    assert observed["status"] == "available"
    assert observed["deposits"] == "1000.00"
    assert observed["investment_result"] == "500.00"
    assert observed["return_pct"] == "1.41"
    brokerage_row = next(row for row in wealth["fidelity"]["accounts"] if row["id"] == brokerage.id)
    assert brokerage_row["performance_status"] == "available"
    assert brokerage_row["investment_result"] == "500.00"
    restricted_row = next(
        row for row in wealth["fidelity"]["accounts"] if row["id"] == restricted.id
    )
    assert restricted_row["access_status"] == "restricted"
    assert restricted_row["accessible_value"] == "0.00"
