from __future__ import annotations

import calendar
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from paycheck_map.models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    GoalProgram,
    ImportArtifact,
    ImportBatch,
    Institution,
    PayrollScheduleEntry,
)


@dataclass(frozen=True)
class GoalGapSeed:
    artifact: ImportArtifact
    cash_account: Account
    goal: GoalProgram | None
    payroll: PayrollScheduleEntry | None


def seed_goal_gap(
    session: Session,
    *,
    monthly_outflow: str = "9802.98",
    cash_balance: str = "5000.00",
    protected_floor: str = "3000.00",
    include_goal: bool = True,
    include_payroll: bool = True,
    complete_months: bool = True,
) -> GoalGapSeed:
    batch = ImportBatch(status="complete", requested_source="synthetic_goal_gap")
    session.add(batch)
    session.flush()
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256=hashlib.sha256(b"invented-goal-gap-evidence").hexdigest(),
        original_filename="invented-goal-gap.csv",
        source_kind="synthetic",
        adapter="synthetic_goal_gap",
        parser_version="test-v1",
    )
    bank = Institution(canonical_name="Invented Goal Gap Bank", kind="bank")
    session.add_all([artifact, bank])
    session.flush()
    cash = Account(
        institution_id=bank.id,
        external_key="invented-goal-gap-checking",
        display_name="Invented goal-gap checking",
        account_type="checking",
    )
    session.add(cash)
    session.flush()
    if complete_months:
        for month in (5, 6, 7):
            final_day = calendar.monthrange(2026, month)[1]
            session.add_all(
                [
                    BalanceSnapshot(
                        account_id=cash.id,
                        artifact_id=artifact.id,
                        snapshot_date=date(2026, month, 1),
                        kind="opening",
                        amount=Decimal(cash_balance),
                    ),
                    BalanceSnapshot(
                        account_id=cash.id,
                        artifact_id=artifact.id,
                        snapshot_date=date(2026, month, final_day),
                        kind="closing",
                        amount=Decimal(cash_balance),
                    ),
                    AccountTransaction(
                        account_id=cash.id,
                        artifact_id=artifact.id,
                        posted_date=date(2026, month, 15),
                        original_description=f"Invented complete-month outflow {month}",
                        role="external_outflow",
                        amount=-Decimal(monthly_outflow),
                        source_row=month,
                    ),
                ]
            )
    session.add(
        BalanceSnapshot(
            account_id=cash.id,
            artifact_id=artifact.id,
            snapshot_date=date(2026, 8, 11),
            kind="current",
            amount=Decimal(cash_balance),
        )
    )

    payroll = None
    if include_payroll:
        payroll = synthetic_payroll()
        session.add(payroll)

    goal = None
    if include_goal:
        now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
        goal = GoalProgram(
            public_key="goal_harbor_studio",
            source_life_goal_id=None,
            name="Invented Harbor Studio",
            target_date=date(2030, 8, 10),
            target_amount=Decimal("1872168.96"),
            protected_cash_floor=Decimal(protected_floor),
            reserved_amount=Decimal("0.00"),
            is_primary=True,
            status="active",
            tracking_mode="explicit_reservation",
            reservation_policy="exclusive_primary_goal",
            field_provenance=goal_provenance(),
            contract_version="money-map-v2-contract-v1",
            migration_version="0009_goal_persistence",
            created_at=now,
            updated_at=now,
        )
        session.add(goal)
    session.flush()
    return GoalGapSeed(
        artifact=artifact,
        cash_account=cash,
        goal=goal,
        payroll=payroll,
    )


def synthetic_payroll(*, gross: str = "3000.00", net: str = "1938.46") -> PayrollScheduleEntry:
    observed = date(2026, 8, 7)
    return PayrollScheduleEntry(
        payroll_statement_id=None,
        previous_checkpoint_id=None,
        next_checkpoint_id=None,
        payment_date=observed,
        observed_deposit_date=observed,
        period_start=observed,
        period_end=observed,
        payroll_year=observed.year,
        payroll_index=1,
        source_kind="calculated",
        calculation_version="completed-payroll-v1",
        employer="Invented Employer",
        job_title="Invented Engineer",
        base_salary=Decimal("78000.00"),
        gross_earnings=Decimal(gross),
        imputed_earnings=Decimal("0.00"),
        pretax_deductions=Decimal("0.00"),
        tax_withholdings=Decimal("1061.54"),
        after_tax_deductions=Decimal("0.00"),
        federal_taxable_gross=Decimal(gross),
        net_payment=Decimal(net),
        gross_adjustment=Decimal("0.00"),
        imputed_adjustment=Decimal("0.00"),
        pretax_adjustment=Decimal("0.00"),
        tax_adjustment=Decimal("0.00"),
        after_tax_adjustment=Decimal("0.00"),
        federal_taxable_adjustment=Decimal("0.00"),
        net_adjustment=Decimal("0.00"),
        deposit_splits=[],
        fingerprint=hashlib.sha256(f"invented-{gross}-{net}".encode()).hexdigest(),
    )


def goal_provenance() -> dict[str, dict[str, object]]:
    return {
        field: {
            "evidence": "user_entered",
            "source_refs": [f"synthetic:goal-gap:{field}"],
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
