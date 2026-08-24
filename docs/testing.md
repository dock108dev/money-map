# Testing and validation

## Complete source gate

From the repository root, after the locked Python and frontend installations described in
[Development](development.md), run:

```bash
uv run paycheck-map verify
```

The command builds the frontend first so a clean checkout has the assets required by runtime tests,
then runs the complete Python test suite, Ruff formatting and linting, strict mypy, Vitest,
TypeScript checking, the documentation-link check, and the private-data scan. It does not use Plaid
credentials or real financial files.

Build the distributable Python artifacts separately when packaging metadata changed:

```bash
uv build
```

## Focused checks

Use the smallest relevant command while iterating, then run the complete gate before handoff:

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

Tests create disposable databases and synthetic files through `tests/conftest.py`. Never point a
test at the repository `.local` database or a packaged Application Support directory. The checked-in
examples and fixtures are synthetic and are the only approved financial-file shapes in Git.

## Native macOS gate

Native shell, lifecycle, proxy, path, capability, and qualification changes require:

```bash
cd desktop/src-tauri
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

`rust-toolchain.toml` pins the local and CI toolchain. These checks compile and test native code but
do not create, sign, install, or launch a release application.

## Continuous integration

Pull requests and pushes to `main` run:

- `source`: complete source gate and Python distribution build on Python 3.12.
- `python-3.13` and `python-3.14`: locked-install backend compatibility tests.
- `native-macos`: the native macOS gate.
- repository-managed CodeQL analysis for Actions, JavaScript/TypeScript, Python, and Rust.

The workflow uses read-only repository permissions, immutable action revisions, lockfile-keyed
download caches, ephemeral state, bounded timeouts, and cancellation of superseded runs. It does not
receive application secrets or run release operations.

## Gates intentionally outside ordinary CI

Dependency advisory audits, arm64 sidecar/application construction, Apple code signing, DMG
reproducibility, installed-app qualification, sleep/wake and offline campaigns, provider-backed
Plaid checks, owner-data cutover, tagging, and publishing have platform, identity, external-service,
or release-authorization requirements. Follow the versioned desktop and release guides for those
gates; a green pull request does not satisfy or authorize them.
