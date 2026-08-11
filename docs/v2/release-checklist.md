# Money Map v2.0 repository release checklist

This checklist is cumulative. Each slice checks its own focused gate and the complete
`uv run paycheck-map verify` gate. Evidence contains synthetic data or private-state
counts/digests only; no statement, account identifier, provider response, report, screenshot,
credential, or real balance enters the repository.

## Every slice

- [ ] Confirm expected branch, baseline, upstream, and clean or intentionally understood
  worktree before editing.
- [ ] Preserve manual import, optional read-only Plaid, exact accounting, provenance,
  forecasting, backup/restore, privacy, and local-only binding behavior.
- [ ] Run focused backend tests for changed contracts/services/migrations.
- [ ] Run focused frontend tests, strict TypeScript, and production build when frontend files
  change.
- [ ] Run `uv run paycheck-map verify` without weakening the gate.
- [ ] Run `git diff --check` and the canonical private-data scan included in the release gate.
- [ ] Confirm no private artifact, credential, raw provider response, or active database is
  tracked or staged.
- [ ] Record exact commands, results, version state, database-mutation state, limitations,
  and rollback boundary.
- [ ] Create one intentional local checkpoint and leave the repository clean.

## Slice 0 — contracts and safety rails

- [ ] ADR accepts Goals, Retirement, Life Lab, and Money boundaries.
- [ ] Backend contracts and frontend mirrors cover primary program, position, immutable
  check-in, distinct comparison, milestone, evidence, retirement selection, Lab seed, and
  promotion preview.
- [ ] Every money field is `Decimal` internally, an exact decimal string on serialization,
  and inseparable from an allowed evidence class.
- [ ] Tests reject double allocation shape, retirement-as-cash arithmetic, unsupported causal
  claims, duplicate source-equivalent check-ins, and silent cross-surface mutation.
- [ ] Calendar, cent rounding, comparison residual, milestone order, and source fingerprint
  vectors pass boundary/leap/expiry tests.
- [ ] All required invented v1.2.1 fixture states validate and pass the privacy scan.
- [ ] Migration, downgrade, backup, restore, logical equality, idempotency, and recovery are
  documented; confirm migration `0009` does not exist.
- [ ] Confirm every runtime version surface remains `1.2.1` and no runtime behavior changed.

## Slice 1 — additive schema and lossless migration

- [ ] Verify a fresh backup before any migration drill.
- [ ] Upgrade/downgrade/re-upgrade empty and every synthetic v1.2.1 fixture.
- [ ] Run the same drill on an isolated restored database before any active database action.
- [ ] Confirm SQLite `integrity_check=ok` and zero foreign-key violations at every boundary.
- [ ] Compare pre/post/downgrade logical manifests for every pre-v2 table.
- [ ] Assert exact goal, floor, and reserved mapping; ambiguous multiple goals select none.
- [ ] Assert one-primary unique enforcement, deterministic source mapping, and idempotent
  repeated upgrade.
- [ ] Assert every original `life_*` row and existing scenario fingerprint remains unchanged.
- [ ] Capture and prove injected-failure recovery and rollback evidence.

## Slice 2 — goal engine and APIs

- [ ] Test exact arithmetic, missing evidence, cents, same-day and changed same-day states,
  month boundaries, leap years, expired dates, and completed goals.
- [ ] Test deterministic canonical fingerprints and concurrent duplicate convergence.
- [ ] Test comparisons for cash, accessible investment, debt, target, floor, reservation,
  supported events, and unexplained residual.
- [ ] Test the floor → recurring gap → goal funding → complete milestone order.
- [ ] Assert retirement assets never enter accessible goal capital and capacity never becomes
  reserved progress.
- [ ] Run API success, unavailable, validation, conflict, and failure-path tests.

## Slice 3 — Goals default surface

- [ ] Test migrated, empty, unavailable, stale, attention, and completed states.
- [ ] Confirm the ordinary answer fits the reference desktop viewport without scrolling.
- [ ] Run automated accessibility checks plus manual keyboard order, focus, headings, names,
  contrast, and reduced-motion review.
