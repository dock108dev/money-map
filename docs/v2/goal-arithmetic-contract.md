# Money Map v2 goal arithmetic contract

## Scope and versions

This document freezes `goal-arithmetic-v1` for Slice 0. The executable contract vectors
live in `src/paycheck_map/v2_contracts.py`; Slice 2 will implement the runtime goal engine.
All monetary arithmetic uses `Decimal`. A final monetary result is quantized to cents with
`ROUND_HALF_UP`. No binary float participates.

Every monetary result carries one evidence class and source references through
`EvidencedMoney`. Exact serialized values such as `"12000.00"` are data. Currency symbols,
grouping separators, verdict sentences, and other display copy are outside the contract.

## Headline values

Given an effective observation date and one primary goal:

- **Accessible cash** is the sum of the latest supported checking and savings observations.
- **Accessible investments** is confirmed sellable, non-retirement investment value.
- **Accessible now** = `money(accessible cash + accessible investments)`.
- **Retirement assets excluded** is reported separately and never enters accessible now.
- **Protected cash floor** is the exact owner-entered floor.
- **Available above floor** = `money(max(accessible now - protected cash floor, 0))`.
  It is capacity, never inferred goal dedication.
- **Reserved for goal** is the exact owner-entered exclusive reservation. It is not inferred
  from an account balance and cannot exceed the goal target.
- **Remaining target** = `money(max(goal target - reserved for goal, 0))`.
- **Effective recurring take-home** is a derived monthly value from supported recurring
  payroll evidence under a versioned cadence rule. Slice 2 must expose its inputs.
- **Recurring cash-flow gap** =
  `money(max(observed recurring outflow - effective recurring take-home, 0))`.
- **Required funding pace** = `money(remaining target / funding months)` when the target is
  unfinished and not expired. A completed target has `0.00`; an unfinished expired target
  is `unavailable` rather than infinity or an invented schedule.

If a required source is absent, the dependent value is `unavailable` with a reason. Zero
means an evidenced exact zero; it never substitutes for missing evidence.

## Calendar convention

Funding months use actual calendar-month fractions, inclusive of both the observation and
target dates:

1. If both dates are in the same month, funding months are
   `(target day - observation day + 1) / days in that calendar month`.
2. Otherwise, add:
   - `(days in observation month - observation day + 1) / days in observation month`;
   - every whole intervening calendar month as `1`; and
   - `target day / days in target month`.
3. Quantize the month value to 12 decimal places with `ROUND_HALF_UP`.
4. Divide the exact-cent remaining target by that quantized month value and round only the
   final money result to cents with `ROUND_HALF_UP`.
5. If the target precedes the observation date, funding months are `0.000000000000`. An
   unfinished goal has `expired` pace status and unavailable required pace. A completed
   goal remains complete even when its target date has passed.

This actual-calendar convention automatically uses 29 days for February in a leap year.
Contract vectors cover month boundaries, same-month targets, same-day targets, expired
targets, leap day, and cent rounding.

The observation date is a live calculation input, not financial evidence. A later caller date
may change funding months and required pace without changing the source fingerprint or creating
a financial-change check-in. A persisted check-in retains the pace calculated on its original
Eastern business observation date; the current Goals card uses the live position read.

## Comparison contract

A comparison uses two immutable check-ins with different source fingerprints, ordered
from the earlier observation to the later observation. Direct components are exact
`current - previous` deltas for:

- accessible now;
- accessible cash;
- accessible investments;
- tracked debt;
- goal target;
- protected cash floor; and
- reserved amount.

These are arithmetic descriptions, not causal explanations. Supported event components
may additionally identify payroll, transfer, or market movement only when the component
contains explicit evidence references for matching source records.

The accessible-capital attribution must reconcile:

`unexplained residual = accessible-now delta - sum(evidence-supported event components)`

The residual is retained even when zero. Cash and investment deltas explain the arithmetic
composition of accessible now and are not subtracted again as causal events. Unsupported
merchant, behavioral, or event explanations cannot be represented by the typed contract.

## Milestone selection

Exactly one milestone is selected from a source-fingerprinted position:

1. If accessible cash is below the protected floor, `restore_floor` for the exact floor
   shortfall.
2. Otherwise, if the recurring cash-flow gap is positive, `close_recurring_gap` for the
   exact monthly gap.
3. Otherwise, if remaining target is positive and pace is available, `fund_goal` for the
   current required monthly pace.
4. Otherwise, when remaining target is zero, `goal_complete` for `0.00`.

If required evidence is unavailable or an unfinished target is expired, the contract
returns `data_unavailable` rather than silently skipping a higher-priority constraint.

## Non-goals for Slice 0

This contract does not change the v1.2.1 forecasting or Life Lab engines. It does not
create positions, persist check-ins, select sources, infer recurring payroll, match events,
or expose APIs. Those runtime responsibilities begin in Slice 2 after Slice 1 establishes
the additive schema.
