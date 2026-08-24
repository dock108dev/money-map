# Security hardening findings

Status: implemented and source-validated, 2026-08-23. This document describes the current source
tree, including the adjacent uncommitted production error-handling changes. It does not promote the
3.0.0 beta candidate, authorize owner-data access, or approve external distribution.

## Security understanding

Money Map is a single-owner, local-first financial application. It has no public accounts, roles,
admin tier, multi-tenant authorization, cookies, password reset, invites, webhooks, queues, payment
processing, analytics, or money-movement authority. The supported surfaces are:

1. The standalone browser process at exactly `http://127.0.0.1:8765`.
2. The bundled Tauri WebView with a narrow command capability set.
3. The Rust-to-Python sidecar proxy, authenticated by a generation-specific 256-bit session.
4. The Python service and its single local SQLite writer.
5. Explicit manual PDF/XLSX/CSV/JSON imports under approved private roots.
6. Optional read-only Plaid calls whose credentials and item tokens live in macOS Keychain.
7. Owner-selected report, backup, restore, and sanitized-diagnostics filesystem operations.

The desktop renderer has no generic shell, filesystem, HTTP, opener, or window-creation authority.
The sidecar validates Host, session, origin, framing, path, method, content type, size, response,
and concurrency. Database activation, restore, import, and reporting use separate identity,
integrity, path, and atomic-write controls documented in the desktop threat model.

## Fixed findings

| ID | Finding | Category | Severity / confidence | Evidence and realistic abuse | Implemented status |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | Standalone localhost request forgery and DNS-rebinding boundary | Authentication / request integrity | High / high | `app` previously trusted any Host/origin reaching the loopback port. A hostile page or rebound hostname could target mutation routes such as import, refresh, report, or payroll regeneration. | Fixed. `LocalSecurityMiddleware` requires exact Host, rejects foreign Origin and `Sec-Fetch-Site`, JSON-gates mutations, rejects ambiguous headers/methods/paths, and bounds body size and concurrency. |
| SEC-02 | Missing browser security and privacy headers | XSS / clickjacking / data exposure | Medium / high | Standalone HTML and API responses previously lacked CSP, frame denial, MIME-sniff protection, referrer policy, permissions policy, noindex, and uniform `no-store`. | Fixed. Every standalone response replaces conflicting cache policy and adds the documented header set. CSP retains only the existing Plaid hosts and adds same-origin API access. |
| SEC-03 | Unnecessary framework documentation surface | Information exposure | Low / high | FastAPI exposed `/api/docs` and its schema even though operator documentation does not depend on it. | Fixed. Swagger, ReDoc, and OpenAPI routes are disabled, and reserved documentation/API paths cannot fall through to the SPA. |
| SEC-04 | Failed private-data status could become false readiness | Authorization / data integrity | High / high | The desktop UI converted any status-request failure into `{ready: true, phase: already_migrated}` and could continue to financial APIs without verified private-data state. | Fixed. The UI blocks, displays a safe status error, and requires an explicit successful retry. |
| SEC-05 | Partial Keychain rollback ambiguity | Credential integrity | High / high | A failure while restoring earlier Plaid configuration could mask the original setup failure and leave unclear mixed values. | Fixed. Every prior value is attempted; incomplete rollback raises a distinct safe `SecretStoreError` and setup cannot proceed. |
| SEC-06 | Security-relevant secondary failures lacked durable distinction | Auditability | Medium / high | Fatal sidecar exit and derived goal-currentness/check-in failures were safe to users but not separately observable across recurrence. | Fixed. Fixed-schema codes record fatal lifecycle and goal-observation failures without values, paths, identifiers, or exception text. |
| SEC-07 | Missing backup evidence could be reported verified | Diagnostic integrity | Medium / high | The native fallback returned zero backups with `all_verified: true` when the backend field was absent. | Fixed. Missing evidence is `status: unavailable` and `all_verified: false`. |

## Intentional acceptable patterns

- API object identifiers are not tenant authorization boundaries. There is one local owner, the
  desktop API requires its private sidecar session, and the standalone surface is exact-loopback
  only. Returned financial detail is the owner-facing product, not an excessive cross-user result.
- Broad catches at the per-connection refresh orchestration boundary retain successful connections
  while producing explicit failed connection results and durable sync-run state. They do not turn
  partial refresh into complete currentness.
- Goal-observation persistence is derived evidence. Its failure rolls back only that transaction,
  returns `unavailable/retryable`, and does not undo committed source financial data.
- HSTS and secure-cookie attributes do not apply: standalone mode is plain loopback HTTP and the
  application has no cookies. Network or reverse-proxy deployment is unsupported.
- CSP `style-src 'unsafe-inline'` is retained for the current React/Plaid style path. Script
  execution still excludes inline script, eval, wildcards, arbitrary frames, objects, workers,
  forms, and unapproved network destinations.

## Deferred or decision-required findings

1. **External macOS distribution identity — High.** Developer ID Application signing, a proven
   hardened-runtime-compatible nested-code layout, notarization, stapling, and clean downloaded-copy
   Gatekeeper assessment remain mandatory before external distribution. Do not weaken this gate.
2. **Same-user process access to standalone mode — Medium.** Exact Host/origin and browser request
   controls stop web-origin attacks, but another process already running as the owner can call the
   standalone port. If standalone mode becomes an end-user production path, add a launch-specific
   secret delivered outside URLs/storage, rotate it on restart, and require it on every API call.
   The packaged desktop path already has this design.
3. **Unkeyed recovery metadata — Medium.** Digests detect corruption but not a same-user attacker
   able to rewrite both metadata and digest. A future design can authenticate metadata with a
   versioned Keychain-held HMAC key plus explicit rotation/recovery behavior.
4. **Inline styles — Low.** Removing `style-src 'unsafe-inline'` requires a coordinated style/CSP
   refactor and a real signed Plaid Link campaign. Use hashes/nonces or extracted styles only after
   proving component and provider compatibility.
5. **Provider and Keychain owner proof — Medium.** Real Plaid CSP behavior, consent flows, Keychain
   ACL prompts, revocation, and provider-side retention require the existing owner-authorized
   installed-app campaigns. Synthetic tests cannot establish those facts.

## Manual and dependency verification

- Fresh 2026-08-23 locked audits found no known Python, npm production, or Rust vulnerabilities.
  RustSec reported the same 17 allowed warnings: ten GTK3-family maintenance warnings,
  `proc-macro-error` maintenance, five `unic-*` maintenance warnings, and the known `glib`
  iterator unsoundness warning. These remain dependency-hardening items rather than confirmed
  reachable Apple Silicon vulnerabilities; re-audit them before every candidate.
- A fully compromised logged-in macOS account remains outside the application boundary and can
  inspect process memory, displayed values, and user-writable files. FileVault, login protection,
  malware prevention, and physical custody remain owner/OS controls.
- Advisory results are point-in-time evidence. Run Python, npm, and Rust audits against the locked
  dependencies for every candidate and review maintenance-only Rust warnings separately from known
  vulnerabilities.
- No claim in this document replaces signed installed-app, Gatekeeper, Keychain, Plaid, offline,
  sleep/wake, or owner cutover validation.
