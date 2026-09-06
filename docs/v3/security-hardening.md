# Security hardening findings

Current source review: **2026-09-06**, baseline `193eb68`. The September changes are local and
uncommitted. This record describes source behavior; prior signed-app campaigns are historical
and do not qualify these changes for release or owner cutover.

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

## September findings: confirmed boundary defects

These findings distinguish demonstrated behavior from hypothetical downstream exploitation. No
critical issue or demonstrated unauthenticated remote takeover was found in this pass.

| ID / title | Category / affected area | Severity / confidence | Why it matters, scenario, and code evidence | Fix / status |
| --- | --- | --- | --- | --- |
| SEC-08 — Rejected secrets reflected in validation responses | Sensitive-data exposure; `app.py`, `api_inputs.py` | Medium / high | A synthetic extra `secret` field sent to `/api/plaid/configuration` came back verbatim in FastAPI's 422 `input` field. Nested input and field names can also carry private values into client error handling. This demonstrates unnecessary reflection to the caller, not disclosure to an unrelated user. | **Fixed.** A global request-validation handler returns a fixed 422 message without input, context, locations, or exception strings. Exchange input rejects extra fields and bounds session/token lengths. |
| SEC-09 — Workbook policy bypass by XML spelling | Untrusted-file validation; `import_security.py` | Medium / high | `TargetMode = "External"` passed the former literal-byte filter. Namespace prefixes, character references and UTF-16 also evade byte matching. Such files bypassed the documented acceptance policy; no external fetch or formula execution was demonstrated. | **Fixed.** Parse bounded workbook XML, reject DTDs, external relationships and worksheet formula elements by structure; reject duplicate/encrypted ZIP entries. Tests cover whitespace, entity spelling, namespaces and UTF-16. |
| SEC-10 — Body admission can be renewed indefinitely | Resource exhaustion; both Python security middleware classes | Medium / high | The former two-second timeout restarted after every chunk, and zero-length chunks accumulated without a count bound. A local client able to submit accepted headers could occupy the 32 admitted requests indefinitely with slow bodies. | **Fixed.** One two-second deadline covers the entire body; at most 1,024 chunks and 1 MiB are accepted. Existing `finally` cleanup releases capacity. Desktop Content-Type and Transfer-Encoding duplicates are rejected. |

## September hardening opportunities implemented

These are code-backed improvements whose wider exploitation depends on additional conditions;
they are not claims of demonstrated cross-user compromise.

| ID / title | Category / affected area | Severity / confidence | Realistic condition and code evidence | Fix / status |
| --- | --- | --- | --- | --- |
| SEC-11 — Transport authority broader than intended | Session handling; Rust `proxy.rs` | Medium / high | The client used default redirects and environment proxy discovery while adding a custom session header. A future or erroneous redirect could escape the fixed loopback destination. No current API route producing an external redirect was identified. | **Fixed.** Disable redirects and environment proxies. A two-listener synthetic test verifies a 302 is returned without contacting its destination. |
| SEC-12 — Sensitive connection operations can overlap | Credential/consent integrity; `api_plaid.py` | Medium / high | Refresh held an operation lock, but configuration changes, exchange, reconnect-token issuance and revocation did not. Concurrent owner/API requests could change credentials or consent while synchronization was using them. | **Fixed.** Those six routes share the existing refresh guard and return 409 while busy, before invoking prompts or providers. Status reads remain available. Tests prove guarded callbacks are not reached. |
| SEC-13 — Standalone private directories inherit permissive modes | Local storage/configuration; `config.py` | Medium / high | `mkdir` used the process umask. A private root under a traversable/shared parent could be readable by other OS users; actual exposure depends on parent permissions. Direct Settings use also allowed unsupported host values despite the CLI guard. | **Fixed.** Explicit private root/inbox/data/report/backup directories use 0700, existing modes are tightened, and symlink directory targets fail. Settings restricts Host to `127.0.0.1` and port to 1–65535. This is not a same-user sandbox. |
| SEC-14 — Predictable report temp and non-atomic export writes | File handling; `reporting.py`, native diagnostics export | Medium / high | A shared report temporary filename could race another report write or follow a preplaced link. Diagnostics wrote directly to a selected target before tightening its mode. Link substitution requires filesystem access; already compromised owner processes remain out of scope. | **Fixed.** Exclusive 0600 temporary files, fsync and atomic replacement. Native export rejects nonregular and multiply linked existing destinations. Cancellation still writes nothing. Tests preserve link targets and verify replacement/permissions. |
| SEC-15 — Ambiguous JSON and untrusted Link error text | Input/privacy hardening; import JSON, `plaid-link.ts` | Low / high | JSON accepted duplicate fields/non-finite constants; extreme nesting could become an uncontrolled parser exception. Plaid Link copied third-party error strings directly into the local UI. | **Fixed.** Reject duplicate/non-finite JSON and classify recursion failure safely; Link exit uses fixed text. Normal user cancellation remains a successful no-op. |

