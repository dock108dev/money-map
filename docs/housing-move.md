# Housing Move: implementation and owner evaluation

Housing Move is a separate planning workspace in the ordinary navigation. It creates a housing
goal without requiring an existing operational goal or importing accounts. A saved document contains
the goal, baseline, ownership assumptions, dated transition items and up to eight named alternatives.
It does not reserve money in another goal or write to imported financial records. Use Accounts,
Income allocations, Cash Flow and Review to reconcile the baseline, then explicitly enter the
planning amounts and their sources/dates. Saved baselines remain dated rather than silently changing
after imports. Unknown values stay null; zero is an explicit statement of no cost. Coverage checkboxes
are user attestations, not automatic evidence of completeness.

The Long Branch starting brief fills only the supplied amount to clarify, payment, rate, destination,
rent and target date. Closing, funds and rental dates are adjustable planning assumptions. It does
not infer principal from an ambiguous payment or assign the $260,000 to property value or mortgage
balance. Approximate loan age/term is retained in notes; a current balance and separate P&I amount
are required for the debt projection. The payoff at closing is a separate quote or explicit estimate.

## Calculation contract (housing-v1)

All amounts use Decimal arithmetic, with cents rounded half-up for display and required saving rounded
up to cents. Dates use date-only arithmetic. No market/network inputs are fetched.

- Sale cash = sale price − dated mortgage payoff − selling expenses. This is equity converted to
  cash after debt settlement and expenses, not a profit calculation. Negative proceeds are due at
  closing even if the positive-proceeds availability date is later.
- Transition funding starts with cash dedicated to both the move and its reserve, a subset of liquid
  cash. A reserve already held outside that subset must be assigned to the plan once; it is never
  subtracted again from the full cash comparison. Savings accumulate on
  completed monthly anniversaries of the baseline date. Dated expenses and deposits reduce funds;
  refunds increase them; positive proceeds arrive on the entered availability date. The reserve
  is a protected floor, never an expense. Required monthly saving is the maximum cumulative deficit
  relative to that floor divided by completed saving dates. A deficit before the first saving date
  is shown separately as cash to dedicate now; no monthly saving can repair that earlier shortage.
- Rental overlap is automatically added to the transition schedule, due on rental-start anniversaries
  and prorated over calendar days through closing. Do not enter it a second time as a transition item.
  The cash comparison already includes overlapping ownership/rent, so it does not subtract these
  timeline overlap entries again. Same-day receipts/costs are netted; if intraday availability matters,
  use the next business date for funds availability.
- Monthly housing payments = total mortgage payment + costs outside that payment, versus rent +
  costs outside rent. Escrow belongs in the total payment, not again in extras. P&I is a component
  used for debt reduction, not an additional expense. Income is cash take-home; non-housing spending
  excludes all housing. Other savings are allocations from that income, not additional expenses.
- The comparison runs from baseline through the explicit end date. Monthly income and outflows are
  spread evenly across each calendar month's days; event cash is applied on its entered date. It is
  a planning estimate, not a bank-balance forecast around payday or actual bill due dates. Ownership
  stops at closing; rent begins on rental start. A sale-before-move gap requires explicit temporary
  accommodation costs. Prepaid rent must replace corresponding rent cash outflows; it must not be
  added as a new transition expense. The current interface models ordinary rent, not a prepaid lease.
- Mortgage debt reduces on monthly anniversaries: payment P&I minus opening principal times annual
  rate / 1200, capped at remaining debt. Negative amortization increases debt. Cash mortgage payments
  follow the same calendar-day budgeting convention as other monthly outflows. The entered closing
  payoff overrides the estimated balance for the sale; notes must identify its source/date and fees.
- Stay net worth = cash + constant condo value − remaining mortgage + other net assets + savings
  transferred elsewhere. Move net worth includes unsold property/debt before closing; after closing
  it includes refundable deposits and positive sale proceeds receivable until available. Deposits
  reduce liquidity without becoming expenses. An unknown return date leaves the deposit as an asset.
  Other net assets exclude this cash, condo and mortgage. Values and unrelated debts are held constant.
  No appreciation, investment return, tax benefit or unentered tax expense is assumed.

These are always conditional estimates. Missing required monetary inputs withhold dependent results;
unchecked completeness or unknown condo meaning remain visible warnings. A plan can be saved before
it is complete. Changing any field clears the previous preview. Full projections require complete
monetary inputs; sale proceeds and monthly budget can be shown independently when their inputs exist.

## Persistence and migration design

`housing.py` owns immutable request validation and calculation; `api_housing.py` owns API transactions
and revision checks. `models.HousingPlan` owns the single JSON document with a typed version-one input
contract, revision and update timestamp. Inputs are persisted; results are recomputed with the recorded
engine version when opened. This is an editable plan, not an immutable historical projection snapshot.
`planning_snapshots.py` remains the authority for Retirement/Lab historical results.

Authorized migration `0010_housing_plans` follows `0009_goal_persistence` and adds only `housing_plans`.
It performs no backfill and alters no imported, operational-goal or historical snapshot rows. Existing
0009 remains a supported migration source. Metadata is advanced in Python and native code. Repository
initialization uses Alembic; packaged activation continues through verified staging and atomic activation.
No owner database is migrated during engineering validation. Downgrade drops housing plans and is only
for disposable validation; owner rollback uses the verified pre-migration backup, never an in-place
lossy downgrade. Synthetic tests cover an upgrade from 0009, repeated upgrade, preservation, integrity,
foreign keys, rollback, saved plans and optimistic-write conflict refusal.

## Guided owner use (all steps not run)

Start only after the artifact and data-setup prerequisites in
[owner-local delivery](v3/owner-local-delivery.md). The facilitator supplies one short prompt, waits
for operation and actual feedback, and records the owner's words. No expected answer or verdict is
suggested. Keep raw account values outside engineering trackers.

| Step | Prompt |
| --- | --- |
| 1 | Add the accounts you want included and tell me what you understand about your current finances. |
| 2 | Show me where your money goes today and what is available for goals. |
| 3 | Set up the Long Branch move you want to evaluate. |
| 4 | Use the plan to understand how much cash a condo sale could leave you. |
| 5 | Find out what you would need available before moving and what to set aside. |
| 6 | Compare staying here with moving to Long Branch. |
| 7 | Change an assumption that matters to your decision and tell me what changes. |
| 8 | Leave the plan and return to it, then tell me what you would do next. |

For each finding record session/step/candidate/build mode, observed behavior, verbatim feedback,
minimal reproduction, engineering interpretation (separately), focused fix and synthetic validation.
Then return the affected step to the owner on the identified new candidate. Status is not run,
observed, blocked or revisited. Tests do not imply owner acceptance or a decision to move. If a
calculation does not explain the user's question, record that gap and fix it; do not replace product
work with another preparation plan. Signing, provider/data access, cutover and publication stay separate.
