from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.analytics import payroll_allocation_summary
from paycheck_map.models import (
    Account,
    AccountTransaction,
    ImportArtifact,
    ImportBatch,
    Institution,
    PayrollAllocation,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
    PayrollTransactionMatch,
)
from paycheck_map.payroll import (
    MONEY_FIELDS,
    generate_payroll_schedule,
    official_pay_dates,
    schedule_validation,
)
from paycheck_map.reconciliation import reconcile_all
from paycheck_map.services import accounts_dashboard, payroll_history

CHECKPOINTS = [
    (
        "2025-12-19",
        "168260.00",
        ("6485.00", "13.46", "497.61", "1534.12", "647.15", "5987.39", "3792.66"),
        ("195695.70", "704.73", "14049.23", "60255.87", "21496.95", "181646.47", "99188.92"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-01-02",
        "168260.00",
        ("6485.16", "13.62", "519.83", "1957.56", "647.15", "5965.33", "3347.00"),
        ("6485.16", "13.62", "519.83", "1957.56", "647.15", "5965.33", "3347.00"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-02-13",
        "168260.00",
        ("6485.16", "13.62", "519.83", "1957.56", "647.15", "5965.33", "3347.00"),
        ("25940.64", "54.48", "2079.32", "7830.24", "2588.60", "23861.32", "13388.00"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-03-27",
        "170560.00",
        ("6573.62", "13.62", "525.14", "1962.88", "656.00", "6048.48", "3415.98"),
        ("73679.01", "95.34", "4794.29", "24198.34", "9754.15", "68884.72", "34836.89"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-05-22",
        "170560.00",
        ("6573.62", "13.62", "525.14", "1962.88", "656.00", "6048.48", "3415.98"),
        ("99973.49", "149.82", "6894.85", "32049.88", "12378.15", "93078.64", "48500.79"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-06-05",
        "170560.00",
        ("6573.62", "13.62", "525.14", "1962.89", "656.00", "6048.48", "3415.97"),
        ("106547.11", "163.44", "7419.99", "34012.77", "13034.15", "99127.12", "51916.76"),
        "Lead DevOps Engineer",
    ),
    (
        "2026-07-03",
        "190000.00",
        ("7321.31", "13.62", "570.00", "2241.09", "730.77", "6751.31", "3765.83"),
        ("122106.56", "1107.51", "8559.99", "38494.95", "14495.69", "112629.74", "59448.42"),
        "Principal Site Reliability Engineer",
    ),
    (
        "2026-07-31",
        "190000.00",
        ("7321.31", "13.62", "570.00", "2241.09", "730.77", "6751.31", "3765.83"),
        ("136749.18", "1134.75", "9699.99", "42977.12", "15957.23", "126132.36", "66980.09"),
        "Principal Site Reliability Engineer",
    ),
]


def _add_complete_checkpoints(session: Session) -> list[PayrollStatement]:
    batch = ImportBatch(status="complete", requested_source="synthetic")
    session.add(batch)
    session.flush()
    statements = []
    for index, (day, salary, current, ytd, title) in enumerate(CHECKPOINTS, start=1):
        payment_date = date.fromisoformat(day)
        artifact = ImportArtifact(
            batch_id=batch.id,
            sha256=f"{index:064x}",
            original_filename=f"checkpoint-{day}.json",
            source_kind="payroll",
            adapter="synthetic",
            parser_version="test-v1",
        )
        session.add(artifact)
        session.flush()
        values = dict(zip(MONEY_FIELDS, current, strict=True))
        statement = PayrollStatement(
            artifact_id=artifact.id,
            employer="Synthetic Employer, Inc",
            job_title=title,
            period_start=payment_date - timedelta(days=19),
            period_end=payment_date - timedelta(days=6),
            payment_date=payment_date,
            observed_deposit_date=(
                date(2026, 7, 29) if payment_date == date(2026, 7, 31) else None
            ),
            pay_frequency="biweekly",
            base_salary=Decimal(salary),
            detail_complete=payment_date
            in {
                date(2025, 12, 19),
                date(2026, 6, 5),
                date(2026, 7, 31),
            },
            ytd_values=dict(zip(MONEY_FIELDS, ytd, strict=True)),
            **{name: Decimal(value) for name, value in values.items()},
        )
        session.add(statement)
        session.flush()
        if payment_date == date(2025, 12, 19):
            session.add_all(
                [
                    PayrollLineItem(
                        statement_id=statement.id,
                        category="net_distribution.legacy_provident",
                        original_label="Provident ••3055",
                        amount=Decimal("300.00"),
                        ytd_amount=None,
                        reduces_net=False,
                    ),
                    PayrollLineItem(
                        statement_id=statement.id,
                        category="net_distribution.sofi",
                        original_label="SoFi ••1206",
                        amount=Decimal("3492.66"),
                        ytd_amount=None,
                        reduces_net=False,
                    ),
                ]
            )
        statements.append(statement)
    session.flush()
    return statements


def test_schedule_dates_and_exact_completed_totals(session: Session) -> None:
    _add_complete_checkpoints(session)
    result = generate_payroll_schedule(session)
    session.flush()

    assert result["rows"] == 42
    assert result["statement_rows"] == 8
    assert result["calculated_rows"] == 34
    rows = list(
        session.scalars(select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.payment_date))
    )
    assert [row.payment_date for row in rows] == official_pay_dates()
    assert rows[0].observed_deposit_date == date(2025, 1, 1)
    assert rows[-1].observed_deposit_date == date(2026, 7, 29)
    assert rows[26].payment_date == date(2026, 1, 2)
    assert rows[26].observed_deposit_date == date(2025, 12, 31)
    assert sum(row.payroll_year == 2025 for row in rows) == 26
    assert sum(row.payroll_year == 2026 for row in rows) == 16
    assert sum((row.gross_earnings for row in rows), Decimal("0")) == Decimal("332444.88")
    assert sum((row.tax_withholdings for row in rows), Decimal("0")) == Decimal("103232.99")
    assert sum((row.net_payment for row in rows), Decimal("0")) == Decimal("166169.01")
    assert all(check["status"] == "reconciled" for check in schedule_validation(session))
    allocations = list(session.scalars(select(PayrollAllocation)))
    assert allocations
    for row in rows:
        per_section = {
            section: sum(
                (
                    allocation.amount
                    for allocation in allocations
                    if allocation.schedule_entry_id == row.id and allocation.section == section
                ),
                Decimal("0"),
            )
            for section in ("compensation", "pretax", "tax", "after_tax", "net")
        }
        assert per_section == {
            "compensation": row.gross_earnings,
            "pretax": row.pretax_deductions,
            "tax": row.tax_withholdings,
            "after_tax": row.after_tax_deductions,
            "net": row.net_payment,
        }


def test_checkpoints_are_immutable_and_residuals_are_separate(session: Session) -> None:
    statements = _add_complete_checkpoints(session)
    original = {
        statement.id: tuple(getattr(statement, name) for name in MONEY_FIELDS)
        for statement in statements
    }
    generate_payroll_schedule(session)
    session.flush()

    assert {
        statement.id: tuple(getattr(statement, name) for name in MONEY_FIELDS)
        for statement in statements
    } == original
    variable = session.scalar(
        select(PayrollScheduleEntry).where(PayrollScheduleEntry.payment_date == date(2026, 3, 13))
    )
    assert variable is not None
    assert variable.gross_adjustment == Decimal("28017.51")
    assert variable.net_adjustment == Decimal("11200.95")
    current = session.scalar(
        select(PayrollScheduleEntry).where(PayrollScheduleEntry.payment_date == date(2026, 7, 31))
    )
    assert current is not None
    assert current.source_kind == "statement"
    assert current.net_payment == Decimal("3765.83")
    assert current.net_adjustment == Decimal("0.00")


def test_generation_is_idempotent_and_uses_integer_cents(session: Session) -> None:
    _add_complete_checkpoints(session)
    first = generate_payroll_schedule(session)
    session.flush()
    ids = list(session.scalars(select(PayrollScheduleEntry.id).order_by(PayrollScheduleEntry.id)))
    first_fingerprints = first["fingerprints"]
    second = generate_payroll_schedule(session)
    session.flush()
    assert second["fingerprints"] == first_fingerprints
    assert (
        list(session.scalars(select(PayrollScheduleEntry.id).order_by(PayrollScheduleEntry.id)))
        == ids
    )
    for value in session.scalars(select(PayrollScheduleEntry.net_payment)):
        assert value == value.quantize(Decimal("0.01"))


def test_date_ranges_and_normalized_deposit_splits(session: Session) -> None:
    _add_complete_checkpoints(session)
    generate_payroll_schedule(session)
    session.flush()
    full = payroll_history(session)
    assert full["count"] == 42
    assert full["totals"]["gross_compensation"] == "332444.88"
    assert full["totals"]["tax_withholdings"] == "103232.99"
    assert full["totals"]["net_payments"] == "166169.01"
    single = payroll_history(session, date(2026, 7, 29), date(2026, 7, 29))
    assert single["count"] == 1
    assert single["rows"][0]["net_payment"] == "3765.83"
    legacy = next(row for row in full["rows"] if row["payment_date"] == date(2025, 12, 19))
    assert {split["institution"] for split in legacy["deposit_splits"]} == {"SoFi"}
    assert legacy["deposit_splits"][0]["account"] == "SoFi legacy ••3055"


def test_payroll_reporting_collapses_to_current_sofi_accounts_and_reconciles_gross(
    session: Session,
) -> None:
    _add_complete_checkpoints(session)
    generate_payroll_schedule(session)
    session.flush()

    summary = payroll_allocation_summary(
        session,
        date(2025, 1, 1),
        date(2026, 7, 29),
    )
    net_destinations = [
        destination for destination in summary["destinations"] if destination["section"] == "net"
    ]
    assert {
        (destination["category"], destination["label"]) for destination in net_destinations
    } == {
        ("net.1206", "SoFi Checking"),
        ("net.0697", "SoFi Savings"),
    }
    assert sum(Decimal(str(destination["amount"])) for destination in net_destinations) == Decimal(
        "166169.01"
    )
    assert summary["reconciliation"] == {
        "gross": "332444.88",
        "accounted_from_gross": "332444.88",
        "residual": "0.00",
        "status": "reconciled",
        "employer_additions": "0.00",
    }


def test_split_plaid_deposits_match_once_without_cashflow_duplication(session: Session) -> None:
    _add_complete_checkpoints(session)
    generate_payroll_schedule(session)
    batch = session.scalar(select(ImportBatch).limit(1))
    assert batch is not None
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256="f" * 64,
        original_filename="plaid-transactions.json",
        source_kind="plaid",
        adapter="synthetic",
        parser_version="test-v1",
    )
    institution = Institution(canonical_name="SoFi", kind="bank")
    session.add_all([artifact, institution])
    session.flush()
    checking = Account(
        institution_id=institution.id,
        external_key="checking",
        display_name="SoFi Checking ••1206",
        account_type="checking",
    )
    savings = Account(
        institution_id=institution.id,
        external_key="savings",
        display_name="SoFi Savings ••0697",
        account_type="savings",
    )
    session.add_all([checking, savings])
    session.flush()
    session.add_all(
        [
            AccountTransaction(
                account_id=checking.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 7, 29),
                original_description="Optum Services",
                role="external_inflow",
                amount=Decimal("1500.00"),
                balance_after=None,
                source_row=1,
            ),
            AccountTransaction(
                account_id=savings.id,
                artifact_id=artifact.id,
                posted_date=date(2026, 7, 29),
                original_description="Optum Services",
                role="external_inflow",
                amount=Decimal("2265.83"),
                balance_after=None,
                source_row=2,
            ),
        ]
    )
    session.flush()
    reconcile_all(session)
    session.flush()

    assert session.scalar(select(func.count(PayrollTransactionMatch.id))) == 2
    current = payroll_history(session, date(2026, 7, 29), date(2026, 7, 29))
    assert current["rows"][0]["plaid_match_status"] == "matched"
    assert sum(
        Decimal(item["amount"]) for item in current["rows"][0]["plaid_transactions"]
    ) == Decimal("3765.83")
    cashflow = accounts_dashboard(session)
    assert cashflow["totals"]["money_in"] == "3765.83"
