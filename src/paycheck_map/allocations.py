from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PayrollAllocation, PayrollLineItem, PayrollScheduleEntry, PayrollStatement
from .money import ZERO, money

CALCULATION_VERSION = "payroll-allocation-v1"

SECTION_PREFIXES: dict[str, tuple[str, ...]] = {
    "compensation": ("earnings.", "imputed."),
    "pretax": ("pretax.",),
    "tax": ("taxes.",),
    "after_tax": ("after_tax.",),
    "employer": ("employer_benefit.",),
}

SECTION_TOTAL_FIELD = {
    "compensation": "gross_earnings",
    "pretax": "pretax_deductions",
    "tax": "tax_withholdings",
    "after_tax": "after_tax_deductions",
}

FRIENDLY_LABELS = {
    "pretax.employee_retirement": "Employee 401(k)",
    "pretax.employee_hsa": "Employee HSA",
    "pretax.medical": "Medical",
    "pretax.dental": "Dental",
    "pretax.vision": "Vision",
    "after_tax.employee_stock_purchase": "Employee stock plan",
    "after_tax.stock_offset": "Stock offset",
    "employer_benefit.employer_retirement": "Employer retirement",
    "employer_benefit.employer_hsa": "Employer HSA",
}


class PayrollAllocationError(ValueError):
    pass


class AllocationValues(TypedDict):
    schedule_entry_id: int
    category: str
    label: str
    section: str
    amount: Decimal
    source_kind: str
    previous_checkpoint_id: int | None
    next_checkpoint_id: int | None
    calculation_version: str
    fingerprint: str


def _matches(category: str, prefixes: Iterable[str]) -> bool:
    return any(category.startswith(prefix) for prefix in prefixes)


def _to_cents(value: Decimal) -> int:
    return int(money(value) * 100)


def _from_cents(value: int) -> Decimal:
    return money(Decimal(value) / 100)


