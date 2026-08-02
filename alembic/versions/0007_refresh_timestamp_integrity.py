"""Repair and enforce refresh timestamp ordering.

Revision ID: 0007_refresh_timestamp_integrity
Revises: 0006_daily_data_refresh
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_refresh_timestamp_integrity"
down_revision: str | Sequence[str] | None = "0006_daily_data_refresh"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE plaid_sync_runs "
            "SET finished_at = started_at "
            "WHERE finished_at IS NOT NULL AND finished_at < started_at"
        )
    )


def downgrade() -> None:
    # The repaired completion ordering is valid for every earlier schema version.
    pass
