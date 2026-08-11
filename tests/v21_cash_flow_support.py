from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from paycheck_map.models import (
    Account,
    AccountTransaction,
    ImportArtifact,
    ImportBatch,
    Institution,
    PlaidConnection,
    TransferMatch,
)


@dataclass(frozen=True)
class SyntheticCashFlowAccounts:
    artifact: ImportArtifact
    checking: Account
    savings: Account
    investment: Account
    connection: PlaidConnection | None


def synthetic_cash_flow_accounts(
    session: Session,
    *,
    with_connection: bool = False,
    last_synced_at: datetime | None = None,
) -> SyntheticCashFlowAccounts:
    batch = ImportBatch(status="complete", requested_source="synthetic_manual")
    session.add(batch)
    session.flush()
    artifact = ImportArtifact(
        batch_id=batch.id,
        sha256="c" * 64,
        original_filename="invented-cash-flow.csv",
        source_kind="synthetic",
        adapter="synthetic_cash_flow",
        parser_version="test-v1",
    )
    bank = Institution(canonical_name="Juniper Community Bank", kind="bank")
    investment_institution = Institution(
        canonical_name="Harbor Synthetic Investments", kind="investment"
    )
    session.add_all([artifact, bank, investment_institution])
    session.flush()
    connection = None
    if with_connection:
        connection = PlaidConnection(
            environment="sandbox",
            target="synthetic_bank",
            item_id="synthetic-item-not-a-provider-id",
            institution_id="invented-institution",
            institution_name="Juniper Community Bank",
            status="active",
            products=["transactions"],
            last_synced_at=last_synced_at,
        )
        session.add(connection)
        session.flush()
    checking = Account(
        institution_id=bank.id,
        plaid_connection_id=connection.id if connection else None,
        external_key="synthetic-checking",
        display_name="Invented Checking",
        account_type="checking",
    )
    savings = Account(
        institution_id=bank.id,
        plaid_connection_id=connection.id if connection else None,
        external_key="synthetic-savings",
        display_name="Invented Savings",
        account_type="savings",
    )
    investment = Account(
        institution_id=investment_institution.id,
        external_key="synthetic-investment",
        display_name="Invented Investment",
        account_type="brokerage",
    )
    session.add_all([checking, savings, investment])
    session.flush()
    return SyntheticCashFlowAccounts(
        artifact=artifact,
        checking=checking,
        savings=savings,
        investment=investment,
        connection=connection,
    )


def synthetic_transaction(
    session: Session,
    accounts: SyntheticCashFlowAccounts,
    *,
    posted_date: date,
    amount: str,
    role: str,
    source_row: int,
    account: Account | None = None,
) -> AccountTransaction:
    row = AccountTransaction(
        account_id=(account or accounts.checking).id,
        artifact_id=accounts.artifact.id,
        posted_date=posted_date,
        original_description=f"Invented {role} {source_row}",
        role=role,
        amount=Decimal(amount),
        source_row=source_row,
    )
    session.add(row)
    session.flush()
    return row


def synthetic_transfer_match(
    session: Session,
    left: AccountTransaction,
    right: AccountTransaction,
) -> TransferMatch:
    match = TransferMatch(
        left_transaction_id=left.id,
        right_transaction_id=right.id,
        amount=abs(left.amount),
        confidence="high",
    )
    session.add(match)
    session.flush()
    return match
