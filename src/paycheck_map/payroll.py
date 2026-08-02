from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    ImportArtifact,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
    PayrollTransactionMatch,
)
from .money import ZERO, money

CALCULATION_VERSION = "payroll-history-v1"
SCHEDULE_ANCHOR = date(2026, 7, 31)
SCOPE_START = date(2025, 1, 3)
SCOPE_END = date(2026, 7, 31)
RECEIVED_START = date(2025, 1, 1)
RECEIVED_END = date(2026, 7, 29)

MONEY_FIELDS = (
    "gross_earnings",
    "imputed_earnings",
    "pretax_deductions",
    "tax_withholdings",
    "after_tax_deductions",
    "federal_taxable_gross",
    "net_payment",
)
ADJUSTMENT_FIELDS = {
    "gross_earnings": "gross_adjustment",
    "imputed_earnings": "imputed_adjustment",
    "pretax_deductions": "pretax_adjustment",
    "tax_withholdings": "tax_adjustment",
    "after_tax_deductions": "after_tax_adjustment",
    "federal_taxable_gross": "federal_taxable_adjustment",
    "net_payment": "net_adjustment",
}


class PayrollCalculationError(ValueError):
    pass


@dataclass
class _Draft:
    payment_date: date
    observed_deposit_date: date
    period_start: date
    period_end: date
    payroll_year: int
    payroll_index: int
    source_kind: str
    statement_id: int | None
    previous_checkpoint_id: int | None
    next_checkpoint_id: int | None
    employer: str
    job_title: str | None
    base_salary: Decimal
    gross_earnings: Decimal
    imputed_earnings: Decimal
    pretax_deductions: Decimal
    tax_withholdings: Decimal
    after_tax_deductions: Decimal
    federal_taxable_gross: Decimal
    net_payment: Decimal
    adjustments: dict[str, Decimal] = field(default_factory=dict)
    deposit_splits: list[dict[str, Any]] = field(default_factory=list)


def official_pay_dates(start: date = SCOPE_START, end: date = SCOPE_END) -> list[date]:
    """Return the Friday schedule anchored to the known 2026-07-31 paycheck."""

    current = SCHEDULE_ANCHOR
    rows: list[date] = []
    while current >= start:
        if current <= end:
            rows.append(current)
        current -= timedelta(days=14)
    return sorted(rows)


def _statement_values(statement: PayrollStatement) -> dict[str, Decimal]:
    return {name: money(getattr(statement, name)) for name in MONEY_FIELDS}


def _salary_for_date(payment_date: date, statements: list[PayrollStatement]) -> Decimal | None:
    salaries = {money(statement.base_salary) for statement in statements}
    if payment_date.year == 2025 and Decimal("168260.00") in salaries:
        return Decimal("168260.00")
    if payment_date.year == 2026:
        if payment_date <= date(2026, 2, 13) and Decimal("168260.00") in salaries:
            return Decimal("168260.00")
        if payment_date <= date(2026, 6, 5) and Decimal("170560.00") in salaries:
            return Decimal("170560.00")
        if payment_date >= date(2026, 6, 19) and Decimal("190000.00") in salaries:
            return Decimal("190000.00")
    return None


def _template_for_date(payment_date: date, statements: list[PayrollStatement]) -> PayrollStatement:
    desired_salary = _salary_for_date(payment_date, statements)
    candidates = [
        statement
        for statement in statements
        if desired_salary is None or money(statement.base_salary) == desired_salary
    ]
    if not candidates:
        candidates = statements
    return min(
        candidates,
        key=lambda statement: (abs((statement.payment_date - payment_date).days), statement.id),
    )


