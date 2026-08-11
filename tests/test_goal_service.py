from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from paycheck_map.app import app
from paycheck_map.db import get_session
from paycheck_map.goal_observation import (
    CompletedOperationState,
    SourceCurrentnessUpdate,
    coordinate_goal_observation,
    load_backfill_goal_observation,
)
from paycheck_map.goal_service import (
    CalculatedGoalPosition,
    GoalCheckInTrigger,
    GoalValidationError,
    IneligibleGoalError,
    StaleGoalWriteError,
    calculate_primary_goal_position,
    check_in_timeline,
    current_milestone,
    edit_goal,
    ensure_goal_check_in,
    goal_candidates,
    latest_comparison,
    primary_goal,
    primary_goal_state,
    program_edit_token,
    select_primary_goal,
)
from paycheck_map.models import (
    Account,
    AccountTransaction,
    ApplicationSetting,
    BalanceSnapshot,
    GoalCheckIn,
    GoalCheckInComponent,
    GoalProgram,
    ImportArtifact,
    ImportBatch,
    Institution,
    InvestmentHolding,
    InvestmentValueBridge,
    LifeGoal,
    LifePlanProfile,
    PayrollScheduleEntry,
    PayrollTransactionMatch,
    TransferMatch,
)
from paycheck_map.v2_contracts import (
    ComparisonComponentKind,
    GoalComparison,
    GoalComparisonComponent,
    GoalEditRequest,
    GoalPosition,
    PrimaryGoalSelectionRequest,
)

from .v2_migration_support import database_revision, migration_config


@dataclass(frozen=True)
class SeededIds:
    artifact_id: int
    cash_account_id: int
    brokerage_account_id: int
    retirement_account_id: int
    debt_account_id: int
    payroll_id: int
    goal_id: int
    life_goal_id: int


@pytest.fixture
def migrated_engine(tmp_path: Path) -> Iterator[Engine]:
    database = tmp_path / "slice2.sqlite3"
    command.upgrade(migration_config(database), "0009_goal_persistence")
    assert database_revision(database) == "0009_goal_persistence"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield engine
    engine.dispose()


def _seed(session: Session) -> SeededIds:
    batch = ImportBatch(status="complete", requested_source="synthetic")
    session.add(batch)
    session.flush()
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256=hashlib.sha256(b"slice-2-synthetic-artifact").hexdigest(),
        original_filename="synthetic.csv",
        source_kind="synthetic",
        adapter="synthetic-v1",
        parser_version="synthetic-v1",
    )
    bank = Institution(canonical_name="Synthetic Bank", kind="bank")
    investment = Institution(canonical_name="Synthetic Investments", kind="investment")
    lender = Institution(canonical_name="Synthetic Lender", kind="bank")
    session.add_all([artifact, bank, investment, lender])
    session.flush()

    cash = Account(
        institution_id=bank.id,
        external_key="cash-stable-id",
        display_name="Synthetic checking display",
        account_type="checking",
    )
    brokerage = Account(
        institution_id=investment.id,
        external_key="brokerage-stable-id",
        display_name="Synthetic brokerage display",
        account_type="brokerage",
    )
    retirement = Account(
        institution_id=investment.id,
        external_key="retirement-stable-id",
        display_name="Synthetic 401k display",
        account_type="401k",
    )
    debt = Account(
        institution_id=lender.id,
        external_key="debt-stable-id",
        display_name="Synthetic loan display",
        account_type="loan",
    )
    session.add_all([cash, brokerage, retirement, debt])
    session.flush()
    session.add_all(
        [
            BalanceSnapshot(
                account_id=cash.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 1),
                kind="opening",
                amount=Decimal("5000.00"),
            ),
            BalanceSnapshot(
                account_id=cash.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 7, 31),
                kind="closing",
                amount=Decimal("5800.00"),
            ),
            BalanceSnapshot(
                account_id=cash.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 8, 10),
                kind="current",
                amount=Decimal("6000.00"),
            ),
            BalanceSnapshot(
                account_id=brokerage.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 8, 10),
                kind="current",
                amount=Decimal("1500.00"),
            ),
            BalanceSnapshot(
                account_id=retirement.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 8, 10),
                kind="current",
                amount=Decimal("18000.00"),
            ),
            BalanceSnapshot(
                account_id=debt.id,
                artifact_id=artifact.id,
                snapshot_date=date(2026, 8, 10),
                kind="current",
                amount=Decimal("-400.00"),
            ),
            AccountTransaction(
                account_id=cash.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 7, 15),
                original_description="Synthetic external outflow",
                role="external_outflow",
                amount=Decimal("-3900.00"),
                source_row=1,
            ),
        ]
    )

    payroll = _payroll(observed_on=date(2026, 8, 7), fingerprint_seed="baseline")
    session.add(payroll)
    session.flush()

    profile = LifePlanProfile(
        birth_date=date(1990, 1, 1),
        state="NJ",
        end_age=95,
        current_monthly_outflow=Decimal("3900.00"),
        essential_monthly_spend=Decimal("3000.00"),
        flexible_monthly_spend=Decimal("900.00"),
        cash_floor=Decimal("3000.00"),
        retirement_tax_rate_pct=Decimal("20.00"),
        target_ages=[50],
        notes="synthetic",
    )
    session.add(profile)
    session.flush()
    life_goal = LifeGoal(
        profile_id=profile.id,
        name="Synthetic source Life Goal",
        target_date=date(2027, 8, 9),
        target_amount=Decimal("14000.00"),
        reserved_amount=Decimal("2000.00"),
        annual_cost=Decimal("0.00"),
        priority="required",
        enabled=True,
        notes="source remains immutable",
    )
    session.add(life_goal)
    session.flush()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    goal = GoalProgram(
        public_key="goal_synthetic_home",
        source_life_goal_id=life_goal.id,
        name="Synthetic operational goal",
        target_date=date(2027, 8, 9),
        target_amount=Decimal("14000.00"),
        protected_cash_floor=Decimal("3000.00"),
        reserved_amount=Decimal("2000.00"),
        is_primary=True,
        status="active",
        tracking_mode="explicit_reservation",
        reservation_policy="exclusive_primary_goal",
        field_provenance=_provenance("seed"),
        contract_version="money-map-v2-contract-v1",
        migration_version="0009_goal_persistence",
        created_at=now,
        updated_at=now,
    )
    session.add(goal)
    session.commit()
    return SeededIds(
        artifact_id=artifact.id,
        cash_account_id=cash.id,
        brokerage_account_id=brokerage.id,
        retirement_account_id=retirement.id,
        debt_account_id=debt.id,
        payroll_id=payroll.id,
        goal_id=goal.id,
        life_goal_id=life_goal.id,
    )


