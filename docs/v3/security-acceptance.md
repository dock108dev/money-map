# Money Map Slice 4 security acceptance

Status: engineering acceptance candidate, 2026-08-22. Threat model `slice4-v1`. Runtime `2.1.0`;
schema `0009_goal_persistence`; no migration added.

## Capability, navigation and command contract

`tauri.conf.json` activates only `main-window` and `safe-error-window`. The main window has the 13
custom permissions below; the recovery window has only runtime status, restart, and About. No
Tauri default, wildcard, shell, generic filesystem, generic HTTP, opener, or window-creation
permission is present.

| Command | Surface and typed data | Effect and safe failure |
|---|---|---|
| `desktop_fetch` | main; bounded method/path/optional JSON body -> bounded HTTP-shaped response | Fixed active loopback target only; adds session in Rust; generic unavailable error. |
| `desktop_reload` | main; none -> none | Reloads only bundled content under navigation policy. |
| `desktop_print` | main; none -> none | Native print panel; no implicit file write. |
| `desktop_runtime_status` | both; none -> safe lifecycle status | No port, PID, session, path or private value. |
| `desktop_restart` | both; none -> safe lifecycle status | Rotates process/session; a successful recovery swaps safe-error for main. |
| `desktop_about` | both; none -> build/runtime metadata | No filesystem/network effect. |
| `desktop_select_import` | main; native choice -> safe preview | One selected SQLite path is revalidated by sidecar; no arbitrary frontend path. |
| `desktop_reveal_backup` | main; 24-hex ID -> none | Backend-verified basename under backup root; fixed `/usr/bin/open -R`; reject otherwise. |
| `desktop_report_action` | main; fixed report ID and `open|reveal` -> none | Verified child under report root; fixed Quick Look/Finder binaries only. |
| `desktop_diagnostics_preview` | main; none -> allowlisted JSON | Read-only sanitized health; no raw path/value/ID. |
| `desktop_export_diagnostics` | main; none -> boolean | Native save panel, symlink rejection, private `0600` JSON. |
| `desktop_set_operations_enabled` | main; boolean -> none | Enables/disables exact native menu IDs only. |
| `desktop_open_external` | main; exact URL -> none | Exact two-URL HTTPS allowlist passed as one `/usr/bin/open --` argument; no shell. |

