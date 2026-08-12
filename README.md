# Money Map

Money Map is a local-first, read-only application for reconstructing where gross
compensation went, exploring future allocation changes, and testing what a particular
life would require from the money already tracked.
It does not move money, store bank passwords, categorize purchases, or provide
financial advice. SoFi and Fidelity can be connected through optional Plaid
read-only access or imported manually.

Current local release: **Money Map v2.1.0**.

## Privacy first

All real source files, the SQLite database, generated reports, and backups live under
`.local/`, which is excluded from Git. Put manual imports in:

```text
.local/inbox/payroll/
.local/inbox/sofi/
.local/inbox/fidelity/
```

Do not copy real statements into `tests/`, `examples/`, screenshots, or documentation.
Plaid API credentials and per-connection access tokens are stored in macOS Keychain,
not in `.local/` or the repository. Normalized account records stay in the private
SQLite database. A Plaid sync necessarily sends the authorized request through Plaid.

## Start

Install the local dependencies once, then start the application:

```bash
uv sync --extra dev
pnpm --dir web install
uv run paycheck-map serve
```

The server binds only to `127.0.0.1` and displays `http://127.0.0.1:8765`.
If the frontend has not been built, the startup command builds it locally.

Import files from the private inbox using the application’s **Import private inbox**
button, or:

```bash
uv run paycheck-map import
```

## Connect accounts with Plaid

Open **Connect** in the local application:

1. Activate Plaid Trial for real account data and paste the Production secret. The
   existing Client ID is reused automatically. The application writes the secret
   directly to macOS Keychain and never returns it.
2. Choose **Bank, credit or loan** or **Investment account**, then select the
   institution in Plaid Link.
3. Complete authorization inside Plaid Link. Money Map receives a one-time public
   token, exchanges it server-side, stores the resulting access token in Keychain, and
   synchronizes the selected read-only data.
4. Use **Update data** in the header to refresh every active account. **Update** on
   an individual connection refreshes just that connection. **Reconnect** refreshes an expired
   authorization. **Disconnect & delete** calls Plaid revocation, deletes the Keychain
   token, and removes that connection’s normalized local records.

SoFi requests posted transactions and current balances. Fidelity requests holdings,
current account values, and investment transactions. The application never requests
Plaid Transfer, Auth, Identity, payment, or trading products.

New bank links request up to 730 days of transaction history. Plaid cannot expand an
already initialized Item's history window, so an older short-history connection may
need to be removed and linked again if its available coverage does not expand after a
sync. Investment history remains subject to provider coverage and Plaid's plan.

Money Map also checks once per local calendar day when the application opens. This
automatic update can be turned off in **Add account**. Every successful day creates at
most one observed balance snapshot per account, so repeated updates are safe and do
not duplicate history. When consecutive investment values exist, the corresponding
value bridges are rebuilt automatically.

The same global refresh and its current status are available from the command line:

```bash
uv run paycheck-map sync
uv run paycheck-map sync --status
```

## Completed payroll history

The local payroll timeline covers every biweekly paycheck from January 1, 2025
through the current July 29, 2026 deposit. Imported statements remain unchanged;
missing periods are calculated from exact year-to-date checkpoints. Rebuild or
validate that timeline with:

```bash
uv run paycheck-map payroll-regenerate
uv run paycheck-map payroll-status
```

Calculated rows are completed history, not evidence warnings. Actual Plaid deposits
are linked to the matching paycheck without being counted a second time.

Money Map allocates every completed paycheck to taxes, benefits, employee saving,
employer contributions, stock-plan saving, and masked deposit destinations. Connected
bank balances are reconstructed backward across available posted activity; these
calculated balance points remain distinct from observed snapshots. Investment result
appears only when two dated values exist, and an earlier statement value can be added
from any investment account's detail view.

## Main views

- **Cash Flow:** the default frequent-use loop for the selected period, recurring baseline,
  current goal gap, and one next action
- **Goals:** supporting planning for closer/same/farther, the distinct financial change,
  and one binding milestone