def _normalized_splits(
    session: Session,
    draft: _Draft,
    statement: PayrollStatement | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if statement is not None:
        lines = list(
            session.scalars(
                select(PayrollLineItem)
                .where(
                    PayrollLineItem.statement_id == statement.id,
                    PayrollLineItem.category.like("net_distribution.%"),
                )
                .order_by(PayrollLineItem.id)
            )
        )
        for line in lines:
            suffix = re.search(r"(?:•|X){2,}(\d{4})", line.original_label)
            last4 = suffix.group(1) if suffix else None
            legacy = any(name in line.original_label.lower() for name in ("provident", "axos"))
            account = (
                f"SoFi legacy ••{last4}"
                if legacy and last4
                else line.original_label.replace("PROVIDENT", "SoFi").replace("Provident", "SoFi")
            )
            rows.append(
                {
                    "institution": "SoFi",
                    "account": account,
                    "last4": last4,
                    "amount": f"{money(line.amount):.2f}",
                    "source_kind": "statement",
                }
            )
    if rows:
        return rows
    if draft.base_salary == Decimal("190000.00") and draft.net_payment >= Decimal("1500.00"):
        return [
            {
                "institution": "SoFi",
                "account": "SoFi Checking ••1206",
                "last4": "1206",
                "amount": "1500.00",
                "source_kind": "calculated",
            },
            {
                "institution": "SoFi",
                "account": "SoFi Savings ••0697",
                "last4": "0697",
                "amount": f"{money(draft.net_payment - Decimal('1500.00')):.2f}",
                "source_kind": "calculated",
            },
        ]
    return [
        {
            "institution": "SoFi",
            "account": "SoFi payroll",
            "last4": None,
            "amount": f"{money(draft.net_payment):.2f}",
            "source_kind": "calculated",
        }
    ]


def _fingerprint(draft: _Draft) -> str:
    payload = {
        "calculation_version": CALCULATION_VERSION,
        "payment_date": draft.payment_date.isoformat(),
        "observed_deposit_date": draft.observed_deposit_date.isoformat(),
        "source_kind": draft.source_kind,
        "statement_id": draft.statement_id,
        "previous_checkpoint_id": draft.previous_checkpoint_id,
        "next_checkpoint_id": draft.next_checkpoint_id,
        "employer": draft.employer,
        "job_title": draft.job_title,
        "base_salary": f"{money(draft.base_salary):.2f}",
        **{name: f"{money(getattr(draft, name)):.2f}" for name in MONEY_FIELDS},
        "adjustments": {
            name: f"{money(draft.adjustments.get(name, ZERO)):.2f}"
            for name in ADJUSTMENT_FIELDS.values()
        },
        "deposit_splits": draft.deposit_splits,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _checkpoint_value(statement: PayrollStatement, field_name: str) -> Decimal:
    raw = statement.ytd_values.get(field_name)
    if raw is None:
        raise PayrollCalculationError(
            f"Statement {statement.payment_date} has no {field_name} YTD checkpoint"
        )
    return money(Decimal(str(raw)))


def _build_drafts(session: Session) -> list[_Draft]:
    statements = list(
        session.scalars(
            select(PayrollStatement)
            .where(
                PayrollStatement.payment_date >= SCOPE_START,
                PayrollStatement.payment_date <= SCOPE_END,
            )
            .order_by(PayrollStatement.payment_date, PayrollStatement.id)
        )
    )
    if not statements:
        return []
    by_date = {statement.payment_date: statement for statement in statements}
    years = {statement.payment_date.year for statement in statements}
    latest_by_year = {
        year: max(
            statement.payment_date
            for statement in statements
            if statement.payment_date.year == year
        )
        for year in years
    }
    dates = [
        payment_date
        for payment_date in official_pay_dates()
        if payment_date.year in years and payment_date <= latest_by_year[payment_date.year]
    ]
    indices: dict[int, int] = {}
    drafts: list[_Draft] = []
    for payment_date in dates:
        indices[payment_date.year] = indices.get(payment_date.year, 0) + 1
        statement = by_date.get(payment_date)
        template = statement or _template_for_date(payment_date, statements)
        values = _statement_values(template)
        period_end = payment_date - timedelta(days=6)
        drafts.append(
            _Draft(
                payment_date=payment_date,
                observed_deposit_date=(
                    statement.observed_deposit_date
                    if statement is not None and statement.observed_deposit_date is not None
                    else payment_date - timedelta(days=2)
                ),
                period_start=(
                    statement.period_start
                    if statement is not None
                    else period_end - timedelta(days=13)
                ),
                period_end=statement.period_end if statement is not None else period_end,
                payroll_year=payment_date.year,
                payroll_index=indices[payment_date.year],
                source_kind="statement" if statement is not None else "calculated",
                statement_id=statement.id if statement is not None else None,
                previous_checkpoint_id=None,
                next_checkpoint_id=statement.id if statement is not None else None,
                employer=template.employer,
                job_title=template.job_title,
                base_salary=money(template.base_salary),
                gross_earnings=values["gross_earnings"],
                imputed_earnings=values["imputed_earnings"],
                pretax_deductions=values["pretax_deductions"],
                tax_withholdings=values["tax_withholdings"],
                after_tax_deductions=values["after_tax_deductions"],
                federal_taxable_gross=values["federal_taxable_gross"],
                net_payment=values["net_payment"],
            )
        )

    for year in sorted(years):
        checkpoints = [statement for statement in statements if statement.payment_date.year == year]
        previous_date: date | None = None
        previous_ytd = {name: ZERO for name in MONEY_FIELDS}
        previous_checkpoint_id: int | None = None
        for checkpoint in checkpoints:
            interval = [
                draft
                for draft in drafts
                if draft.payroll_year == year
                and (previous_date is None or draft.payment_date > previous_date)
                and draft.payment_date <= checkpoint.payment_date
            ]
            calculated = [draft for draft in interval if draft.source_kind == "calculated"]
            for draft in calculated:
                draft.previous_checkpoint_id = previous_checkpoint_id
                draft.next_checkpoint_id = checkpoint.id
            for field_name in MONEY_FIELDS:
                checkpoint_ytd = _checkpoint_value(checkpoint, field_name)
                interval_target = money(checkpoint_ytd - previous_ytd[field_name])
                interval_current = money(
                    sum((getattr(draft, field_name) for draft in interval), ZERO)
                )
                residual = money(interval_target - interval_current)
                if residual != ZERO:
                    if not calculated:
                        raise PayrollCalculationError(
                            f"{field_name} cannot reconcile at "
                            f"{checkpoint.payment_date}: {residual}"
                        )
                    target = calculated[-1]
                    setattr(target, field_name, money(getattr(target, field_name) + residual))
                    adjustment_name = ADJUSTMENT_FIELDS[field_name]
                    target.adjustments[adjustment_name] = money(
                        target.adjustments.get(adjustment_name, ZERO) + residual
                    )
                previous_ytd[field_name] = checkpoint_ytd
            previous_date = checkpoint.payment_date
            previous_checkpoint_id = checkpoint.id

    for draft in drafts:
        statement = by_date.get(draft.payment_date)
        draft.deposit_splits = _normalized_splits(session, draft, statement)
        arithmetic = money(
            draft.gross_earnings
            - draft.imputed_earnings
            - draft.pretax_deductions
            - draft.tax_withholdings
            - draft.after_tax_deductions
            - draft.net_payment
        )
        if arithmetic != ZERO:
            raise PayrollCalculationError(
                f"Calculated paycheck {draft.payment_date} has arithmetic residual {arithmetic}"
            )
    return drafts


def generate_payroll_schedule(session: Session) -> dict[str, Any]:
    """Transactionally rebuild calculated rows while preserving imported statements."""

    drafts = _build_drafts(session)
    session.execute(delete(PayrollTransactionMatch))
    existing = {
        row.payment_date: row
        for row in session.scalars(select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.id))
    }
    desired_dates = {draft.payment_date for draft in drafts}
    for payment_date, row in existing.items():
        if payment_date not in desired_dates:
            session.delete(row)
    session.flush()
    for draft in drafts:
        row = existing.get(draft.payment_date) or PayrollScheduleEntry(
            payment_date=draft.payment_date,
            observed_deposit_date=draft.observed_deposit_date,
            period_start=draft.period_start,
            period_end=draft.period_end,
            payroll_year=draft.payroll_year,
            payroll_index=draft.payroll_index,
            source_kind=draft.source_kind,
            calculation_version=CALCULATION_VERSION,
            employer=draft.employer,
            job_title=draft.job_title,
            base_salary=draft.base_salary,
            gross_earnings=draft.gross_earnings,
            imputed_earnings=draft.imputed_earnings,
            pretax_deductions=draft.pretax_deductions,
            tax_withholdings=draft.tax_withholdings,
            after_tax_deductions=draft.after_tax_deductions,
            federal_taxable_gross=draft.federal_taxable_gross,
            net_payment=draft.net_payment,
            fingerprint=_fingerprint(draft),
        )
        row.payroll_statement_id = draft.statement_id
        row.previous_checkpoint_id = draft.previous_checkpoint_id
        row.next_checkpoint_id = draft.next_checkpoint_id
        row.observed_deposit_date = draft.observed_deposit_date
        row.period_start = draft.period_start
        row.period_end = draft.period_end
        row.payroll_year = draft.payroll_year
        row.payroll_index = draft.payroll_index
        row.source_kind = draft.source_kind
        row.calculation_version = CALCULATION_VERSION
        row.employer = draft.employer
        row.job_title = draft.job_title
        row.base_salary = draft.base_salary
        for field_name in MONEY_FIELDS:
            setattr(row, field_name, money(getattr(draft, field_name)))
        for adjustment_name in ADJUSTMENT_FIELDS.values():
            setattr(row, adjustment_name, money(draft.adjustments.get(adjustment_name, ZERO)))
        row.deposit_splits = draft.deposit_splits
        row.fingerprint = _fingerprint(draft)
        session.add(row)
    session.flush()
    from .allocations import generate_payroll_allocations

    allocation_result = generate_payroll_allocations(session)
    return {
        "rows": len(drafts),
        "statement_rows": sum(draft.source_kind == "statement" for draft in drafts),
        "calculated_rows": sum(draft.source_kind == "calculated" for draft in drafts),
        "calculation_version": CALCULATION_VERSION,
        "fingerprints": [
            draft.payment_date.isoformat() + ":" + _fingerprint(draft) for draft in drafts
        ],
        "allocation_rows": allocation_result["rows"],
        "allocation_fingerprints": allocation_result["fingerprints"],
    }


def schedule_validation(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.payment_date))
    )
    checks: list[dict[str, Any]] = []
    cadence_failures = [
        (left.payment_date, right.payment_date)
        for left, right in pairwise(rows)
        if (right.payment_date - left.payment_date).days != 14
    ]
    checks.append(
        {
            "rule": "fourteen_day_cadence",
            "status": "reconciled" if not cadence_failures else "unreconciled",
            "residual": "0.00" if not cadence_failures else str(len(cadence_failures)),
            "details": {"failures": [[str(left), str(right)] for left, right in cadence_failures]},
        }
    )
    for year in sorted({row.payroll_year for row in rows}):
        year_rows = [row for row in rows if row.payroll_year == year]
        expected = [
            payment_date
            for payment_date in official_pay_dates()
            if payment_date.year == year and payment_date <= year_rows[-1].payment_date
        ]
        actual = [row.payment_date for row in year_rows]
        checks.append(
            {
                "rule": f"payroll_year_{year}_coverage",
                "status": "reconciled" if actual == expected else "unreconciled",
                "residual": f"{len(actual) - len(expected):.2f}",
                "details": {"expected": len(expected), "actual": len(actual)},
            }
        )
    arithmetic_failures = []
    for row in rows:
        residual = money(
            row.gross_earnings
            - row.imputed_earnings
            - row.pretax_deductions
            - row.tax_withholdings
            - row.after_tax_deductions
            - row.net_payment
        )
        if residual != ZERO:
            arithmetic_failures.append((row.payment_date, residual))
    checks.append(
        {
            "rule": "calculated_payroll_arithmetic",
            "status": "reconciled" if not arithmetic_failures else "unreconciled",
            "residual": "0.00",
            "details": {
                "failures": [
                    [str(payment_date), f"{residual:.2f}"]
                    for payment_date, residual in arithmetic_failures
                ]
            },
        }
    )
    statements = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date))
    )
    for statement in statements:
        year_rows = [
            row
            for row in rows
            if row.payroll_year == statement.payment_date.year
            and row.payment_date <= statement.payment_date
        ]
        residuals = {
            field_name: money(
                sum((getattr(row, field_name) for row in year_rows), ZERO)
                - _checkpoint_value(statement, field_name)
            )
            for field_name in MONEY_FIELDS
        }
        failed = {name: value for name, value in residuals.items() if value != ZERO}
        checks.append(
            {
                "rule": "checkpoint_ytd",
                "entity_id": str(statement.id),
                "checkpoint": statement.payment_date.isoformat(),
                "status": "reconciled" if not failed else "unreconciled",
                "residual": "0.00" if not failed else f"{sum(map(abs, failed.values()), ZERO):.2f}",
                "details": {name: f"{value:.2f}" for name, value in failed.items()},
            }
        )
    from .allocations import allocation_validation

    checks.extend(allocation_validation(session))
    return checks


def checkpoint_artifact_hash(session: Session, statement_id: int | None) -> str | None:
    if statement_id is None:
        return None
    statement = session.get(PayrollStatement, statement_id)
    artifact = session.get(ImportArtifact, statement.artifact_id) if statement else None
    return artifact.sha256 if artifact else None