- [ ] Visually validate reference desktop, narrow desktop, and phone widths.
- [ ] Confirm no Retirement or Life Lab working surface appears in the first Goals viewport.
- [ ] Confirm direct Money utility routes remain available.

## Slice 4 — update integration and timeline

- [x] Source fingerprints use financial/configuration evidence dates rather than the caller's
  observation date. Identical evidence on a later day remains source-equivalent while the live
  required pace can advance independently.
- [x] One shared post-operation coordinator serves global and individual read-only Plaid,
  manual import, payroll rebuild, and explicit load backfill. It returns only `created`,
  `unchanged`, `no_primary`, `not_current`, or retryable `unavailable` contracts.
- [x] Repeated unchanged complete refresh/open/import/payroll operations write zero additional
  check-ins. One changed complete operation writes one check-in; a global refresh never writes
  once per connection.
- [x] Partial, failed, and skipped operations write zero successful-current check-ins. Persisted
  per-source currentness prevents load backfill from laundering a preceding failure, and a later
  complete operation for that source restores eligibility.
- [x] Check-in persistence has its own transaction boundary. An injected insertion failure
  preserved already committed financial evidence, rolled back only the observation, and returned
  a visible retryable result without converting provider success into provider failure.
- [x] Every Goals GET remains write-free. `POST /api/v2/goals/check-ins/backfill` is the sole
  explicit load command and sends no browser timestamp, telemetry, filename, account identifier,
  merchant detail, credential, or raw provider payload.
- [x] “Since last financial change” compares the latest two distinct persisted fingerprints.
  The recent timeline retains cursor pagination and the 25-row render cap, with compressed safe
  summaries and expandable exact evidence/components including unexplained residual.
- [x] Synthetic Alembic-`0009` coverage passed for unchanged/changed/partial/failed global and
  individual refresh, import, payroll, repeated/concurrent backfill, no-primary, independent
  observation rollback, exact comparison reconciliation, read purity, and timestamp invariants.
- [x] Isolated browser validation on alternate ports passed at 1440×900, 1024×768, and 390×844
  for first/unchanged backfill, positive/negative/zero comparison, not-current, retryable
  observation failure, no-primary, and compressed/expanded timeline. It found no horizontal
  overflow, clipped money, console warning/error, heading/live-region issue, or Goals-surface
  Retirement/Life Lab leakage; ignored evidence is under
  `.local/v2-slice4-browser-20260810/screenshots/`.
- [x] `uv run paycheck-map verify` passed 135 backend tests with one intentionally opt-in skip,
  63 frontend tests, formatting, Ruff, strict mypy, TypeScript, production build, and privacy
  scan. Standalone private-data, lock, diff, and frontend-build gates passed without a provider
  call, Keychain access, credential, or owner-database migration/write.

## Slice 5 — Retirement and Lab separation

- [x] Retirement excludes operational goals by default and includes only an explicitly named
  immutable goal snapshot for a selected run.
- [x] Editing Retirement leaves Goals unchanged.
- [x] Every Lab seed is isolated; editing a Lab draft leaves Goals and Retirement
  fingerprints unchanged.
- [x] Promotion preview shows exact before/after values and provenance; only an explicit
  confirmed supported promotion mutates its target.
- [x] Existing v1.2.1 Life Lab scenarios and monthly rows remain readable and reproducible.
- [x] The deterministic projection core accepts immutable inputs while the accepted combined
  v1.2.1 adapter and all existing engine fixtures remain unchanged.
- [x] No `0010` migration was required. New Retirement and Lab snapshots use the existing
  `life_scenarios` JSON/period capacity, and narrow profile-provenance metadata uses the existing
  application-settings domain without rewriting historical `life_*` rows.
- [x] Cross-surface tests cover default exclusion, named inclusion, seed immutability, draft-only
  fingerprints, read purity, zero-write preview/stale/unsupported paths, exact-field Goal and
  Retirement promotion, promotion provenance, post-commit observation failure, and legacy
  combined-fingerprint staleness.