Top-level navigation accepts only `tauri://localhost` (or Tauri's equivalent local asset origin)
at `/` or `/index.html`, with optional internal hash. Query strings, credentials, alternate ports,
remote/file/data/javascript/custom schemes and new windows are denied. The native click handler
opens only the Plaid dashboard and one IRS informational URL.

The CSP is:

```text
default-src 'none'; script-src 'self' https://cdn.plaid.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://cdn.plaid.com; font-src 'self'; frame-src https://cdn.plaid.com; connect-src https://sandbox.plaid.com https://production.plaid.com; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; media-src 'none'
```

`unsafe-eval`, wildcards, loopback frontend connections, remote development servers and source
maps are absent. `style-src 'unsafe-inline'` is retained only for current component/Plaid style
compatibility. Plaid documents `cdn.plaid.com` for Link's script/frame and its API hosts for
connections; `OV-04` remains the dedicated signed-WebView sandbox proof.

## Transport, storage, imports and secrets

Rust generates 32 random bytes per sidecar generation and writes the 64-hex session once through
an inherited Unix-domain socket duplicated to descriptor 3. The environment carries only the
descriptor number. The sidecar bounds and consumes the bootstrap JSON, closes the descriptor,
installs session/active port in process-private state, and removes the descriptor marker.
Shutdown uses a separate inherited Unix-domain socket duplicated to descriptor 63, outside the
PyInstaller one-file bootloader's internal low-descriptor range. It accepts only
the fixed bounded control record, and its nonsecret descriptor marker is removed before readiness.
Neither bootstrap nor lifecycle control uses stdin, arguments, files, WebView state, or loopback.
If the one-file bootloader does not preserve the control descriptor into its child, the native
supervisor sends a data-free `SIGTERM` to the isolated sidecar group. The child maps it to the same
graceful server exit, with a bounded `SIGKILL` retained only as the final cleanup fallback.

The server binds `127.0.0.1:0`. It requires one exact Host and session, at most one trusted Origin,
rejects duplicate security headers, Content-Length plus Transfer-Encoding, control bytes,
unsupported methods/content types, bodies above 1 MiB, more than 32 active requests, and non-API,
traversal or double-encoded paths. Preflight is allowed only from the exact trusted local origin,
without credentials. Responses are bounded and `no-store`.

Database startup requires a regular single-link file, stable identity, nonzero bytes, integrity,
foreign keys, the exact supported revision and required tables. Catalog and journal formats are
closed schemas with digest sidecars. Backup IDs, sizes, hashes, revisions and SQLite verification
must agree. Restore confirmations are one-use, five-minute, active-database-digest-bound tokens.

Import limits are 16 MiB/file and a 240-byte normalized filename. PDF is limited to 32 pages and
2 MiB extracted text with active-content markers rejected. XLSX allows at most 2,000 ZIP entries,
64 MiB expanded bytes and 100:1 compression ratio, with traversal, macros/executables, external
relationships and formulas rejected. CSV allows 100,000 rows, 256 fields, 16 KiB fields and 64 KiB
rows in UTF-8; spreadsheet-formula prefixes are rejected except ordinary negative numbers. JSON
is UTF-8 with nesting limited to 32 and 20,000 aggregate items. Rejection precedes parser/import
writes and returns no attacker-controlled text.

Keychain namespaces and account patterns are closed in `MacOSKeychainSecretStore`; all others
raise. The signed acceptance build wrote, read and deleted the synthetic item before it emitted
ready, and an independent `security find-generic-password` returned item-not-found afterward.
Production financial namespaces were never read. React now sends only `{environment}`; fixed
sidecar-owned native prompts collect the client ID and hidden secret without placing values in the
WebView, arguments or environment. Configuration writes roll back to the prior Keychain state if
any step fails.

## Campaign results

| Campaign | Result |
|---|---|
| A — malicious web content | PASS: live ordinary-browser page and iframe reported no Tauri internals; direct loopback fetch was blocked. Rust denied remote/file/data/javascript/custom top-level navigation, new windows and unapproved opener values. |
| B — unauthorized local client | PASS: 14 raw HTTP cases, 64 concurrent requests and 16 slow clients were rejected/closed; normal UI remained ready. |
| C — process/canary inspection | PASS: session absent from arguments/environment/files/logs/evidence; only nonsecret descriptor number remained. Fixed logs and diagnostics contained no seeded private canaries. |
| D — artifact tampering | PASS: 9/9 copied-bundle mutations rejected (replace, truncate, symlink, hard link, metadata, frozen archive/resource, database, source map, executable). |
| E — data/recovery tampering | PASS: corrupt/wrong database and catalog/journal/backup/confirmation/path substitutions failed without activating poisoned data. |
| F — hostile imports | PASS: complete PDF/XLSX/CSV/JSON/link/path corpus rejected within limits with no accepted-data change or network fetch. |

## Build, artifact, signing and dependencies

The accepted candidate is `/private/tmp/Money Map Slice4 Final Accepted.app`, built with a disposable
fake home and Keychain-acceptance marker, then deep-signed by Apple Development team
`E3G5D247ZN`. Strict deep verification and designated-requirement checks pass. The app is 55.4 MiB
(56,680 KiB). Native SHA-256 is
`ba3b4aa6aebb7acccb36b055051d86b19976ad559b03044d35028a7c28043b37`; sidecar SHA-256 is
`aa23f3175059fd58aab214804b11edfd8721ea25b2d8a26b450c23baf77dcdaa`. The extracted scan passes
4 bundle files, 384 sidecar archive entries and 1,935
frozen modules, including all migrations through `0009` and all security modules; it rejects
private/development paths, databases, reports, backups, source maps, canaries and unapproved code.

The accepted owner-machine build intentionally does not enable hardened runtime: the PyInstaller
one-file extraction contains nested ad-hoc runtime code, so the separate hardened-runtime
experiment failed closed before sidecar startup. Developer ID, nested-code layout, hardened
runtime, notarization and stapling remain mandatory Slice 5 work and were not weakened here.

Python (70 locked packages), npm production (3 packages), and Rust (497 locked crates) advisory
audits reported no known vulnerabilities. RustSec also reported 17 allowed warnings: 10
unmaintained GTK3-family crates, `glib` unsoundness, `proc-macro-error`, and five unmaintained
`unic-*` crates. The GTK/`glib`/`proc-macro-error` entries have no Apple Silicon target path; the
`unic-*` entries are build/runtime transitive Tauri URL-pattern dependencies and are maintenance
not vulnerability advisories. They are accepted without a broad Tauri upgrade and remain a Slice
5 re-audit item. All non-workspace sources are registries; no unintended Git/path dependency was
found. The sanitized inventory records package name/version/source only in ignored evidence.

## Residual and owner-dependent validation

- `OV-01` through `OV-10` remain queued and unperformed; Slice 4 adds `OV-11`.
- `OV-04` remains the real signed-WebView Plaid sandbox/CSP proof.
- `OV-11` is the owner-observed Keychain ACL/authorization behavior for the installed packaged
  identity. The library proves exact namespaces and signed write/read/delete, but not denial to a
  differently signed helper without an owner-facing Keychain authorization event.
- Unkeyed recovery metadata detects corruption, not a same-user attacker who rewrites both content
  and digest. No hidden recovery key was invented.
- A fully compromised logged-in macOS account can inspect process memory, control the WebView,
  modify user-writable data or observe displayed values. FileVault, login security and malware
  prevention remain outside the application's local-only boundary.
- Developer ID/hardened runtime/notarization is Slice 5, which was not started.

No owner database, production Application Support home, production financial Keychain item or
provider was accessed. Nothing was pushed, tagged, uploaded, published, deployed or released.
