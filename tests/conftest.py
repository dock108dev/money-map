from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from paycheck_map.config import Settings
from paycheck_map.db import make_engine
from paycheck_map.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_synthetic_payroll(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=(1000, 700))
    lines = [
        "Payslip",
        "Page: 1 of 2",
        "Payroll Relationship Number",
        "Tax Reporting Unit Name",
        "Synthetic Employer, Inc",
        "Period Type Period Start Date Period End Date Payment Date Base Salary",
        "Biweekly 14-Jun-2026 27-Jun-2026 3-Jul-2026 190,000.00",
        "Summary",
        "Gross Earnings 7,321.31 122,106.56",
        "Imputed Earnings 13.62 1,107.51",
        "Pretax Deductions 570.00 8,559.99",
        "Tax Withholdings 2,241.09 38,494.95",
        "After-tax Deductions 730.77 14,495.69",
        "Federal Taxable Gross 6,751.31 112,629.74",
        "Net Payment 3,765.83 59,448.42",
    ]
    y = 660
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 34
    pdf.save()


def write_synthetic_payroll_detail(path: Path) -> None:
    payload = {
        "format": "paycheck-map-payroll-v1",
        "employer": "Synthetic Employer, Inc",
        "job_title": "Synthetic Reliability Engineer",
        "pay_frequency": "biweekly",
        "period_start": "2026-06-14",
        "period_end": "2026-06-27",
        "payment_date": "2026-07-03",
        "observed_deposit_date": "2026-07-01",
        "base_salary": "190000.00",
        "detail_complete": True,
        "summary": {
            "gross_earnings": {"current": "7321.31", "ytd": "122106.56"},
            "imputed_earnings": {"current": "13.62", "ytd": "1107.51"},
            "pretax_deductions": {"current": "570.00", "ytd": "8559.99"},
            "tax_withholdings": {"current": "2241.09", "ytd": "38494.95"},
            "after_tax_deductions": {"current": "730.77", "ytd": "14495.69"},
            "federal_taxable_gross": {"current": "6751.31", "ytd": "112629.74"},
            "net_payment": {"current": "3765.83", "ytd": "59448.42"},
        },
        "details": [
            _payroll_detail("earnings.regular_salary", "Regular Salary", "5846.15", "96674.00"),
            _payroll_detail("earnings.pto", "PTO", "1461.54", "10834.46"),
            _payroll_detail("imputed.group_term_life", "GTL Imputed", "13.62", "217.92"),
            _payroll_detail("pretax.dental", "Dental Pretax", "3.62", "57.92", True),
            _payroll_detail(
                "pretax.employee_hsa", "Health Savings Account", "34.61", "553.76", True
            ),
            _payroll_detail("pretax.medical", "Medical Pretax", "90.23", "1443.68", True),
            _payroll_detail("pretax.employee_retirement", "401(k)", "438.46", "7595.35", True),
            _payroll_detail("pretax.vision", "Vision Pretax", "3.08", "49.28", True),
            _payroll_detail("taxes.aggregate", "Tax Withholdings", "2241.09", "42977.12", True),
            _payroll_detail("after_tax.stock_offset", "Stock Offset", "0.00", "5206.40", True),
            _payroll_detail(
                "after_tax.employee_stock_purchase", "Stock Purchase", "730.77", "2192.31", True
            ),
            _payroll_detail("employer_benefit.employer_hsa", "Employer HSA", "19.23", "307.68"),
            _payroll_detail(
                "employer_benefit.employer_retirement", "Employer Match", "255.77", "4430.62"
            ),
            _payroll_detail("net_distribution.sofi", "SoFi ••1206", "1500.00", None),
            _payroll_detail("net_distribution.sofi", "SoFi ••0697", "2265.83", None),
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _payroll_detail(
    category: str,
    label: str,
    current: str,
    ytd: str | None,
    reduces_net: bool = False,
) -> dict[str, str | bool | None]:
    return {
        "category": category,
        "label": label,
        "current": current,
        "ytd": ytd,
        "reduces_net": reduces_net,
    }


@pytest.fixture
def runtime_settings(tmp_path: Path) -> Settings:
    return Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")


@pytest.fixture
def db_engine(runtime_settings: Settings) -> Iterator[Engine]:
    engine = make_engine(runtime_settings)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    with Session(db_engine, expire_on_commit=False) as db_session:
        yield db_session


@pytest.fixture
def populated_inbox(runtime_settings: Settings) -> Path:
    payroll_dir = runtime_settings.inbox_dir / "payroll"
    sofi_dir = runtime_settings.inbox_dir / "sofi"
    fidelity_dir = runtime_settings.inbox_dir / "fidelity"
    for directory in (payroll_dir, sofi_dir, fidelity_dir):
        directory.mkdir(parents=True, exist_ok=True)
    write_synthetic_payroll(payroll_dir / "synthetic-payroll.pdf")
    write_synthetic_payroll_detail(payroll_dir / "zz-synthetic-payroll-detail.json")
    shutil.copy2(
        PROJECT_ROOT / "examples" / "synthetic" / "sofi-ledger.csv",
        sofi_dir / "sofi-ledger.csv",
    )
    shutil.copy2(
        PROJECT_ROOT / "examples" / "synthetic" / "fidelity-ledger.csv",
        fidelity_dir / "fidelity-ledger.csv",
    )
    return runtime_settings.inbox_dir
