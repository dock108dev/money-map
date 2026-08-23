# Money Map desktop threat model

Version: `slice4-v1` (2026-08-22). Runtime `2.1.0`; schema `0009_goal_persistence`.

## Assets and boundaries

Protected assets are the active SQLite database, verified backups and rollback material, imported
documents, reports, financial values and identifiers, Plaid client credentials and item tokens,
the per-generation desktop session, recovery metadata, and the integrity of the signed app and
sidecar. Trust boundaries are: ordinary browser to loopback; bundled main WebView to Rust; remote
Plaid frame to bundled page; Rust to the private bootstrap pipe and sidecar; sidecar to SQLite and
Keychain; filesystem input to import/recovery parsers; and build inputs to the signed bundle.

Entry points are WebView navigation/new-window requests, the 13 permissioned Tauri commands,
loopback HTTP, the inherited bootstrap descriptor, native file selection, the private inbox,
SQLite/backup/catalog/journal files, Keychain calls, approved external links, and frozen build
resources. Attackers include malicious web content, an unprivileged local process, crafted files,
a person modifying a copied bundle, and a same-user process able to inspect owner processes.

## Threat and control matrix

| # | Threat and capability | Prevention and detection | Recovery, evidence, and residual risk |
|---|---|---|---|
| 1 | Malicious ordinary website probes loopback or imitates the UI. | Ephemeral IPv4 `127.0.0.1`, 256-bit session, exact Host/origin/header rules, no credentialed CORS. | Campaign A and 78-request Campaign B. A fully compromised browser in the owner account can still attempt traffic but does not possess the session. |
| 2 | Top-level WebView navigation to remote, `file:`, `data:`, `javascript:`, or custom content. | Rust accepts only the bundled Tauri origin and root/index paths; queries, credentials and new windows fail closed. | Rust navigation matrix plus signed-app bundled-origin observation. Denial leaves the accepted UI loaded. |
| 3 | Malicious iframe or Plaid frame seeks native authority. | Capabilities match exact local window labels; Plaid receives CSP frame/script access, never a capable window label. | Live hostile iframe reported no Tauri internals. `OV-04` retains the real sandbox-Link CSP proof. |
| 4 | Frontend script compromise invokes excessive native authority. | Thirteen typed, reviewed commands; no shell/fs/http/opener/window primitives; Rust adds session and fixed destination. Separate safe-error window has only status/restart/About. | Command/capability equality test. Compromised bundled script can invoke the reviewed main commands, so input and state validation remains mandatory. |
| 5 | Unauthorized local process connects directly. | Secret pipe, constant-time authentication, exact port/Host, bounded methods/body/response/concurrency and ambiguity rejection. | Python header matrix and Campaign B. Same-user debugging rights remain an OS boundary. |
| 6 | Same-user process inspects arguments, environment, files, output or logs. | Session is passed once over inherited descriptor 3, removed from child state, never supplied to JavaScript or files; safe event codes only. | Process inspection and canary scans. A fully compromised account can attach to memory or replace trusted user files and is not solved locally. |
| 7 | Duplicate/replayed session or replay after restart. | One session per generation; process-private single install; restart clears old session/port before new generation. | Entropy/replacement Rust test, stale/wrong/duplicate probes, restart campaign. |
| 8 | Modified app bundle or sidecar executes. | Regular single-link arm64 sidecar at exact path; whole-bundle strict Apple Team signature verification before spawn; artifact extraction scan. | Nine copied-bundle mutations rejected. Apple Development signing is owner-machine acceptance only; Developer ID/notarization remains Slice 5. |
| 9 | Crafted import exhausts resources, escapes paths, runs active content, or causes a fetch. | Central filename/file/link limits; PDF, ZIP/XLSX, CSV and JSON structural budgets; traversal, macro, executable, external relationship and formula rejection. | Hostile-import matrix; rejection occurs before hashing/parsing or data writes. Parser/library bugs within accepted limits remain possible. |
| 10 | Tampered SQLite database starts normally. | Regular single-link identity check before/after read, nonempty file, SQLite integrity/foreign keys, exactly one supported revision and required-table contract. | Data tamper tests; readiness fails and the safe-error window replaces the financial surface. |
| 11 | Poisoned backup, catalog, journal or rollback pointer becomes active. | Exact schemas, SHA-256 metadata sidecars, derived IDs, duplicate rejection, verified SQLite contents, one-use digest-bound restore token. | Recovery tamper matrix; last accepted database is retained. A same-user attacker able to rewrite an artifact and its unkeyed digest is residual. |
| 12 | Symlink, hard-link, traversal or path race changes a selected target. | Root/parent checks, regular/nlink-one enforcement, lexical normalization, identity rechecks, confirmation expiry/consumption and source binding. | Filesystem and TOCTOU tests. APFS/macos kernel integrity and the owner account remain trusted. |
| 13 | Secrets/private values leak through logs, diagnostics, crashes, artifacts or evidence. | Fixed log schema/codes; sanitized diagnostics; generic exceptions; no bodies, paths, IDs, values or environment dumps; archive and canary scans. | Safe-log/canary tests and extracted scan of 384 entries plus 1,935 modules. In-memory values can be read by a fully compromised account. |
| 14 | Dependency/build input is compromised. | Frozen uv/pnpm/Cargo locks; registry-source inventory; RustSec, Python and npm advisory audits; no unreviewed Git/path runtime dependency; signed output scan. | Audit results are frozen in `security-acceptance.md`. Registry or toolchain compromise is not eliminated by lockfiles alone. |
| 15 | Physical access or compromised macOS account. | macOS Keychain, code signing, private modes, local-only design and owner-controlled backups reduce casual exposure. | FileVault, login security, malware prevention and physical custody are owner/OS responsibilities. Money Map cannot protect plaintext shown to, or memory/files controlled by, a fully compromised logged-in account. |

## Key security contracts

The main and safe-error WebViews have separate exact capability files. Remote frames cannot acquire
a local window label. The main page has no direct loopback network permission: its `/api/` call is
converted into a typed Tauri invocation, and Rust supplies the private destination and session.
The CSP defaults to deny, disallows objects, forms, workers, media, arbitrary bases and framing,
and grants only bundled content plus the documented Plaid hosts.

Plaid configuration is requested by the signed sidecar through fixed `/usr/bin/osascript` native
dialogs. Credential values do not enter command arguments, environment variables, request bodies,
React state or responses. They are written under versioned service
`com.moneymap.desktop.secrets.v1.plaid.config`; item tokens use the exact `plaid.items` namespace.
The packaged acceptance mode uses only `slice4.acceptance/slice4.signed-app`, proves
write/read/delete before readiness, and then uses an in-memory store so production financial
entries cannot be queried. The Python keyring API does not expose a portable way to assert a
different unsigned helper's ACL denial without provoking owner authorization; this exact packaged
ACL proof is queued as `OV-11` and no broad access group or entitlement was added.

Metadata digests detect accidents and partial corruption, but they are not authentication against
a malicious process already acting as the owner. An authentication key would introduce custody,
backup and loss-recovery consequences, so Slice 4 does not invent one. The local architecture's
hard boundary is an uncompromised macOS account and trusted OS/keychain/signing implementation.
