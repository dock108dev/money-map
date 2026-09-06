# Testing and validation

## Complete source gate

From the repository root, after the locked Python and frontend installations described in
[Development](development.md), run:

```bash
uv run --locked --python 3.12 paycheck-map verify
```

The command builds the frontend first so a clean checkout has the assets required by runtime tests,
then runs the complete Python test suite, Ruff formatting and linting, strict mypy, Vitest,
TypeScript checking, the documentation-link check, and the private-data scan. It does not use Plaid
credentials or real financial files.

Build the distributable Python artifacts separately when packaging metadata changed:

```bash
uv build --python 3.12
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

Use a disposable checkout with the frontend already built by the install workflow. A clean tree
needs Tauri's compile-time sidecar entry, so create the same empty fixture as CI before checking:

```bash
cd desktop/src-tauri
install -d binaries
ci_sidecar_fixture="binaries/money-map-sidecar-$(rustc --print host-tuple)"
if [ ! -e "$ci_sidecar_fixture" ]; then
  install -m 755 /dev/null "$ci_sidecar_fixture"
fi
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

`rust-toolchain.toml` pins the local and CI toolchain. These checks compile and test native code but
do not create, sign, install, or launch a release application. On a clean hosted runner, CI creates
an empty executable sidecar fixture solely to satisfy Tauri's compile-time external-binary manifest;
native unit tests do not treat that fixture as a built or qualified sidecar.
Never use this fixture to launch or package the application; release builds supply the real sidecar.

## Continuous integration

Pull requests and pushes to `main` run:

- `source`: complete source gate and Python distribution build on Python 3.12.
- `native-macos`: the native macOS gate.

The same workflow supports manual dispatch. `.github/dependabot.yml` schedules dependency-update
pull requests weekly on Monday at 09:00 Eastern for uv, npm, Cargo and Actions. That is repository
maintenance, not an application data-refresh job.

Python 3.13/3.14 compatibility jobs are deferred while the app is used on one machine. The
source job already runs the complete backend suite; the native job checks separate Rust code.

The workflow uses read-only repository permissions, immutable action revisions, lockfile-keyed
download caches, ephemeral state, bounded timeouts, and cancellation of superseded runs. It does not
receive application secrets or run release operations.

The packaging step selects the same Python 3.12 interpreter as the source gate. The gate also
enforces `--locked`, so it cannot silently refresh dependency resolution. Action logs retain each
command's output; runtime state, databases and financial fixtures are not uploaded as artifacts.
Download the per-job logs from the Actions run when diagnosing a failure.

CodeQL default setup, required checks and branch protection are GitHub-side settings, not defined
by this workflow. This documentation pass did not refresh that remote configuration or run hosted
Actions. Inspect the repository's Actions runs, code-scanning setup and rulesets before claiming
hosted readiness or enforced merge protection. Local source/native success cannot establish runner,
cache, CodeQL or branch-rule behavior.

## Gates intentionally outside ordinary CI

Dependency advisory audits, arm64 sidecar/application construction, Apple code signing, DMG
reproducibility, installed-app qualification, sleep/wake and offline campaigns, provider-backed
Plaid checks, owner-data cutover, tagging, and publishing have platform, identity, external-service,
or release-authorization requirements. Follow the versioned desktop and release guides for those
gates; a green pull request does not satisfy or authorize them.

## Documentation workflow validation — September 6, 2026

Validated a fresh disposable checkout of `d9c2cd0` plus this documentation/CLI change, with a new
locked Python 3.12 environment. Frozen frontend install, frontend build and `uv sync --all-extras
--locked` passed. The complete source gate passed: 557 Python tests, one existing opt-in restored-copy
drill skipped, 225 web tests, Ruff formatting/lint, strict mypy (113 files), TypeScript, documentation
links and the private-data scan. Native formatting, Clippy and 44 tests passed using the compile-only
sidecar fixture; Python sdist/wheel construction also passed.

A disposable synthetic operation walkthrough exercised CLI help/version, initial and duplicate
imports, partial-import failure, report prerequisite rejection, report generation with payroll,
backup, rollback, restore, payroll regeneration/status, and sync/status with zero provider
connections. Integrated `serve` returned health and HTML on an alternate IPv4 loopback port and was
stopped afterward. No provider, Keychain or installed signed-app workflow was exercised. Benchmark
regeneration and release/cutover scripts were inspected but not executed because they fetch external
inputs or construct/qualify a different release artifact; use their dedicated reviewed workflow.
