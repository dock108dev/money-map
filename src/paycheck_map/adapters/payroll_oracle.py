from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from ..money import money
from .base import Evidence, ParsedPayroll, UnsupportedLayoutError

SUMMARY_LABELS = {
    "gross_earnings": "Gross Earnings",
    "imputed_earnings": "Imputed Earnings",
    "pretax_deductions": "Pretax Deductions",
    "tax_withholdings": "Tax Withholdings",
    "after_tax_deductions": "After-tax Deductions",
    "federal_taxable_gross": "Federal Taxable Gross",
    "net_payment": "Net Payment",
}


def _decimal(raw: str) -> Decimal:
    return money(raw.replace(",", "").replace("$", ""))


def _date(raw: str) -> date:
    return datetime.strptime(raw, "%d-%b-%Y").date()


class OraclePayslipSummaryAdapter:
    """Adapter for the supplied Oracle/UnitedHealth Group payslip summary capture."""

    name = "oracle_payslip_summary"
    parser_version = "1.0.0"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedPayroll:
        with pdfplumber.open(path) as pdf:
            page_texts = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(page_texts)
        if "Payslip" not in text or "Payroll Relationship Number" not in text:
            raise UnsupportedLayoutError("PDF is not the supported Oracle payslip layout")

        period = re.search(
            r"(Biweekly|Weekly|Monthly|Semimonthly)\s+"
            r"(\d{1,2}-[A-Za-z]{3}-\d{4})\s+"
            r"(\d{1,2}-[A-Za-z]{3}-\d{4})\s+"
            r"(\d{1,2}-[A-Za-z]{3}-\d{4})\s+([\d,.]+)",
            text,
        )
        if period is None:
            raise ValueError("Required pay-period fields were not found")

        values: dict[str, Decimal] = {}
        ytd: dict[str, str] = {}
        evidence: list[Evidence] = [
            Evidence("period", "page 1, pay-period table", "Period Type"),
            Evidence("base_salary", "page 1, pay-period table", "Base Salary"),
        ]
        for field_name, label in SUMMARY_LABELS.items():
            match = re.search(rf"{re.escape(label)}\s+([\d,.]+)\s+([\d,.]+)", text)
            if match is None:
                raise ValueError(f"Required summary field was not found: {label}")
            values[field_name] = _decimal(match.group(1))
            ytd[field_name] = str(_decimal(match.group(2)))
            evidence.append(Evidence(field_name, "page 1, Summary table", label))

        employer_match = re.search(r"Tax Reporting Unit Name\s+([^\n]+)", text, flags=re.IGNORECASE)
        employer = employer_match.group(1).strip() if employer_match else "Employer"

        expected_pages = re.search(r"Page:\s*1\s+of\s+(\d+)", text)
        expected_count = int(expected_pages.group(1)) if expected_pages else len(page_texts)
        detail_complete = len(page_texts) >= expected_count
        warnings: list[str] = []
        if not detail_complete:
            warnings.append("Summary-only payroll source imported as archived baseline history.")

        return ParsedPayroll(
            employer=employer,
            period_start=_date(period.group(2)),
            period_end=_date(period.group(3)),
            payment_date=_date(period.group(4)),
            pay_frequency=period.group(1).lower(),
            base_salary=_decimal(period.group(5)),
            gross_earnings=values["gross_earnings"],
            imputed_earnings=values["imputed_earnings"],
            pretax_deductions=values["pretax_deductions"],
            tax_withholdings=values["tax_withholdings"],
            after_tax_deductions=values["after_tax_deductions"],
            federal_taxable_gross=values["federal_taxable_gross"],
            net_payment=values["net_payment"],
            ytd_values=ytd,
            detail_complete=detail_complete,
            evidence=tuple(evidence),
            warnings=tuple(warnings),
        )
