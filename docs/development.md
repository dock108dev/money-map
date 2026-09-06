# Development guide

## Supported toolchain

The source gate is exercised with Python 3.12, `uv`, Node.js 22, and pnpm 10. The native macOS
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

The command builds `web/dist` when it is absent, initializes the repository-mode database under
`.local/`, and serves the API and compiled React application at `http://127.0.0.1:8765`. The server
rejects a non-loopback host.

For frontend-only iteration after dependencies are installed:

```bash
pnpm --dir web dev
```

This is a development asset server, not the supported integrated product workflow.

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

Use [Testing](testing.md) for the complete source gate, focused commands, native prerequisites and
CI check names. That guide owns validation commands; avoid adding a second checklist here.
[Maintenance](maintenance.md) records the large-file boundaries and appropriate extraction points.

## Deployment and release boundary

There is no hosted deployment. The production-relevant target is the signed, arm64 macOS desktop
application described by the [desktop packaging](v3/desktop-packaging.md),
[release qualification](v3/desktop-release-qualification.md), and
[release contract](v3/release-contract.md) documents. Those workflows require an exact clean commit,
Apple signing identity, disposable build/qualification roots, and separate release authorization.
Ordinary development and pull-request checks do not package, install, sign, publish, or promote a
candidate.

## Change workflow

1. Check `git status` and preserve unrelated worktree changes.
2. Keep real financial state under `.local/`; tests and examples must remain synthetic.
3. Follow the [SSOT map](v3/single-source-of-truth.md) instead of introducing parallel policy paths.
4. Add focused regression coverage for changed behavior or module boundaries.
5. Run the source gate and the native gate when applicable.
6. Do not create migrations, access providers or owner Keychain data, package, sign, tag, publish, or
   push unless that action is explicitly in scope.