## Previously implemented controls retained

The earlier SEC-01 through SEC-07 source controls remain: exact standalone Host/origin and fetch-site
checks; restrictive privacy/browser headers; disabled API documentation; fail-closed data-home
readiness; explicit Keychain rollback failure; private-safe lifecycle/observation events; and
unavailable rather than verified missing backup evidence. See [error handling](error-handling.md)
for the current failure contract, including the September commit, logging, provider-normalization,
provenance, and native-cleanup fixes. Historical August installed campaigns are recorded in
[security acceptance](security-acceptance.md); they are not fresh September candidate evidence.

## Intentional acceptable patterns

| Pattern / category | Severity / confidence | Rationale / status |
| --- | --- | --- |
| Single-owner object access / authorization | Informational / high | **Accepted.** Object IDs select the owner's data, not tenants. The Admin disclosure is a UI grouping, not a role boundary. There are no accounts, invites, password resets, webhooks, payment/entitlement endpoints or server queue workers. |
| Local HTTP without HSTS or cookies / transport | Informational / high | **Accepted.** Exact loopback service, no cookies, no network/reverse-proxy deployment. Desktop requests carry the private session outside the renderer; standalone browser-origin restrictions are not local-process authentication. |
| ORM queries and trusted process arguments / injection | Informational / high | **Accepted.** Owner input is bound through SQLAlchemy or validated fields; correction attribute names are allowlisted. Native external links and commands are exact/fixed, argument arrays are used, and the child environment is cleared. No owner input is evaluated as code. |
| React escaping and HTML report escaping / rendering | Informational / high | **Accepted.** React renders text and report strings use escaping. No arbitrary HTML or markdown execution surface was found. Inline styles remain required by the current UI; removing them needs compatibility work. |
| Partial sync/import and optional observation / error handling | Informational / high | **Accepted.** Explicit failure status, rollback boundaries and private-safe events preserve independent successes without claiming complete currentness. Auto-refresh is a UI request with a process lock and daily attempt guard, not a hidden scheduler. |
| Local bounded diagnostics / privacy | Informational / high | **Accepted.** Fixed codes and safe source locations only; no remote analytics, raw payload logs or secrets in browser storage. Routine denied requests are not logged individually to avoid unbounded noise; their responses are explicit denials. |

## Prioritized decisions and deferred work