def _distribute(total: int, weights: list[int]) -> list[int]:
    """Distribute non-negative integer cents by stable largest remainder."""

    if total < 0:
        raise PayrollAllocationError(f"Cannot distribute a negative allocation: {total}")
    if not weights:
        if total:
            raise PayrollAllocationError("No payroll rows are available for allocation")
        return []
    denominator = sum(weights)
    if denominator <= 0:
        base, remainder = divmod(total, len(weights))
        return [base + (1 if index < remainder else 0) for index in range(len(weights))]
    floors = [(total * weight) // denominator for weight in weights]
    remainder = total - sum(floors)
    ranking = sorted(
        range(len(weights)),
        key=lambda index: ((total * weights[index]) % denominator, -index),
        reverse=True,
    )
    for index in ranking[:remainder]:
        floors[index] += 1
    return floors


def _allocation_matrix(
    row_totals: list[int], column_totals: dict[str, int]
) -> list[dict[str, int]]:
    """Create an exact non-negative matrix with deterministic row and column margins."""

    if any(value < 0 for value in row_totals) or any(value < 0 for value in column_totals.values()):
        raise PayrollAllocationError("Allocation margins cannot be negative")
    if sum(row_totals) != sum(column_totals.values()):
        raise PayrollAllocationError(
            "Allocation margins differ: "
            f"rows={sum(row_totals)} columns={sum(column_totals.values())}"
        )
    matrix: list[defaultdict[str, int]] = [defaultdict(int) for _ in row_totals]
    for category in sorted(column_totals):
        shares = _distribute(column_totals[category], row_totals)
        for index, share in enumerate(shares):
            matrix[index][category] = share

    row_sums = [sum(row.values()) for row in matrix]
    excess = [max(0, row_sums[index] - row_totals[index]) for index in range(len(row_totals))]
    deficit = [max(0, row_totals[index] - row_sums[index]) for index in range(len(row_totals))]
    for source in range(len(row_totals)):
        if not excess[source]:
            continue
        for target in range(len(row_totals)):
            if not excess[source]:
                break
            if not deficit[target]:
                continue
            for category in sorted(column_totals):
                available = matrix[source][category]
                moved = min(excess[source], deficit[target], available)
                if not moved:
                    continue
                matrix[source][category] -= moved
                matrix[target][category] += moved
                excess[source] -= moved
                deficit[target] -= moved
                if not excess[source] or not deficit[target]:
                    break
    if any(excess) or any(deficit):
        raise PayrollAllocationError("Could not balance payroll allocation margins")
    return [dict(row) for row in matrix]


def _label(category: str, observed: dict[str, str]) -> str:
    if category in FRIENDLY_LABELS:
        return FRIENDLY_LABELS[category]
    if category in observed:
        return observed[category]
    suffix = category.split(".", 1)[-1]
    return suffix.replace("_", " ").title()


def _fingerprint(
    row: PayrollScheduleEntry,
    *,
    category: str,
    section: str,
    amount: Decimal,
    source_kind: str,
    previous_checkpoint_id: int | None,
    next_checkpoint_id: int | None,
) -> str:
    payload = {
        "version": CALCULATION_VERSION,
        "schedule": row.fingerprint,
        "category": category,
        "section": section,
        "amount": f"{money(amount):.2f}",
        "source_kind": source_kind,
        "previous_checkpoint_id": previous_checkpoint_id,
        "next_checkpoint_id": next_checkpoint_id,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _line_map(session: Session) -> tuple[dict[int, list[PayrollLineItem]], dict[str, str]]:
    by_statement: dict[int, list[PayrollLineItem]] = defaultdict(list)
    labels: dict[str, str] = {}
    for line in session.scalars(select(PayrollLineItem).order_by(PayrollLineItem.id)):
        by_statement[line.statement_id].append(line)
        labels[line.category] = line.original_label
    return by_statement, labels


def _checkpoint_values(
    lines: list[PayrollLineItem], prefixes: tuple[str, ...], previous: dict[str, Decimal]
) -> dict[str, Decimal]:
    current = dict(previous)
    for line in lines:
        if _matches(line.category, prefixes) and line.ytd_amount is not None:
            current[line.category] = money(line.ytd_amount)
    return current


def _append(
    desired: dict[tuple[int, str], AllocationValues],
    row: PayrollScheduleEntry,
    *,
    category: str,
    label: str,
    section: str,
    amount_value: Decimal,
    source_kind: str,
    previous_checkpoint_id: int | None,
    next_checkpoint_id: int | None,
) -> None:
    value = money(amount_value)
    if value == ZERO:
        return
    desired[(row.id, category)] = {
        "schedule_entry_id": row.id,
        "category": category,
        "label": label,
        "section": section,
        "amount": value,
        "source_kind": source_kind,
        "previous_checkpoint_id": previous_checkpoint_id,
        "next_checkpoint_id": next_checkpoint_id,
        "calculation_version": CALCULATION_VERSION,
        "fingerprint": _fingerprint(
            row,
            category=category,
            section=section,
            amount=value,
            source_kind=source_kind,
            previous_checkpoint_id=previous_checkpoint_id,
            next_checkpoint_id=next_checkpoint_id,
        ),
    }


def generate_payroll_allocations(session: Session) -> dict[str, object]:
    """Build exact category allocations without mutating statement evidence."""

    rows = list(
        session.scalars(select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.payment_date))
    )
    statements = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date))
    )
    lines_by_statement, labels = _line_map(session)
    desired: dict[tuple[int, str], AllocationValues] = {}

    for section, prefixes in SECTION_PREFIXES.items():
        for year in sorted({row.payroll_year for row in rows}):
            year_rows = [row for row in rows if row.payroll_year == year]
            checkpoints = [
                statement
                for statement in statements
                if statement.payment_date.year == year
                and any(
                    _matches(line.category, prefixes) and line.ytd_amount is not None
                    for line in lines_by_statement.get(statement.id, [])
                )
            ]
            previous_date: date | None = None
            previous_values: dict[str, Decimal] = {}
            previous_checkpoint_id: int | None = None
            for checkpoint in checkpoints:
                interval_rows = [
                    row
                    for row in year_rows
                    if (previous_date is None or row.payment_date > previous_date)
                    and row.payment_date <= checkpoint.payment_date
                ]
                current_values = _checkpoint_values(
                    lines_by_statement.get(checkpoint.id, []), prefixes, previous_values
                )
                categories = sorted(set(previous_values) | set(current_values))
                exact_by_row: dict[int, dict[str, Decimal]] = {}
                for row in interval_rows:
                    if row.payroll_statement_id is None:
                        continue
                    exact_lines = [
                        line
                        for line in lines_by_statement.get(row.payroll_statement_id, [])
                        if _matches(line.category, prefixes)
                    ]
                    if not exact_lines:
                        continue
                    exact_by_row[row.id] = {
                        line.category: money(line.amount) for line in exact_lines
                    }
                    for line in exact_lines:
                        _append(
                            desired,
                            row,
                            category=line.category,
                            label=_label(line.category, labels),
                            section=section,
                            amount_value=line.amount,
                            source_kind="statement",
                            previous_checkpoint_id=previous_checkpoint_id,
                            next_checkpoint_id=checkpoint.id,
                        )

                calculated_rows = [row for row in interval_rows if row.id not in exact_by_row]
                column_cents: dict[str, int] = {}
                for category in categories:
                    interval_target = money(
                        current_values.get(category, previous_values.get(category, ZERO))
                        - previous_values.get(category, ZERO)
                    )
                    exact_total = money(
                        sum(
                            (values.get(category, ZERO) for values in exact_by_row.values()),
                            ZERO,
                        )
                    )
                    missing = _to_cents(interval_target - exact_total)
                    if missing < 0:
                        # Some legacy detail enrichments carry a later line-item YTD than the
                        # summary checkpoint they enrich. The immutable current amount is still
                        # useful; the incompatible YTD is not used to manufacture negative rows.
                        missing = 0
                    if missing:
                        column_cents[category] = missing

                if section == "employer":
                    weights = [_to_cents(row.gross_earnings) for row in calculated_rows]
                    for category, total_cents in column_cents.items():
                        for row, allocated in zip(
                            calculated_rows, _distribute(total_cents, weights), strict=True
                        ):
                            _append(
                                desired,
                                row,
                                category=category,
                                label=_label(category, labels),
                                section=section,
                                amount_value=_from_cents(allocated),
                                source_kind="calculated",
                                previous_checkpoint_id=previous_checkpoint_id,
                                next_checkpoint_id=checkpoint.id,
                            )
                else:
                    total_field = SECTION_TOTAL_FIELD[section]
                    row_cents = [_to_cents(getattr(row, total_field)) for row in calculated_rows]
                    residual = sum(row_cents) - sum(column_cents.values())
                    if residual < 0:
                        categories_in_order = sorted(column_cents)
                        scaled = _distribute(
                            sum(row_cents),
                            [column_cents[category] for category in categories_in_order],
                        )
                        column_cents = dict(zip(categories_in_order, scaled, strict=True))
                        residual = 0
                    if residual:
                        column_cents[f"{section}.other"] = residual
                    matrix = _allocation_matrix(row_cents, column_cents)
                    for row, values in zip(calculated_rows, matrix, strict=True):
                        for category, allocated in values.items():
                            _append(
                                desired,
                                row,
                                category=category,
                                label=_label(category, labels),
                                section=section,
                                amount_value=_from_cents(allocated),
                                source_kind="calculated",
                                previous_checkpoint_id=previous_checkpoint_id,
                                next_checkpoint_id=checkpoint.id,
                            )
                previous_values = current_values
                previous_date = checkpoint.payment_date
                previous_checkpoint_id = checkpoint.id

    for row in rows:
        for section, field_name in SECTION_TOTAL_FIELD.items():
            existing_total = money(
                sum(
                    (
                        values["amount"]
                        for (entry_id, _), values in desired.items()
                        if entry_id == row.id and values["section"] == section
                    ),
                    ZERO,
                )
            )
            section_residual = money(getattr(row, field_name) - existing_total)
            if section_residual < ZERO:
                raise PayrollAllocationError(
                    f"{section} allocations exceed paycheck {row.payment_date} "
                    f"by {abs(section_residual)}"
                )
            if section_residual:
                category = f"{section}.other"
                existing_other = desired.get((row.id, category))
                existing_amount = (
                    Decimal(str(existing_other["amount"])) if existing_other is not None else ZERO
                )
                _append(
                    desired,
                    row,
                    category=category,
                    label=_label(category, labels),
                    section=section,
                    amount_value=existing_amount + section_residual,
                    source_kind="calculated",
                    previous_checkpoint_id=row.previous_checkpoint_id,
                    next_checkpoint_id=row.next_checkpoint_id,
                )

    for row in rows:
        for index, split in enumerate(row.deposit_splits):
            split_key = str(split.get("last4") or index)
            _append(
                desired,
                row,
                category=f"net.{split_key}",
                label=str(split.get("account") or "Payroll deposit"),
                section="net",
                amount_value=Decimal(str(split["amount"])),
                source_kind=str(split.get("source_kind") or "calculated"),
                previous_checkpoint_id=row.previous_checkpoint_id,
                next_checkpoint_id=row.next_checkpoint_id,
            )

    existing = {
        (allocation.schedule_entry_id, allocation.category): allocation
        for allocation in session.scalars(select(PayrollAllocation).order_by(PayrollAllocation.id))
    }
    for allocation_key, allocation in existing.items():
        if allocation_key not in desired:
            session.delete(allocation)
    for allocation_key, allocation_values in desired.items():
        allocation = existing.get(allocation_key) or PayrollAllocation(**allocation_values)
        for field_name, value in allocation_values.items():
            setattr(allocation, field_name, value)
        session.add(allocation)
    session.flush()
    return {
        "rows": len(desired),
        "fingerprints": sorted(str(values["fingerprint"]) for values in desired.values()),
    }


