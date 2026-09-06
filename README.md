# Money Map

Money Map is a local-first, read-only application for reconstructing where compensation went and
exploring future allocation choices. It does not move money or store bank passwords.

Current candidate: **3.0.0-beta.1 — not accepted for release**.

## Start here

Use Python 3.12, uv, Node.js 22 and pnpm 10.9.0. From the repository root:

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

- [Testing](docs/testing.md): complete source gate, native checks and CI
- [Configuration](docs/configuration.md) and [operations](docs/operations.md): runtime settings and local workflows
- [Architecture](docs/architecture.md) and [module ownership](docs/v3/single-source-of-truth.md)
- [Maintenance](docs/maintenance.md): large-file boundaries and follow-up work
- [Documentation index](docs/README.md): security, accounting, product and release references

Run `uv run --locked --python 3.12 paycheck-map --help` for supported commands. There is no hosted
deployment. Signed desktop builds and owner acceptance are separate workflows; passing tests does
not qualify or release a candidate.
