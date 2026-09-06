# Maintenance boundaries

Use [Development](development.md) to set up a checkout, [Testing](testing.md) for executable checks,
and the [SSOT map](v3/single-source-of-truth.md) when deciding where a change belongs. Keep historical
release evidence in its versioned location; it is not setup documentation or current acceptance.

## Cleanup decisions

The September 6 cleanup preserves the uncommitted SSOT work and product behavior. It corrects the
README install order, consolidates validation instructions in Testing, removes an uncalled
reconciliation helper, and extracts pure Plaid record parsing/classification into `plaid_records.py`.
`plaid_service.py` remains responsible for credentials, workflow ordering, transactions and
persistence. The runtime module inventory includes the new module. Existing synthetic provider
and failure tests exercise the extracted code through the supported service entry points.

No actionable TODO/FIXME/HACK markers were found in application source or scripts during this pass.
No environment template is needed: manual-import development requires no credentials; supported
settings live in [Configuration](configuration.md). Release scripts, synthetic fixtures and old
schema readers have active qualification/migration callers and are retained.

## Files over roughly 500 lines

This is an ownership inventory, not a size limit. Counts are intentionally omitted because ordinary
edits change them; each group below was reviewed in the current source. Test files are listed
separately from shipped application code.

| Files | Why retained / useful extraction boundary |
| --- | --- |
| `src/paycheck_map/analytics.py`, `cash_flow_service.py` | Related read projections and coverage/period arithmetic. Extract a projection when its callers and evidence contract can move together. |
| `src/paycheck_map/cutover_readiness.py`, `data_home.py` | Fail-closed recovery state machines with ordering, rollback and filesystem invariants. Splitting needs recovery/fault-injection coverage, not a line-count-only move. |
| `src/paycheck_map/forecasting.py`, `life_plan.py` | Cohesive deterministic financial engines. Separate immutable input construction from simulation in a future focused change; preserve rounding and result fingerprints. |
| `src/paycheck_map/goal_service.py`, `retirement_lab.py` | Related mutation, provenance, stale-write and promotion rules. Future splits should isolate snapshot persistence or read projections without duplicating transaction ownership. |
| `src/paycheck_map/models.py` | One mapped schema with interrelated relationships and shared metadata. Splitting now would add registration/import ordering without changing ownership. |
| `src/paycheck_map/payroll.py`, `reconciliation.py` | Ordered payroll and accounting rules share reconciliation context. Extract complete rule families only with invariant tests. |
| `src/paycheck_map/plaid_service.py` | Sync/revocation and persistence remain cohesive after pure parsing extraction. A later persistence split needs explicit transaction/rollback ownership. |
| `src/paycheck_map/v2_contracts.py`, `v21_contracts.py` | Versioned schemas and cross-field validation are public boundaries. Split by complete domain families while preserving exports and contract checks. |
| `web/src/App.tsx` | Navigation and application/runtime coordination. A runtime hook is a reasonable later extraction, backed by existing navigation/lifecycle tests. |
| `web/src/goals/GoalsView.tsx`, `cash-flow/CashFlowView.tsx` | Closely related view state and currentness behavior. Extract complete dialogs or read-only result sections, not fragments that share mutation state. |
| `web/src/types.ts`, `v21-contracts.ts` | Shared response types and runtime contract validation. Domain splits should keep imports predictable and validation paired with its type. |
| `web/src/styles.css`, `goals/goals.css`, `cash-flow/cash-flow.css` | Cascade order, responsive rules, print styles and shared selectors are behavior. Moving them needs rendered responsive/print review; a blind size split risks visual regressions. |
| `desktop/src-tauri/src/main.rs`, `runtime.rs`, `qualification.rs` | Native command/menu wiring, generation lifecycle and qualification protocols have different owners but internal ordering invariants. Extract coherent command groups only with native and signed-candidate validation. |
| `scripts/package_desktop_release.py`, `qualify_desktop_release.py`, `qualify_slice6_campaign_b.py` | Auditable release pipelines with identity-bound gates and cleanup. Keep sequencing explicit; shared stage helpers require controlled release regression work. |
| `web/src/App.test.tsx`, `components.test.tsx`, `goals/GoalsView.test.tsx` | Grouped product behavior with shared fixtures. Split by feature when fixtures can be shared without mutable test coupling. |

## Separate follow-up work

1. Split the global stylesheet by layout/product/print ownership only with rendered desktop, narrow
   viewport and print checks; preserve cascade order and historical selector dependencies.
2. Extract planning snapshot persistence and native command groups in separate changes with their
   transaction/lifecycle tests. Do not combine these with schema or protocol changes.
3. Legacy-table removal, broader calendar-policy changes, real provider/Keychain checks and signed
   candidate qualification remain separate work described by the SSOT and release guides.

Do not introduce additional CI matrices or release gates merely to enforce module length.
