# Development guide

## Supported toolchain

The source gate is exercised with Python 3.12, `uv`, Node.js 22, and pnpm 10. The native macOS
runtime additionally requires the Rust toolchain and the system dependencies needed by Tauri.
Python supports 3.12 through 3.14. CI runs the complete source gate on 3.12 and the backend test
suite on 3.13 and 3.14. The native gate uses the Rust version pinned in `rust-toolchain.toml`.

## Install

From the repository root:

```bash
uv sync --all-extras --locked
pnpm --dir web install --frozen-lockfile
```

There is no checked-in `.env` template. Ordinary manual-import development needs no credentials.
Plaid credentials are optional and must be entered through the application so secrets stay in
macOS Keychain rather than source files, shell history, or the database.

## Run locally

```bash
uv run paycheck-map serve
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
API route families use `api_*.py`; read projections use `service_*.py`; `api.py` and `services.py`
remain stable entry facades. React product views live in domain folders, while `components.tsx`
retains only stable exports and the shared evidence/review surfaces.

## Validation

Run the complete source gate before handoff:

```bash
uv run paycheck-map verify
```

Useful focused commands while editing:

```bash
uv run pytest tests/test_api.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
uv run python scripts/check_docs.py
uv run python scripts/check_private_data.py
```

For native changes:

```bash
cd desktop/src-tauri
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

`uv run paycheck-map verify` does not run the Rust checks, dependency audits, signed packaging, or
installed-app owner qualification. Those are separate gates documented in the versioned desktop and
release guides.

Pull requests and pushes to `main` run four stable GitHub checks: `source`, `python-3.13`,
`python-3.14`, and `native-macos`. CI uses locked installs, read-only repository permissions,
ephemeral synthetic state, and no credentials. Signing, packaging, release qualification, provider
access, and owner-data checks remain outside ordinary pull-request CI.

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
