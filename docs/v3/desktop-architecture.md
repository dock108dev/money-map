# Money Map v3 desktop architecture

Status: frozen by Slice 0, productionized by Slice 1, extended by Slice 2 data-home recovery, and
completed at the Slice 3 product-experience boundary for the Apple Silicon owner beta.

## Decision

Money Map uses one native shell and one sidecar builder:

- **Shell:** Tauri 2, with WebKit/WKWebView and the existing compiled React application.
- **Service:** the existing Python/FastAPI application, frozen as a one-file Apple Silicon
  executable by **PyInstaller 6.x**.
- **Authority:** SQLite remains the financial-data authority and macOS Keychain remains the
  secret authority. Rust does not reproduce financial logic and React is not rewritten.

The Slice 1 runtime remains deliberately disposable and synthetic. It stays at application version
`2.1.0` and schema `0009_goal_persistence`; production data-home and migration work begin only in
Slice 2.

## Ownership and process lifecycle

The Tauri process owns the application window, menus, route-preserving reload, native print
panel, native file chooser, startup, readiness, and shutdown. Its process tree is:

```text
Money Map.app/Contents/MacOS/money-map-desktop
  -> Money Map.app/Contents/MacOS/money-map-sidecar
     -> PyInstaller-extracted Python/FastAPI runtime
```

At launch, Tauri generates a cryptographically random 256-bit session and starts the sidecar
without command-line arguments. It creates a private Unix-domain socket pair, duplicates the child
end to descriptor 3, clears close-on-exec, writes one bounded bootstrap JSON record from the parent,
and closes both ends after delivery. The cleared child environment contains only trusted mode/path
markers and the nonsecret descriptor number. The sidecar consumes and closes that descriptor and
removes its marker before readiness. The session never enters an environment value, URL, WebView,
storage, file, log, diagnostic, database, crash message, artifact, evidence, or argument.

The shell also creates a second private Unix-domain socket pair, duplicates its child end to
descriptor 4, and retains only the parent writer. The sidecar consumes the fixed bounded shutdown
record from that descriptor. This avoids PyInstaller bootloader stdin behavior while keeping
control out of arguments, files, logs, the WebView, and the network.

The shell owns an explicit `Starting`, `Ready`, `Failed`, `Restarting`, `Stopping`, and `Stopped`
state machine. Every generation receives a new session and exactly one process group. The sidecar
reserves an OS-selected port by binding `127.0.0.1:0`, then prints only `MONEY_MAP_READY <port>`.
The shell bounds the signal wait to 30 seconds and authenticated health readiness to 45 seconds,
while continuing to monitor process termination after readiness. Unexpected death clears the dead
port and session, hides stale controls, and shows one deliberate restart action; there is no
automatic retry loop.

On restart or application exit, Tauri writes `shutdown` to the private control descriptor and
allows 1.5 seconds for clean
Uvicorn, SQLite, and writer-lock shutdown. It then kills the entire isolated process group as a
fallback and independently waits up to five seconds for the group and listener to disappear. The
shell explicitly removes its temporary parent after shutdown rather than relying on process-exit
destructors.

The official Tauri single-instance plugin is registered before setup. A second launch shows,
unminimizes, and focuses the existing window before any second sidecar can start. Independently,
the Python boundary takes a nonblocking OS file lock scoped to the selected data root before the
database is initialized. Clean shutdown removes the lock file; a stale file is replaced only after
the OS lock is successfully acquired, which proves that no active owner holds it.

## Bundle and immutable resources

`desktop/runtime-resources.json` is the checked-in inventory and an automated test compares its
Python module and migration lists with the source tree. `scripts/build_desktop_runtime.sh`:

1. compiles the React production assets;
2. freezes every `paycheck_map` submodule plus locked third-party dependencies, Keychain
   backends, Alembic environment/revisions, and configuration into one PyInstaller executable;
3. gives the executable Tauri's target-triple sidecar name; and
4. bundles it and the React assets inside `Money Map.app`.

Tauri embeds the compiled React assets in its resource binary. The sidecar includes package
metadata/version, all migration revisions through `0009_goal_persistence`, SQLite initialization,
the approved contribution-limit configuration, report code, and required native libraries.
There is no Python, Node, source checkout, or network download requirement at runtime.

Desktop settings resolve immutable resources only from the frozen PyInstaller root. Focused tests
may supply an explicit synthetic test-project root; the production shell clears inherited
environment and never supplies that override. There is no production repository fallback. The
artifact scan rejects databases, `.local`, statements, backups, source maps, repository-private
path markers, and required-resource omissions.

## React and API transport

