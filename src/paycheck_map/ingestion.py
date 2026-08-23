from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .adapters.base import ParsedLedger, ParsedPayroll, UnsupportedLayoutError
from .adapters.canonical_ledger import CanonicalLedgerAdapter
from .adapters.canonical_payroll import CanonicalPayrollAdapter
from .adapters.payroll_oracle import OraclePayslipSummaryAdapter
from .config import Settings, settings
from .import_security import SUPPORTED_EXTENSIONS, ImportSecurityError, validate_import
from .models import (
    Account,
    AccountTransaction,
    BalanceSnapshot,
    ForecastScenario,
    ImportArtifact,
    ImportBatch,
    Institution,
    PayrollLineItem,
    PayrollStatement,
    SourceEvidence,
)
from .reconciliation import reconcile_all


@dataclass(frozen=True)
class ImportOutcome:
    batch_id: int
    discovered: int
    imported: int
    duplicates: int
    errors: tuple[dict[str, str], ...]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_files(runtime_settings: Settings) -> list[Path]:
    return sorted(
        path
        for path in runtime_settings.inbox_dir.rglob("*")
        if path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _get_or_create_institution(session: Session, name: str) -> Institution:
    institution = session.scalar(select(Institution).where(Institution.canonical_name == name))
    if institution is None:
        kind = "bank" if name == "SoFi" else "investment" if name == "Fidelity" else "other"
        institution = Institution(canonical_name=name, kind=kind)
        session.add(institution)
        session.flush()
    return institution


def _get_or_create_account(
    session: Session, institution: Institution, key: str, account_type: str
) -> Account:
    account = session.scalar(
        select(Account).where(
            Account.institution_id == institution.id,
            Account.external_key == key,
        )
    )
    if account is None:
        account = Account(
            institution_id=institution.id,
            external_key=key,
            display_name=key,
            account_type=account_type,
        )
        session.add(account)
        session.flush()
    return account


def _store_payroll(
    session: Session, artifact: ImportArtifact, parsed: ParsedPayroll
) -> PayrollStatement:
    statement = session.scalar(
        select(PayrollStatement).where(PayrollStatement.payment_date == parsed.payment_date)
    )
    if statement is not None:
        comparable = {
            "period_start": parsed.period_start,
            "period_end": parsed.period_end,
            "pay_frequency": parsed.pay_frequency,
            "base_salary": parsed.base_salary,
            "gross_earnings": parsed.gross_earnings,
            "imputed_earnings": parsed.imputed_earnings,
            "pretax_deductions": parsed.pretax_deductions,
            "tax_withholdings": parsed.tax_withholdings,
            "after_tax_deductions": parsed.after_tax_deductions,
            "federal_taxable_gross": parsed.federal_taxable_gross,
            "net_payment": parsed.net_payment,
        }
        conflicts = [
            field for field, expected in comparable.items() if getattr(statement, field) != expected
        ]
        if conflicts:
            raise ValueError(
                f"Existing payroll {parsed.payment_date} conflicts in fields: {conflicts}"
            )
        if not parsed.detail_complete:
            raise ValueError(
                f"Payroll {parsed.payment_date} is already imported; new evidence adds no detail"
            )
        statement.artifact_id = artifact.id
        statement.employer = parsed.employer
        statement.job_title = parsed.job_title or statement.job_title
        statement.observed_deposit_date = (
            parsed.observed_deposit_date or statement.observed_deposit_date
        )
        statement.ytd_values = parsed.ytd_values
        statement.detail_complete = True
        session.execute(delete(PayrollLineItem).where(PayrollLineItem.statement_id == statement.id))
        session.execute(
            delete(SourceEvidence).where(
                SourceEvidence.entity_type == "payroll_statement",
                SourceEvidence.entity_id == str(statement.id),
            )
        )
    else:
        statement = PayrollStatement(
            artifact_id=artifact.id,
            employer=parsed.employer,
            job_title=parsed.job_title,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
            payment_date=parsed.payment_date,
            observed_deposit_date=parsed.observed_deposit_date,
            pay_frequency=parsed.pay_frequency,
            base_salary=parsed.base_salary,
            gross_earnings=parsed.gross_earnings,
            imputed_earnings=parsed.imputed_earnings,
            pretax_deductions=parsed.pretax_deductions,
            tax_withholdings=parsed.tax_withholdings,
            after_tax_deductions=parsed.after_tax_deductions,
            federal_taxable_gross=parsed.federal_taxable_gross,
            net_payment=parsed.net_payment,
            ytd_values=parsed.ytd_values,
            detail_complete=parsed.detail_complete,
        )
        session.add(statement)
        session.flush()
    line_values = (
        ("gross_compensation", "Gross Earnings", parsed.gross_earnings, False),
        ("imputed_non_cash", "Imputed Earnings", parsed.imputed_earnings, True),
        ("pretax_aggregate", "Pretax Deductions", parsed.pretax_deductions, True),
        ("taxes_aggregate", "Tax Withholdings", parsed.tax_withholdings, True),
        ("after_tax_aggregate", "After-tax Deductions", parsed.after_tax_deductions, True),
        ("net_payment", "Net Payment", parsed.net_payment, False),
    )
    for category, label, amount, reduces_net in line_values:
        ytd_key = {
            "Gross Earnings": "gross_earnings",
            "Imputed Earnings": "imputed_earnings",
            "Pretax Deductions": "pretax_deductions",
            "Tax Withholdings": "tax_withholdings",
            "After-tax Deductions": "after_tax_deductions",
            "Net Payment": "net_payment",
        }[label]
        statement.lines.append(
            PayrollLineItem(
                category=category,
                original_label=label,
                amount=amount,
                ytd_amount=parsed.ytd_values.get(ytd_key),
                reduces_net=reduces_net,
            )
        )
    for line in parsed.detail_lines:
        statement.lines.append(
            PayrollLineItem(
                category=line.category,
                original_label=line.original_label,
                amount=line.amount,
                ytd_amount=line.ytd_amount,
                reduces_net=line.reduces_net,
            )
        )
    for evidence in parsed.evidence:
        session.add(
            SourceEvidence(
                artifact_id=artifact.id,
                entity_type="payroll_statement",
                entity_id=str(statement.id),
                field_name=evidence.field_name,
                location=evidence.location,
                original_label=evidence.original_label,
                extraction_method=evidence.extraction_method,
                confidence=evidence.confidence,
            )
        )
    return statement


def _store_ledger(session: Session, artifact: ImportArtifact, parsed: ParsedLedger) -> None:
    account_cache: dict[tuple[str, str], Account] = {}
    for record in parsed.records:
        cache_key = (record.institution, record.account)
        account = account_cache.get(cache_key)
        if account is None:
            institution = _get_or_create_institution(session, record.institution)
            account = _get_or_create_account(
                session, institution, record.account, record.account_type
            )
            account_cache[cache_key] = account
        if record.record_type == "balance":
            balance_entity = BalanceSnapshot(
                account_id=account.id,
                artifact_id=artifact.id,
                snapshot_date=record.record_date,
                kind=record.role,
                amount=record.amount,
            )
            session.add(balance_entity)
            session.flush()
            entity_type = "balance_snapshot"
            entity_id = balance_entity.id
        else:
            transaction_entity = AccountTransaction(
                account_id=account.id,
                artifact_id=artifact.id,
                posted_date=record.record_date,
                original_description=record.description,
                role=record.role,
                amount=record.amount,
                balance_after=record.balance,
                source_row=record.row_number,
            )
            session.add(transaction_entity)
            session.flush()
            entity_type = "account_transaction"
            entity_id = transaction_entity.id
        session.add(
            SourceEvidence(
                artifact_id=artifact.id,
                entity_type=entity_type,
                entity_id=str(entity_id),
                field_name="amount",
                location=f"row {record.row_number}",
                original_label=record.role,
                extraction_method=artifact.source_kind,
                confidence="high",
            )
        )


def import_private_inbox(session: Session, runtime_settings: Settings = settings) -> ImportOutcome:
    runtime_settings.ensure_private_dirs()
    paths = _private_files(runtime_settings)
    batch = ImportBatch(artifact_count=len(paths))
    session.add(batch)
    session.flush()
    imported = 0
    duplicates = 0
    errors: list[dict[str, str]] = []

    payroll_adapter = OraclePayslipSummaryAdapter()
    canonical_payroll_adapter = CanonicalPayrollAdapter()
    ledger_adapter = CanonicalLedgerAdapter()
    for path in paths:
        try:
            validate_import(path, approved_root=runtime_settings.inbox_dir)
            sha256 = file_hash(path)
            existing = session.scalar(
                select(ImportArtifact.id).where(ImportArtifact.sha256 == sha256)
            )
            if existing is not None:
                duplicates += 1
                continue
            with session.begin_nested():
                if path.suffix.lower() == ".pdf":
                    parsed_payroll = payroll_adapter.parse(path)
                    artifact = ImportArtifact(
                        batch_id=batch.id,
                        sha256=sha256,
                        original_filename=path.name,
                        source_kind="pdf",
                        adapter=payroll_adapter.name,
                        parser_version=payroll_adapter.parser_version,
                    )
                    session.add(artifact)
                    session.flush()
                    _store_payroll(session, artifact, parsed_payroll)
                elif canonical_payroll_adapter.supports(path):
                    parsed_payroll = canonical_payroll_adapter.parse(path)
                    artifact = ImportArtifact(
                        batch_id=batch.id,
                        sha256=sha256,
                        original_filename=path.name,
                        source_kind="json",
                        adapter=canonical_payroll_adapter.name,
                        parser_version=canonical_payroll_adapter.parser_version,
                    )
                    session.add(artifact)
                    session.flush()
                    _store_payroll(session, artifact, parsed_payroll)
                elif ledger_adapter.supports(path):
                    parsed_ledger = ledger_adapter.parse(path)
                    artifact = ImportArtifact(
                        batch_id=batch.id,
                        sha256=sha256,
                        original_filename=path.name,
                        source_kind=path.suffix.lower().lstrip("."),
                        adapter=ledger_adapter.name,
                        parser_version=ledger_adapter.parser_version,
                    )
                    session.add(artifact)
                    session.flush()
                    _store_ledger(session, artifact, parsed_ledger)
                else:
                    raise UnsupportedLayoutError("No adapter supports this file")
                session.flush()
            imported += 1
        except (ImportSecurityError, ValueError, OSError):
            errors.append(
                {
                    "filename": "rejected import",
                    "message": "This private import was rejected safely.",
                }
            )

    batch.imported_count = imported
    batch.duplicate_count = duplicates
    batch.error_count = len(errors)
    batch.status = "complete_with_errors" if errors else "complete"
    session.flush()
    session.execute(delete(ForecastScenario))
    reconcile_all(session)
    session.commit()
    return ImportOutcome(
        batch_id=batch.id,
        discovered=len(paths),
        imported=imported,
        duplicates=duplicates,
        errors=tuple(errors),
    )


def rollback_import_batch(session: Session, batch_id: int) -> bool:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        return False
    session.delete(batch)
    session.flush()
    session.execute(delete(ForecastScenario))
    reconcile_all(session)
    session.commit()
    return True
