"""Create the local v0.1 accounting schema.

Revision ID: 0001_local_v01
Revises:
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
from paycheck_map.models import Base

revision: str = "0001_local_v01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V01_TABLES = (
    "import_batches",
    "institutions",
    "forecast_assumptions",
    "forecast_scenarios",
    "manual_corrections",
    "import_artifacts",
    "accounts",
    "payroll_statements",
    "source_evidence",
    "balance_snapshots",
    "payroll_line_items",
    "account_transactions",
    "forecast_periods",
    "transfer_matches",
    "external_flows",
    "investment_value_bridges",
    "reconciliation_results",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in V01_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    tables = [Base.metadata.tables[name] for name in reversed(V01_TABLES)]
    Base.metadata.drop_all(bind=op.get_bind(), tables=tables)
