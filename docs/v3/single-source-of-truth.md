# Current single sources of truth

Reviewed September 6, 2026; source follow-ups based on `e0f3567`. This is the current supported source contract, not proof
that these changes are installed or qualified. Historical candidate evidence stays identity-bound.

## Authority map

Domain: Routing and client API access

SSOT module/file: `paycheck_map.app`, domain routers `api`, `api_v2`, `api_plaid`; `web/src/api.ts`

Why this is authoritative: App assembly mounts supported domain routers once. The shared client
owns transport and safe errors; domain client modules supply typed endpoints.

Known callers: CLI/sidecar startup, App, Goals, Retirement, Lab and data-home UI.

Domain: Planning and operational goals

SSOT module/file: `api_v2.py`, `retirement_lab.py`, `planning_snapshots.py`, `goal_service.py`, `life_plan.py`

Why this is authoritative: `goal_service` controls operational goal writes; `retirement_lab`
controls Retirement edits, isolated Lab experiments, promotion confirmation and snapshot validation.
`planning_snapshots` owns snapshot/period persistence and serialization without committing; API
handlers own the transaction.
`life_plan.project_projection_inputs` is the immutable-input calculation engine, not an alternate
combined-plan mutation service.

Known callers: v2 routers, goal observation, Goals/Retirement/Lab clients and synthetic validation.

Domain: Configuration and feature policy

SSOT module/file: `config.Settings`, `desktop_policy.py`, native `data_home.rs`

Why this is authoritative: Settings defines Python runtime paths; desktop_policy defines supported
modes and secret-store policy. Native code supplies trusted desktop paths; Python independently
validates the cross-process input. Production, managed synthetic acceptance, Keychain acceptance
and disposable synthetic test modes all have launcher/test callers.

Known callers: App, database initialization, sidecar, data-home API, cutover and Keychain selection.

Domain: Persistence and recovery

SSOT module/file: `data_home.DataHomeManager`, `db.py`

Why this is authoritative: DataHomeManager alone owns packaged migration/activation/backup/restore
and recovery journals. db owns SQLAlchemy and supported repository-mode initialization.

Known callers: Desktop data API, startup, CLI development flows and release qualification.

Domain: Product/schema identity

SSOT module/file: `product_metadata.py`, `release_candidate.py`

Why this is authoritative: product_metadata owns Python version/schema/DMG identity;
release_candidate consumes it for candidate validation. Build-manifest/native repetitions are
required by their tools and checked by `test_version_consistency.py`.

Known callers: Data-home, sidecar attestation, build scripts, About and qualification.

Domain: Ingestion and provider access

SSOT module/file: `ingestion.py`, `adapters`, `reconciliation.py`, `plaid_service.py`, `plaid_records.py`, `plaid_client.py`

Why this is authoritative: Import coordination, format parsing, accounting classification, provider
workflows, pure payload parsing/classification and provider HTTP each have one responsibility. Manual import and optional Plaid are
both supported sources.

Known callers: API/CLI mutation workflows, refresh and deterministic import/provider tests.

Domain: Scheduling, time and observation

SSOT module/file: `refresh.py`, `business_time.py`, `goal_operations.py`, `goal_observation.py`

Why this is authoritative: refresh owns explicit/daily provider orchestration; business_time owns
UTC normalization, Eastern refresh dates and nondecreasing operation timestamps. goal_operations
coordinates durable mutations and goal_observation handles optional post-mutation observation.

Known callers: Provider service, API, CLI, Retirement, goal operations and refresh.

Domain: Read projections

SSOT module/file: `service_common.py`, `service_accounts`, `service_wealth`, `service_overview`,
`service_payroll`, `service_summaries`

Why this is authoritative: Shared classification stays in service_common; each domain owns its
projection. `services.py` is a public export facade without competing calculations.

Known callers: API, forecast/planning inputs and report generation.

Domain: Authentication, authorization and validation

SSOT module/file: `desktop_bootstrap.py`, `desktop_app.py`, `local_security.py`, `keychain.py`,
`api_inputs.py`, `v2_contracts.py`, `v21_contracts.py`

Why this is authoritative: Native creates the private bootstrap/session; desktop_app enforces its
loopback boundary. local_security enforces browser Host/origin/framing and response privacy.
MacOSKeychainSecretStore owns production credentials; schemas own their versioned input contracts.
Independent native/Python validation is intentional defense at a process boundary.

Known callers: Sidecar, standalone server, routers, production provider workflows and synthetic tests.

Domain: Rendering and state

SSOT module/file: `web/src/App.tsx`, domain views, `web/src/format.ts`, ordered `web/src/styles.css` imports

Why this is authoritative: App owns navigation/refresh coordination, domain views own presentation
and ephemeral drafts, and backend responses own financial state. Shared formatters own general
money/UTC date display; domain-specific labels and precision remain intentional. Global stylesheet
imports preserve the original cascade across layout, product, responsive and print owners.

