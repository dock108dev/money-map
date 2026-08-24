from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountTransaction,
    ImportArtifact,
    Institution,
    PayrollAllocation,
    PayrollLineItem,
    PayrollScheduleEntry,
    PayrollStatement,
    PayrollTransactionMatch,
    ReconciliationResult,
    SourceEvidence,
)
from .money import ZERO, money
from .payroll import (
    RECEIVED_END,
    RECEIVED_START,
    checkpoint_artifact_hash,
    schedule_validation,
)
from .service_common import amount


def payroll_history(
    session: Session,
    start_date: date = RECEIVED_START,
    end_date: date = RECEIVED_END,
) -> dict[str, Any]:
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")
    rows = list(
        session.scalars(
            select(PayrollScheduleEntry)
            .where(
                PayrollScheduleEntry.observed_deposit_date >= start_date,
                PayrollScheduleEntry.observed_deposit_date <= end_date,
            )
            .order_by(PayrollScheduleEntry.observed_deposit_date.desc())
        )
    )
    allocations_by_entry: dict[int, list[PayrollAllocation]] = defaultdict(list)
    for allocation in session.scalars(
        select(PayrollAllocation).where(
            PayrollAllocation.schedule_entry_id.in_([row.id for row in rows])
        )
    ):
        allocations_by_entry[allocation.schedule_entry_id].append(allocation)
    matches_by_entry: dict[int, list[dict[str, Any]]] = defaultdict(list)
    matches = list(
        session.scalars(select(PayrollTransactionMatch).order_by(PayrollTransactionMatch.id))
    )
    for match in matches:
        transaction = session.get(AccountTransaction, match.transaction_id)
        account = session.get(Account, transaction.account_id) if transaction else None
        institution = session.get(Institution, account.institution_id) if account else None
        matches_by_entry[match.schedule_entry_id].append(
            {
                "transaction_id": match.transaction_id,
                "date": transaction.posted_date if transaction else None,
                "amount": amount(match.amount),
                "account": account.display_name if account else "Unknown account",
                "institution": institution.canonical_name if institution else "Unknown",
                "description": transaction.original_description if transaction else "",
            }
        )

    def account_values(row: PayrollScheduleEntry) -> dict[str, Decimal]:
        allocations = allocations_by_entry.get(row.id, [])

        def total(category: str) -> Decimal:
            return money(
                sum((item.amount for item in allocations if item.category == category), ZERO)
            )

        retirement = total("pretax.employee_retirement")
        hsa = total("pretax.employee_hsa")
        stock = total("after_tax.employee_stock_purchase")
        employer_retirement = total("employer_benefit.employer_retirement")
        employer_hsa = total("employer_benefit.employer_hsa")
        employee_funding = money(retirement + hsa + stock)
        employer_funding = money(employer_retirement + employer_hsa)
        accessible_value = money(row.net_payment + stock)
        locked_funding = money(retirement + hsa + employer_funding)
        return {
            "employee_retirement": retirement,
            "employee_hsa": hsa,
            "employee_stock_purchase": stock,
            "employee_account_funding": employee_funding,
            "employer_retirement": employer_retirement,
            "employer_hsa": employer_hsa,
            "employer_account_funding": employer_funding,
            "employee_owned_value": money(row.net_payment + employee_funding),
            "accessible_value_before_spending": accessible_value,
            "locked_account_funding": locked_funding,
            "total_paycheck_value": money(row.net_payment + employee_funding + employer_funding),
        }

    def row_payload(row: PayrollScheduleEntry) -> dict[str, Any]:
        adjustments = {
            "variable_compensation": amount(row.gross_adjustment),
            "imputed_income": amount(row.imputed_adjustment),
            "pretax": amount(row.pretax_adjustment),
            "tax": amount(row.tax_adjustment),
            "after_tax": amount(row.after_tax_adjustment),
            "federal_taxable": amount(row.federal_taxable_adjustment),
            "net_payment": amount(row.net_adjustment),
        }
        linked = matches_by_entry.get(row.id, [])
        values = account_values(row)
        return {
            "id": row.id,
            "payment_date": row.payment_date,
            "observed_deposit_date": row.observed_deposit_date,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "payroll_year": row.payroll_year,
            "payroll_index": row.payroll_index,
            "source_kind": row.source_kind,
            "calculation_version": row.calculation_version,
            "employer": row.employer,
            "job_title": row.job_title,
            "base_salary": amount(row.base_salary),
            "gross_earnings": amount(row.gross_earnings),
            "imputed_earnings": amount(row.imputed_earnings),
            "pretax_deductions": amount(row.pretax_deductions),
            "tax_withholdings": amount(row.tax_withholdings),
            "after_tax_deductions": amount(row.after_tax_deductions),
            "federal_taxable_gross": amount(row.federal_taxable_gross),
            "net_payment": amount(row.net_payment),
            **{key: amount(value) for key, value in values.items()},
            "adjustments": adjustments,
            "has_adjustments": any(
                Decimal(str(value or "0")) != ZERO for value in adjustments.values()
            ),
            "deposit_splits": row.deposit_splits,
            "plaid_match_status": "matched" if linked else "not_available",
            "plaid_transactions": linked,
            "previous_checkpoint_id": row.previous_checkpoint_id,
            "next_checkpoint_id": row.next_checkpoint_id,
            "source_hash": checkpoint_artifact_hash(session, row.payroll_statement_id),
            "fingerprint": row.fingerprint,
            "allocations": [
                {
                    "section": allocation.section,
                    "category": allocation.category,
                    "label": allocation.label,
                    "amount": amount(allocation.amount),
                    "source_kind": allocation.source_kind,
                }
                for allocation in sorted(
                    allocations_by_entry.get(row.id, []),
                    key=lambda item: (item.section, item.category),
                )
            ],
        }

    totals = {
        "gross_compensation": amount(sum((row.gross_earnings for row in rows), ZERO)),
        "imputed_earnings": amount(sum((row.imputed_earnings for row in rows), ZERO)),
        "pretax_deductions": amount(sum((row.pretax_deductions for row in rows), ZERO)),
        "tax_withholdings": amount(sum((row.tax_withholdings for row in rows), ZERO)),
        "after_tax_deductions": amount(sum((row.after_tax_deductions for row in rows), ZERO)),
        "federal_taxable_gross": amount(sum((row.federal_taxable_gross for row in rows), ZERO)),
        "net_payments": amount(sum((row.net_payment for row in rows), ZERO)),
    }
    for key in (
        "employee_retirement",
        "employee_hsa",
        "employee_stock_purchase",
        "employee_account_funding",
        "employer_retirement",
        "employer_hsa",
        "employer_account_funding",
        "employee_owned_value",
        "accessible_value_before_spending",
        "locked_account_funding",
        "total_paycheck_value",
    ):
        totals[key] = amount(sum((account_values(row)[key] for row in rows), ZERO))
    return {
        "period": {"start": start_date, "end": end_date},
        "count": len(rows),
        "statement_count": sum(row.source_kind == "statement" for row in rows),
        "calculated_count": sum(row.source_kind == "calculated" for row in rows),
        "totals": totals,
        "rows": [row_payload(row) for row in rows],
    }


