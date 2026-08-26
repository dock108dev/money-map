from __future__ import annotations

import calendar
import hashlib
import json
import os
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from paycheck_map.models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    GoalProgram,
    ImportArtifact,
    ImportBatch,
    Institution,
    LifeGoal,
    LifePlanProfile,
    LifeProjectionPeriod,
    LifeScenario,
    PayrollScheduleEntry,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests/fixtures/synthetic/v1_2_1"
STATES_PATH = FIXTURE_ROOT / "states.json"
CONTRACT_PATH = FIXTURE_ROOT / "release-state-contract.json"
REFERENCE = datetime(2026, 8, 10, 16, 0, tzinfo=UTC)


def materialize_release_state(database: Path, state_id: str) -> dict[str, Any]:
    """Create one deterministic synthetic database without reading candidate output."""
    states = {
        row["id"]: row for row in json.loads(STATES_PATH.read_text(encoding="utf-8"))["states"]
    }
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["states"][state_id]
    state = states[state_id]
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(database.parent, 0o700)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0009_goal_persistence")
    os.chmod(database, 0o600)

    if state_id == "partial_coverage":
        _seed_partial(database)
    elif state_id in {"loading", "recoverable_failure", "stale_evidence", "complete_current"}:
        _seed_complete(database, stale=state_id == "stale_evidence")
    elif state_id == "large_history":
        _seed_large(database)
    else:
        _seed_life_tables(database, state["tables"])
        _seed_source_summary(database, state_id, state["source_summary"])

    counts = _declared_counts(database, contract["expected_table_counts"])
    if counts != contract["expected_table_counts"]:
        raise ValueError(f"materialized table counts differ for {state_id}")
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if integrity != [("ok",)] or foreign_keys or revision != ("0009_goal_persistence",):
        raise ValueError(f"materialized database health differs for {state_id}")
    return {
        "state": state_id,
        "revision": revision[0],
        "table_counts": counts,
        "integrity": "ok",
        "foreign_keys": "ok",
    }


def _seed_partial(database: Path) -> None:
    with _session(database) as session:
        artifact, accounts = _accounts(session, "partial")
        session.add_all(
            [
                _transaction(
                    accounts[0], artifact, date(2026, 1, 15), "100.00", "external_inflow", 1
                ),
                _transaction(
                    accounts[0], artifact, date(2026, 3, 10), "-40.00", "external_outflow", 2
                ),
            ]
        )
        session.commit()


def _seed_complete(database: Path, *, stale: bool) -> None:
    evidence_date = date(2026, 6, 30) if stale else date(2026, 8, 10)
    with _session(database) as session:
        artifact, accounts = _accounts(session, "complete")
        rows = [
            ("2100.00", "external_inflow"),
            ("2100.00", "external_inflow"),
            ("-1950.00", "external_outflow"),
            ("-1950.00", "external_outflow"),
            ("-500.00", "internal_transfer"),
            ("500.00", "internal_transfer"),
        ]
        for index, (amount, role) in enumerate(rows, 1):
            session.add(
                _transaction(
                    accounts[0 if index != 6 else 1],
                    artifact,
                    evidence_date - timedelta(days=6 - index),
                    amount,
                    role,
                    index,
                )
            )
        session.add_all(
            [
                BalanceSnapshot(
                    account_id=accounts[0].id,
                    artifact_id=artifact.id,
                    snapshot_date=evidence_date,
                    kind="current",
                    amount=Decimal("3200.00"),
                ),
                BalanceSnapshot(
                    account_id=accounts[1].id,
                    artifact_id=artifact.id,
                    snapshot_date=evidence_date,
                    kind="current",
                    amount=Decimal("3000.00"),
                ),
                BalanceSnapshot(
                    account_id=accounts[2].id,
                    artifact_id=artifact.id,
                    snapshot_date=evidence_date,
                    kind="current",
                    amount=Decimal("19400.00"),
                ),
            ]
        )
        payment_dates = (
            (date(2026, 6, 16), date(2026, 6, 30))
            if stale
            else (date(2026, 7, 24), date(2026, 8, 7))
        )
        for index, payment_date in enumerate(payment_dates, 1):
            session.add(_payroll(index, payment_date, "3000.00", "2100.00"))
        profile = _profile()
        session.add(profile)
        session.flush()
        life_goal = _life_goal(profile.id)
        session.add(life_goal)
        session.flush()
        session.add(_goal_program(life_goal.id))
        session.commit()


