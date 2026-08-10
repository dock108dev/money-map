"""Add independent v2 operational-goal persistence.

Revision ID: 0009_goal_persistence
Revises: 0008_life_lab_v01
Create Date: 2026-08-10
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_goal_persistence"
down_revision: str | Sequence[str] | None = "0008_life_lab_v01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FAILURE_INJECTION_ENV = "PAYCHECK_MAP_MIGRATION_0009_FAIL_AT"


def upgrade() -> None:
    op.create_table(
        "goal_programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "source_life_goal_id",
            sa.Integer(),
            sa.ForeignKey("life_goals.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("protected_cash_floor", sa.Numeric(20, 2), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tracking_mode", sa.String(length=32), nullable=False),
        sa.Column("reservation_policy", sa.String(length=40), nullable=False),
        sa.Column("field_provenance", sa.JSON(), nullable=False),
        sa.Column("contract_version", sa.String(length=40), nullable=False),
        sa.Column("migration_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target_amount >= 0", name="ck_goal_program_target_nonnegative"),
        sa.CheckConstraint("protected_cash_floor >= 0", name="ck_goal_program_floor_nonnegative"),
        sa.CheckConstraint("reserved_amount >= 0", name="ck_goal_program_reserved_nonnegative"),
        sa.CheckConstraint(
            "reserved_amount <= target_amount", name="ck_goal_program_reserved_within_target"
        ),
        sa.CheckConstraint(
            "reservation_policy = 'exclusive_primary_goal'",
            name="ck_goal_program_reservation_policy",
        ),
        sa.CheckConstraint("status IN ('active', 'complete')", name="ck_goal_program_status"),
        sa.CheckConstraint(
            "tracking_mode = 'explicit_reservation'", name="ck_goal_program_tracking_mode"
        ),
        sa.CheckConstraint("json_valid(field_provenance)", name="ck_goal_program_provenance_json"),
    )
    op.create_index(
        "uq_goal_programs_single_primary",
        "goal_programs",
        ["is_primary"],
        unique=True,
        sqlite_where=sa.text("is_primary = 1"),
    )
    op.create_table(
        "goal_check_ins",
        sa.Column("check_in_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "goal_program_id",
            sa.Integer(),
            sa.ForeignKey("goal_programs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("effective_observation_date", sa.Date(), nullable=False),
        sa.Column("accessible_cash", sa.Numeric(20, 2), nullable=True),
        sa.Column("accessible_investments", sa.Numeric(20, 2), nullable=True),
        sa.Column("retirement_assets_excluded", sa.Numeric(20, 2), nullable=True),
        sa.Column("tracked_debt", sa.Numeric(20, 2), nullable=True),
        sa.Column("accessible_now", sa.Numeric(20, 2), nullable=True),
        sa.Column("protected_cash_floor", sa.Numeric(20, 2), nullable=False),
        sa.Column("available_above_floor", sa.Numeric(20, 2), nullable=True),
        sa.Column("reserved_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("goal_target", sa.Numeric(20, 2), nullable=False),
        sa.Column("remaining_target", sa.Numeric(20, 2), nullable=False),
        sa.Column("effective_recurring_take_home", sa.Numeric(20, 2), nullable=True),
        sa.Column("observed_recurring_outflow", sa.Numeric(20, 2), nullable=True),
        sa.Column("recurring_cash_flow_gap", sa.Numeric(20, 2), nullable=True),
        sa.Column("funding_months", sa.Numeric(24, 12), nullable=False),
        sa.Column("pace_status", sa.String(length=16), nullable=False),
        sa.Column("required_funding_pace", sa.Numeric(20, 2), nullable=True),
        sa.Column("position_evidence", sa.JSON(), nullable=False),
        sa.Column("canonical_position_payload", sa.JSON(), nullable=False),
        sa.Column("position_payload_version", sa.String(length=40), nullable=False),
        sa.Column("contract_version", sa.String(length=40), nullable=False),
        sa.Column("calculation_version", sa.String(length=40), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "goal_program_id", "source_fingerprint", name="uq_goal_check_in_program_source"
        ),
        sa.CheckConstraint("length(check_in_id) = 64", name="ck_goal_check_in_id_length"),
        sa.CheckConstraint("check_in_id NOT GLOB '*[^0-9a-f]*'", name="ck_goal_check_in_id_hex"),
        sa.CheckConstraint(
            "length(source_fingerprint) = 64", name="ck_goal_check_in_fingerprint_length"
        ),
        sa.CheckConstraint(
            "source_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_goal_check_in_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "json_valid(position_evidence) AND json_type(position_evidence) = 'object'",
            name="ck_goal_check_in_evidence_json",
        ),
        sa.CheckConstraint(
            "json_valid(canonical_position_payload) "
            "AND json_type(canonical_position_payload) = 'object'",
            name="ck_goal_check_in_payload_json",
        ),
    )
    op.create_index("ix_goal_check_ins_goal_program_id", "goal_check_ins", ["goal_program_id"])
    op.create_table(
        "goal_check_in_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "check_in_id",
            sa.String(length=64),
            sa.ForeignKey("goal_check_ins.check_in_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("component_key", sa.String(length=64), nullable=False),
        sa.Column("component_version", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("evidence_class", sa.String(length=16), nullable=False),
        sa.Column("derivation", sa.String(length=48), nullable=True),
        sa.Column("supporting_source_refs", sa.JSON(), nullable=False),
        sa.UniqueConstraint("check_in_id", "component_key", name="uq_goal_check_in_component_key"),
        sa.CheckConstraint(
            "evidence_class IN ('observed', 'derived', 'user_entered', 'assumed')",
            name="ck_goal_component_evidence_class",
        ),
        sa.CheckConstraint(
            "json_valid(supporting_source_refs) "
            "AND json_type(supporting_source_refs) = 'array' "
            "AND json_array_length(supporting_source_refs) > 0",
            name="ck_goal_component_source_refs_json",
        ),
    )
    op.create_index(
        "ix_goal_check_in_components_check_in_id",
        "goal_check_in_components",
        ["check_in_id"],
    )
    _create_append_only_triggers()
    _inject_failure("after_tables")
    _copy_enabled_goals(fail_during_copy=os.getenv(FAILURE_INJECTION_ENV) == "during_copy")


def _copy_enabled_goals(*, fail_during_copy: bool) -> None:
    limit = " ORDER BY goal.id LIMIT 1" if fail_during_copy else ""
    op.get_bind().exec_driver_sql(
        """
            INSERT INTO goal_programs (
                public_key,
                source_life_goal_id,
                name,
                target_date,
                target_amount,
                protected_cash_floor,
                reserved_amount,
                is_primary,
                status,
                tracking_mode,
                reservation_policy,
                field_provenance,
                contract_version,
                migration_version,
                created_at,
                updated_at
            )
            SELECT
                'goal_life_' || goal.id,
                goal.id,
                goal.name,
                goal.target_date,
                goal.target_amount,
                profile.cash_floor,
                goal.reserved_amount,
                CASE WHEN (
                    SELECT COUNT(*) FROM life_goals AS enabled_goal WHERE enabled_goal.enabled = 1
                ) = 1 THEN 1 ELSE 0 END,
                CASE
                    WHEN goal.reserved_amount >= goal.target_amount THEN 'complete'
                    ELSE 'active'
                END,
                'explicit_reservation',
                'exclusive_primary_goal',
                json_object(
                    'public_key', json_object(
                        'evidence', 'derived',
                        'source_refs', json_array('life_goals:' || goal.id || ':id')
                    ),
                    'name', json_object(
                        'evidence', 'user_entered',
                        'source_refs', json_array('life_goals:' || goal.id || ':name')
                    ),
                    'target_date', json_object(
                        'evidence', 'user_entered',
                        'source_refs', json_array('life_goals:' || goal.id || ':target_date')
                    ),
                    'target_amount', json_object(
                        'evidence', 'user_entered',
                        'source_refs', json_array('life_goals:' || goal.id || ':target_amount')
                    ),
                    'protected_cash_floor', json_object(
                        'evidence', 'user_entered',
                        'source_refs', json_array(
                            'life_plan_profiles:' || profile.id || ':cash_floor'
                        )
                    ),
                    'reserved_amount', json_object(
                        'evidence', 'user_entered',
                        'source_refs', json_array('life_goals:' || goal.id || ':reserved_amount')
                    ),
                    'is_primary', json_object(
                        'evidence', 'derived',
                        'source_refs', json_array('life_goals:enabled-cardinality')
                    ),
                    'status', json_object(
                        'evidence', 'derived',
                        'source_refs', json_array(
                            'life_goals:' || goal.id || ':reserved_amount',
                            'life_goals:' || goal.id || ':target_amount'
                        )
                    ),
                    'tracking_mode', json_object(
                        'evidence', 'assumed',
                        'source_refs', json_array('migration:0009:tracking_mode')
                    ),
                    'reservation_policy', json_object(
                        'evidence', 'assumed',
                        'source_refs', json_array('migration:0009:reservation_policy')
                    )
                ),
                'money-map-v2-contract-v1',
                '0009_goal_persistence',
                strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'),
                strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
            FROM life_goals AS goal
            JOIN life_plan_profiles AS profile ON profile.id = goal.profile_id
            WHERE goal.enabled = 1
            """
        + limit
    )
    if fail_during_copy:
        raise RuntimeError("Injected 0009 failure during goal copying")


def _create_append_only_triggers() -> None:
    for table in ("goal_check_ins", "goal_check_in_components"):
        for operation in ("UPDATE", "DELETE"):
            trigger = f"trg_{table}_no_{operation.lower()}"
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER {trigger}
                    BEFORE {operation} ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, 'v2 goal check-in history is append-only');
                    END
                    """
                )
            )


def _inject_failure(stage: str) -> None:
    if os.getenv(FAILURE_INJECTION_ENV) == stage:
        raise RuntimeError(f"Injected 0009 failure at {stage}")


def downgrade() -> None:
    for table in ("goal_check_in_components", "goal_check_ins"):
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_{operation}"))
    op.drop_index("ix_goal_check_in_components_check_in_id", table_name="goal_check_in_components")
    op.drop_table("goal_check_in_components")
    op.drop_index("ix_goal_check_ins_goal_program_id", table_name="goal_check_ins")
    op.drop_table("goal_check_ins")
    op.drop_index("uq_goal_programs_single_primary", table_name="goal_programs")
    op.drop_table("goal_programs")