def allocation_validation(session: Session) -> list[dict[str, object]]:
    rows = list(
        session.scalars(select(PayrollScheduleEntry).order_by(PayrollScheduleEntry.payment_date))
    )
    checks: list[dict[str, object]] = []
    allocations_by_entry: dict[int, list[PayrollAllocation]] = defaultdict(list)
    for allocation in session.scalars(select(PayrollAllocation)):
        allocations_by_entry[allocation.schedule_entry_id].append(allocation)
    section_fields = {
        "compensation": "gross_earnings",
        "pretax": "pretax_deductions",
        "tax": "tax_withholdings",
        "after_tax": "after_tax_deductions",
        "net": "net_payment",
    }
    for section, field_name in section_fields.items():
        failures: list[list[str]] = []
        for row in rows:
            allocated = money(
                sum(
                    (
                        allocation.amount
                        for allocation in allocations_by_entry.get(row.id, [])
                        if allocation.section == section
                    ),
                    ZERO,
                )
            )
            residual = money(allocated - getattr(row, field_name))
            if residual != ZERO:
                failures.append([row.payment_date.isoformat(), f"{residual:.2f}"])
        checks.append(
            {
                "rule": f"payroll_allocation_{section}",
                "status": "reconciled" if not failures else "unreconciled",
                "residual": "0.00" if not failures else f"{len(failures):.2f}",
                "details": {"failures": failures},
            }
        )
    return checks
