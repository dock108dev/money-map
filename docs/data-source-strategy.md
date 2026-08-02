# Data-source strategy

Manual imports are the permanent source-of-truth fallback. Put real files only below
`.local/inbox/`; that directory is excluded from Git.

Plaid is an optional read-only convenience source, not a replacement for statements
or manual exports. Plaid-normalized records use the same account, transaction,
balance, evidence, and reconciliation contracts as manual imports.

## Payroll PDFs

The v1.0 exact adapter supports the supplied text-based Oracle/UnitedHealth Group
payslip summary layout. It extracts the pay period, payment date, annual salary, current
summary values, and year-to-date values. It records the page/table location, original
label, parser version, source hash, batch, and confidence.

Scanned PDFs are represented by the adapter boundary but require a future local OCR
implementation. No OCR service or external transmission is used.

## Canonical payroll detail

`paycheck-map-payroll-v1` JSON is the private manual contract for a transcribed full
payslip. It stores only the financial and employment facts used by the application:
period dates, official payment date, optional observed early-deposit date, salary,
summary/YTD values, job title, detailed earnings, deductions, taxes, employer-paid
benefits, employer taxes, and masked net-pay destinations.

It intentionally excludes employee name, home and employer addresses, phone number,
payroll/person/assignment identifiers, check or deposit numbers, and full bank routing
or account numbers. A complete detail record must contain the earnings, imputed,
pretax, tax, after-tax, employer-benefit, and net-distribution sections. Each detailed
section reconciles to its corresponding summary before being shown as reconciled.

When the official pay date already exists from a PDF summary, a matching canonical
detail record supersedes the normalized statement evidence and replaces its aggregate
line set. A conflicting summary is rejected instead of silently overwriting facts.

## Canonical CSV/XLSX ledger

SoFi and Fidelity can be imported using the same portable columns:

| Column | Required | Meaning |
| --- | --- | --- |
| `institution` | yes | `SoFi`, `Fidelity`, or a recognized historical SoFi alias |
| `account` | yes | user-approved local display name |
| `date` | yes | ISO date (`YYYY-MM-DD`) |
| `record_type` | yes | `balance` or `transaction` |
| `role` | yes | accounting role listed below |
| `amount` | yes | exact signed decimal |
| `balance` | no | balance after a transaction |
| `description` | no | original local description |

Balance roles are `opening` and `closing`.

SoFi transaction roles are `external_inflow`, `external_outflow`,
`internal_transfer`, `interest`, `fee`, `adjustment`, `unresolved`, and
`payroll_deposit`.

Fidelity transaction roles are `employee_contribution`, `employer_contribution`,
`stock_plan_contribution`, `external_deposit`, `external_withdrawal`,
`internal_transfer`, `purchase`, `sale`, `dividend`, `interest`, `reinvestment`,
`fee`, `adjustment`, and `unresolved`.

See `examples/synthetic/` for non-private templates.

## Plaid read-only source

Bank connections request Plaid Transactions and current balances. New Items request up
to 730 days of history. Posted activity is
normalized to signed local flows; pending transactions are not imported. Payroll
credits, interest, fees, transfers, and remaining external flows are classified from
Plaid’s category plus the original description and then reconciled locally.

Investment connections request Investments holdings, current account values, and up to
the provider’s available investment-transaction history. Holdings are stored as a
current dated snapshot. Contributions, withdrawals, trades, distributions, fees, and
unresolved rows retain separate roles. A single current value never creates a
historical investment return. A second provider observation or a user-entered dated
statement value enables the exact contribution-versus-result bridge.

Every sync has a batch, status, endpoint evidence, parser version, retrieval time,
response hash, record counts, and safe failure state. Provider account and transaction
identifiers are item-namespaced and SHA-256-derived before storage, so repeated syncs
are idempotent, two connections cannot collide, and raw identifiers are not exposed in
local summaries. A failed normalization commits no partial financial rows.

## Institution-native adapters

The architecture supports additional native PDF/CSV/XLSX adapters, but v1.0 does not
claim support for any SoFi or Fidelity institution-native layout that was not supplied
and tested. Importing a new layout should fail visibly and leave the file available for
a future parser revision.
