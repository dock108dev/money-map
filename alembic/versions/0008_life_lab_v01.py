"""Add Life Lab profiles, generic goals, and reproducible projections.

Revision ID: 0008_life_lab_v01
Revises: 0007_refresh_timestamp_integrity
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_life_lab_v01"
down_revision: str | Sequence[str] | None = "0007_refresh_timestamp_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "life_plan_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("end_age", sa.Integer(), nullable=False),
        sa.Column("current_monthly_outflow", sa.Numeric(20, 2), nullable=False),
        sa.Column("essential_monthly_spend", sa.Numeric(20, 2), nullable=False),
        sa.Column("flexible_monthly_spend", sa.Numeric(20, 2), nullable=False),
        sa.Column("cash_floor", sa.Numeric(20, 2), nullable=False),
        sa.Column("retirement_tax_rate_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("target_ages", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "life_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("life_plan_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("annual_cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_life_goals_profile_id", "life_goals", ["profile_id"])
    op.create_index("ix_life_goals_target_date", "life_goals", ["target_date"])
    op.create_table(
        "life_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("life_plan_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_age", sa.Integer(), nullable=False),
        sa.Column("path_key", sa.String(length=32), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("assumption_version", sa.String(length=32), nullable=False),
        sa.Column("benchmark_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_life_scenarios_profile_id", "life_scenarios", ["profile_id"])
    op.create_index(
        "ix_life_scenarios_source_fingerprint", "life_scenarios", ["source_fingerprint"]
    )
    op.create_table(
        "life_projection_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Integer(),
            sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("age_months", sa.Integer(), nullable=False),
        sa.Column("working", sa.Boolean(), nullable=False),
        sa.Column("gross_income", sa.Numeric(20, 2), nullable=False),
        sa.Column("net_income", sa.Numeric(20, 2), nullable=False),
        sa.Column("employee_retirement", sa.Numeric(20, 2), nullable=False),
        sa.Column("employer_retirement", sa.Numeric(20, 2), nullable=False),
        sa.Column("stock_plan", sa.Numeric(20, 2), nullable=False),
        sa.Column("essential_spend", sa.Numeric(20, 2), nullable=False),
        sa.Column("flexible_spend", sa.Numeric(20, 2), nullable=False),
        sa.Column("goal_spend", sa.Numeric(20, 2), nullable=False),
        sa.Column("cash", sa.Numeric(20, 2), nullable=False),
        sa.Column("accessible_investments", sa.Numeric(20, 2), nullable=False),
        sa.Column("pretax_retirement", sa.Numeric(20, 2), nullable=False),
        sa.Column("hsa", sa.Numeric(20, 2), nullable=False),
        sa.Column("restricted_assets", sa.Numeric(20, 2), nullable=False),
        sa.Column("debt", sa.Numeric(20, 2), nullable=False),
        sa.Column("investment_result", sa.Numeric(20, 2), nullable=False),
        sa.Column("total_spendable", sa.Numeric(20, 2), nullable=False),
        sa.UniqueConstraint("scenario_id", "month", name="uq_life_scenario_month"),
    )
    op.create_index(
        "ix_life_projection_periods_scenario_id",
        "life_projection_periods",
        ["scenario_id"],
    )
    op.create_index("ix_life_projection_periods_month", "life_projection_periods", ["month"])


def downgrade() -> None:
    op.drop_index("ix_life_projection_periods_month", table_name="life_projection_periods")
    op.drop_index("ix_life_projection_periods_scenario_id", table_name="life_projection_periods")
    op.drop_table("life_projection_periods")
    op.drop_index("ix_life_scenarios_source_fingerprint", table_name="life_scenarios")
    op.drop_index("ix_life_scenarios_profile_id", table_name="life_scenarios")
    op.drop_table("life_scenarios")
    op.drop_index("ix_life_goals_target_date", table_name="life_goals")
    op.drop_index("ix_life_goals_profile_id", table_name="life_goals")
    op.drop_table("life_goals")
    op.drop_table("life_plan_profiles")
