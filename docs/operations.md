# Local operations guide

This guide covers the supported repository-mode workflow. The packaged macOS runtime uses private
Application Support, Cache, and Logs locations managed by the native launcher; it does not fall back
to repository `.local` paths.

## Private local paths

Repository-mode state lives under ignored paths:

```text
.local/inbox/payroll/
.local/inbox/sofi/
.local/inbox/fidelity/
.local/data/paycheck-map.sqlite3
.local/reports/
.local/backups/
```

Do not copy real statements into tests, examples, screenshots, documentation, or retained command
output. Plaid credentials and connection access tokens belong in macOS Keychain.

## Start and stop

```bash
uv run --locked --python 3.12 paycheck-map serve
```

The integrated application defaults to `127.0.0.1:8765`; `PAYCHECK_MAP_PORT` selects another
loopback port. Open the exact printed URL, not `localhost`. Stop the foreground repository server
with the terminal interrupt. Native app shutdown is supervised by the Tauri lifecycle controller.

Most repository commands initialize/upgrade the selected local database before doing their work:
`serve`, `import`, `rollback`, `report`, `payroll-regenerate`, `payroll-status`, and `sync` (including
`--status`). Set the private-root override before invoking them. `backup`, `restore` and `verify`
do not run that initialization path.

## Manual import

Place supported files in the appropriate private inbox directory, then use **Import private inbox**
in the application or run:

```bash
uv run --locked --python 3.12 paycheck-map import
```

The importer recursively discovers PDF, JSON, CSV and XLSX files under the inbox; the suggested
subdirectories organize files but do not choose the adapter. Other extensions are ignored.
Each rejected supported file is isolated; successful files in the batch remain committed. The CLI
returns status 1 if any files were rejected, and 0 for an error-free or duplicate-only batch.
Read the summary before retrying; a partial failure does not undo successful files.

Imports retain source evidence and use SHA-256 duplicate protection. Supported formats and canonical
columns are documented in [data-source-strategy.md](data-source-strategy.md); reconciliation behavior
is documented in [accounting-rules.md](accounting-rules.md).

To remove a known import batch:

```bash
uv run --locked --python 3.12 paycheck-map rollback <batch-id>
```

## Read-only provider refresh

Plaid is optional. Configure it through the application so credentials are stored in Keychain.
Automatic refresh defaults to enabled and is stored in `application_settings`, not an environment
variable. Once connections exist, the mounted React application can request one automatic attempt
per **America/New_York calendar day** when evidence is stale. The attempt date is stored before
provider work, so failure does not cause an automatic retry loop that day. Manual Update data or
`sync` can retry. `refresh.py` serializes refresh/credential operations with a process-local guard;
concurrent operations are rejected rather than queued.

There is no daemon, cron task, launch agent, server-side background scheduler, or midnight timer.
Closing a repository browser tab prevents further automatic requests but does not cancel backend
work already running. Native shutdown also stops its supervised sidecar. The CLI can refresh
without the UI when explicitly invoked.

```bash
uv run --locked --python 3.12 paycheck-map sync --status
uv run --locked --python 3.12 paycheck-map sync
```

The first command reports freshness without refreshing. The second updates active read-only
connections and exits unsuccessfully if any connection needs attention. Money Map does not request
payment, transfer, identity, or trading products.

## Payroll maintenance

```bash
uv run --locked --python 3.12 paycheck-map payroll-status
uv run --locked --python 3.12 paycheck-map payroll-regenerate
```

Run status to check the completed schedule and reconciliation rules. Regeneration rebuilds calculated
history from stored evidence; it does not modify imported source artifacts.

## Backup, restore, and reports

```bash
uv run --locked --python 3.12 paycheck-map backup
uv run --locked --python 3.12 paycheck-map restore /absolute/path/to/backup.sqlite3
uv run --locked --python 3.12 paycheck-map report
```

Stop the repository server and other CLI writers before repository-mode restore: it replaces the
active database file and does not coordinate with another running process.

Backup uses SQLite's backup API. Restore requires an explicit path, validates SQLite integrity, and
creates a safety backup of the current database before replacement. Reports remain local under the
private reports directory. Report generation includes a baseline forecast and requires at least
one imported payroll statement; ledger-only data is insufficient.

Repository-mode restore expects an existing active database because the current database is backed
up before replacement. Restoring into a fresh packaged installation is handled by the native
data-home workflow, not by the repository CLI.

The packaged app exposes these operations through native menus and dialogs. Packaged data-home,
cutover, recovery, and backup rules are documented in [cutover-readiness.md](v3/cutover-readiness.md).

## Disposable manual-import example

After installation, use a fresh synthetic root rather than the default private database:

```bash
export PAYCHECK_MAP_LOCAL_DIR="$(mktemp -d /private/tmp/money-map-example.XXXXXX)"
mkdir -p "$PAYCHECK_MAP_LOCAL_DIR/inbox"
cp examples/synthetic/sofi-ledger.csv examples/synthetic/fidelity-ledger.csv "$PAYCHECK_MAP_LOCAL_DIR/inbox/"
uv run --locked --python 3.12 paycheck-map import
uv run --locked --python 3.12 paycheck-map import
uv run --locked --python 3.12 paycheck-map backup
uv run --locked --python 3.12 paycheck-map sync --status
```

The first import accepts two files; the second reports two duplicates. This ledger-only example
has no payroll baseline or provider connections, so it cannot qualify payroll completeness or live
provider access. Do not copy the `money-map-v2*-contracts.json` API fixtures into the inbox: they
are not payroll import files. Keep this environment override for all operations on the example.

## Failure handling

User-facing failures are sanitized and private-safe. Do not add raw exception text, filesystem paths,
provider payloads, tokens, or financial values to logs. Use the stable event codes and recovery rules
in [error-handling.md](v3/error-handling.md). Security boundaries are in
[security-model.md](security-model.md).
