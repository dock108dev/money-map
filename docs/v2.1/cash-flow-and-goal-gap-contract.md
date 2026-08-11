# Money Map v2.1 cash-flow and goal-gap contract

## Scope

This is the normative source for the v2.1 cash-flow-first language and arithmetic. Its
executable mirrors are `src/paycheck_map/v21_contracts.py` and
`web/src/v21-contracts.ts`; serialized synthetic vectors live at
`examples/synthetic/money-map-v2.1-contracts.json`.

All money crosses an API-style boundary as an exact two-place decimal string. Arithmetic
uses decimal cents with final monetary rounding `ROUND_HALF_UP`. A formatted currency
label is presentation, not contract data. Every available monetary value carries one of
`observed`, `derived`, `user_entered`, or `assumed`; an unavailable value carries
`unavailable` and a reason. Missing evidence never becomes an evidenced zero.

## Selected-period cash flow

The selected start and end dates govern the summary, every monthly row, coverage,
transaction count, and later activity evidence together. The presets are:

- **All imported history:** the explicitly reported imported coverage range.
- **Trailing 12 months:** the first day of the month eleven months before `as_of_date`
  through `as_of_date`.
- **Year to date:** January 1 of `as_of_date`'s year through `as_of_date`.
- **Custom range:** the explicit inclusive start and end dates.

For the inclusive selected period:

- **Money in** = external cash inflows + interest received.
- **Money out** = external cash outflows + fees paid.
- **Net cash flow** = money in - money out.
- Matched owned-account transfers and transactions classified as internal transfers are
  excluded from both money in and money out. Their absolute amounts and counts remain
  separately auditable.
- Investment market movement, balance changes, and employer contributions that never
  entered cash are not cash inflow.

Summary and monthly rows use the same classification and inclusive date boundaries. Each
monthly row lies within the selection; rows are ordered and non-overlapping. The exact sums
of monthly external inflows, interest, money in, external outflows, fees, money out, net,
excluded-transfer amounts, counts, and transaction counts equal the period summary. A
month is marked partial when its row covers less than that whole calendar month. The
coverage start and end, partial opening and closing state, transaction count, evidence
completeness, freshness, and warnings remain explicit even when activity is zero.

## Current recurring facts

Historical period performance and the current supported recurring pattern are independent
facts:

- **Current monthly margin** = effective recurring take-home - observed recurring monthly
  outflow.
- **Stabilization gap** = `max(-current monthly margin, 0)`.

The recurring margin is negative, zero, positive, or unavailable. It is never calculated
by dividing the selected-period net by a month count, and the selected-period net must not
be substituted for it. Missing recurring payroll makes the margin and stabilization gap
unavailable without affecting evidenced period cash flow or the independent goal pace.
Missing recurring-outflow coverage has the same dependent-only propagation.

## Goal facts

The operational goal remains the owner of target, date, protected cash floor, and explicit
reservation. The v2.1 contract imports `remaining_funding_months` and
`required_funding_pace` from the existing `goal-arithmetic-v1` implementation. It does not
create a second goal-date formula.

- **Remaining target** = `max(goal target - explicit owner reservation, 0)`.
- **Required goal pace** retains the existing inclusive actual-calendar fractional-month
  convention and rounds only the final monetary result to cents.
- **Combined monthly improvement** =
  `max(required goal pace - current monthly margin, 0)`.

When the margin is negative, the combined result contains the separately visible
stabilization gap plus the required goal pace. Accessible wealth reduces the goal only
after the owner explicitly enters a reservation. Retirement and otherwise restricted
wealth remain excluded.

An active goal, completed goal, expired unfinished goal, and cash-floor breach are distinct
states. An expired unfinished goal has unavailable required pace; a completed goal has an
evidenced `0.00` pace. Missing or stale required evidence returns unavailable with a reason.
A negative, zero, or positive recurring margin remains separately identified even when the
goal has another state.

## Synthetic arithmetic example

The following invented contract example demonstrates the relationship; it is not an owner
snapshot or financial advice:

| Fact | Exact amount |
|---|---:|
| Current monthly margin | `-5602.98` |
| Stabilization gap | `5602.98` |
| Required goal pace | `39003.52` |
| Combined monthly improvement | `44606.50` |

The arithmetic is `max(39003.52 - (-5602.98), 0) = 44606.50`. The repository vectors use
invented institutions, transactions, identifiers, dates, and amounts and contain no owner
accounts, connection facts, Review values, private paths, or hashes.

## Slice 0 boundary

These definitions and validators are pure contract surfaces. Slice 0 does not select
production transactions, infer recurring facts, match transfers, create or alter APIs,
change navigation or UI, write a database, create a migration, contact Plaid, generate a
report, or promote version 2.0.0.