Known callers: All current routes. `components.tsx` remains a used facade/shared evidence UI.

Domain: Native artifact commands

SSOT module/file: `desktop/src-tauri/src/commands/{data_files,diagnostics}.rs`

Why this is authoritative: These modules own verified file actions and sanitized diagnostic
preview/export. Their parent shares authenticated local reads; main registers commands and owns
window/menu wiring. Existing capabilities and backend validation remain independent boundaries.

Known callers: Native menu dispatch and the frontend desktop bridge.

## Conflicting and unused construct inventory

| Candidate | Usage evidence and relationship to authority | Action |
| --- | --- | --- |
| Combined `/api/life-plan/*` router | No current UI, CLI or provider caller. Its writers bypassed v2 edit tokens/provenance and separate planning policy. Native qualification still called old reads. | Deleted all 12 operations and `api_life_plan.py`; requests receive the existing API not-found/method-not-allowed response. Updated native observer and oracle to current Lab entry requests. |
| Legacy projection/save/CRUD helpers in `life_plan.py` | Only the removed router, its tests or no callers used them. | Deleted legacy request models, persistence writers, duplicate serializers, database-to-combined-run adapter and unused deletion/test helpers. Kept deterministic core and legacy fingerprint/read support. |
| Legacy client functions, GoalEditor, LifeProfileForm | No imports from the mounted UI. Current Lab edits isolated drafts and promotes explicitly. | Deleted helpers, components, their unused styles and request/snapshot types; removed stale successful-response mocks. |
| Lab source reads | Same endpoints/types as Goals and Retirement client modules. | Lab now calls `loadPrimaryGoal` and `loadRetirementProfile` directly; removed both wrappers. |
| Goals read/write transport | Reads had a no-op catch/rethrow wrapper; writes separately decoded errors and could mishandle null bodies. | Reads use the shared request directly. Writes use it with a typed status-to-GoalApiError adapter so existing conflict recovery remains intact. Structured/null error regressions cover the shared decoder. |
| Provider/refresh UTC conversion and timestamp-floor implementations | Both actively implemented identical policy. Retirement also duplicated UTC conversion. | Routed through business_time; API/CLI/planning import business dates directly from that module. |
| Acceptance-mode literals outside desktop_policy | Sidecar seed validation, data-home fixture selection and cutover rehearsal use the same mode. | Replaced repeated literals with ACCEPTANCE_DATA_MODE. |
| Runtime-resource module inventory | The package inventory still named the retired router. | Removed that module; inventory checks continue to validate the remaining package. |
| Qualification Lab expectations | Native and fixture repeated obsolete endpoints while the UI used v2. | Updated both and added a guard against disagreement with mounted current routes. Repinned the reviewed source oracle in `preflight_slice6_source_matrix.py`; this changes future qualification inputs, not historical acceptance. |

## Retained boundaries and follow-ups

- Repository CLI/manual import remains a supported development surface, not a packaged fallback.
  No environment aliases or supported launcher modes were removed. Fault-injection/startup-delay
  hooks have bounded synthetic qualification callers and remain guarded by the launcher contract.
- Legacy `LifeGoal`/`LifeScenario` records, fingerprinting and snapshot classification remain required
  by cutover, historical evidence display and Lab seeding. They are read compatibility, not a second
  public mutation API. A regression verifies legacy evidence stays unchanged while stale status
  updates after current assumptions change. Removing those records requires a separate migration.
- Strict timestamp input validation deliberately rejects naive timestamps in some contracts;
  persistence normalization deliberately accepts historical naive UTC values. Do not merge these
  into a permissive validator merely because both inspect timezones.
- Other financial/forecast calendar defaults still use explicit as-of dates or the host calendar.
  Unifying all planning calendars with the Eastern refresh day would change behavior and needs a
  separate date-policy pass with boundary tests. This pass consolidates identical clock behavior.
- Python and Rust admission/framing checks and desktop mode validation remain independent process
  boundaries. Shared numeric limits could be generated later, but authentication must remain
  validated on both sides. Version/qualification representations use guard tests where practical.
- No schema, version, financial calculation, release/cutover state or installed artifact changed.
  Qualifying these source changes requires a new exact candidate; real Keychain/provider and
  signed-app owner workflows were not exercised by synthetic source tests.

## Regression evidence

`test_ssot_enforcement.py` rejects retired API calls, binds the Lab qualification oracle to mounted
routes and native observation, and checks shared timestamp behavior at Eastern midnight and
backwards clocks. Existing v2 profile/goal/experiment/promotion tests protect active workflows;
legacy snapshot read/staleness coverage remains in `test_retirement_lab.py`. The full source gate,
native checks and package inventory validation remain required. Run totals are in the Desktop
`savings_next_steps.md` tracker.
