# ADR 0006: Keep Life Lab deterministic, access-aware, and separate

## Status

Accepted for Money Map v1.1.0; extended for v1.2.0 and corrected in v1.2.1.

## Context

Total net worth alone cannot answer when work can become optional. Money held in pretax
retirement, HSA, restricted equity, or an unmodeled home may exist while the cash and
sellable-investment bridge fails. A single success percentage would also imply a
probabilistic methodology and input quality the local evidence does not currently have.

The desired product must support arbitrary ages and generic life goals rather than
hard-coded examples such as a particular trip, house, or retirement date.

## Decision

- Add a separate Life Lab profile, generic goal, scenario, and monthly-period schema.
- Reuse observed normalized balances and completed detailed payroll without changing
  the existing 12-month forecast or evidence records.
- Divide assets into cash, confirmed accessible investments, pretax retirement, HSA,
  restricted/unverified assets, and debt. Do not use inaccessible buckets for ordinary
  spending.
- Use three labeled, deterministic real-return paths and expose every assumption and
  major omission. Never present these paths as a probability of success.
- Fund required life and required goals before optional life and optional goals.
- Report the first required shortfall and distinguish an accessible bridge failure when
  retirement assets remain before age 59½. Do not assume a 401(k) loan or tax exception.
- Represent every splurge or milestone through the same dated-goal fields.
- Save immutable input/assumption snapshots, monthly results, version strings, warnings,
  and a source fingerprint. Mark a snapshot stale when current inputs no longer match.
- Generate state-income context from versioned public IRS thresholds and BLS CPI-U into
  a checked-in aggregate-only artifact. Runtime projection remains network-free and
  labels salary-versus-AGI comparability limits.
- In v1.2.1, solve every age/path backward for the minimum recurring after-tax income
  needed to repair the full path and the accessible-capital event needed at work stop to
  fund retirement from that point onward. Report an earlier required liquidity hole as a
  separate prerequisite instead of replacing the retirement deadline. Do not stop at a
  presentational cap.
- Translate the capital requirement into editable compound-sprint, business-exit, and
  401(k)-loan arithmetic that shares the target and work-stop deadline by default. Label
  extraordinary return and exit assumptions as requirements, not forecasts; identify
  edited targets or dates as custom math; require eligibility inputs for borrowing; and
  never inject a borrowing route into the core projection without an explicit future decision.

## Consequences

The output is inspectable and honest about liquidity, but it is not yet a complete
retirement, tax, healthcare, debt, or estate model. Adding those domains requires new
explicit assumptions and tests rather than silently widening existing buckets.

The v1.2.1 reverse solver can therefore say what a fanatical path mathematically demands
without claiming that its market return, company valuation, financing, or loan eligibility
is realistic. The gap between the formula and proof remains visible to the user.
