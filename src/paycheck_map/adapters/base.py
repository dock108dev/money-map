from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol


class UnsupportedLayoutError(ValueError):
    pass


@dataclass(frozen=True)
class Evidence:
    field_name: str
    location: str
    original_label: str
    extraction_method: str = "text"
    confidence: str = "high"


@dataclass(frozen=True)
class ParsedPayrollLine:
    category: str
    original_label: str
    amount: Decimal
    ytd_amount: Decimal | None
    reduces_net: bool


@dataclass(frozen=True)
class ParsedPayroll:
    employer: str
    period_start: date
    period_end: date
    payment_date: date
    pay_frequency: str
    base_salary: Decimal
    gross_earnings: Decimal
    imputed_earnings: Decimal
    pretax_deductions: Decimal
    tax_withholdings: Decimal
    after_tax_deductions: Decimal
    federal_taxable_gross: Decimal
    net_payment: Decimal
    ytd_values: dict[str, str]
    detail_complete: bool
    evidence: tuple[Evidence, ...]
    warnings: tuple[str, ...] = ()
    job_title: str | None = None
    observed_deposit_date: date | None = None
    detail_lines: tuple[ParsedPayrollLine, ...] = ()


@dataclass(frozen=True)
class ParsedRecord:
    institution: str
    account: str
    account_type: str
    record_date: date
    record_type: str
    role: str
    amount: Decimal
    description: str = ""
    balance: Decimal | None = None
    row_number: int = 0


@dataclass(frozen=True)
class ParsedLedger:
    records: tuple[ParsedRecord, ...]
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


class Adapter(Protocol):
    name: str
    parser_version: str

    def supports(self, path: Path) -> bool: ...
