# ADR 0007: Separate v2 operating surfaces behind evidence-bound contracts

## Status

Accepted for Money Map v2.0 planning in Slice 0. Runtime remains v1.2.1.

## Context

Money Map v1.2.1 combines evidence, forecasting, retirement planning, dated goals, and
Life Lab experiments on a long planning surface. The calculations are useful, but the
ordinary return loop does not quickly answer whether the owner moved closer to the active
goal, what changed, and which constraint binds next.

A major-version redesign must not reinterpret existing private evidence or allow one
surface to mutate another by accident. Slice 0 therefore freezes contracts before any
schema, API, calculation-engine, or UI change.

## Decision

Money Map v2 has four explicit product boundaries:

- **Goals** is the frequent-use operational surface. Exactly one primary operational goal
  may own an exclusive reserved-dollar claim. Observed capacity above the protected floor
  remains distinct from owner-reserved progress.
- **Retirement** is an independent, occasional solvency tool. Retirement assets never
  enter ordinary goal cash. An operational goal is excluded from a retirement run unless
  the owner explicitly selects an immutable goal snapshot for that run.
- **Life Lab** is an isolated experimental workspace. A Lab seed copies values into a
  draft. Editing the draft changes neither Goals nor Retirement. A supported value may
  cross the boundary only through a reviewable promotion preview and a later explicit
  confirmation action.
- **Money** views remain the evidence and utility foundation: payroll, accounts, balances,
  activity, wealth, imports, connections, forecasts, review, and provenance. They supply
  facts without becoming a transaction-budgeting product.

The executable contract is `src/paycheck_map/v2_contracts.py`, mirrored for future
frontend use in `web/src/v2-contracts.ts`. It makes these rules structural:

1. Every monetary field is an `EvidencedMoney` value containing an internal `Decimal`, an
   exact two-place decimal serialization, one evidence class (`observed`, `derived`,
   `user_entered`, `assumed`, or `unavailable`), and source references or an unavailable
   reason. Formatted display copy is not part of the value.
2. The primary program has `primary=true` and
   `reservation_policy=exclusive_primary_goal`; there is no secondary allocation list in
   the contract. Slice 1 must enforce one primary record and exclusive reservation at the
   database boundary.
3. `accessible_now` is exactly accessible cash plus confirmed sellable investments.
   Retirement assets are a separate, explicitly excluded value and cannot participate in
   that sum.
4. A check-in identifier is deterministic from the goal program and source fingerprint.
   Check-in collections reject duplicate goal/fingerprint pairs, and comparisons require
   two distinct fingerprints.
5. Comparison values are arithmetic deltas. Event classifications such as payroll,
   transfer, or market movement require explicit supporting source references. Any
   unmatched accessible-capital change remains an exact unexplained residual; free-form
   causal claims are forbidden.
6. Retirement selections declare that operational goals are excluded by default and that
   the selection cannot mutate the goal program.
7. Lab seeds declare an isolated draft. Promotion contracts represent preview-only state,
   enumerate supported fields, require explicit confirmation, and cannot represent an
   applied mutation.

The goal arithmetic and source-fingerprint conventions are frozen in:

- `docs/v2/goal-arithmetic-contract.md`
- `docs/v2/source-fingerprint-contract.md`

Synthetic serialized vectors are checked in at
`examples/synthetic/money-map-v2-contracts.json`.

## Migration invariants

The v2 schema will be additive. Migration must preserve all v1.2.1 records, exact monetary
values, source evidence, and identifiers. In particular, every `life_plan_profiles`,
`life_goals`, `life_scenarios`, and `life_projection_periods` record remains immutable
through upgrade and downgrade. The selected enabled goal, protected floor, and reserved
amount are copied exactly into the new goal domain; they are not moved or rewritten.

No active database may be upgraded until backup verification and an isolated restored-copy
upgrade/downgrade/re-upgrade drill passes. The complete plan is
`docs/v2/migration-recovery-plan.md`.

## Consequences

Slice 0 adds no runtime endpoint, service, table, migration, or visible behavior. It does
add strict contracts that later slices must implement without weakening. Some guarantees,
including database uniqueness, concurrent idempotency, persistence, API behavior, and
visible promotion confirmation, remain intentionally deferred to Slices 1–5.

Existing v1.2.1 accounting, provenance, imports, optional read-only Plaid behavior,
forecasting, Life Lab results, backup behavior, privacy boundaries, and runtime version are
unchanged.

## Slice 4 operation boundary

Slice 4 implements one explicit post-operation observation coordinator. Plaid refreshes,
manual imports, payroll rebuilds, and the typed Goals load-backfill command pass an Eastern
business observation date plus a completed operation state. The coordinator persists sanitized
per-source currentness in the existing application-settings domain, then creates an idempotent
check-in in a separate transaction only when every affected persisted source is current.

Partial and failed states remain retryable and cannot be converted into successful-current
observations by a browser load. A later complete operation for the affected source restores
eligibility. Zero Plaid connections remains a valid manual-only state. Existing Goals GET
endpoints remain read-only; only the explicit backfill command may request persistence.
