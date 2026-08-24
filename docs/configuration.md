# Configuration

Money Map has two configuration boundaries: small repository-mode developer overrides and
launcher-owned packaged-desktop protocol values. It does not load a checked-in `.env` file.

## Repository-mode environment

`paycheck_map.config.Settings` reads variables with the `PAYCHECK_MAP_` prefix. These are the
supported developer-facing overrides:

| Variable | Default | Use |
| --- | --- | --- |
| `PAYCHECK_MAP_LOCAL_DIR` | `<repository>/.local` | Put the inbox, database, reports, and backups under another private root. CI and tests use this for isolation. |
| `PAYCHECK_MAP_PORT` | `8765` | Select another local port for `paycheck-map serve`. The service still binds only IPv4 loopback. |
| `PAYCHECK_MAP_HOST` | `127.0.0.1` | Safety guard only. Any other value makes startup fail; network exposure is unsupported. |

Set overrides in the process environment, for example:

```bash
PAYCHECK_MAP_LOCAL_DIR=/absolute/private/path uv run paycheck-map serve
```

The selected directory may contain financial data. Keep it outside Git, restrict access to the
local user, and do not use a shared or synchronized repository path. `PAYCHECK_MAP_PROJECT_ROOT` and
the `PAYCHECK_MAP_DESKTOP_*` names are internal runtime/test fields; they are not supported manual
configuration.

## Packaged desktop configuration

The Tauri launcher supplies desktop mode, data mode, Application Support, Cache, Logs, bootstrap and
control descriptors, owner process, and bundle roots to its sidecar. The sidecar validates the
complete contract and fails closed when required fields are missing or inconsistent. Do not launch
the sidecar directly or hand-construct these values.

`MONEY_MAP_*` build and qualification variables are also controlled inputs to the versioned
packaging and installed-app qualification scripts. Their exact use belongs to the
[packaging](v3/desktop-packaging.md) and
[qualification](v3/desktop-release-qualification.md) procedures, not ordinary local setup.

## Secrets and external integration

Manual import requires no credentials. Plaid is optional and accepts credentials only through the
application's private native macOS prompts. Client credentials, the stable local client identity,
and per-connection access tokens are stored in versioned macOS Keychain namespaces. They are not
supported as environment variables, `.env` entries, request bodies, browser storage, or database
columns.

The production application exposes only production Plaid setup in the Connections view. Tests and
bounded acceptance paths also exercise sandbox configuration. Provider calls occur only after the
operator configures, connects, refreshes, reauthorizes, or removes a connection.

## Checked-in calculation and identity inputs

- `config/contribution_limits.json` contains versioned retirement contribution limits used by the
  forecast engine.
- `src/paycheck_map/data/income_benchmarks.json` contains the generated public aggregate benchmark
  artifact used by Life Lab. Runtime code does not fetch benchmark data.
- `src/paycheck_map/product_metadata.py` owns Python product/package versions, schema head, and the
  derived desktop artifact name. Build-system manifests repeat required versions and consistency
  tests reject drift.
- `alembic/versions/` is the ordered database schema history; migration `0009_goal_persistence` is
  the current head.

Changing a checked-in calculation input or schema is an implementation change and requires focused
tests plus the complete source gate. It is not an operator configuration action.
