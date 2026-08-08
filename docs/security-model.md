# Security model

## Threats in scope

- Accidentally committing statements or extracted personal information.
- Exposing the application on the local network.
- Logging raw account identifiers or document contents.
- Writing Plaid credentials or access tokens to the database, repository, logs,
  reports, or browser storage.
- Requesting broader provider products than the evidence workflow needs.
- Retaining provider access after the operator disconnects.
- Duplicate imports or silent parser changes.
- Treating incomplete evidence as a complete financial picture.
- Overwriting the only local database during restore.

## Controls

- The server refuses to bind outside `127.0.0.1`.
- `.local/` contains inbox files, SQLite data, reports, temporary renders, and backups,
  and is excluded from Git.
- The privacy check rejects financial file types outside approved synthetic paths and
  scans source-like files for likely long identifiers.
- Imported artifacts have a unique SHA-256 hash, batch, filename, adapter, and parser
  version.
- Application output reports filenames and safe error messages but never logs extracted
  document text or raw account identifiers.
- Manual corrections append old/new values and a reason before reconciliation reruns.
- Restore first creates a recoverable pre-restore backup and validates SQLite integrity.
- Raw inputs are read-only. No code writes to financial-provider source files.
- Plaid Client IDs, secrets, stable local client identity, and per-item access tokens
  are stored in macOS Keychain. Only non-secret status and a four-character Client ID
  hint are returned to the interface.
- Plaid secrets are sent as request headers, not request-body fields. Access tokens are
  exchanged and used only by the loopback backend; Plaid Link public tokens are
  single-use.
- The connector requests only Transactions for SoFi and Investments for Fidelity.
  Auth, Identity, Transfer, payment, and trading capabilities are absent.
- Link sessions are local, expiring, and single-use. Sync mutations are idempotent,
  response-hashed, and transaction-scoped so a failure cannot leave partial normalized
  data.
- Disconnect invokes Plaid item removal, deletes the Keychain access token, and by
  default cascade-deletes that connection’s normalized local records.
- Remote Plaid and CDN calls occur only after explicit connector actions. Manual
  import, reconciliation, forecasting, reporting, backup, and restore remain local.
- Life Lab projection requests, profiles, goals, and saved scenarios remain in the local
  SQLite database. Its runtime has no public-network dependency and returns no provider
  identifiers or raw transaction descriptions.
- The checked-in state-income artifact contains public aggregate IRS/BLS data only.
  Regeneration is an explicit developer action; the runtime does not fetch benchmarks.
- Drive Calculator arithmetic runs entirely in the browser. Its IRS reference is an
  ordinary external link opened only when the user chooses it; the app does not transmit
  plan values, balances, or calculator inputs to the IRS or another service.
- No telemetry, screen scraping, trading, or money movement exists.

## Operator responsibility

Disk encryption, macOS account security, and local backups remain outside the
application. Generated `.local/` data is private and should be handled like the
original statements. Plaid availability, institution coverage, consent renewal,
third-party retention, plan eligibility, and billing remain external dependencies.
