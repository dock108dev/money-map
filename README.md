# Money Map

Money Map is a local-first, read-only application for reconstructing where compensation went and
exploring future allocation choices. It does not move money, store bank passwords, categorize
purchases, or provide financial advice.

Current candidate: **3.0.0-beta.1 — not accepted for release**.

## Quick start

Requirements: Python 3.12, `uv`, Node.js 22, and pnpm 10.

```bash
uv sync --all-extras --locked
pnpm --dir web install --frozen-lockfile
uv run paycheck-map serve
```

Open `http://127.0.0.1:8765`. Money Map refuses non-loopback binding. The first start builds the
frontend locally when needed.

Real imports, the SQLite database, reports, and backups belong under the ignored `.local/` tree.
Never add statements, account identifiers, credentials, generated reports, or SQLite files to Git.

## Verify changes

```bash
uv run paycheck-map verify
```

This builds the frontend, then runs backend tests, Python formatting and linting, strict type
checking, frontend tests, TypeScript checking, documentation-link validation, and the private-data
scan. Native desktop changes also require:

```bash
cd desktop/src-tauri
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

## Documentation

- [Developer guide](docs/development.md): setup, repository map, focused checks, and change workflow
- [Configuration](docs/configuration.md): supported environment overrides, static inputs, and secrets
- [Testing](docs/testing.md): source, compatibility, native, CI, and release-validation boundaries
- [Operations guide](docs/operations.md): imports, refresh, backup, restore, reporting, and safe data paths
- [Known limitations](docs/known-limitations.md): intentional non-support and external validation gaps
- [Documentation index](docs/README.md): current contracts, architecture, security, and historical records
- [Architecture](docs/architecture.md) and [SSOT map](docs/v3/single-source-of-truth.md)
- [Security model](docs/security-model.md) and [error handling](docs/v3/error-handling.md)
- [Product charter](docs/product-charter.md), [data-source strategy](docs/data-source-strategy.md), and
  [accounting rules](docs/accounting-rules.md)

Use `uv run paycheck-map --help` for the current command list. Packaging, signing, qualification,
owner validation, tagging, and publishing are separate controlled workflows; do not infer release
authorization from a green source gate.