def _payroll(*, observed_on: date, fingerprint_seed: str) -> PayrollScheduleEntry:
    return PayrollScheduleEntry(
        payroll_statement_id=None,
        previous_checkpoint_id=None,
        next_checkpoint_id=None,
        payment_date=observed_on,
        observed_deposit_date=observed_on,
        period_start=observed_on,
        period_end=observed_on,
        payroll_year=observed_on.year,
        payroll_index=1,
        source_kind="calculated",
        calculation_version="completed-payroll-v1",
        employer="Synthetic Employer",
        job_title="Synthetic Engineer",
        base_salary=Decimal("190000.00"),
        gross_earnings=Decimal("3000.00"),
        imputed_earnings=Decimal("0.00"),
        pretax_deductions=Decimal("0.00"),
        tax_withholdings=Decimal("1061.54"),
        after_tax_deductions=Decimal("0.00"),
        federal_taxable_gross=Decimal("3000.00"),
        net_payment=Decimal("1938.46"),
        gross_adjustment=Decimal("0.00"),
        imputed_adjustment=Decimal("0.00"),
        pretax_adjustment=Decimal("0.00"),
        tax_adjustment=Decimal("0.00"),
        after_tax_adjustment=Decimal("0.00"),
        federal_taxable_adjustment=Decimal("0.00"),
        net_adjustment=Decimal("0.00"),
        deposit_splits=[],
        fingerprint=hashlib.sha256(fingerprint_seed.encode()).hexdigest(),
    )


def _provenance(seed: str) -> dict[str, dict[str, object]]:
    return {
        field: {
            "evidence": "user_entered",
            "source_refs": [f"synthetic:{seed}:{field}"],
        }
        for field in (
            "name",
            "target_date",
            "target_amount",
            "protected_cash_floor",
            "reserved_amount",
            "is_primary",
            "status",
        )
    }


def _calculated(session: Session, observed_on: date = date(2026, 8, 10)) -> CalculatedGoalPosition:
    result = calculate_primary_goal_position(session, observed_on=observed_on)
    assert result is not None
    return result


def _component(
    comparison: GoalComparison, kind: ComparisonComponentKind
) -> GoalComparisonComponent:
    return next(item for item in comparison.components if item.component is kind)


def _add_snapshot(
    session: Session,
    *,
    account_id: int,
    artifact_id: int,
    observed_on: date,
    amount: str,
) -> None:
    session.add(
        BalanceSnapshot(
            account_id=account_id,
            artifact_id=artifact_id,
            snapshot_date=observed_on,
            kind="current",
            amount=Decimal(amount),
        )
    )


