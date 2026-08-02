from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..money import money
from .base import Evidence, ParsedPayroll, ParsedPayrollLine, UnsupportedLayoutError

FORMAT = "paycheck-map-payroll-v1"
SUMMARY_FIELDS = (
    "gross_earnings",
    "imputed_earnings",
    "pretax_deductions",
    "tax_withholdings",
    "after_tax_deductions",
    "federal_taxable_gross",
    "net_payment",
)
SUMMARY_LABELS = {
    "gross_earnings": "Gross Earnings",
    "imputed_earnings": "Imputed Earnings",
    "pretax_deductions": "Pretax Deductions",
    "tax_withholdings": "Tax Withholdings",
    "after_tax_deductions": "After-tax Deductions",
    "federal_taxable_gross": "Federal Taxable Gross",
    "net_payment": "Net Payment",
}


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"Canonical payroll field is required: {key}")
    return value


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


class CanonicalPayrollAdapter:
    """Private, redacted JSON contract for user-supplied payroll detail."""

    name = "canonical_payroll"
    parser_version = "1.0.0"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".json"

    def parse(self, path: Path) -> ParsedPayroll:
        raw = json.loads(path.read_text(encoding="utf-8"))
        row = _object(raw, "Canonical payroll document")
        if row.get("format") != FORMAT:
            raise UnsupportedLayoutError(f"JSON is not the supported {FORMAT} format")

        summary = _object(row.get("summary"), "summary")
        current: dict[str, Any] = {}
        ytd: dict[str, str] = {}
        evidence: list[Evidence] = [
            Evidence("period", "period", "Period dates", "canonical_json"),
            Evidence("base_salary", "base_salary", "Base Salary", "canonical_json"),
        ]
        for field in SUMMARY_FIELDS:
            values = _object(summary.get(field), f"summary.{field}")
            current[field] = money(_text(values, "current"))
            ytd[field] = str(money(_text(values, "ytd")))
            evidence.append(
                Evidence(
                    field,
                    f"summary.{field}",
                    SUMMARY_LABELS[field],
                    "canonical_json",
                )
            )

        details: list[ParsedPayrollLine] = []
        raw_details = row.get("details")
        if not isinstance(raw_details, list):
            raise ValueError("details must be a list")
        for index, raw_detail in enumerate(raw_details, start=1):
            detail = _object(raw_detail, f"details[{index}]")
            category = _text(detail, "category")
            if "." not in category:
                raise ValueError(f"details[{index}].category must include its section prefix")
            ytd_value = detail.get("ytd")
            details.append(
                ParsedPayrollLine(
                    category=category,
                    original_label=_text(detail, "label"),
                    amount=money(_text(detail, "current")),
                    ytd_amount=(None if ytd_value in (None, "") else money(str(ytd_value))),
                    reduces_net=bool(detail.get("reduces_net", False)),
                )
            )
            evidence.append(
                Evidence(
                    f"detail.{category}",
                    f"details[{index}]",
                    _text(detail, "label"),
                    "canonical_json",
                )
            )

        detail_complete = bool(row.get("detail_complete"))
        if detail_complete:
            sections = {line.category.split(".", 1)[0] for line in details}
            required_sections = {
                "earnings",
                "imputed",
                "pretax",
                "taxes",
                "after_tax",
                "employer_benefit",
                "net_distribution",
            }
            missing = sorted(required_sections - sections)
            if missing:
                raise ValueError(f"Complete payroll detail is missing sections: {missing}")

        return ParsedPayroll(
            employer=_text(row, "employer"),
            job_title=str(row.get("job_title") or "").strip() or None,
            period_start=date.fromisoformat(_text(row, "period_start")),
            period_end=date.fromisoformat(_text(row, "period_end")),
            payment_date=date.fromisoformat(_text(row, "payment_date")),
            observed_deposit_date=_optional_date(row.get("observed_deposit_date")),
            pay_frequency=_text(row, "pay_frequency").lower(),
            base_salary=money(_text(row, "base_salary")),
            gross_earnings=current["gross_earnings"],
            imputed_earnings=current["imputed_earnings"],
            pretax_deductions=current["pretax_deductions"],
            tax_withholdings=current["tax_withholdings"],
            after_tax_deductions=current["after_tax_deductions"],
            federal_taxable_gross=current["federal_taxable_gross"],
            net_payment=current["net_payment"],
            ytd_values=ytd,
            detail_complete=detail_complete,
            detail_lines=tuple(details),
            evidence=tuple(evidence),
        )