def payroll_entry(session: Session, entry_id: int) -> dict[str, Any] | None:
    row = session.get(PayrollScheduleEntry, entry_id)
    if row is None:
        return None
    history = payroll_history(session, row.observed_deposit_date, row.observed_deposit_date)
    return next((item for item in history["rows"] if item["id"] == entry_id), None)


def payroll_reconciliation(session: Session) -> dict[str, Any]:
    checks = schedule_validation(session)
    return {
        "status": (
            "reconciled"
            if checks and all(check["status"] == "reconciled" for check in checks)
            else "unreconciled"
        ),
        "checks": checks,
    }


def paychecks(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(select(PayrollStatement).order_by(PayrollStatement.payment_date.desc()))
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        results = list(
            session.scalars(
                select(ReconciliationResult).where(
                    ReconciliationResult.entity_type == "payroll_statement",
                    ReconciliationResult.entity_id == str(row.id),
                )
            )
        )
        evidence = list(
            session.scalars(
                select(SourceEvidence)
                .join(ImportArtifact)
                .where(
                    SourceEvidence.entity_type == "payroll_statement",
                    SourceEvidence.entity_id == str(row.id),
                )
            )
        )
        artifact = session.get(ImportArtifact, row.artifact_id)
        lines = list(
            session.scalars(
                select(PayrollLineItem)
                .where(
                    PayrollLineItem.statement_id == row.id,
                    PayrollLineItem.category.contains("."),
                )
                .order_by(PayrollLineItem.id)
            )
        )
        output.append(
            {
                "id": row.id,
                "payment_date": row.payment_date,
                "observed_deposit_date": row.observed_deposit_date,
                "period_start": row.period_start,
                "period_end": row.period_end,
                "employer": row.employer,
                "job_title": row.job_title,
                "base_salary": amount(row.base_salary),
                "gross_earnings": amount(row.gross_earnings),
                "imputed_earnings": amount(row.imputed_earnings),
                "pretax_deductions": amount(row.pretax_deductions),
                "tax_withholdings": amount(row.tax_withholdings),
                "after_tax_deductions": amount(row.after_tax_deductions),
                "federal_taxable_gross": amount(row.federal_taxable_gross),
                "net_payment": amount(row.net_payment),
                "detail_complete": row.detail_complete,
                "details": [
                    {
                        "section": line.category.split(".", 1)[0],
                        "category": line.category.split(".", 1)[1],
                        "label": line.original_label,
                        "amount": amount(line.amount),
                        "ytd_amount": amount(line.ytd_amount),
                        "reduces_net": line.reduces_net,
                    }
                    for line in lines
                ],
                "source": {
                    "filename": artifact.original_filename if artifact else "unknown",
                    "hash": artifact.sha256 if artifact else "",
                    "parser_version": artifact.parser_version if artifact else "",
                },
                "evidence": [
                    {
                        "field": item.field_name,
                        "location": item.location,
                        "label": item.original_label,
                        "confidence": item.confidence,
                        "review_status": item.review_status,
                    }
                    for item in evidence
                ],
                "reconciliation": [
                    {
                        "rule": result.rule,
                        "status": result.status,
                        "residual": amount(result.residual),
                        "details": result.details,
                    }
                    for result in results
                ],
            }
        )
    return output