def test_exact_position_calendar_evidence_and_milestones(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        result = _calculated(session)
        position = result.position
        assert position.accessible_cash.amount == Decimal("6000.00")
        assert position.accessible_investments.amount == Decimal("1500.00")
        assert position.retirement_assets_excluded.amount == Decimal("18000.00")
        assert position.tracked_debt.amount == Decimal("400.00")
        assert position.accessible_now.amount == Decimal("7500.00")
        assert position.available_above_floor.amount == Decimal("4500.00")
        assert position.remaining_target.amount == Decimal("12000.00")
        assert position.effective_recurring_take_home.amount == Decimal("4200.00")
        assert position.observed_recurring_outflow.amount == Decimal("3900.00")
        assert position.recurring_cash_flow_gap.amount == Decimal("0.00")
        assert position.funding_months == Decimal("12.000000000000")
        assert position.required_funding_pace.amount == Decimal("1000.00")
        assert current_milestone(result).kind == "fund_goal"

        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.protected_cash_floor = Decimal("7000.00")
        session.flush()
        assert current_milestone(_calculated(session)).kind == "restore_floor"
        goal.protected_cash_floor = Decimal("3000.00")
        outflow = session.scalar(
            select(AccountTransaction).where(AccountTransaction.role == "external_outflow")
        )
        assert outflow is not None
        outflow.amount = Decimal("-5000.00")
        session.flush()
        assert current_milestone(_calculated(session)).kind == "close_recurring_gap"
        outflow.amount = Decimal("-3900.00")
        goal.reserved_amount = goal.target_amount
        goal.status = "complete"
        session.flush()
        assert current_milestone(_calculated(session)).kind == "goal_complete"


@pytest.mark.parametrize(
    ("observed_on", "target_date", "expected_months"),
    [
        (date(2026, 8, 10), date(2026, 8, 10), Decimal("0.032258064516")),
        (date(2026, 1, 31), date(2026, 2, 1), Decimal("0.067972350230")),
        (date(2028, 2, 29), date(2028, 2, 29), Decimal("0.034482758621")),
    ],
)
def test_service_calendar_boundaries(
    migrated_engine: Engine,
    observed_on: date,
    target_date: date,
    expected_months: Decimal,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.target_date = target_date
        session.flush()
        assert _calculated(session, observed_on).position.funding_months == expected_months


def test_expired_unfinished_and_completed_goal_states(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.target_date = date(2026, 8, 9)
        session.flush()
        expired = _calculated(session)
        assert expired.position.pace_status == "expired"
        assert expired.position.required_funding_pace.amount is None
        assert current_milestone(expired).kind == "data_unavailable"
        goal.reserved_amount = goal.target_amount
        goal.status = "complete"
        session.flush()
        complete = _calculated(session)
        assert complete.position.pace_status == "complete"
        assert complete.position.required_funding_pace.amount == Decimal("0.00")
        assert current_milestone(complete).kind == "goal_complete"


def test_missing_and_evidenced_zero_balances(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        latest_cash = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == ids.cash_account_id)
            .order_by(BalanceSnapshot.snapshot_date.desc())
            .limit(1)
        )
        assert latest_cash is not None
        session.delete(latest_cash)
        session.flush()
        # Earlier closing evidence remains a supported latest observation.
        assert _calculated(session).position.accessible_cash.amount == Decimal("5800.00")
        for snapshot in session.scalars(
            select(BalanceSnapshot).where(BalanceSnapshot.account_id == ids.cash_account_id)
        ):
            session.delete(snapshot)
        session.flush()
        missing = _calculated(session).position
        assert missing.accessible_cash.amount is None
        assert missing.accessible_now.amount is None
        session.rollback()

    with Session(migrated_engine, expire_on_commit=False) as session:
        latest_cash = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == ids.cash_account_id)
            .order_by(BalanceSnapshot.snapshot_date.desc())
            .limit(1)
        )
        assert latest_cash is not None
        latest_cash.amount = Decimal("0.00")
        session.flush()
        zero = _calculated(session).position
        assert zero.accessible_cash.amount == Decimal("0.00")
        assert zero.accessible_cash.evidence == "observed"
        assert current_milestone(_calculated(session)).kind == "restore_floor"


