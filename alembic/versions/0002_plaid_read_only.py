"""Add the read-only Plaid connector schema.

Revision ID: 0002_plaid_read_only
Revises: 0001_local_v01
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op
from paycheck_map.models import Base

revision: str = "0002_plaid_read_only"
down_revision: str | Sequence[str] | None = "0001_local_v01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V02_TABLES = (
    "plaid_connections",
    "plaid_link_sessions",
    "plaid_sync_runs",
    "plaid_endpoint_evidence",
    "investment_holdings",
)


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in inspect(op.get_bind()).get_indexes(table)
        if index["name"] is not None
    }


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in V02_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)

    if "plaid_connection_id" not in _columns("accounts"):
        op.add_column("accounts", sa.Column("plaid_connection_id", sa.Integer(), nullable=True))
        with op.batch_alter_table("accounts") as batch:
            batch.create_foreign_key(
                "fk_accounts_plaid_connection",
                "plaid_connections",
                ["plaid_connection_id"],
                ["id"],
                ondelete="CASCADE",
            )
    if "ix_accounts_plaid_connection_id" not in _indexes("accounts"):
        op.create_index(
            "ix_accounts_plaid_connection_id",
            "accounts",
            ["plaid_connection_id"],
            unique=False,
        )

    if "provider_transaction_id" not in _columns("account_transactions"):
        op.add_column(
            "account_transactions",
            sa.Column("provider_transaction_id", sa.String(length=160), nullable=True),
        )
    transaction_indexes = _indexes("account_transactions")
    if "ix_account_transactions_provider_transaction_id" not in transaction_indexes:
        op.create_index(
            "ix_account_transactions_provider_transaction_id",
            "account_transactions",
            ["provider_transaction_id"],
            unique=True,
        )


def downgrade() -> None:
    account_indexes = _indexes("accounts")
    if "ix_accounts_plaid_connection_id" in account_indexes:
        op.drop_index("ix_accounts_plaid_connection_id", table_name="accounts")
    if "plaid_connection_id" in _columns("accounts"):
        with op.batch_alter_table("accounts") as batch:
            batch.drop_column("plaid_connection_id")

    transaction_indexes = _indexes("account_transactions")
    if "ix_account_transactions_provider_transaction_id" in transaction_indexes:
        op.drop_index(
            "ix_account_transactions_provider_transaction_id",
            table_name="account_transactions",
        )
    if "provider_transaction_id" in _columns("account_transactions"):
        with op.batch_alter_table("account_transactions") as batch:
            batch.drop_column("provider_transaction_id")

    tables = [Base.metadata.tables[name] for name in reversed(V02_TABLES)]
    Base.metadata.drop_all(bind=op.get_bind(), tables=tables)
