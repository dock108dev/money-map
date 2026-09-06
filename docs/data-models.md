# Data model and migration ownership

[`models.py`](../src/paycheck_map/models.py) defines one SQLAlchemy metadata registry.
[`db.py`](../src/paycheck_map/db.py) enables SQLite foreign keys on every engine connection and
supplies sessions. Money and rates use explicit decimal precision; timestamps use the model's UTC
normalization. API contracts can reject ambiguous timestamps even when historical database reads
normalize naive UTC values.

## Stored record families

| Records | Purpose and write owner |
| --- | --- |
| Import batches, artifacts, source evidence | File hashes, parser identity, provenance and per-batch outcomes; `ingestion.py` and adapters. |
| Institutions, accounts, balances, transactions, holdings | Normalized financial facts from imports, manual operations and optional provider sync. |
| Payroll statements, line items, schedule entries, allocations and matches | Imported payroll evidence and derived completed schedules; `payroll.py`, `allocations.py` and reconciliation. |
| Transfers, external flows, balance points, investment bridges and reconciliation results | Rebuilt accounting/read evidence; reconciliation and balance services. |
| Plaid connections, Link sessions, sync runs and endpoint evidence | Connection state, single-use Link lifecycle and digest-based sync evidence; provider service. Secrets belong in Keychain. |
| Application settings | Refresh preferences/attempt dates and planning provenance; their domain services own each key. |
| Forecast assumptions, scenarios and periods | Twelve-month allocation scenarios, separate from retirement solvency; `forecasting.py`. |
| Life profiles, scenarios and projection periods | Durable Retirement profile and context-labelled Retirement/Lab snapshots; `retirement_lab.py` and `planning_snapshots.py`. |
| Operational goal programs, check-ins and components | Independent v2 goals and immutable observation evidence; `goal_service.py` and `goal_observation.py`. |
| Manual corrections | Old/new values and correction reason, followed by reconciliation. |

Legacy `life_goals` records and combined snapshot readers remain for compatibility and historical
evidence. The combined `/api/life-plan/*` mutation API is removed. Current goal writes use v2 goal
programs; do not infer a second supported writer from retained table names.

## Transaction boundaries

Import uses per-file savepoints and commits successful files even if another file is rejected.
A batch can therefore finish with errors; retry is hash-idempotent. Snapshot storage flushes the
scenario and periods without committing; the API caller owns commit or rollback. Provider sync
isolates financial writes per connection. Transactions are domain-owned; `get_session` itself does
not auto-commit every request. Follow the [ownership map](v3/single-source-of-truth.md) before adding
a mutation.

## Schema lifecycle

[`alembic/versions`](../alembic/versions) contains a linear revision chain:

1. `0001_local_v01`: core accounting.
2. `0002_plaid_read_only`: provider records.
3. `0003_payroll_detail`: detailed payroll.
4. `0004_completed_payroll_schedule`: completed schedule.
5. `0005_money_map_v1`: allocations, balance history and forecast HSA fields.
6. `0006_daily_data_refresh`: refresh settings.
7. `0007_refresh_timestamp_integrity`: timestamp ordering repair/enforcement.
8. `0008_life_lab_v01`: life profiles, goals and projections.
9. `0009_goal_persistence`: independent operational goals.

`product_metadata.SCHEMA_HEAD` binds the supported revision. Repository initialization upgrades to
head; it also recognizes the original unversioned payroll schema before upgrading. Packaged startup
uses the staged data-home activation/verification protocol instead of repository initialization.
Do not run ad-hoc schema commands on an owner's database. Removing compatibility tables or changing
migration/restore policy requires a separate migration design and recovery tests.

Repository backup/restore commands and their existing-database requirement are documented in
[Operations](operations.md). Packaged activation and recovery are documented in
[Desktop architecture](v3/desktop-architecture.md).
