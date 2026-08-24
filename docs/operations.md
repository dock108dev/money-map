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
uv run paycheck-map serve
```

The integrated application listens only on `127.0.0.1:8765`. Stop the foreground repository server
with the terminal interrupt. Native app shutdown is supervised by the Tauri lifecycle controller.

## Manual import

Place supported files in the appropriate private inbox directory, then use **Import private inbox**
in the application or run:

```bash
uv run paycheck-map import
```

Imports retain source evidence and use SHA-256 duplicate protection. Supported formats and canonical
columns are documented in [data-source-strategy.md](data-source-strategy.md); reconciliation behavior
is documented in [accounting-rules.md](accounting-rules.md).

To remove a known import batch:

```bash
uv run paycheck-map rollback <batch-id>
```

## Read-only provider refresh

Plaid is optional. Configure it through the application so credentials are stored in Keychain.
When automatic refresh is enabled, the React application requests at most one refresh for the local
business day when Money Map opens and the backend reports that connected data is stale. There is no
daemon, cron task, launch agent, or server-side background scheduler. Closing the application stops
all refresh activity.

```bash
uv run paycheck-map sync --status
uv run paycheck-map sync
```

The first command reports freshness without refreshing. The second updates active read-only
connections and exits unsuccessfully if any connection needs attention. Money Map does not request
payment, transfer, identity, or trading products.

## Payroll maintenance

```bash
uv run paycheck-map payroll-status
uv run paycheck-map payroll-regenerate
```

Run status to check the completed schedule and reconciliation rules. Regeneration rebuilds calculated
history from stored evidence; it does not modify imported source artifacts.

## Backup, restore, and reports

```bash
uv run paycheck-map backup
uv run paycheck-map restore /absolute/path/to/backup.sqlite3
uv run paycheck-map report
```

Backup uses SQLite's backup API. Restore requires an explicit path, validates SQLite integrity, and
creates a safety backup of the current database before replacement. Reports remain local under the
private reports directory.

Repository-mode restore expects an existing active database because the current database is backed
up before replacement. Restoring into a fresh packaged installation is handled by the native
data-home workflow, not by the repository CLI.

The packaged app exposes these operations through native menus and dialogs. Packaged data-home,
cutover, recovery, and backup rules are documented in [cutover-readiness.md](v3/cutover-readiness.md).

## Failure handling

User-facing failures are sanitized and private-safe. Do not add raw exception text, filesystem paths,
provider payloads, tokens, or financial values to logs. Use the stable event codes and recovery rules
in [error-handling.md](v3/error-handling.md). Security boundaries are in
[security-model.md](security-model.md).
