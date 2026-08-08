from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .money import ZERO, Money


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="running")
    requested_source: Mapped[str] = mapped_column(String(64), default="local_inbox")
    artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    artifacts: Mapped[list[ImportArtifact]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportArtifact(Base):
    __tablename__ = "import_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    source_kind: Mapped[str] = mapped_column(String(64))
    adapter: Mapped[str] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(32))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    batch: Mapped[ImportBatch] = relationship(back_populates="artifacts")
    evidence: Mapped[list[SourceEvidence]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class SourceEvidence(Base):
    __tablename__ = "source_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("import_artifacts.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    field_name: Mapped[str] = mapped_column(String(128))
    location: Mapped[str] = mapped_column(String(128))
    original_label: Mapped[str] = mapped_column(String(255))
    extraction_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(32), default="high")
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    artifact: Mapped[ImportArtifact] = relationship(back_populates="evidence")


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    accounts: Mapped[list[Account]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )


class PlaidConnection(Base):
    __tablename__ = "plaid_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(128), unique=True)
    institution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    institution_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")
    products: Mapped[list[str]] = mapped_column(JSON, default=list)
    consent_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transactions_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    accounts: Mapped[list[Account]] = relationship(
        back_populates="plaid_connection", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[list[PlaidSyncRun]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class PlaidLinkSession(Base):
    __tablename__ = "plaid_link_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    environment: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlaidSyncRun(Base):
    __tablename__ = "plaid_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("plaid_connections.id", ondelete="CASCADE")
    )
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    account_count: Mapped[int] = mapped_column(Integer, default=0)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    holding_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection: Mapped[PlaidConnection] = relationship(back_populates="sync_runs")
    endpoint_evidence: Mapped[list[PlaidEndpointEvidence]] = relationship(
        back_populates="sync_run", cascade="all, delete-orphan"
    )


class PlaidEndpointEvidence(Base):
    __tablename__ = "plaid_endpoint_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("plaid_sync_runs.id", ondelete="CASCADE"))
    artifact_id: Mapped[int] = mapped_column(ForeignKey("import_artifacts.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_sha256: Mapped[str] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parser_version: Mapped[str] = mapped_column(String(32))
    sync_run: Mapped[PlaidSyncRun] = relationship(back_populates="endpoint_evidence")


class ApplicationSetting(Base):
    """Small local-only preferences and refresh markers."""

    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("institution_id", "external_key", name="uq_account_external_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    plaid_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("plaid_connections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    external_key: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(128))
    account_type: Mapped[str] = mapped_column(String(32))
    institution: Mapped[Institution] = relationship(back_populates="accounts")
    plaid_connection: Mapped[PlaidConnection | None] = relationship(back_populates="accounts")


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", "kind", name="uq_balance_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    artifact_id: Mapped[int] = mapped_column(ForeignKey("import_artifacts.id", ondelete="CASCADE"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Money, default=ZERO)


class PayrollStatement(Base):
    __tablename__ = "payroll_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("import_artifacts.id", ondelete="CASCADE"), unique=True
    )
    employer: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    observed_deposit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_frequency: Mapped[str] = mapped_column(String(32))
    base_salary: Mapped[Decimal] = mapped_column(Money)
    gross_earnings: Mapped[Decimal] = mapped_column(Money)
    imputed_earnings: Mapped[Decimal] = mapped_column(Money)
    pretax_deductions: Mapped[Decimal] = mapped_column(Money)
    tax_withholdings: Mapped[Decimal] = mapped_column(Money)
    after_tax_deductions: Mapped[Decimal] = mapped_column(Money)
    federal_taxable_gross: Mapped[Decimal] = mapped_column(Money)
    net_payment: Mapped[Decimal] = mapped_column(Money)
    ytd_values: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    detail_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    lines: Mapped[list[PayrollLineItem]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )


class PayrollLineItem(Base):
    __tablename__ = "payroll_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(64))
    original_label: Mapped[str] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Money)
    ytd_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    reduces_net: Mapped[bool] = mapped_column(Boolean, default=True)
    statement: Mapped[PayrollStatement] = relationship(back_populates="lines")


class PayrollScheduleEntry(Base):
    """Completed payroll history derived without mutating source statements."""

    __tablename__ = "payroll_schedule_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    previous_checkpoint_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"), nullable=True
    )
    next_checkpoint_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"), nullable=True
    )
    payment_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    observed_deposit_date: Mapped[date] = mapped_column(Date, index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    payroll_year: Mapped[int] = mapped_column(Integer, index=True)
    payroll_index: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(32))
    calculation_version: Mapped[str] = mapped_column(String(32))
    employer: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_salary: Mapped[Decimal] = mapped_column(Money)
    gross_earnings: Mapped[Decimal] = mapped_column(Money)
    imputed_earnings: Mapped[Decimal] = mapped_column(Money)
    pretax_deductions: Mapped[Decimal] = mapped_column(Money)
    tax_withholdings: Mapped[Decimal] = mapped_column(Money)
    after_tax_deductions: Mapped[Decimal] = mapped_column(Money)
    federal_taxable_gross: Mapped[Decimal] = mapped_column(Money)
    net_payment: Mapped[Decimal] = mapped_column(Money)
    gross_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    imputed_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    pretax_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    tax_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    after_tax_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    federal_taxable_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    net_adjustment: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    deposit_splits: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    allocations: Mapped[list[PayrollAllocation]] = relationship(
        back_populates="schedule_entry", cascade="all, delete-orphan"
    )


