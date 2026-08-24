# Architecture

The maintained authority map is [Current single sources of truth](v3/single-source-of-truth.md).

## Components

```text
Private inbox (.local/inbox)
  -> versioned PDF, canonical payroll JSON, and ledger adapters
Optional Plaid Link + read-only API
  -> endpoint response hashes + versioned Plaid normalizers
Both paths
  -> normalized SQLite records + source evidence
  -> reconciliation services
  -> FastAPI read/review/forecast/Life Lab endpoints
  -> locally bundled React interface and print report
```

SQLAlchemy models keep import batches, artifact hashes, evidence, institutions,
accounts, balances, payroll records and detailed lines, transactions, transfer matches, external flows,
Fidelity holdings and value bridges, Plaid connections and sync evidence,
reconciliation results, allocation scenarios, Life Lab profiles/goals/saved projections,
periods, and manual corrections.

FastAPI serves both the API and the production React build from one loopback process.
There is no separate service account, cloud database, or telemetry. Manual imports
have no runtime external dependency. Plaid Link loads from Plaid’s CDN only when the
operator starts a Plaid connection, and Plaid API calls occur only for configuration,
authorization, explicit sync, reauthorization, or revocation actions.

## Adapter boundary

Adapters return immutable parsed records. Ingestion stores provenance and institution
aliases; reconciliation owns accounting classification and matching. This separation
allows a parser revision to be tested without changing formulas.

The Plaid adapter follows the same boundary. API response bodies are not persisted
verbatim; each response is canonicalized and SHA-256 hashed, with endpoint, retrieval
time, request ID, parser version, and normalized record counts stored as evidence.
Connection and provider account identifiers live only in the private database.
Credentials and access tokens live only in macOS Keychain.

## Runtime modes and process ownership

Repository mode runs one Python process through `paycheck-map serve`. It owns SQLite, migrations,
the loopback API, and the compiled React assets under the repository workflow. Its default private
root is `.local/`.

The packaged macOS mode runs a Tauri shell and one supervised Python sidecar. Tauri owns trusted
macOS paths, the private bootstrap/session, lifecycle, native menus, and safe failure windows. The
sidecar remains the only SQLite writer and binds an OS-selected loopback port. Desktop environment
variables are launcher-owned protocol fields, not user configuration.

There are no independent workers, queues, cron jobs, launch agents, or long-lived schedulers.
Automatic Plaid refresh is a once-per-local-day request made by the loaded React application when
the backend reports stale connected data. Import, payroll regeneration, reporting, backup, restore,
and provider mutations are explicit operations.

## Persistence and schema

`models.py` defines the SQLAlchemy model authority. `alembic/versions/` contains the ordered schema
history, and `product_metadata.SCHEMA_HEAD` identifies the required head. Repository startup upgrades
the local database through Alembic. Packaged startup instead uses the data-home manager's staged,
verified activation workflow; it never substitutes repository `.local` state.

The main persistence groups are import provenance and evidence, institutions/accounts and dated
values, payroll and allocations, transactions and reconciliation, Plaid connections and sync
evidence, forecast scenarios, Life Lab profiles/projections, operational goals/check-ins, and manual
corrections. Exact ownership is listed in the [SSOT map](v3/single-source-of-truth.md); migration and
cutover behavior is documented in [desktop architecture](v3/desktop-architecture.md).

## Life Lab boundary

`life_plan.py` owns the monthly today-dollar projection engine. It reads normalized
balances and the latest completed detailed payroll, but it never mutates source records
or existing 12-month forecast scenarios. User assumptions, generic goals, and saved
projection periods live in separate `life_*` tables introduced by migration 0008.

The React Plan bundle is lazy-loaded after the ordinary dashboard has rendered. Runtime
calculation is local and network-free. The checked-in income benchmark JSON is generated
separately from fixed public IRS and BLS sources; its source URLs, hashes, source year,
CPI periods, normalization factor, and artifact version travel with the data.

## Backup, rollback, and reports

- Import batches cascade-delete their artifacts and derived source rows; reconciliation
  is rebuilt after rollback.
- SQLite backup uses the database backup API rather than copying a live file.
- Restore validates integrity and keeps a pre-restore backup.
- The trailing-12 report is deterministic for unchanged data and remains under
  `.local/reports/`.

The packaged macOS runtime replaces repository `.local` with the centralized
`money-map-macos-data-home-v1` provider: Application Support owns data/inbox/reports/backups/
migration/state, while macOS Cache and Logs remain distinct. Tauri resolves those roots and Python
alone owns SQLite initialization, online backup, staging migration, manifest validation, atomic
activation, restore, and digest-only recovery state. Repository-mode CLI behavior remains available
for development and does not become a packaged-runtime fallback.