- [x] Frontend tests cover distinct lazy routes, all seed kinds, bridge states, chart/table,
  profile stale conflicts, stored evidence, promotion diff/confirmation focus trap, stale draft
  preservation, no cross-surface writes, and retained Overview/Accounts/Income/Activity/Wealth/
  Add account/Review navigation.
- [x] Isolated browser validation at 1440×900, 1024×768, and 390×844 found and fixed the
  narrow-desktop verdict overflow, then passed with zero overflow, clipped money, or console
  warning/error. Primary phone controls are at least 44px, reduced-motion rules are present,
  and ignored screenshots are under `.local/v2-slice5-browser-20260810/screenshots/`.
- [x] Final `uv run paycheck-map verify` passed 144 backend tests with one intentionally
  opt-in skip, 74 frontend tests, formatting, Ruff, strict mypy, TypeScript, production build,
  and private-data scanning. Standalone private-data, lockfile, diff, and build gates passed;
  package/API/CLI/frontend versions remain `1.2.1` and the owner database evidence is unchanged.

## Slice 6 — application-wide concision and polish

- [x] Enforce ordinary-state copy budget and remove repeated explanations.
- [x] Test semantic presence of critical evidence and absence of retired duplicate copy.
- [x] Visually validate empty, ordinary, attention, failed-refresh, stale, floor-breach,
  negative-flow, on-pace, complete, and legacy-scenario states.
- [x] Validate desktop, narrow desktop, and phone widths; confirm ordinary Goals fits one
  reference desktop viewport.
- [x] Confirm no critical limitation depends only on color, hover, or inaccessible controls.
- [x] Confirm zero console errors or warnings on tested paths.
- [x] Limit Goals/Retirement/Lab histories to three, imports/activity to five, preserve the
  Goals cursor and 25-row cap, and retain searchable stored and legacy evidence.
- [x] Use shared focused dialogs for long edits and promotion preview with initial focus,
  trap, Escape, focus return, background inertness, associated errors, and retained input.
- [x] Preserve exact printable evidence by opening disclosures for print, restoring their
  screen state afterward, excluding transient controls, and visually reviewing a synthetic PDF.
- [x] Keep package/API/CLI/frontend at `1.2.1`, migration head at `0009`, and the active
  owner database byte-identical at revision `0008`; no `0010` exists.
- [x] Pass 144 backend tests with one intentional skip, 91 frontend tests, strict types,
  formatting/lint, production build with distinct Goals/Retirement/Lab chunks, privacy,
  lockfile, and diff gates.

## Slice 7 — release candidate and v2.0.0

- [ ] Create and verify a fresh active-database backup; record local path, size, SHA-256,
  integrity, foreign-key, revision, and logical-manifest evidence without private values.
- [ ] Complete isolated restore upgrade/start/Goals/Retirement/Lab/downgrade/re-upgrade drill.
- [ ] Prove pre-v2 logical equality and independently verify all v2 mappings/check-ins.
- [ ] Run focused tests and full backend/frontend release gate from a clean checkout.
- [ ] Run synthetic CI with no `.local` data, credentials, provider access, or network
  dependency.
- [ ] Run canonical privacy scan, package build, formatting, lint, strict types, migrations,
  backup/restore, SQLite integrity, and foreign-key checks.
- [ ] Run accessibility and visual validation at all reference states/viewports.
- [ ] If freshness requires it, perform only one explicitly authorized read-only refresh;
  otherwise use current observed state. Never move money.
- [ ] Complete bounded owner acceptance for closer / what changed / what next in about 15
  seconds and record the result.
- [ ] Update all version surfaces to `2.0.0` only after every release-candidate gate passes:
  Python package, API health/FastAPI, CLI/help, frontend package/lockfile, docs, and release
  evidence.
- [ ] Re-run the entire release gate after version changes and prove all surfaces agree.
- [ ] Record downgrade and verified-backup restore commands, v2-only data-loss boundary,
  logical rollback evidence, and application restart checks.
- [ ] Obtain final owner acceptance before any push, pull request, merge, deploy, tag, or
  publication; those external actions require separate instruction.
