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

- [ ] Repeated unchanged refresh/open/import produces no duplicate check-in.
- [ ] One changed successful synthetic update produces exactly one comparable check-in.
- [ ] Partial and failed refreshes remain visible and cannot create a successful-current
  check-in.
- [ ] Manual import and read-only Plaid paths use the same post-operation service.
- [ ] Timeline contains distinct financial observations, not browser-open telemetry.
- [ ] Verify no provider call is needed by synthetic CI.

## Slice 5 — Retirement and Lab separation

- [ ] Retirement excludes operational goals by default and includes only an explicitly named
  immutable goal snapshot for a selected run.
- [ ] Editing Retirement leaves Goals unchanged.
- [ ] Every Lab seed is isolated; editing a Lab draft leaves Goals and Retirement
  fingerprints unchanged.
- [ ] Promotion preview shows exact before/after values and provenance; only an explicit
  confirmed supported promotion mutates its target.
- [ ] Existing v1.2.1 Life Lab scenarios and monthly rows remain readable and reproducible.
- [ ] Run cross-surface regression, accessibility, and visual tests.

## Slice 6 — application-wide concision and polish

- [ ] Enforce ordinary-state copy budget and remove repeated explanations.
- [ ] Test semantic presence of critical evidence and absence of retired duplicate copy.
- [ ] Visually validate empty, ordinary, attention, failed-refresh, stale, floor-breach,
  negative-flow, on-pace, complete, and legacy-scenario states.
- [ ] Validate desktop, narrow desktop, and phone widths; confirm ordinary Goals fits one
  reference desktop viewport.
- [ ] Confirm no critical limitation depends only on color, hover, or inaccessible controls.
- [ ] Confirm zero console errors or warnings on tested paths.

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