| Priority / title | Category / affected area | Severity / confidence | Scenario, evidence and concrete next step | Status |
| --- | --- | --- | --- | --- |
| 1 — External distribution identity and candidate proof | Deployment; signed application | High / high | New source is not the old signed candidate. Build and qualify an exact candidate, then prove Developer ID/notarization/stapling and downloaded-copy Gatekeeper behavior before external distribution. Retain the existing authorization and owner-data boundaries. | **Deferred**, separate release work. |
| 2 — Third-party script in privileged renderer | Supply chain; `web/src/plaid-link.ts`, main capability/CSP configuration | High / high | The official Link loader executes in the main document. Compromise of that trusted script could use the main page's allowed native commands. Capability-free remote frames do not isolate a script loaded into the parent document. Evaluate a separate capability-free Link surface with a narrow result bridge, or explicitly accept the provider-script trust after validating supported Link behavior. No CDN compromise is alleged. | **Needs decision**; isolation can change provider/product behavior. |
| 3 — Parser process isolation and aggregate budgets | Availability; PDF/XLSX imports and provider history | Medium / high | File/page/expanded-size/depth limits do not constitute a CPU/memory sandbox. PDF marker checks are conservative screening, not a complete active-content parser. Provider timeouts are per request, with a 100-page cap but no end-to-end deadline. Use a bounded disposable parsing worker and a total provider-operation deadline, preserving transaction rollback semantics. | **Deferred**, architecture work. |
| 4 — Local-process trust and recovery authenticity | Authentication/integrity; standalone API and metadata | Medium / high | Another local process can call the standalone API; a fully compromised owner account can edit metadata plus its unkeyed digest. If standalone becomes a distributed production mode, add a launch-specific secret outside URLs/storage. Consider Keychain-held HMAC with explicit recovery/rotation for metadata. | **Needs decision**; existing local-owner threat boundary retained. |
| 5 — Rust dependency maintenance and inline styles | Supply chain/CSP; Tauri graph and UI | Low–medium / high | Five `unic-*` maintenance warnings occur through `urlpattern`/`tauri-utils` on Apple Silicon. Follow upstream replacements and re-audit each candidate. Removing inline styles needs a coordinated style/CSP change and real Link compatibility proof. | **Deferred**, dependency/UI compatibility work. |

## Fresh dependency and validation evidence

September 6 locked audits queried advisory services without provider credentials or owner data:

- Python runtime export: 43 dependencies audited, no known vulnerabilities reported.
- Python export including development/build dependencies: 64 audited, none reported.
- pnpm production graph: 4 dependencies, zero advisory counts. Full graph: 198, zero counts.
- Cargo audit: zero entries in its vulnerability list; **17 warnings remain**: ten GTK3-family
  maintenance advisories, `proc-macro-error` maintenance, five `unic-*` maintenance advisories, and
  `glib` iterator unsoundness (`RUSTSEC-2024-0429`). Apple Silicon inverse dependency queries produced
  no active path for `glib` or `proc-macro-error`; `unic-char-property` is present through Tauri's
  `urlpattern` graph. This is target-specific evidence, not dismissal of the lockfile warnings.

Python audit tooling emitted cache-deserialization notices and a generic no-deps/hash advisory;
it still completed both scans with no known vulnerabilities. Advisory results are point-in-time,
not a proof of absence. No dependencies, lockfiles, CI jobs, or vulnerability suppressions were
changed in this pass. The source privacy scan remains a heuristic private-data check, not a
replacement for repository-host secret scanning or an exhaustive history credential review.

The full source gate covers formatter/linter, strict Python typing, Python integration/runtime
smokes, frontend tests/build/typing, docs and privacy checks. Native validation uses formatting,
Clippy with warnings denied, and unit/integration tests. New negative tests cover every September
code boundary above. Exact run totals and candidate status are recorded in the Desktop
`savings_next_steps.md` tracker.

## Manual verification outside this pass

Real Keychain ACL prompts, provider consent/revocation/retention and CDN behavior, signed installed
navigation/CSP, offline/sleep-wake behavior, and downloaded-copy Gatekeeper checks require an
explicitly authorized candidate session. No such evidence is inferred from mocked or source tests.
FileVault, account/physical security and protection against a compromised logged-in macOS account
remain OS/owner responsibilities. No owner database or Keychain was used in this review.
