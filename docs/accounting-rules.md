# Accounting rules

All stored money uses `Decimal` with two-place database numerics. Binary floating point
is not used for stored or reconciled values.

## Payroll

For the supplied summary layout, gross earnings include imputed non-cash earnings.
The validated cash equation is:

```text
gross earnings
- imputed non-cash earnings
- pretax deductions
- tax withholdings
- after-tax deductions
= net payment
```

The general destination equation remains:

```text
cash gross compensation
- taxes
- healthcare and benefits
- employee retirement
- employee stock plan
- other deductions
= net deposits
```

Employer contributions are additional compensation and never reduce net pay.

Historical statements receive only arithmetic and duplicate-pay-date checks. Detailed
section checks run only when the source includes those sections. Missing intervening
paychecks, absent detail pages, and unmatched historical deposits are not review work.

For a detailed statement, five additional equations must independently reconcile:

```text
cash earnings + imputed earnings = gross earnings
pretax detail = pretax summary
tax detail = tax-withholding summary
after-tax detail = after-tax summary
masked net-pay destinations = net payment
```

Employer-paid HSA and retirement contributions are recorded as additional benefits and
are excluded from the employee net-pay equation. Employer payroll taxes are preserved
as context and are not counted as employee compensation.

The official payment date remains the payslip fact used for continuity and YTD checks.
When the bank makes direct-deposit funds available earlier, that observed date is a
separate cash-timing fact and anchors the forward pay cadence.

## SoFi

Checking and savings reconcile separately:

```text
opening balance + signed account activity = closing balance
```

Matched equal-and-opposite transfers remain in each ledger but cancel in the
consolidated view. Unmatched transfer candidates remain review items. Axos, Provident,
and SoFi source institution labels normalize to the canonical current institution
“SoFi”; original labels remain in source files and evidence.

Payroll destination reporting uses only the two current cash destinations: SoFi
Checking and SoFi Savings. Suffix `1206` reports as checking. Historical Provident,
Axos, legacy, and otherwise-undetailed payroll deposits report as savings while their
source labels remain unchanged in statement evidence and paycheck detail.

The gross-pay flow excludes employer-paid additions and includes imputed non-cash
taxable benefits so that taxes, deductions, net deposits, and non-cash compensation
reconcile exactly to statement gross pay. Employer retirement and HSA contributions
are shown separately as additions above gross pay.

## Fidelity

The value bridge is:

```text
opening market value
+ employee contributions
+ employer contributions
+ stock-plan contributions
+ other external deposits
- external withdrawals
+ investment result
= closing market value
```

The dollar investment result is the exact residual. Purchases, sales, dividends,
interest, and reinvestments are preserved as transactions but are not external
contributions. A percentage return is shown only when provider-reported methodology or
sufficient dated cash flows exist; otherwise the method is “not available.”

## Forecasting

The latest imported payroll statement establishes the current salary and observed
withholding/deduction baseline. The forecast begins with the next calendar month and
uses actual biweekly pay-date cadence.

- Current retirement, stock-plan, employer-contribution, HSA, and benefit rates come
  from the latest detailed payslip. They are not inferred when detail is absent.
- A higher employee contribution does not invent a higher employer match. Incremental
  matching is modeled only when an explicit match percentage is supplied.
- Proposed 401(k) and stock-plan rates are modeled separately.
- Tax effects use the latest observed withholding ratio and are labeled estimates.
- Market appreciation defaults to 0%.
- Optional return scenarios are shown separately from contributions and are not
  predictions.
- Contribution limits are year-specific configuration, never hard-coded into formulas.
- An optional cash-floor rule can redirect projected consolidated cash above the floor
  into investments; it is off by default and never moves real money.

## Life Lab projections

Life Lab is separate from the 12-month allocation forecast. It uses monthly `Decimal`
calculations in today’s dollars and stores two-place values for reproducibility.

- Cash and confirmed sellable investments fund spending first, while preserving the
  user-entered cash floor.
- Pretax retirement funds ordinary withdrawals only at age 59½ or later and receives the
  visible user-entered tax haircut. Early-withdrawal exceptions and 401(k) loans are not
  silently invented.
- HSA and restricted assets grow in the displayed paths but do not fund ordinary spending.
- After work stops, required lifestyle is funded first, then required dated goals,
  flexible lifestyle, and flexible goals. A required shortfall before retirement access
  is classified as an accessible-bridge failure when retirement money remains.
- The middle and rough paths use fixed 4% and 2% annual real returns. The early-crash
  path applies a 35% loss at work stop, two flat years, and then a fixed 3% real return.
  Cash earns 0% real in all paths.
- Results are deterministic statuses—works, essentials only, shortfall, or bridge
  failure—not probabilities. Social Security, healthcare/Medicare, pensions, RMDs,
  Roth conversions, home equity, debt schedules, and early-withdrawal strategies remain
  visible omissions in v0.2.
- Each age and path is also solved backward, without a presentational cap, for (a) the
  minimum extra after-tax monthly income received while working that repairs the complete
  path and (b) the minimum additional accessible lump sum needed at work stop to fund the
  retirement period. The retirement-capital solver evaluates success from work stop
  onward; an earlier shortfall is returned separately as a prerequisite. Solvers use the
  same monthly engine, path, goals, ordering, rounding, and end-of-plan requirements.
- The compound-sprint and business-exit cards are standalone arithmetic translations of
  that retirement-capital target and work-stop deadline. Target, deadline, seed, return,
  ownership, tax haircut, and revenue multiple remain editable. Changing the calculated
  target or deadline enters custom math mode and does not rewrite the core projection.
- The 401(k)-loan card shows a conservative normal federal-rule ceiling from the entered
  eligible vested balance and recent loan balances. It does not infer plan permission,
  eligibility, vesting, tax treatment, job continuity, or repayment ability from the
  aggregate retirement balance, and it does not silently add loan proceeds to the plan.
