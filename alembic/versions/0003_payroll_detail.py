"""Add detailed payroll context.

Revision ID: 0003_payroll_detail
Revises: 0002_plaid_read_only
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0003_payroll_detail"
down_revision: str | Sequence[str] | None = "0002_plaid_read_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns("payroll_statements")
    if "job_title" not in columns:
        op.add_column(
            "payroll_statements",
            sa.Column("job_title", sa.String(length=255), nullable=True),
        )
    if "observed_deposit_date" not in columns:
        op.add_column(
            "payroll_statements",
            sa.Column("observed_deposit_date", sa.Date(), nullable=True),
        )

    # Correct the earlier summary parser's combined job-title/employer field for the
    # already imported Optum statements without introducing any new private data.
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, employer FROM payroll_statements "
            "WHERE employer LIKE :suffix AND job_title IS NULL"
        ),
        {"suffix": "% Optum Services, Inc"},
    ).fetchall()
    employer = "Optum Services, Inc"
    for statement_id, combined in rows:
        title = str(combined)[: -len(employer)].strip()
        connection.execute(
            sa.text(
                "UPDATE payroll_statements "
                "SET employer = :employer, job_title = :title WHERE id = :id"
            ),
            {"employer": employer, "title": title or None, "id": statement_id},
        )


def downgrade() -> None:
    columns = _columns("payroll_statements")
    with op.batch_alter_table("payroll_statements") as batch:
        if "observed_deposit_date" in columns:
            batch.drop_column("observed_deposit_date")
        if "job_title" in columns:
            batch.drop_column("job_title")
