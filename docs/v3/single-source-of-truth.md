# Current single sources of truth

This document records the supported authority boundaries in the current Money Map tree. It is a
maintenance map, not a new compatibility contract.

## Runtime routing and client access

- `paycheck_map.app` assembles FastAPI and mounts the supported routers.
- `paycheck_map.api` owns core account, payroll, import, correction, report, and forecast routes.
  `paycheck_map.api_v2`, `paycheck_map.api_life_plan`, and `paycheck_map.api_plaid` own their named
  route families. `paycheck_map.app` mounts each router exactly once.
- `paycheck_map.desktop_data_api` owns the authenticated desktop data-home routes.
- `paycheck_map.api_inputs` owns request bodies used only by the ordinary API router; versioned
  cross-surface contracts remain in `paycheck_map.v2_contracts` and `paycheck_map.v21_contracts`.
- `web/src/api.ts` is the browser client's request and safe-error boundary. UI components do not
  invent missing backend state. The data-home UI reports an omitted schema as unavailable.

## Configuration and feature policy

- `paycheck_map.config.Settings` owns repository and Python runtime path configuration.
- `paycheck_map.desktop_policy` owns Python decisions about supported managed, acceptance, and
  disposable desktop data modes. Python callers use its predicates instead of local mode lists.
- `desktop/src-tauri/src/data_home.rs` is the native authority that creates and passes trusted macOS
  paths. Matching Python validation is an intentional cross-process trust check, not an alternate
  configuration path.

## Persistence and migration

- `paycheck_map.data_home.DataHomeManager` alone owns packaged desktop database preparation,
  migration, activation, backup, restore, and recovery-journal state.
- `paycheck_map.db` owns SQLAlchemy engine/session construction and repository-mode initialization.
- `paycheck_map.product_metadata.SCHEMA_HEAD` is the Python schema identity consumed by data-home,
  sidecar attestation, release packaging, and qualification.

## Product and release identity

- `paycheck_map.product_metadata` owns the Python public version, package version, schema head, and
  derived DMG name.
- `paycheck_map.release_candidate` owns candidate and promotion-state validation and consumes that
  identity instead of redefining it.
- `pyproject.toml`, frontend, Tauri/Cargo, and native metadata repeat versions because their build
  systems require it. `tests/test_version_consistency.py` rejects drift across those representations.

## Data ingestion and provider access

- `paycheck_map.ingestion` coordinates manual imports; `paycheck_map.adapters` owns source parsing;
  `paycheck_map.reconciliation` owns accounting classification and matching.
- `paycheck_map.plaid_service` owns read-only Plaid workflows and normalized persistence;
  `paycheck_map.plaid_client` owns the provider HTTP boundary.
- Manual import and optional Plaid are both supported. Manual import is not a legacy fallback.

## Read projections

- `paycheck_map.service_common` owns shared account classification and investment-access policy.
- `paycheck_map.service_wealth`, `service_accounts`, `service_overview`, `service_payroll`, and
  `service_summaries` own their read projections. `paycheck_map.services` is a stable public facade;
  it contains no competing projection implementation.

## Scheduling and observation

- `paycheck_map.refresh` owns explicit and once-per-local-day provider refresh orchestration.
- `paycheck_map.goal_observation` owns post-mutation goal observation and sanitized failure behavior.

## Authentication and authorization

- The packaged native runtime creates the private session/bootstrap contract;
  `paycheck_map.desktop_bootstrap` validates it for the loopback API.
- `paycheck_map.local_security` enforces session authentication, request origin/host policy,
  method/content limits, and browser security headers.
- `paycheck_map.keychain.MacOSKeychainSecretStore` is the production credential authority. The
  in-memory store is restricted by `paycheck_map.desktop_policy` to synthetic acceptance modes.

## Rendering and state management

- FastAPI responses are authoritative financial state. React owns presentation and ephemeral drafts.
- `web/src/App.tsx` owns top-level navigation and refresh coordination. Account/Activity, Income,
  Connections, Overview, and Wealth views live in their domain folders and submit changes through
  `web/src/api.ts`. `web/src/components.tsx` is only the stable export facade plus shared evidence and
  review views.
- `web/src/format.ts` owns shared general-purpose money and UTC date presentation. Domain-specific
  formatters may intentionally use different unavailable labels or precision.

## Retained compatibility boundaries

- Repository `.local` paths and the CLI remain supported development and manual-import behavior;
  they are not a packaged-runtime fallback.
- Synthetic and Keychain acceptance modes are required by signed-app qualification. Disposable
  synthetic mode is required by isolated sidecar tests. None is reachable as a production data mode
  without the native launcher contract.
- Historical database classification and Life Lab legacy evidence remain readable because current
  cutover and evidence views use them. They do not provide an alternate mutation engine.
