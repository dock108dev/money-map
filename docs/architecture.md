# Architecture

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