class PayrollAllocation(Base):
    """A statement-backed or calculated destination within one completed paycheck."""

    __tablename__ = "payroll_allocations"
    __table_args__ = (
        UniqueConstraint("schedule_entry_id", "category", name="uq_payroll_allocation_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_entry_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_schedule_entries.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(96))
    label: Mapped[str] = mapped_column(String(160))
    section: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    source_kind: Mapped[str] = mapped_column(String(32))
    previous_checkpoint_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"), nullable=True
    )
    next_checkpoint_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"), nullable=True
    )
    calculation_version: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    schedule_entry: Mapped[PayrollScheduleEntry] = relationship(back_populates="allocations")


class PayrollTransactionMatch(Base):
    __tablename__ = "payroll_transaction_matches"
    __table_args__ = (
        UniqueConstraint("schedule_entry_id", "transaction_id", name="uq_payroll_transaction_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_entry_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_schedule_entries.id", ondelete="CASCADE"), index=True
    )
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("account_transactions.id", ondelete="CASCADE"), unique=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    match_group: Mapped[str] = mapped_column(String(64))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountTransaction(Base):
    __tablename__ = "account_transactions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id", "source_row", "account_id", name="uq_transaction_source_row"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    artifact_id: Mapped[int] = mapped_column(ForeignKey("import_artifacts.id", ondelete="CASCADE"))
    posted_date: Mapped[date] = mapped_column(Date, index=True)
    original_description: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source_row: Mapped[int] = mapped_column(Integer)
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True, unique=True, index=True
    )


class AccountBalancePoint(Base):
    """Observed-anchor or transaction-derived balance used for history charts."""

    __tablename__ = "account_balance_points"
    __table_args__ = (
        UniqueConstraint("account_id", "balance_date", "kind", name="uq_account_balance_point"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    anchor_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("balance_snapshots.id", ondelete="CASCADE"), index=True
    )
    balance_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Money)
    source_kind: Mapped[str] = mapped_column(String(32))
    coverage_start: Mapped[date] = mapped_column(Date)
    coverage_end: Mapped[date] = mapped_column(Date)
    calculation_version: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)


class InvestmentHolding(Base):
    __tablename__ = "investment_holdings"
    __table_args__ = (
        UniqueConstraint("account_id", "security_id", name="uq_holding_account_security"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    artifact_id: Mapped[int] = mapped_column(ForeignKey("import_artifacts.id", ondelete="CASCADE"))
    security_id: Mapped[str] = mapped_column(String(160))
    security_name: Mapped[str] = mapped_column(String(255))
    ticker_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    security_type: Mapped[str] = mapped_column(String(64), default="other")
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8, asdecimal=True))
    institution_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    institution_value: Mapped[Decimal] = mapped_column(Money)
    cost_basis: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    as_of: Mapped[date] = mapped_column(Date)


class TransferMatch(Base):
    __tablename__ = "transfer_matches"
    __table_args__ = (
        UniqueConstraint("left_transaction_id", "right_transaction_id", name="uq_transfer_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    left_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("account_transactions.id", ondelete="CASCADE")
    )
    right_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("account_transactions.id", ondelete="CASCADE")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    confidence: Mapped[str] = mapped_column(String(32))


class ExternalFlow(Base):
    __tablename__ = "external_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("account_transactions.id", ondelete="CASCADE")
    )
    payroll_statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_statements.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Money)


