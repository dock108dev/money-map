# Security model

## Slice 4 desktop boundary

The normative desktop threat/control matrix is `docs/v3/desktop-threat-model.md`; the executed
gates are `docs/v3/security-acceptance.md`. The signed shell activates two exact Tauri capability
sets: 13 reviewed application commands for bundled `main`, and only status/restart/About for the
nonfinancial `safe-error` window. Remote content, Plaid frames, and arbitrary windows receive no
native authority. Shell, generic filesystem, generic HTTP, arbitrary opener, and window creation
permissions are absent.

Every sidecar generation receives a new 256-bit session through a private inherited descriptor,
not arguments or environment values. The authenticated server binds only ephemeral
`127.0.0.1`, requires the exact Host/session/origin contract, rejects duplicate or ambiguous
framing, and bounds bodies, concurrency and responses. Rust supplies the destination and secret;
React cannot read either. Startup verifies the strict Apple-team-signed bundle/arm64 sidecar before
spawn, and database/recovery/import artifacts pass closed-schema, identity and resource gates.

Plaid credentials are collected by fixed sidecar-owned native macOS prompts; React sends only the
environment and never receives client credentials or access tokens. Keychain services and account
patterns are versioned exact allowlists. Safe event logs contain only fixed code/classification/time
fields and rotate at bounded size. These controls do not protect a fully compromised logged-in
macOS account that can inspect memory or rewrite both a file and its unkeyed digest.

## Desktop reports and sanitized diagnostics

React receives opaque report identities, never filesystem authority. The backend approves the one
supported report filename under the report root; Rust independently rejects traversal, symlinks,
non-files, and parent mismatches before Quick Look or Finder access. Report writes are atomic,
private, and local.

Diagnostics cross the native/backend boundary only as allowlisted health classifications. They
exclude financial data, account or institution identifiers, credentials, sessions, ports, paths,
database hashes, private filenames, raw exceptions, request/response bodies, report contents,
screenshots, and environment dumps. Export requires a native destination panel, writes mode `0600`,
and performs no write when canceled.

## Standalone loopback browser boundary

`uv run paycheck-map serve` is a single-owner local surface, not a public or multi-user service.
It binds only the configured `127.0.0.1:8765` authority. The standalone middleware requires that
exact Host, rejects cross-origin and cross-site browser requests, requires JSON for mutations,
rejects ambiguous framing and duplicate security headers, and bounds bodies and active requests.
Responses are `no-store`, non-indexable, non-frameable, MIME-sniff protected, referrer-free, and
covered by a restrictive CSP and Permissions Policy. Framework API documentation and the OpenAPI
schema are disabled. HSTS and cookie flags do not apply because this mode uses plain loopback HTTP
and has no cookies; it must not be reverse-proxied or exposed on a network.

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

- The desktop server binds only ephemeral IPv4 `127.0.0.1`; exact Host, origin, one-time session,
  framing, size, method, content-type, path and concurrency rules fail closed.
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
- Plaid Client IDs, secrets, stable local client identity, and per-item access tokens are stored in
  versioned exact macOS Keychain namespaces. Sidecar-owned native prompts prevent client
  credentials from entering React; only non-secret status and a four-character hint return.
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
- Packaged macOS paths are supplied only by the Tauri path authority after its inherited child
  environment is cleared. Data, cache, and logs are separate; private directories use `0700` and
  accepted database/backup files use `0600`.
- Import is explicit and read-only until a second confirmation. Symlink chains, active-file hard
  links, repository/app-bundle relationships, unapproved backup parents, corrupt or incompatible
  revisions, and insufficient space fail closed.
- Migration and restore operate on isolated online-backup restores. Atomic activation retains the
  prior accepted database and a verified safety backup until post-activation digest, integrity,
  foreign-key, revision, and logical-manifest verification succeeds.
- Recovery journals and UI errors contain safe codes/classifications only; they exclude raw paths,
  rows, descriptions, identifiers, credentials, tokens, and unsanitized exceptions.

## Operator responsibility

Disk encryption, macOS account security, and local backups remain outside the
application. Generated `.local/` data is private and should be handled like the
original statements. Plaid availability, institution coverage, consent renewal,
third-party retention, plan eligibility, and billing remain external dependencies.
