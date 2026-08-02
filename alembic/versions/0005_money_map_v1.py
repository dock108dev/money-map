"""Add completed allocations, balance history, and forecast HSA fields.

Revision ID: 0005_money_map_v1
Revises: 0004_completed_payroll_schedule
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_money_map_v1"
down_revision: str | Sequence[str] | None = "0004_completed_payroll_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payroll_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "schedule_entry_id",
            sa.Integer(),
            sa.ForeignKey("payroll_schedule_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=96), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
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
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.UniqueConstraint("schedule_entry_id", "category", name="uq_payroll_allocation_category"),
    )
    op.create_index(
        "ix_payroll_allocations_schedule_entry_id",
        "payroll_allocations",
        ["schedule_entry_id"],
    )
    op.create_index("ix_payroll_allocations_section", "payroll_allocations", ["section"])
    op.create_table(
        "account_balance_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anchor_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("balance_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.UniqueConstraint("account_id", "balance_date", "kind", name="uq_account_balance_point"),
    )
    op.create_index(
        "ix_account_balance_points_account_id", "account_balance_points", ["account_id"]
    )
    op.create_index(
        "ix_account_balance_points_anchor_snapshot_id",
        "account_balance_points",
        ["anchor_snapshot_id"],
    )
    op.create_index(
        "ix_account_balance_points_balance_date", "account_balance_points", ["balance_date"]
    )
    inspector = sa.inspect(op.get_bind())
    bridge_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("investment_value_bridges")
    }
    if "uq_investment_value_bridge" not in bridge_constraints:
        with op.batch_alter_table("investment_value_bridges") as batch:
            batch.create_unique_constraint(
                "uq_investment_value_bridge", ["account_id", "period_start", "period_end"]
            )
    forecast_columns = {column["name"] for column in inspector.get_columns("forecast_periods")}
    with op.batch_alter_table("forecast_periods") as batch:
        if "employee_hsa" not in forecast_columns:
            batch.add_column(
                sa.Column("employee_hsa", sa.Numeric(18, 2), nullable=False, server_default="0")
            )
        if "employer_hsa" not in forecast_columns:
            batch.add_column(
                sa.Column("employer_hsa", sa.Numeric(18, 2), nullable=False, server_default="0")
            )
        if "cash_redirect_to_investments" not in forecast_columns:
            batch.add_column(
                sa.Column(
                    "cash_redirect_to_investments",
                    sa.Numeric(18, 2),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("forecast_periods") as batch:
        batch.drop_column("cash_redirect_to_investments")
        batch.drop_column("employer_hsa")
        batch.drop_column("employee_hsa")
    with op.batch_alter_table("investment_value_bridges") as batch:
        batch.drop_constraint("uq_investment_value_bridge", type_="unique")
    op.drop_index("ix_account_balance_points_balance_date", table_name="account_balance_points")
    op.drop_index(
        "ix_account_balance_points_anchor_snapshot_id", table_name="account_balance_points"
    )
    op.drop_index("ix_account_balance_points_account_id", table_name="account_balance_points")
    op.drop_table("account_balance_points")
    op.drop_index("ix_payroll_allocations_section", table_name="payroll_allocations")
    op.drop_index("ix_payroll_allocations_schedule_entry_id", table_name="payroll_allocations")
    op.drop_table("payroll_allocations")
