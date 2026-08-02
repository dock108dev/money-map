from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from paycheck_map.adapters.canonical_ledger import (
    CanonicalLedgerAdapter,
    canonical_institution,
)
from paycheck_map.adapters.canonical_payroll import CanonicalPayrollAdapter
from paycheck_map.adapters.payroll_oracle import OraclePayslipSummaryAdapter

from .conftest import (
    PROJECT_ROOT,
    write_synthetic_payroll,
    write_synthetic_payroll_detail,
)


def test_oracle_summary_parser_reconciles_and_marks_missing_detail(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    write_synthetic_payroll(path)
    parsed = OraclePayslipSummaryAdapter().parse(path)

    assert parsed.payment_date.isoformat() == "2026-07-03"
    assert parsed.base_salary == Decimal("190000.00")
    assert parsed.net_payment == Decimal("3765.83")
    assert parsed.detail_complete is False
    assert parsed.warnings
    assert (
        parsed.gross_earnings
        - (
            parsed.imputed_earnings
            + parsed.pretax_deductions
            + parsed.tax_withholdings
            + parsed.after_tax_deductions
        )
        == parsed.net_payment
    )


def test_canonical_ledger_preserves_roles_and_normalizes_old_sofi_labels() -> None:
    parsed = CanonicalLedgerAdapter().parse(
        PROJECT_ROOT / "examples" / "synthetic" / "sofi-ledger.csv"
    )
    assert {record.institution for record in parsed.records} == {"SoFi"}
    assert sum(record.record_type == "balance" for record in parsed.records) == 4
    assert canonical_institution("Axos") == "SoFi"
    assert canonical_institution("provident") == "SoFi"


def test_canonical_payroll_preserves_detail_and_early_deposit_date(tmp_path: Path) -> None:
    path = tmp_path / "payroll-detail.json"
    write_synthetic_payroll_detail(path)
    parsed = CanonicalPayrollAdapter().parse(path)

    assert parsed.detail_complete
    assert parsed.job_title == "Synthetic Reliability Engineer"
    assert parsed.payment_date.isoformat() == "2026-07-03"
    assert parsed.observed_deposit_date is not None
    assert parsed.observed_deposit_date.isoformat() == "2026-07-01"
    assert sum(
        line.amount for line in parsed.detail_lines if line.category.startswith("pretax.")
    ) == Decimal("570.00")
    assert (
        sum(
            line.amount
            for line in parsed.detail_lines
            if line.category.startswith("net_distribution.")
        )
        == parsed.net_payment
    )


def test_fidelity_ledger_keeps_investment_activity() -> None:
    parsed = CanonicalLedgerAdapter().parse(
        PROJECT_ROOT / "examples" / "synthetic" / "fidelity-ledger.csv"
    )
    roles = {record.role for record in parsed.records}
    assert {"employee_contribution", "employer_contribution", "dividend", "reinvestment"} <= roles
