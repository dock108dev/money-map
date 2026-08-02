"""Add deterministic completed payroll history.

Revision ID: 0004_completed_payroll_schedule
Revises: 0003_payroll_detail
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_completed_payroll_schedule"
down_revision: str | Sequence[str] | None = "0003_payroll_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payroll_schedule_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payroll_statement_id",
            sa.Integer(),
            sa.ForeignKey("payroll_statements.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "previous_checkpoint_id",
            sa.Integer(),
            sa.ForeignKey("payroll_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "next_checkpoint_id",
            sa.Integer(),
            sa.ForeignKey("payroll_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payment_date", sa.Date(), nullable=False, unique=True),
        sa.Column("observed_deposit_date", sa.Date(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("payroll_year", sa.Integer(), nullable=False),
        sa.Column("payroll_index", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("employer", sa.String(length=255), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=True),
        sa.Column("base_salary", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_earnings", sa.Numeric(18, 2), nullable=False),
        sa.Column("imputed_earnings", sa.Numeric(18, 2), nullable=False),
        sa.Column("pretax_deductions", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_withholdings", sa.Numeric(18, 2), nullable=False),
        sa.Column("after_tax_deductions", sa.Numeric(18, 2), nullable=False),
        sa.Column("federal_taxable_gross", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_payment", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("imputed_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("pretax_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("after_tax_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "federal_taxable_adjustment",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("net_adjustment", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("deposit_splits", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_payroll_schedule_entries_payment_date",
        "payroll_schedule_entries",
        ["payment_date"],
    )
    op.create_index(
        "ix_payroll_schedule_entries_observed_deposit_date",
        "payroll_schedule_entries",
        ["observed_deposit_date"],
    )
    op.create_index(
        "ix_payroll_schedule_entries_payroll_year",
        "payroll_schedule_entries",
        ["payroll_year"],
    )
    op.create_table(
        "payroll_transaction_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "schedule_entry_id",
            sa.Integer(),
            sa.ForeignKey("payroll_schedule_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("account_transactions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("match_group", sa.String(length=64), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "schedule_entry_id", "transaction_id", name="uq_payroll_transaction_pair"
        ),
    )
    op.create_index(
        "ix_payroll_transaction_matches_schedule_entry_id",
        "payroll_transaction_matches",
        ["schedule_entry_id"],
    )
    op.create_index(
        "ix_payroll_transaction_matches_transaction_id",
        "payroll_transaction_matches",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payroll_transaction_matches_transaction_id",
        table_name="payroll_transaction_matches",
    )
    op.drop_index(
        "ix_payroll_transaction_matches_schedule_entry_id",
        table_name="payroll_transaction_matches",
    )
    op.drop_table("payroll_transaction_matches")
    op.drop_index(
        "ix_payroll_schedule_entries_payroll_year",
        table_name="payroll_schedule_entries",
    )
    op.drop_index(
        "ix_payroll_schedule_entries_observed_deposit_date",
        table_name="payroll_schedule_entries",
    )
    op.drop_index(
        "ix_payroll_schedule_entries_payment_date",
        table_name="payroll_schedule_entries",
    )
    op.drop_table("payroll_schedule_entries")