Tauri's asset protocol loads `index.html`; desktop navigation is hash based (`#view=...`) so a
deep view survives WebView reload without asking the sidecar to serve frontend files. The native
initialization script intercepts only relative `/api/` fetches. It invokes a narrow Rust command
that accepts GET, POST, PUT, and DELETE; rejects traversal, encoded traversal, newlines, malformed
paths, unsupported methods, and bodies over 1 MiB; and adds the secret session inside Rust. A
maintained HTTP client handles content-length and chunked framing with a two-second connect bound,
a ten-second I/O and total bound, an 8 MiB response cap, a safe response-header allowlist,
hop-by-hop header exclusion, and `no-store`. JavaScript can neither read the session nor choose the
host, port, arbitrary headers, or destination.

The FastAPI wrapper independently requires:

- an exact `Host` of `127.0.0.1:<port>`;
- no origin or an origin of exactly `tauri://localhost` or `http://tauri.localhost`; and
- exactly one constant-time match of `X-Money-Map-Session` for every non-preflight request.

It also rejects duplicate Host/origin/session/content-length fields, Content-Length combined with
Transfer-Encoding, ASCII controls, unsupported content types/methods, bodies above 1 MiB, more
than 32 active requests, traversal and double encoding. Preflight is permitted only for the exact
trusted local origin and never enables credentials.

Responses are `no-store`. An ordinary browser does not possess the session, while a hostile
origin and a misleading host are rejected even if a session were supplied. The Python boundary
also independently rejects non-API and traversal paths, unsupported methods, and oversized bodies.

## Persistent macOS storage contract

Slice 2 makes Tauri the one path provider. It derives the production home from the macOS user
Library and passes only the resolved application, cache, and log roots through the cleared child
environment. Python validates that trusted boundary again and remains the only SQLite process.
Production launch accepts no repository or current-working-directory fallback. Signed synthetic
acceptance uses a build-time-only fake-home value rooted below `/private/tmp`; ordinary production
builds contain no runtime path override.

The versioned `money-map-macos-data-home-v1` layout is:

- application root: `~/Library/Application Support/Money Map/`
- SQLite: `data/paycheck-map.sqlite3`
- manual-import inbox: `inbox/payroll/`, `inbox/sofi/`, and `inbox/fidelity/`
- reports: `reports/`
- verified SQLite backups: `backups/`
- isolated staging and rollback material: `migration/`
- digest-only recovery journal and backup catalog: `state/`
- cache: `~/Library/Caches/com.moneymap.desktop/`
- safe diagnostic logs: `~/Library/Logs/Money Map/`

Only the Python sidecar opens SQLite. It remains the sole writer and retains exact decimals,
provenance, reconciliation, goal, retirement, Life Lab, payroll-baseline, and read-only Plaid
semantics. Runtime files are never written into the application bundle or repository.

Every owned directory is mode `0700` and every accepted database/backup is mode `0600`. Existing
symlinks in any root or artifact chain are rejected. Source/destination identity and hard links,
app-bundle/repository relationships, non-approved backup parents, and cache/log/data overlap fail
closed. Diagnostics contain safe codes and classifications only.

## Initialization, migration, and recovery

The durable state machine covers fresh setup, explicit candidate selection, read-only inspection,
preview and confirmation, online backup, isolated restore, staging validation, optional packaged
Alembic migration, logical-manifest validation, activation, completed/idempotent state,
recoverable failure, resume, rollback, restore preview, restore, and completion.

Fresh setup upgrades only a staging database through `0009_goal_persistence`, verifies integrity,
foreign keys, schema, and its logical manifest, fsyncs the staged file and directory, then atomically
renames it into the active data directory. It creates no financial rows.

Existing-data import never scans. A native chooser sends the selected database directly from Rust
to the authenticated Python boundary; the frontend receives only safe classification, revision,
size, required space, and confirmation state. Inspection uses SQLite read-only/query-only mode and
records no journal. Confirmation creates and verifies an online SQLite backup, restores that backup
to isolated staging, upgrades only staging when required, compares every pre-existing logical
domain, fsyncs, and activates only the verified result. The source identity and bytes are checked
again after activation and the source is retained.

Replacement keeps three distinct artifacts: the verified pre-replacement backup under `backups/`,
the old accepted database as the rollback pointer under `migration/`, and the fully verified
staging database. The old active file is atomically renamed to rollback, staging is atomically
renamed active, the directory is fsynced, and post-activation digest/schema/manifest verification
must pass before journal completion. Restart uses the journal and digests to choose exactly one of
finalize, resume, or rollback.

Manual backup uses SQLite's online backup API and verifies distinct inode, nonzero size, SHA-256,
integrity, foreign keys, revision, and logical manifest before cataloging it. Restore re-verifies
the chosen approved backup, creates and verifies a pre-restore safety backup, restores into staging,
and uses the same replacement contract. Finder reveal accepts only a backend-verified catalog ID
and a basename under the Tauri-resolved backup root.

