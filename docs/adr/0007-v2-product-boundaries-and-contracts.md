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

## Slice 5 separation and promotion mapping

Slice 5 makes the Retirement and Lab boundaries executable. `LifePlanProfile` retains its
identifier and exact stored values and is owned by Retirement. A Retirement run is created
from an immutable projection input, excludes all operational and legacy `life_goals` by
default, and can include one explicitly selected `GoalProgram` only as a copied target,
reservation, remaining-target, evidence, and source-fingerprint snapshot. Neither a run nor
a saved run can mutate its source goal.

Lab experiments are complete isolated drafts. Blank seeds copy no Goal or Retirement money;
current-goal seeds copy the accepted Goal fingerprint and exact configured values; and
retirement-result seeds copy one immutable saved Retirement result and its run fingerprint.
Draft projection and snapshot reads are write-free. Values cross a boundary only through a
server-generated preview followed by a distinct stale-safe confirmation.

Every supported promotion field maps one-to-one to exactly one persisted target:

| Promotion field | Stored target |
|---|---|
| `goal_target` | `goal_programs.target_amount` |
| `reserved_for_goal` | `goal_programs.reserved_amount` |
| `protected_cash_floor` | `goal_programs.protected_cash_floor` |
| `retirement_essential_monthly_spend` | `life_plan_profiles.essential_monthly_spend` |
| `retirement_flexible_monthly_spend` | `life_plan_profiles.flexible_monthly_spend` |

The former ambiguous `retirement_monthly_spend` field is removed. A single total is never
split between essential and flexible spending, and confirmation never writes an unpreviewed
companion field. Speculative returns, compound-sprint rates, business multiples or revenue,
valuations, loan eligibility or borrowing capacity, and income-ranking thresholds remain
Lab-only and non-promotable.

Preview recomputes the submitted experiment fingerprint, reads the current target token,
shows exact before/after values and provenance, and performs zero writes. Confirmation
recomputes the same material, rejects a changed experiment or target, applies only the shown
fields in one target transaction, and records the Lab fingerprint in field provenance. Goal
promotion then requests one idempotent Slice 4 observation after the goal commit; an
unavailable observation cannot roll back the accepted edit.

The typed runtime surfaces are intentionally separate:

- `/api/v2/retirement/profile`, `/starting-point`, `/operational-goals`, `/project`, and
  `/snapshots` own durable Retirement assumptions, observed starting evidence, immutable run
  selection, deterministic results, and stored Retirement evidence. The projection command has
  no operational-goal mutation capability.
- `/api/v2/lab/experiments`, `/experiments/project`, `/snapshots`, `/promotions/preview`, and
  `/promotions/confirm` own explicit seeding, isolated draft arithmetic, stored experiment and
  legacy evidence, and the sole supported cross-surface mutation boundary.

No `0010_retirement_lab_boundaries` migration is needed. Existing `life_scenarios.input_snapshot`
and `life_projection_periods` preserve each new explicit context and complete deterministic
result, while pre-split scenarios retain their original payload, fingerprint, versions, warnings,
and monthly rows. A pre-split scenario is labeled `Legacy combined plan · v1.2.1 inputs` and is
compared only with the legacy combined fingerprint. New contexts are `retirement_default`,
`retirement_with_goal`, `lab_blank`, `lab_current_goal`, and `lab_retirement_result`; opening any
stored snapshot renders its saved evidence without a current-input rerun.
