"""Add housing planning documents without copying or changing financial records."""

import sqlalchemy as sa

from alembic import op

revision = "0010_housing_plans"
down_revision = "0009_goal_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "housing_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("housing_plans")