class InvestmentValueBridge(Base):
    __tablename__ = "investment_value_bridges"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "period_start", "period_end", name="uq_investment_value_bridge"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    opening_value: Mapped[Decimal] = mapped_column(Money)
    employee_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    employer_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    stock_plan_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    other_deposits: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    withdrawals: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    investment_result: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    closing_value: Mapped[Decimal] = mapped_column(Money)
    reported_return_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    calculated_return_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    return_method: Mapped[str] = mapped_column(String(64), default="not_available")


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "rule", name="uq_reconciliation_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    rule: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    residual: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastAssumption(Base):
    __tablename__ = "forecast_assumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    value: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(128))
    as_of: Mapped[date] = mapped_column(Date)


class ForecastScenario(Base):
    __tablename__ = "forecast_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    periods: Mapped[list[ForecastPeriod]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class ForecastPeriod(Base):
    __tablename__ = "forecast_periods"
    __table_args__ = (UniqueConstraint("scenario_id", "month", name="uq_forecast_scenario_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_scenarios.id", ondelete="CASCADE")
    )
    month: Mapped[date] = mapped_column(Date)
    gross_pay: Mapped[Decimal] = mapped_column(Money)
    taxes: Mapped[Decimal] = mapped_column(Money)
    benefits_and_other: Mapped[Decimal] = mapped_column(Money)
    employee_retirement: Mapped[Decimal] = mapped_column(Money)
    employee_hsa: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    stock_plan: Mapped[Decimal] = mapped_column(Money)
    employer_retirement: Mapped[Decimal] = mapped_column(Money)
    employer_hsa: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    sofi_checking: Mapped[Decimal] = mapped_column(Money)
    sofi_savings: Mapped[Decimal] = mapped_column(Money)
    external_outflow: Mapped[Decimal] = mapped_column(Money)
    ending_checking: Mapped[Decimal] = mapped_column(Money)
    ending_savings: Mapped[Decimal] = mapped_column(Money)
    ending_cash: Mapped[Decimal] = mapped_column(Money)
    cash_redirect_to_investments: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    assumed_investment_result: Mapped[Decimal] = mapped_column(Money)
    scenario: Mapped[ForecastScenario] = relationship(back_populates="periods")


class LifePlanProfile(Base):
    """Local assumptions for the active Life Lab plan."""

    __tablename__ = "life_plan_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    birth_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(2))
    end_age: Mapped[int] = mapped_column(Integer, default=95)
    current_monthly_outflow: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    essential_monthly_spend: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    flexible_monthly_spend: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cash_floor: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    retirement_tax_rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4, asdecimal=True), default=ZERO
    )
    target_ages: Mapped[list[int]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    goals: Mapped[list[LifeGoal]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    scenarios: Mapped[list[LifeScenario]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class LifeGoal(Base):
    """A generic dated cash goal with an optional continuing real cost."""

    __tablename__ = "life_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("life_plan_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    target_date: Mapped[date] = mapped_column(Date, index=True)
    target_amount: Mapped[Decimal] = mapped_column(Money)
    reserved_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    annual_cost: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    priority: Mapped[str] = mapped_column(String(16), default="required")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    profile: Mapped[LifePlanProfile] = relationship(back_populates="goals")


class LifeScenario(Base):
    """A reproducible saved Life Lab projection."""

    __tablename__ = "life_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("life_plan_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    target_age: Mapped[int] = mapped_column(Integer)
    path_key: Mapped[str] = mapped_column(String(32))
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    engine_version: Mapped[str] = mapped_column(String(32))
    assumption_version: Mapped[str] = mapped_column(String(32))
    benchmark_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(40))
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    profile: Mapped[LifePlanProfile] = relationship(back_populates="scenarios")
    periods: Mapped[list[LifeProjectionPeriod]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class LifeProjectionPeriod(Base):
    """One monthly point in a saved Life Lab path."""

    __tablename__ = "life_projection_periods"
    __table_args__ = (UniqueConstraint("scenario_id", "month", name="uq_life_scenario_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("life_scenarios.id", ondelete="CASCADE"), index=True
    )
    month: Mapped[date] = mapped_column(Date, index=True)
    age_months: Mapped[int] = mapped_column(Integer)
    working: Mapped[bool] = mapped_column(Boolean)
    gross_income: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    net_income: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    employee_retirement: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    employer_retirement: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    stock_plan: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    essential_spend: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    flexible_spend: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    goal_spend: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cash: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    accessible_investments: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    pretax_retirement: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    hsa: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    restricted_assets: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    debt: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    investment_result: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    total_spendable: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    scenario: Mapped[LifeScenario] = relationship(back_populates="periods")


class ManualCorrection(Base):
    __tablename__ = "manual_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    field_name: Mapped[str] = mapped_column(String(128))
    old_value: Mapped[str] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
