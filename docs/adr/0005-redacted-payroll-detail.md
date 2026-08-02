# ADR 0005: Redacted canonical payroll detail

Status: accepted
Date: 2026-07-29

## Context

The imported Oracle PDFs contain reliable page 1 summaries, while detailed page 2
facts may arrive as a user-provided transcript. The detail is needed to distinguish
retirement, HSA, health premiums, stock purchases, employer benefits, taxes, and
direct-deposit destinations. Repeating unrelated personal identifiers would increase
privacy risk without improving the accounting model.

The payslip’s official Friday payment date can also differ from the Wednesday when an
early-direct-deposit bank makes funds available.

## Decision

Add a private `paycheck-map-payroll-v1` JSON adapter that:

- records only employment and financial facts used by Paycheck Map;
- excludes names, addresses, employee identifiers, routing numbers, and deposit/check
  numbers;
- retains only masked account suffixes for net-pay destinations;
- enriches a matching summary pay date and rejects conflicting summary values;
- reconciles earnings, pretax, taxes, after-tax, and net distribution independently;
- stores employer benefits outside the employee net-pay equation;
- stores official payment date and observed funds-available date separately; and
- uses the observed date, when present, as the forecast pay-cadence anchor.

## Consequences

The December 2025 payslip can represent a final YTD snapshot without importing every
individual 2025 statement. Trailing-period totals still sum only imported current
amounts and remain labeled incomplete when paychecks are missing. Current detailed
contribution rates can seed the no-change forecast, while additional scenario rates
remain visibly separate.