def test_payroll_and_outflow_availability_rules(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        baseline = session.get(PayrollScheduleEntry, ids.payroll_id)
        assert baseline is not None
        baseline.observed_deposit_date = date(2024, 1, 1)
        baseline.payment_date = date(2024, 1, 1)
        session.flush()
        assert _calculated(session).position.effective_recurring_take_home.amount == Decimal(
            "4200.00"
        )
        session.delete(baseline)
        session.flush()
        missing_payroll = _calculated(session).position
        assert missing_payroll.effective_recurring_take_home.amount is None
        assert missing_payroll.recurring_cash_flow_gap.amount is None
        session.rollback()

    with Session(migrated_engine, expire_on_commit=False) as session:
        for snapshot in session.scalars(
            select(BalanceSnapshot).where(
                BalanceSnapshot.account_id == ids.cash_account_id,
                BalanceSnapshot.snapshot_date < date(2026, 8, 1),
            )
        ):
            session.delete(snapshot)
        session.flush()
        position = _calculated(session).position
        assert position.observed_recurring_outflow.amount is None
        assert position.recurring_cash_flow_gap.amount is None


def test_zero_outflow_with_complete_coverage_is_observed(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)
        outflow = session.scalar(
            select(AccountTransaction).where(AccountTransaction.role == "external_outflow")
        )
        assert outflow is not None
        session.delete(outflow)
        session.flush()
        position = _calculated(session).position
        assert position.observed_recurring_outflow.amount == Decimal("0.00")
        assert position.recurring_cash_flow_gap.amount == Decimal("0.00")


def test_investment_classification_excludes_retirement_and_restricted(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        stock_plan = Account(
            institution_id=session.get(Account, ids.brokerage_account_id).institution_id,  # type: ignore[union-attr]
            external_key="stock-plan-stable-id",
            display_name="Display-only stock plan",
            account_type="stock plan",
        )
        session.add(stock_plan)
        session.flush()
        _add_snapshot(
            session,
            account_id=stock_plan.id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 10),
            amount="1000.00",
        )
        session.add_all(
            [
                InvestmentHolding(
                    account_id=stock_plan.id,
                    artifact_id=ids.artifact_id,
                    security_id="sellable-id",
                    security_name="Synthetic common stock",
                    ticker_symbol="SYN",
                    security_type="equity",
                    quantity=Decimal("1.00000000"),
                    institution_price=Decimal("600.00"),
                    institution_value=Decimal("600.00"),
                    cost_basis=Decimal("500.00"),
                    as_of=date(2026, 8, 10),
                ),
                InvestmentHolding(
                    account_id=stock_plan.id,
                    artifact_id=ids.artifact_id,
                    security_id="restricted-id",
                    security_name="Synthetic restricted RSU",
                    ticker_symbol=None,
                    security_type="equity",
                    quantity=Decimal("1.00000000"),
                    institution_price=Decimal("400.00"),
                    institution_value=Decimal("400.00"),
                    cost_basis=None,
                    as_of=date(2026, 8, 10),
                ),
            ]
        )
        session.flush()
        position = _calculated(session).position
        assert position.accessible_investments.amount == Decimal("2100.00")
        assert position.retirement_assets_excluded.amount == Decimal("18000.00")


def test_source_fingerprint_changes_only_for_canonical_inputs(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        original = _calculated(session)
        assert original.source_fingerprint == original.source_material.fingerprint()
        reordered = original.source_material.model_copy(
            update={"source_records": tuple(reversed(original.source_material.source_records))}
        )
        assert reordered.fingerprint() == original.source_fingerprint

        cash = session.get(Account, ids.cash_account_id)
        assert cash is not None
        cash.display_name = "Changed loan-like display copy only"
        session.flush()
        assert _calculated(session).source_fingerprint == original.source_fingerprint

        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.target_amount = Decimal("15000.00")
        session.flush()
        changed = _calculated(session)
        assert changed.source_fingerprint != original.source_fingerprint
        payload = changed.source_material.canonical_json()
        assert "Changed loan-like display copy only" not in payload
        assert "synthetic.csv" not in payload


def test_check_in_idempotency_same_day_change_and_atomicity(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        first = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        original_created = first.created_at
        second = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.POST_REFRESH,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        assert second.check_in_id == first.check_in_id
        assert second.created_at == original_created
        stored = session.get(GoalCheckIn, first.check_in_id)
        assert stored is not None
        assert stored.trigger == "synthetic_test"

        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.target_amount = Decimal("14001.00")
        session.flush()
        changed = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        assert changed.check_in_id != first.check_in_id
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 2

    with Session(migrated_engine, expire_on_commit=False) as session:
        goal = primary_goal(session)
        assert goal is not None
        goal.target_amount = Decimal("16000.00")
        session.commit()
        import paycheck_map.goal_service as service

        original_components = service._component_rows

        def invalid_components(
            check_in: GoalCheckIn, position: GoalPosition
        ) -> list[GoalCheckInComponent]:
            rows = original_components(check_in, position)
            rows.append(
                GoalCheckInComponent(
                    check_in_id=check_in.check_in_id,
                    component_key=rows[0].component_key,
                    component_version=rows[0].component_version,
                    amount=rows[0].amount,
                    evidence_class=rows[0].evidence_class,
                    derivation=rows[0].derivation,
                    supporting_source_refs=rows[0].supporting_source_refs,
                )
            )
            return rows

        monkeypatch.setattr(service, "_component_rows", invalid_components)
        with pytest.raises(IntegrityError):
            ensure_goal_check_in(
                session,
                trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
                effective_observation_date=date(2026, 8, 10),
            )
        session.rollback()
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 2
        component_count = session.scalar(select(func.count(GoalCheckInComponent.id)))
        assert component_count is not None and component_count > 0


def test_observation_date_changes_live_pace_without_changing_check_in_identity(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)
        first_position = calculate_primary_goal_position(session, observed_on=date(2026, 8, 10))
        assert first_position is not None
        first = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.LOAD_BACKFILL,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()

        later_position = calculate_primary_goal_position(session, observed_on=date(2026, 9, 10))
        assert later_position is not None
        later = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.LOAD_BACKFILL,
            effective_observation_date=date(2026, 9, 10),
        )
        session.commit()

        assert later_position.source_fingerprint == first_position.source_fingerprint
        assert later_position.position.required_funding_pace.amount != (
            first_position.position.required_funding_pace.amount
        )
        assert later.check_in_id == first.check_in_id
        assert later.effective_observation_date == date(2026, 8, 10)
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1


def test_concurrent_duplicate_creation_converges(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)

    def worker() -> str:
        with Session(migrated_engine, expire_on_commit=False) as worker_session:
            result = ensure_goal_check_in(
                worker_session,
                trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
                effective_observation_date=date(2026, 8, 10),
            )
            worker_session.commit()
            return result.check_in_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(lambda _: worker(), range(2)))
    assert len(set(identities)) == 1
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1


def test_load_backfill_created_unchanged_concurrent_and_no_primary(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        first = load_backfill_goal_observation(session, observed_on=date(2026, 8, 10))
        repeated = load_backfill_goal_observation(session, observed_on=date(2026, 8, 11))
        assert first.status == "created"
        assert repeated.status == "unchanged"
        assert first.check_in is not None and repeated.check_in is not None
        assert repeated.check_in.check_in_id == first.check_in.check_in_id
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1

        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.is_primary = False
        session.commit()
        no_primary = load_backfill_goal_observation(session, observed_on=date(2026, 8, 12))
        assert no_primary.status == "no_primary"

    with Session(migrated_engine) as session:
        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.is_primary = True
        goal.target_amount = Decimal("14001.00")
        session.commit()

    def worker() -> str:
        with Session(migrated_engine, expire_on_commit=False) as worker_session:
            result = load_backfill_goal_observation(worker_session, observed_on=date(2026, 8, 12))
            assert result.check_in is not None
            return result.check_in.check_in_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(lambda _: worker(), range(2)))
    assert len(set(identities)) == 1
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 2


def test_partial_source_state_blocks_load_until_same_source_recovers(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)
        partial = coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            observed_on=date(2026, 8, 10),
            operation_state=CompletedOperationState.PARTIAL,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key="manual_import",
                    state="partial",
                    evidence_ref="import_batch:synthetic_partial",
                ),
            ),
        )
        assert partial.status == "not_current"
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 0
        assert (
            load_backfill_goal_observation(session, observed_on=date(2026, 8, 11)).status
            == "not_current"
        )
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 0

        recovered = coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            observed_on=date(2026, 8, 11),
            operation_state=CompletedOperationState.COMPLETE,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key="manual_import",
                    state="complete",
                    evidence_ref="import_batch:synthetic_complete",
                ),
            ),
        )
        assert recovered.status == "created"
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1


