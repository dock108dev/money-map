# Maintenance boundaries

Use [Development](development.md) to set up a checkout, [Testing](testing.md) for executable checks,
and the [SSOT map](v3/single-source-of-truth.md) when deciding where a change belongs. Keep historical
release evidence in its versioned location; it is not setup documentation or current acceptance.

## Cleanup decisions

The September 6 cleanup and follow-up pass preserve the SSOT changes committed in `e0f3567`
and intended product behavior. The initial cleanup corrects the README install order, consolidates validation instructions in Testing, removes an uncalled
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
| `src/paycheck_map/goal_service.py`, `retirement_lab.py` | Related mutation, provenance, stale-write and promotion rules. Snapshot writes and serialization now live in `planning_snapshots.py`; the remaining service coordinates validation, provenance, experiments and promotion without owning commits. |
| `src/paycheck_map/models.py` | One mapped schema with interrelated relationships and shared metadata. Splitting now would add registration/import ordering without changing ownership. |
| `src/paycheck_map/payroll.py`, `reconciliation.py` | Ordered payroll and accounting rules share reconciliation context. Extract complete rule families only with invariant tests. |
| `src/paycheck_map/plaid_service.py` | Sync/revocation and persistence remain cohesive after pure parsing extraction. A later persistence split needs explicit transaction/rollback ownership. |
| `src/paycheck_map/v2_contracts.py`, `v21_contracts.py` | Versioned schemas and cross-field validation are public boundaries. Split by complete domain families while preserving exports and contract checks. |
| `web/src/App.tsx` | Navigation and application/runtime coordination. A runtime hook is a reasonable later extraction, backed by existing navigation/lifecycle tests. |
| `web/src/goals/GoalsView.tsx`, `cash-flow/CashFlowView.tsx` | Closely related view state and currentness behavior. Extract complete dialogs or read-only result sections, not fragments that share mutation state. |
| `web/src/types.ts`, `v21-contracts.ts` | Shared response types and runtime contract validation. Domain splits should keep imports predictable and validation paired with its type. |
| `web/src/styles/accounts.css`, `goals/goals.css`, `cash-flow/cash-flow.css` | Cohesive account, goal and cash-flow presentation. The global entrypoint is now an ordered import manifest; these domain styles retain related selectors and their cascade order. |
| `desktop/src-tauri/src/main.rs`, `runtime.rs`, `qualification.rs` | Artifact and diagnostics commands now live under `commands/`. Main retains window/menu wiring and qualification observation; runtime and qualification retain their lifecycle/protocol state machines. Native source checks do not replace signed-candidate qualification. |
| `scripts/package_desktop_release.py`, `qualify_desktop_release.py`, `qualify_slice6_campaign_b.py` | Auditable release pipelines with identity-bound gates and cleanup. Keep sequencing explicit; shared stage helpers require controlled release regression work. |
| `web/src/App.test.tsx`, `components.test.tsx`, `goals/GoalsView.test.tsx` | Grouped product behavior with shared fixtures. Split by feature when fixtures can be shared without mutable test coupling. |

## Completed source follow-ups

- `web/src/styles.css` is an ordered import manifest. `styles/` groups foundation, shell, dashboard,
  review, connections, overlays, accounts, income, wealth, desktop operations and disclosures.
  Responsive and print blocks retain their original positions between those groups. Concatenating
  the imported files reproduces the previous stylesheet exactly; moving every print rule to the
  end would change the cascade. Domain-loaded Goals, Cash Flow, Retirement and Lab styles stay with
  their views. Add selectors to their owner and preserve import order.
- `planning_snapshots.py` owns snapshot/period writes, context classification and stored-response
  serialization. `retirement_lab.py` still validates stale inputs, constructs snapshot evidence,
  filters permitted contexts and computes legacy freshness. The storage helper flushes twice to
  preserve generated IDs and relationship ordering; the API caller alone commits or rolls back.
  Both Retirement and Lab rollback regressions verify no snapshot or periods survive a rollback.
- Native `commands/data_files.rs` owns import selection, backup reveal and report actions;
  `commands/diagnostics.rs` owns sanitized preview/export and its atomic private-file writer.
  Their parent shares authenticated artifact reads. Main registers the same command names;
  capabilities and transport/lifecycle protocols are unchanged. Path/link rejection and diagnostic
  export tests live with their implementations.

## Follow-up validation — September 6, 2026

The working-tree changes based on `e0f3567` passed the complete source gate on Python 3.12:
556 Python tests passed, with the existing opt-in isolated-restored-copy drill skipped; 225 web
tests passed. Ruff formatting/lint, strict mypy (113 files), TypeScript, frontend build,
documentation links and private-data scan passed. Native formatting, Clippy with warnings denied
and all 44 native tests passed. The source distribution and wheel built successfully; the wheel
contains `planning_snapshots.py` and the runtime inventory check passes.

Synthetic browser comparison used isolated migrated databases, a fixed browser/evidence clock,
reduced motion, and waited for each route heading before capture. Cash Flow, Accounts, Income,
Wealth, Retirement and Lab were reviewed at 1440×1000, 390×844, and print media. Print PDFs were
also generated. Seventeen screenshots matched exactly; the remaining narrow Cash Flow screenshot
had 93 button-edge pixels differing by at most 2/255 per color channel, with identical geometry
and no visible regression. No browser page errors occurred. Ordered CSS contents match the
baseline byte-for-byte. These browser and native unit checks do not qualify an installed WKWebView
or signed application.

## Remaining separate work

Legacy-table removal requires a compatibility migration; broader calendar unification requires a
product date-policy decision and boundary tests. Real provider/Keychain checks and signed candidate
qualification require their dedicated operational/release workflow. See the SSOT and versioned
release guides. These are outside this behavior-preserving source cleanup.

Do not introduce additional CI matrices or release gates merely to enforce module length.
