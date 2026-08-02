"""Add local application refresh preferences.

Revision ID: 0006_daily_data_refresh
Revises: 0005_money_map_v1
Create Date: 2026-07-31
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0006_daily_data_refresh"
down_revision: str | Sequence[str] | None = "0005_money_map_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "application_settings",
            sa.column("key", sa.String()),
            sa.column("value", sa.Text()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "key": "plaid.auto_refresh_enabled",
                "value": "true",
                "updated_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("application_settings")