def _seed_large(database: Path) -> None:
    history_end = date(2026, 8, 10)
    with _session(database) as session:
        bank = Institution(canonical_name="Invented Large History Bank", kind="bank")
        brokerage = Institution(
            canonical_name="Invented Large History Brokerage", kind="investment"
        )
        session.add_all([bank, brokerage])
        session.flush()
        accounts = [
            Account(
                institution_id=bank.id,
                external_key="large-checking",
                display_name="Invented Large Checking",
                account_type="checking",
            ),
            Account(
                institution_id=bank.id,
                external_key="large-savings",
                display_name="Invented Large Savings",
                account_type="savings",
            ),
            Account(
                institution_id=brokerage.id,
                external_key="large-investment",
                display_name="Invented Large Investment",
                account_type="brokerage",
            ),
        ]
        session.add_all(accounts)
        session.flush()
        artifacts: list[ImportArtifact] = []
        for month_index in range(32):
            batch = ImportBatch(
                created_at=REFERENCE + timedelta(seconds=month_index),
                status="complete",
                requested_source="synthetic_large_history",
                artifact_count=1,
                imported_count=30,
            )
            session.add(batch)
            session.flush()
            artifact = ImportArtifact(
                batch_id=batch.id,
                sha256=hashlib.sha256(f"large-artifact-{month_index}".encode()).hexdigest(),
                original_filename=f"invented-large-{month_index:02d}.csv",
                source_kind="synthetic",
                adapter="synthetic_large_history",
                parser_version="test-v1",
                imported_at=REFERENCE + timedelta(seconds=month_index),
            )
            session.add(artifact)
            session.flush()
            artifacts.append(artifact)
            year = 2024 + month_index // 12
            month = month_index % 12 + 1
            if month > 12:
                year += 1
                month -= 12
            for row_index in range(30):
                if row_index < 15:
                    amount, role = "280.00", "external_inflow"
                elif row_index < 29:
                    amount, role = "-200.00", "external_outflow"
                else:
                    amount, role = "-300.00", "external_outflow"
                day = min(row_index + 1, calendar.monthrange(year, month)[1])
                posted_date = min(date(year, month, day), history_end)
                session.add(
                    _transaction(accounts[0], artifact, posted_date, amount, role, row_index + 1)
                )
            snapshot_date = min(date(year, month, calendar.monthrange(year, month)[1]), history_end)
            final = month_index == 31
            snapshot_amounts = (
                ("16000.00", "16000.00", "92000.00")
                if final
                else (
                    f"{5000 + month_index * 300}.00",
                    f"{4000 + month_index * 200}.00",
                    f"{30000 + month_index * 1000}.00",
                )
            )
            for account, amount in zip(accounts, snapshot_amounts, strict=True):
                session.add(
                    BalanceSnapshot(
                        account_id=account.id,
                        artifact_id=artifact.id,
                        snapshot_date=snapshot_date,
                        kind="closing",
                        amount=Decimal(amount),
                    )
                )
        first_pay = date(2024, 1, 5)
        for index in range(68):
            session.add(
                _payroll(index + 1, first_pay + timedelta(days=14 * index), "3000.00", "2100.00")
            )
        profile = _profile()
        session.add(profile)
        session.flush()
        life_goal = _life_goal(profile.id)
        session.add(life_goal)
        session.flush()
        session.add(_goal_program(life_goal.id))
        for scenario_index in range(4):
            scenario = LifeScenario(
                profile_id=profile.id,
                name=f"Invented large scenario {scenario_index + 1}",
                target_age=52 + scenario_index,
                path_key="middle",
                input_snapshot={"scenario": scenario_index + 1},
                source_fingerprint=hashlib.sha256(
                    f"large-scenario-{scenario_index}".encode()
                ).hexdigest(),
                engine_version="life-lab-v0.3.0",
                assumption_version="life-lab-drive-paths-v3",
                benchmark_version="synthetic-benchmark-v1",
                status="works",
                warnings=[],
                summary={"ending_cash": "1000.00"},
                created_at=REFERENCE + timedelta(seconds=100 + scenario_index),
            )
            session.add(scenario)
            session.flush()
            for month_index in range(96):
                year = 2026 + month_index // 12
                month = month_index % 12 + 1
                session.add(
                    LifeProjectionPeriod(
                        scenario_id=scenario.id,
                        month=date(year, month, 1),
                        age_months=412 + month_index,
                        working=True,
                        gross_income=Decimal("5200.00"),
                        net_income=Decimal("4200.00"),
                        employee_retirement=Decimal("300.00"),
                        employer_retirement=Decimal("180.00"),
                        stock_plan=Decimal("100.00"),
                        essential_spend=Decimal("2300.00"),
                        flexible_spend=Decimal("800.00"),
                        goal_spend=Decimal("0.00"),
                        cash=Decimal("32000.00"),
                        accessible_investments=Decimal("24000.00"),
                        pretax_retirement=Decimal("68000.00"),
                        hsa=Decimal("0.00"),
                        restricted_assets=Decimal("0.00"),
                        debt=Decimal("4000.00"),
                        investment_result=Decimal("100.00"),
                        total_spendable=Decimal("56000.00"),
                    )
                )
        session.commit()


