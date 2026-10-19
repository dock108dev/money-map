# Development guide

## Supported toolchain

The source gate uses Python 3.12, `uv`, Node.js 24 (24.15.0 or newer), and pnpm 10.9.0. The
repository `.nvmrc` selects Node.js for local development and CI. The native macOS
runtime additionally requires the Rust toolchain and the system dependencies needed by Tauri.
The declared Python range remains 3.12 through 3.14. For the current single-machine stage, CI
runs the complete source gate only on 3.12; 3.13/3.14 compatibility runs are deferred. The native
gate uses the Rust version pinned in `rust-toolchain.toml`.

## Install

From the repository root:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
uv sync --python 3.12 --all-extras --locked
```

Build the frontend before installing Python: the package includes `web/dist`, including during
editable installation. CI repeats the build inside the verification gate so the gate is also
self-contained after installation.

There is no checked-in `.env` template. Ordinary manual-import development needs no credentials.
Plaid credentials are optional and must be entered through the application so secrets stay in
macOS Keychain rather than source files, shell history, or the database.

## Run locally

```bash
uv run --locked --python 3.12 paycheck-map serve
```

The command builds `web/dist` when it is absent or files under `web/src` are newer, initializes the repository-mode database under
`.local/`, and serves the API and compiled React application at `http://127.0.0.1:8765`. The server
rejects a non-loopback host.

For frontend changes, stop the integrated server, rebuild with `pnpm --dir web build`, and run
`serve` again. Rebuild explicitly after changing Vite configuration, dependencies or compiler
settings: the automatic stale-asset check watches `web/src`, not those files. There is no live
reload in the integrated server.

`web/package.json` also defines `dev` for Vite asset development on port 5173. Its proxy targets
8765, but does not satisfy the API's exact Host/origin boundary; it is not an end-to-end product
workflow. Do not loosen backend admission checks to make this proxy work. A supported hot-reload
workflow needs a separate development transport decision.

## Repository map

- `src/paycheck_map/`: Python application, domain services, persistence, provider integration, and
  packaged sidecar
- `web/src/`: React views, API client, contracts, and presentation tests
- `desktop/src-tauri/`: native macOS shell, lifecycle, proxy, path authority, and qualification code
- `alembic/versions/`: ordered database migrations; current head is defined in
  `paycheck_map.product_metadata`
- `config/`: checked-in public calculation inputs
- `examples/synthetic/`: safe import examples only
- `scripts/`: build, qualification, privacy, and synthetic rehearsal tools
- `tests/`: backend, contract, migration, packaging, and security tests using synthetic state
- `docs/`: current engineering guides, architecture decisions, release records, and versioned contracts

The current module authority map is [single-source-of-truth.md](v3/single-source-of-truth.md).
Use the v2 Goals, Retirement and Lab APIs for planning. The retired combined Life Plan routes and
editors are removed; historical snapshots remain available in Lab through its current API.
API route families use `api_*.py`; read projections use `service_*.py`; `api.py` and `services.py`
remain stable entry facades. React product views live in domain folders, while `components.tsx`
retains only stable exports and the shared evidence/review surfaces.

## Validation

Use [Testing](testing.md) for focused commands and available broader tools. That guide owns validation commands; avoid adding a second checklist here.
[Maintenance](maintenance.md) records the large-file boundaries and appropriate extraction points.

## Personal and small-group use

The existing local server or installed Mac app is enough. Use [personal use](personal-use.md) for current scope. Build assets only when required to run a source change. Signed DMGs, clean-commit build manifests, release authorization campaigns and public delivery are not current prerequisites.

## Change workflow

1. Check `git status` and preserve unrelated worktree changes.
2. Keep real financial state under `.local/`; tests and examples must remain synthetic.
3. Follow the [SSOT map](v3/single-source-of-truth.md) instead of introducing parallel policy paths.
4. Add focused regression coverage for changed behavior or module boundaries.
5. Run focused checks for the actual change and try the affected ordinary flow.
6. Back up before necessary schema/data updates. Provider/Keychain access and real-data setup keep
   their existing authorization; distribution/publishing work remains deferred.
