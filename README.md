# Money Map

Money Map is a local-first financial evidence application for reconstructing where compensation went and
exploring future allocation choices. Provider access is read-only; the app writes local imports,
corrections, goals and planning snapshots. It does not move money or store bank passwords.

Version **3.0.0-beta.1** is prerelease software.

## Start here

Use Python 3.12, uv, Node.js 24 (24.15.0 or newer) and pnpm 10.9.0. The repository `.nvmrc`
selects the Node.js baseline for local development and CI. From the repository root:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
uv sync --python 3.12 --all-extras --locked
uv run --locked --python 3.12 paycheck-map serve
```

Open `http://127.0.0.1:8765`. Build the frontend before installing Python because the Python package
includes those assets. See [Development](docs/development.md) for setup details and the repository map.

Private imports, databases, reports and backups belong under the ignored `.local/` tree.
Never commit financial files or credentials. Tests use synthetic data and disposable databases.

## Engineering guides

- [Testing](docs/testing.md): focused checks for changed behavior
- [Configuration](docs/configuration.md) and [operations](docs/operations.md): runtime settings and local workflows
- [Architecture](docs/architecture.md) and [module ownership](docs/v3/single-source-of-truth.md)
- [Maintenance](docs/maintenance.md): source ownership, cleanup decisions and remaining boundaries
- [Documentation index](docs/README.md): local use, accounting and implementation references

Use [the personal-use approach](docs/personal-use.md): try the existing local app,
improve useful flows and check affected calculations/persistence.
Run `uv run --locked --python 3.12 paycheck-map --help` for supported commands.
A native installer is optional; the existing local server is a usable path.

## UI design

See [UI design](docs/ui-design.md) for the project’s styles and accessibility requirements.