def _accounts(session: Session, suffix: str) -> tuple[ImportArtifact, list[Account]]:
    batch = ImportBatch(
        created_at=REFERENCE,
        status="complete",
        requested_source=f"synthetic_{suffix}",
        artifact_count=1,
    )
    session.add(batch)
    session.flush()
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256=hashlib.sha256(f"artifact-{suffix}".encode()).hexdigest(),
        original_filename=f"invented-{suffix}.csv",
        source_kind="synthetic",
        adapter=f"synthetic_{suffix}",
        parser_version="test-v1",
        imported_at=REFERENCE,
    )
    bank = Institution(canonical_name=f"Invented {suffix.title()} Bank", kind="bank")
    brokerage = Institution(
        canonical_name=f"Invented {suffix.title()} Brokerage", kind="investment"
    )
    session.add_all([artifact, bank, brokerage])
    session.flush()
    accounts = [
        Account(
            institution_id=bank.id,
            external_key=f"{suffix}-checking",
            display_name="Invented Checking",
            account_type="checking",
        ),
        Account(
            institution_id=bank.id,
            external_key=f"{suffix}-savings",
            display_name="Invented Savings",
            account_type="savings",
        ),
        Account(
            institution_id=brokerage.id,
            external_key=f"{suffix}-investment",
            display_name="Invented Investment",
            account_type="brokerage",
        ),
    ]
    session.add_all(accounts)
    session.flush()
    return artifact, accounts


def _transaction(
    account: Account,
    artifact: ImportArtifact,
    posted: date,
    amount: str,
    role: str,
    source_row: int,
) -> AccountTransaction:
    return AccountTransaction(
        account_id=account.id,
        artifact_id=artifact.id,
        posted_date=posted,
        original_description=f"Invented {role} {source_row}",
        role=role,
        amount=Decimal(amount),
        source_row=source_row,
    )


def _payroll(index: int, payment_date: date, gross: str, net: str) -> PayrollScheduleEntry:
    return PayrollScheduleEntry(
        payment_date=payment_date,
        observed_deposit_date=payment_date,
        period_start=payment_date - timedelta(days=13),
        period_end=payment_date,
        payroll_year=payment_date.year,
        payroll_index=index,
        source_kind="calculated",
        calculation_version="completed-payroll-v1",
        employer="Invented Employer",
        job_title="Invented Engineer",
        base_salary=Decimal("78000.00"),
        gross_earnings=Decimal(gross),
        imputed_earnings=Decimal("0.00"),
        pretax_deductions=Decimal("0.00"),
        tax_withholdings=Decimal(gross) - Decimal(net),
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
        fingerprint=hashlib.sha256(f"payroll-{index}-{payment_date}".encode()).hexdigest(),
        created_at=REFERENCE + timedelta(seconds=200 + index),
        updated_at=REFERENCE + timedelta(seconds=200 + index),
    )


def _profile() -> LifePlanProfile:
    return LifePlanProfile(
        birth_date=date(1992, 4, 12),
        state="OR",
        end_age=94,
        current_monthly_outflow=Decimal("3900.00"),
        essential_monthly_spend=Decimal("3000.00"),
        flexible_monthly_spend=Decimal("900.00"),
        cash_floor=Decimal("3000.00"),
        retirement_tax_rate_pct=Decimal("18.0000"),
        target_ages=[52, 61],
        notes="Invented complete-current profile",
        created_at=REFERENCE,
        updated_at=REFERENCE,
    )