def test_observation_failure_rolls_back_only_check_in_transaction(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)
        session.add(ApplicationSetting(key="financial-operation", value="committed"))
        session.commit()

        def fail_check_in(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("synthetic observation failure")

        monkeypatch.setattr(
            "paycheck_map.goal_observation.ensure_goal_check_in_result", fail_check_in
        )
        result = coordinate_goal_observation(
            session,
            trigger=GoalCheckInTrigger.POST_PAYROLL,
            observed_on=date(2026, 8, 10),
            operation_state=CompletedOperationState.COMPLETE,
            source_updates=(
                SourceCurrentnessUpdate(
                    source_key="payroll",
                    state="complete",
                    evidence_ref="payroll_rebuild:synthetic",
                ),
            ),
        )
        assert result.status == "unavailable"
        assert result.retryable is True
        assert session.get(ApplicationSetting, "financial-operation") is not None
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 0


def test_caller_transaction_boundary_success_unchanged_and_rollback(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)
        session.add(ApplicationSetting(key="caller-success", value="complete"))
        first = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        assert session.get(ApplicationSetting, "caller-success") is not None
        unchanged = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        assert unchanged.check_in_id == first.check_in_id

        session.add(ApplicationSetting(key="caller-failed", value="rolling-back"))
        goal = primary_goal(session)
        assert goal is not None
        goal.target_amount = Decimal("14001.00")
        rolled_back = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.POST_IMPORT,
            effective_observation_date=date(2026, 8, 11),
        )
        assert rolled_back.check_in_id != first.check_in_id
        session.rollback()
        assert session.get(ApplicationSetting, "caller-failed") is None
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1


def test_comparison_market_evidence_and_residual(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        first = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        assert latest_comparison(session, program=primary_goal(session)).state == (  # type: ignore[arg-type]
            "no_previous_check_in"
        )
        _add_snapshot(
            session,
            account_id=ids.brokerage_account_id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 11),
            amount="1600.00",
        )
        session.add(
            InvestmentValueBridge(
                account_id=ids.brokerage_account_id,
                period_start=date(2026, 8, 10),
                period_end=date(2026, 8, 11),
                opening_value=Decimal("1500.00"),
                employee_contributions=Decimal("0.00"),
                employer_contributions=Decimal("0.00"),
                stock_plan_contributions=Decimal("0.00"),
                other_deposits=Decimal("0.00"),
                withdrawals=Decimal("0.00"),
                investment_result=Decimal("100.00"),
                closing_value=Decimal("1600.00"),
                reported_return_pct=None,
                calculated_return_pct=Decimal("6.67"),
                return_method="dollar_residual",
            )
        )
        second = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 11),
        )
        session.commit()
        comparison_result = latest_comparison(session, program=primary_goal(session))  # type: ignore[arg-type]
        assert comparison_result.state == "available"
        comparison = comparison_result.comparison
        assert comparison is not None
        assert comparison.previous_check_in_id == first.check_in_id
        assert comparison.current_check_in_id == second.check_in_id
        assert _component(
            comparison, ComparisonComponentKind.SUPPORTED_MARKET_MOVEMENT
        ).change.amount == Decimal("100.00")
        assert _component(
            comparison, ComparisonComponentKind.UNEXPLAINED_RESIDUAL
        ).change.amount == Decimal("0.00")