- **Retirement:** an occasional deterministic solvency and accessible-bridge view
- **Life Lab:** an optional isolated experiment with explicit reviewed promotion
- **Overview:** net worth, trailing 12 complete months, paycheck flow, and monthly history
- **Accounts:** any connected bank, loan, or investment account with generic drill-down
- **Income:** all 42 completed paychecks from 2025-01-01 through 2026-07-29
- **Activity:** account flows without merchant spending categories
- **Wealth:** accessible money, retirement/restricted balances, and investment performance
- **Add account:** generic Plaid Link, local imports, and local report generation

## Life Lab

Open **Life Lab** only when you want an isolated experiment, then enter the assumptions Money Map cannot observe: date of birth,
state, essential and flexible monthly life, a protected cash floor, a visible pretax
withdrawal haircut, and any work-optional ages you want to test. Ages are ordinary
inputs rather than named templates.

Life Lab runs three deterministic, today-dollar paths: middle, rough, and an early
crash at work stop. It distinguishes confirmed accessible money from pretax retirement,
HSA, and restricted assets; pretax retirement is unavailable for ordinary withdrawals
before age 59½. A bridge failure therefore stays visible instead of being hidden by
total net worth. The app does not assume a 401(k) loan, an early-withdrawal exception,
or a probability of success.

For every age and market path, Life Lab solves backward for both the minimum additional
after-tax monthly income that repairs the full path and the additional accessible capital
needed at the selected work-optional date. An earlier cash-flow hole stays visible as a
separate prerequisite; it does not hijack the retirement deadline. The Drive Calculator
uses one editable target and deadline across four inspectable routes: linear earnings, a
seed-and-weekly-compounding sprint, an ownership/tax/multiple business exit, and a
conservative 401(k)-loan ceiling. These are arithmetic requirements, not predictions of
repeatable returns, an investor, an exit, plan loan eligibility, or personal suitability.

Dated goals use generic amount, date, priority, reserved amount, and optional continuing
annual cost fields. Saved scenarios retain their inputs, engine/assumption/benchmark
versions, fingerprint, warnings, summary, and monthly projection rows; they are marked
stale when current inputs move.

The income ladder uses a checked-in public artifact derived from IRS state AGI
percentile thresholds and BLS CPI-U. Salary and AGI are different concepts, so the
ladder is labeled as context rather than a lifestyle recommendation. Building the
artifact requires network access, but running Life Lab does not:

```bash
uv run python scripts/build_income_benchmarks.py
```

## Supported sources

- Oracle/UnitedHealth Group text-based payroll summary PDF (tested against the private
  supplied layout)
- Redacted canonical payroll-detail JSON for user-supplied page 2 facts, employer
  benefits, and masked net-pay destinations
- Canonical manual CSV and XLSX ledgers for SoFi and Fidelity
- Optional Plaid read-only sync for SoFi balances/transactions and Fidelity
  values/holdings/investment transactions
- Multiple files in one batch with SHA-256 duplicate protection

Summary-only payroll captures can serve as exact cumulative checkpoints. A canonical
detail record can enrich an already imported pay date without creating a duplicate statement.
The detail importer omits names, addresses, employee identifiers, routing numbers, and
deposit/check numbers. Official payslip dates and observed early-deposit dates are
stored separately.

Axos, Provident, and SoFi institution labels normalize to the current canonical SoFi
destination. This preserves old source labels while preventing former deposit
destinations from appearing as separate current institutions.

See [docs/data-source-strategy.md](docs/data-source-strategy.md) for the canonical ledger
format and [docs/accounting-rules.md](docs/accounting-rules.md) for reconciliation rules.
See [docs/security-model.md](docs/security-model.md) before enabling Plaid.

## Verify

```bash
uv run paycheck-map verify
```

The command runs backend tests, formatting, linting, strict type checking, frontend
tests, frontend linting, the production build, and the private-data leak check.

## Continuous integration

[![CI](https://github.com/dock108dev/money-map/actions/workflows/ci.yml/badge.svg)](https://github.com/dock108dev/money-map/actions/workflows/ci.yml)

GitHub Actions runs the locked release gate, migration checks, and package build with
synthetic or empty state only. CI never requires private financial data, Plaid
credentials, or repository secrets.

## Local maintenance

```bash
uv run paycheck-map backup
uv run paycheck-map report
uv run paycheck-map rollback <batch-id>
```

Backups and reports stay under `.local/`. Restore requires an explicit backup path; see
`uv run paycheck-map --help`.