Plaid credentials and access tokens remain in macOS Keychain under exact versioned Money Map
service/account allowlists. Fixed sidecar-owned native macOS prompts collect the client ID and
hidden secret without values entering React, API request bodies, arguments or environment. Failed
multi-item configuration restores the prior Keychain state. Credentials must never enter SQLite,
frontend storage, logs, crash output, artifacts, diagnostics or evidence; manual import remains a
permanent fallback.

Slice 4 also creates a separately labeled `safe-error` WebView. It contains no financial data and
has only runtime-status, restart and About permissions. Startup integrity failure hides `main` and
shows this surface; successful deliberate recovery restores the main window. Navigation and new
windows fail closed on both surfaces.

## Plaid, printing, and file selection

The existing Plaid Link loader and callback design remain intact: the WebView may load the
official Plaid Link script and frames under the bundle CSP, receives the public token only in
memory, and sends it through the native authenticated API transport. The CSP allows the Plaid
script host and Plaid/Plaidusercontent frames while keeping API connectivity on loopback. No
safe sandbox client ID and secret were independently available, so Slice 0 did not request a Link
token or contact Plaid. The exact remaining external proof is: provide dedicated Plaid sandbox
credentials, obtain a sandbox Link token, open Link in the signed WebView, and observe its callback
through the native transport without exposing secrets.

`window.print()` is mapped to the Tauri WebView print API and displayed the real macOS print
sheet. The desktop-only file input displayed the real macOS open panel. No file was selected and
no print output was created during the proof.

Slice 3 adds the complete native File, View, Window, and application menus; route-synchronized
keyboard navigation; explicit hide-on-close and reopen behavior; resume health validation; approved
report identities with Quick Look/Finder actions; and native sanitized-diagnostics export. The
complete interaction, focus, printing, and allowlist contracts are in
`docs/v3/desktop-product-experience.md`.

## Signing and distribution

The bundle contains the native executable, the target-triple external binary copied to the final
`Contents/MacOS/money-map-sidecar` name, Tauri-embedded React assets, and `Info.plist`. Slice 0's
extracted app was deep-signed with the installed Apple Development identity, passed strict deep
signature verification, and executed after being copied outside the repository.

PyInstaller's extracted CPython library receives an ad-hoc runtime signature, so combining this
one-file layout with hardened runtime produced a Team-ID validation failure during the spike. The
owner-only proof therefore uses Apple Development signing without hardened runtime. Before any
external distribution, a separately authorized path must use a Developer ID Application identity,
hardened runtime, notarization, stapling, and Gatekeeper assessment, and must resolve the nested-
runtime signing layout (for example by signing a one-folder sidecar's nested code explicitly). A
DMG is not a Slice 0 artifact.

## Why this architecture won

Tauri passed bundled launch outside the repository, visible React startup, deep navigation and
reload, authenticated API access, negative host/origin/session checks, native printing, native
file selection, real Keychain write/read/delete, safe startup failure, child cleanup, strict
Apple Development signature verification, and signed execution. It keeps the existing product
and financial engine while giving one native process lifecycle ownership.

The one permitted fallback—a Python-native WKWebView shell—was rejected without implementation.
There was no failed required Tauri capability to justify maintaining or testing a second shell,
and it would mix shell and service responsibilities while providing a weaker packaging path.

## Slice 4 security hardening

The complete capability table, CSP, navigation policy, Keychain decision, import budgets,
database/recovery integrity gates, signed build evidence and attack campaigns are in
`desktop-threat-model.md` and `security-acceptance.md`. The owner-machine bundle verifies the whole
Apple Development team signature before sidecar spawn. Developer ID, a nested-code layout that can
support hardened runtime, notarization and stapling remain external-distribution work.

## Slice 5 packaging boundary

`scripts/package_desktop_release.py` is the only release-packaging entrypoint. It builds from a
fresh archive of an exact clean commit in a private disposable root, uses the frozen uv, pnpm and
Cargo graphs offline, generates the ICNS from checked-in public artwork, packages the existing
PyInstaller one-file sidecar and Tauri shell, signs all native code inside-out, creates the
two-entry owner-candidate DMG, and runs artifact/privacy verification. Sanitized manifests and
independent-build comparisons are described in `desktop-packaging.md`. Runtime topology, CSP,
capabilities, authenticated pipe/loopback transport, Keychain namespaces, and data-home contracts
do not change.

## Deferred risks

- Owner validation: a real Plaid sandbox Link run after dedicated sandbox credentials are supplied.
- Slice 5: deterministic owner-candidate build, Apple Development signing, DMG, scans,
  reproducibility evidence, and isolated installed-artifact proof.
- External distribution: Developer ID, hardened runtime, notarization, stapling, downloaded-copy
  Gatekeeper assessment, and externally appropriate nested-code layout.
- PyInstaller one-file extraction adds startup cost and transient files; later profiling may choose
  a signed one-folder layout while preserving PyInstaller as the frozen builder.