def test_comparison_market_without_proof_remains_unexplained(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        _add_snapshot(
            session,
            account_id=ids.brokerage_account_id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 11),
            amount="1600.00",
        )
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 11),
        )
        session.commit()
        program = primary_goal(session)
        assert program is not None
        comparison = latest_comparison(session, program=program).comparison
        assert comparison is not None
        assert all(
            item.component is not ComparisonComponentKind.SUPPORTED_MARKET_MOVEMENT
            for item in comparison.components
        )
        assert _component(
            comparison, ComparisonComponentKind.UNEXPLAINED_RESIDUAL
        ).change.amount == Decimal("100.00")


@pytest.mark.parametrize("matched", [True, False], ids=["matched", "ambiguous"])
def test_comparison_transfer_attribution(migrated_engine: Engine, matched: bool) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        left = AccountTransaction(
            account_id=ids.cash_account_id,
            artifact_id=ids.artifact_id,
            posted_date=date(2026, 8, 11),
            original_description="Synthetic transfer out",
            role="internal_transfer" if matched else "unresolved",
            amount=Decimal("-100.00"),
            source_row=20,
        )
        right = AccountTransaction(
            account_id=ids.retirement_account_id,
            artifact_id=ids.artifact_id,
            posted_date=date(2026, 8, 11),
            original_description="Synthetic transfer in",
            role="internal_transfer" if matched else "unresolved",
            amount=Decimal("100.00"),
            source_row=21,
        )
        session.add_all([left, right])
        session.flush()
        if matched:
            session.add(
                TransferMatch(
                    left_transaction_id=left.id,
                    right_transaction_id=right.id,
                    amount=Decimal("100.00"),
                    confidence="high",
                )
            )
        _add_snapshot(
            session,
            account_id=ids.cash_account_id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 11),
            amount="5900.00",
        )
        _add_snapshot(
            session,
            account_id=ids.retirement_account_id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 11),
            amount="18100.00",
        )
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 11),
        )
        session.commit()
        program = primary_goal(session)
        assert program is not None
        comparison = latest_comparison(session, program=program).comparison
        assert comparison is not None
        event = next(
            (
                item
                for item in comparison.components
                if item.component is ComparisonComponentKind.SUPPORTED_TRANSFER
            ),
            None,
        )
        residual = _component(
            comparison, ComparisonComponentKind.UNEXPLAINED_RESIDUAL
        ).change.amount
        if matched:
            assert event is not None and event.change.amount == Decimal("-100.00")
            assert residual == Decimal("0.00")
        else:
            assert event is None
            assert residual == Decimal("-100.00")


@pytest.mark.parametrize("supported", [True, False], ids=["supported", "label-only"])
def test_comparison_payroll_attribution(migrated_engine: Engine, supported: bool) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        schedule = _payroll(observed_on=date(2026, 8, 11), fingerprint_seed="new-payroll")
        transaction = AccountTransaction(
            account_id=ids.cash_account_id,
            artifact_id=ids.artifact_id,
            posted_date=date(2026, 8, 11),
            original_description="Synthetic payroll-like deposit",
            role="external_inflow",
            amount=Decimal("1938.46"),
            source_row=30,
        )
        session.add_all([schedule, transaction])
        session.flush()
        if supported:
            session.add(
                PayrollTransactionMatch(
                    schedule_entry_id=schedule.id,
                    transaction_id=transaction.id,
                    amount=Decimal("1938.46"),
                    match_group="synthetic-exact",
                )
            )
        _add_snapshot(
            session,
            account_id=ids.cash_account_id,
            artifact_id=ids.artifact_id,
            observed_on=date(2026, 8, 11),
            amount="7938.46",
        )
        ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 11),
        )
        session.commit()
        program = primary_goal(session)
        assert program is not None
        comparison = latest_comparison(session, program=program).comparison
        assert comparison is not None
        event = next(
            (
                item
                for item in comparison.components
                if item.component is ComparisonComponentKind.SUPPORTED_PAYROLL
            ),
            None,
        )
        residual = _component(
            comparison, ComparisonComponentKind.UNEXPLAINED_RESIDUAL
        ).change.amount
        if supported:
            assert event is not None and event.change.amount == Decimal("1938.46")
            assert residual == Decimal("0.00")
        else:
            assert event is None
            assert residual == Decimal("1938.46")