def _life_goal(profile_id: int) -> LifeGoal:
    return LifeGoal(
        profile_id=profile_id,
        name="Invented Harbor Studio",
        target_date=date(2030, 8, 10),
        target_amount=Decimal("12000.00"),
        reserved_amount=Decimal("1500.00"),
        annual_cost=Decimal("0.00"),
        priority="required",
        enabled=True,
        notes="Invented complete-current goal",
        created_at=REFERENCE,
        updated_at=REFERENCE,
    )


def _goal_program(source_life_goal_id: int) -> GoalProgram:
    provenance = {
        field: {"evidence": "user_entered", "source_refs": [f"synthetic:complete:{field}"]}
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
    return GoalProgram(
        public_key="goal_harbor_studio",
        source_life_goal_id=source_life_goal_id,
        name="Invented Harbor Studio",
        target_date=date(2030, 8, 10),
        target_amount=Decimal("12000.00"),
        protected_cash_floor=Decimal("3000.00"),
        reserved_amount=Decimal("1500.00"),
        is_primary=True,
        status="active",
        tracking_mode="explicit_reservation",
        reservation_policy="exclusive_primary_goal",
        field_provenance=provenance,
        contract_version="money-map-v2-contract-v1",
        migration_version="0009_goal_persistence",
        created_at=REFERENCE,
        updated_at=REFERENCE,
    )


def _seed_life_tables(database: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table_name in (
            "life_plan_profiles",
            "life_goals",
            "life_scenarios",
            "life_projection_periods",
        ):
            for row in tables[table_name]:
                columns = list(row)
                values = [
                    json.dumps(value, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list))
                    else int(value)
                    if isinstance(value, bool)
                    else value
                    for value in row.values()
                ]
                placeholders = ", ".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                )
                connection.execute(statement, values)


def _seed_source_summary(database: Path, state_id: str, summary: dict[str, Any]) -> None:
    if state_id == "missing_source_coverage":
        as_of = date.fromisoformat(str(summary["as_of"]))
        with _session(database) as session:
            artifact, accounts = _accounts(session, state_id)
            session.add_all(
                [
                    _transaction(accounts[0], artifact, as_of, "0.00", "interest", 1),
                    BalanceSnapshot(
                        account_id=accounts[2].id,
                        artifact_id=artifact.id,
                        snapshot_date=as_of,
                        kind="current",
                        amount=Decimal(str(summary["retirement_assets"])),
                    ),
                ]
            )
            session.commit()
        return
    if summary.get("coverage") != "complete":
        return
    as_of = date.fromisoformat(str(summary["as_of"]))
    money_in = str(summary["effective_monthly_take_home"])
    money_out = str(summary["observed_monthly_outflow"])
    with _session(database) as session:
        artifact, accounts = _accounts(session, state_id)
        session.add_all(
            [
                _transaction(accounts[0], artifact, as_of, money_in, "external_inflow", 1),
                _transaction(accounts[0], artifact, as_of, f"-{money_out}", "external_outflow", 2),
                BalanceSnapshot(
                    account_id=accounts[0].id,
                    artifact_id=artifact.id,
                    snapshot_date=as_of,
                    kind="current",
                    amount=Decimal(str(summary["accessible_cash"])),
                ),
                BalanceSnapshot(
                    account_id=accounts[1].id,
                    artifact_id=artifact.id,
                    snapshot_date=as_of,
                    kind="current",
                    amount=Decimal(str(summary["accessible_investments"])),
                ),
                BalanceSnapshot(
                    account_id=accounts[2].id,
                    artifact_id=artifact.id,
                    snapshot_date=as_of,
                    kind="current",
                    amount=Decimal(str(summary["retirement_assets"])),
                ),
                _payroll(1, as_of, money_in, money_in),
            ]
        )
        session.commit()


def _session(database: Path) -> Session:
    return Session(create_engine(f"sqlite:///{database}"), expire_on_commit=False)


def _declared_counts(database: Path, expected: dict[str, int]) -> dict[str, int]:
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in expected
        }