def test_comparison_direct_components_and_deterministic_tie_order(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
    monkeypatch.setattr("paycheck_map.goal_service.utcnow", lambda: fixed)
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        first = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None
        goal.target_amount = Decimal("15000.00")
        session.commit()
        second = ensure_goal_check_in(
            session,
            trigger=GoalCheckInTrigger.SYNTHETIC_TEST,
            effective_observation_date=date(2026, 8, 10),
        )
        session.commit()
        program = primary_goal(session)
        assert program is not None
        timeline = check_in_timeline(session, program=program, limit=1)
        assert timeline.check_ins[0].check_in_id == max(first.check_in_id, second.check_in_id)
        assert timeline.next_cursor is not None
        next_page = check_in_timeline(
            session, program=program, limit=1, cursor=timeline.next_cursor
        )
        assert len(next_page.check_ins) == 1
        comparison = latest_comparison(session, program=program).comparison
        assert comparison is not None
        assert {
            ComparisonComponentKind.ACCESSIBLE_NOW,
            ComparisonComponentKind.ACCESSIBLE_CASH,
            ComparisonComponentKind.ACCESSIBLE_INVESTMENTS,
            ComparisonComponentKind.TRACKED_DEBT,
            ComparisonComponentKind.GOAL_TARGET,
            ComparisonComponentKind.PROTECTED_CASH_FLOOR,
            ComparisonComponentKind.RESERVED_FOR_GOAL,
            ComparisonComponentKind.UNEXPLAINED_RESIDUAL,
        } <= {item.component for item in comparison.components}


def test_goal_edit_stale_validation_fingerprint_and_life_source_immutability(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        goal = session.get(GoalProgram, ids.goal_id)
        life_goal = session.get(LifeGoal, ids.life_goal_id)
        assert goal is not None and life_goal is not None
        source_before = (life_goal.name, life_goal.target_date, life_goal.target_amount)
        fingerprint_before = _calculated(session).source_fingerprint
        token = program_edit_token(goal)
        request = GoalEditRequest.model_validate(
            {
                "expected_edit_token": token,
                "name": "Edited operational goal",
                "target_date": "2027-09-01",
                "target_amount": "15000.00",
                "protected_cash_floor": "3500.00",
                "reserved_for_goal": "15000.00",
            }
        )
        updated = edit_goal(session, goal_program_id=goal.public_key, request=request)
        session.commit()
        assert updated.status == "complete"
        assert updated.target_amount.amount == Decimal("15000.00")
        assert updated.edit_token != token
        assert _calculated(session).source_fingerprint != fingerprint_before
        life_goal = session.get(LifeGoal, ids.life_goal_id)
        assert life_goal is not None
        assert (life_goal.name, life_goal.target_date, life_goal.target_amount) == source_before
        assert goal.field_provenance["target_amount"]["edit_origin"] == "v2_owner_edit"

        with pytest.raises(StaleGoalWriteError):
            edit_goal(
                session,
                goal_program_id=goal.public_key,
                request=GoalEditRequest.model_validate(
                    {
                        "expected_edit_token": token,
                        "target_amount": "16000.00",
                    }
                ),
            )
        with pytest.raises(GoalValidationError, match="cannot exceed"):
            edit_goal(
                session,
                goal_program_id=goal.public_key,
                request=GoalEditRequest.model_validate(
                    {
                        "expected_edit_token": updated.edit_token,
                        "target_amount": "100.00",
                    }
                ),
            )
        with pytest.raises(ValueError, match="exact decimal strings"):
            GoalEditRequest.model_validate(
                {
                    "expected_edit_token": updated.edit_token,
                    "target_amount": 16000.0,
                }
            )


def test_primary_selection_is_transactional_unique_and_preserves_reservations(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        previous = session.get(GoalProgram, ids.goal_id)
        assert previous is not None
        now = datetime(2026, 8, 10, 12, 1, tzinfo=UTC)
        candidate = GoalProgram(
            public_key="goal_synthetic_second",
            source_life_goal_id=None,
            name="Second candidate",
            target_date=date(2028, 1, 1),
            target_amount=Decimal("5000.00"),
            protected_cash_floor=Decimal("3000.00"),
            reserved_amount=Decimal("250.00"),
            is_primary=False,
            status="active",
            tracking_mode="explicit_reservation",
            reservation_policy="exclusive_primary_goal",
            field_provenance=_provenance("candidate"),
            contract_version="money-map-v2-contract-v1",
            migration_version="0009_goal_persistence",
            created_at=now,
            updated_at=now,
        )
        session.add(candidate)
        session.commit()
        listed = goal_candidates(session)
        assert [item.goal_program_id for item in listed.candidates] == [candidate.public_key]
        previous_reserved = previous.reserved_amount
        candidate_reserved = candidate.reserved_amount
        selected = select_primary_goal(
            session,
            request=PrimaryGoalSelectionRequest(
                goal_program_id=candidate.public_key,
                expected_edit_token=program_edit_token(candidate),
            ),
        )
        session.commit()
        assert selected.is_primary is True
        assert primary_goal_state(session).goal == selected
        assert (
            session.scalar(
                select(func.count(GoalProgram.id)).where(GoalProgram.is_primary.is_(True))
            )
            == 1
        )
        assert previous.reserved_amount == previous_reserved
        assert candidate.reserved_amount == candidate_reserved
        assert previous.field_provenance["is_primary"]["edit_origin"] == "v2_owner_edit"

        stale_token = "0" * 64
        with pytest.raises(StaleGoalWriteError):
            select_primary_goal(
                session,
                request=PrimaryGoalSelectionRequest(
                    goal_program_id=previous.public_key,
                    expected_edit_token=stale_token,
                ),
            )
        assert primary_goal(session).public_key == candidate.public_key  # type: ignore[union-attr]
        previous.status = "complete"
        previous.reserved_amount = previous.target_amount
        session.commit()
        with pytest.raises(IneligibleGoalError):
            select_primary_goal(
                session,
                request=PrimaryGoalSelectionRequest(
                    goal_program_id=previous.public_key,
                    expected_edit_token=program_edit_token(previous),
                ),
            )
        assert primary_goal(session).public_key == candidate.public_key  # type: ignore[union-attr]


def test_failed_selection_preserves_no_primary_state(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        candidate = session.get(GoalProgram, ids.goal_id)
        assert candidate is not None
        candidate.is_primary = False
        session.commit()
        assert primary_goal_state(session).state == "no_primary"
        assert goal_candidates(session).candidates[0].goal_program_id == candidate.public_key

        with pytest.raises(StaleGoalWriteError):
            select_primary_goal(
                session,
                request=PrimaryGoalSelectionRequest(
                    goal_program_id=candidate.public_key,
                    expected_edit_token="0" * 64,
                ),
            )
        assert primary_goal_state(session).state == "no_primary"

        candidate.reserved_amount = candidate.target_amount
        candidate.status = "complete"
        session.commit()
        with pytest.raises(IneligibleGoalError):
            select_primary_goal(
                session,
                request=PrimaryGoalSelectionRequest(
                    goal_program_id=candidate.public_key,
                    expected_edit_token=program_edit_token(candidate),
                ),
            )
        assert primary_goal_state(session).state == "no_primary"


def test_read_apis_are_typed_explicit_and_never_create_check_ins(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)

        def override_session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_session] = override_session
        try:

            async def exercise() -> list[httpx.Response]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test.local"
                ) as client:
                    paths = [
                        "/api/v2/goals/primary",
                        "/api/v2/goals/candidates",
                        "/api/v2/goals/position?observed_on=2026-08-10",
                        "/api/v2/goals/check-ins/latest",
                        "/api/v2/goals/check-ins",
                        "/api/v2/goals/comparison",
                        "/api/v2/goals/milestone?observed_on=2026-08-10",
                        "/api/v2/goals/provenance?observed_on=2026-08-10",
                    ]
                    return [await client.get(path) for path in paths]

            responses = asyncio.run(exercise())
        finally:
            app.dependency_overrides.clear()
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json()["state"] == "primary"
        assert responses[2].json()["position"]["accessible_now"]["amount"] == "7500.00"
        assert responses[3].json()["state"] == "no_check_in"
        assert responses[5].json()["state"] == "no_previous_check_in"
        assert responses[6].json()["milestone"]["kind"] == "fund_goal"
        provenance = responses[7].json()
        assert provenance["source_fingerprint"]
        assert "original_filename" not in str(provenance)
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 0


def test_backfill_api_is_explicit_idempotent_and_accepts_no_browser_telemetry(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        _seed(session)

        def override_session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_session] = override_session
        try:

            async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test.local"
                ) as client:
                    created = await client.post("/api/v2/goals/check-ins/backfill")
                    unchanged = await client.post("/api/v2/goals/check-ins/backfill")
                    rejected_telemetry = await client.post(
                        "/api/v2/goals/check-ins/backfill",
                        json={"opened_at": "2026-08-10T12:00:00Z"},
                    )
                    return created, unchanged, rejected_telemetry

            created, unchanged, rejected_telemetry = asyncio.run(exercise())
        finally:
            app.dependency_overrides.clear()
        assert created.status_code == 200
        assert created.json()["status"] == "created"
        assert unchanged.status_code == 200
        assert unchanged.json()["status"] == "unchanged"
        assert rejected_telemetry.status_code == 200
        assert rejected_telemetry.json()["status"] == "unchanged"
        assert "opened_at" not in rejected_telemetry.text
        assert session.scalar(select(func.count(GoalCheckIn.check_in_id))) == 1


def test_api_goal_edit_and_selection_conflicts(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        ids = _seed(session)
        goal = session.get(GoalProgram, ids.goal_id)
        assert goal is not None

        def override_session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_session] = override_session
        try:

            async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test.local"
                ) as client:
                    token = program_edit_token(goal)
                    updated = await client.patch(
                        f"/api/v2/goals/{goal.public_key}",
                        json={
                            "expected_edit_token": token,
                            "target_amount": "15000.00",
                        },
                    )
                    stale = await client.patch(
                        f"/api/v2/goals/{goal.public_key}",
                        json={
                            "expected_edit_token": token,
                            "target_amount": "16000.00",
                        },
                    )
                    binary_float = await client.patch(
                        f"/api/v2/goals/{goal.public_key}",
                        json={
                            "expected_edit_token": updated.json()["edit_token"],
                            "target_amount": 16000.0,
                        },
                    )
                    return updated, stale, binary_float

            updated, stale, binary_float = asyncio.run(exercise())
        finally:
            app.dependency_overrides.clear()
        assert updated.status_code == 200
        assert updated.json()["target_amount"]["amount"] == "15000.00"
        assert stale.status_code == 409
        assert binary_float.status_code == 422
