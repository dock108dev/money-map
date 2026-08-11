# ADR 0008: Make cash flow the primary Money Map surface

## Status

Accepted for Money Map v2.1 Slice 0. Runtime remains v2.0.0.

## Context

ADR 0007 made Goals the frequent-use operational surface while separating Goals,
Retirement, Life Lab, and the supporting money views. The completed v2.0 product proved
those ownership boundaries, but its ordinary hierarchy still begins with a long-dated goal
instead of the recurring cash pattern that determines whether any goal is supportable.

Slice 0 changes no runtime, schema, persistence, API, or visible behavior. It freezes the
v2.1 product hierarchy and executable arithmetic before later slices consolidate period cash
flow and change the default route.

## Decision

Money Map v2.1 is cash-flow-first:

1. **Cash Flow** is the future frequent-use default. It owns selected-period money in,
   money out, net cash flow, monthly reconciliation, the current recurring margin, source
   coverage, and freshness.
2. **Goals** supports Cash Flow by translating one operational target into a monetary gap.
   It does not become the default surface or infer that accessible wealth has been reserved.
3. **Retirement** remains an occasional, independent solvency surface.
4. **Life Lab** remains an optional, isolated experimental workspace.

This decision supersedes only the ADR 0007 statement that Goals is the frequent-use
operational surface. ADR 0007 otherwise remains accepted. In particular, v2.1 preserves:

- the existing goal program, exclusive owner reservation, fingerprints, immutable
  check-ins, duplicate prevention, and stale-write boundaries;
- exact-decimal arithmetic and the five evidence classes;
- the accepted actual-calendar goal-date formula and final-cent rounding;
- accessible and restricted asset ownership, including retirement exclusion;
- Retirement's default goal exclusion and non-mutation guarantee;
- Life Lab seed isolation and explicit preview/confirmation promotion boundary; and
- all v2.0 accounting, provenance, recovery, privacy, manual-import, and read-only Plaid
  contracts.

The normative definitions and synthetic examples are in
`docs/v2.1/cash-flow-and-goal-gap-contract.md`. The pure executable contracts are
`src/paycheck_map/v21_contracts.py` and `web/src/v21-contracts.ts`; neither is connected to
a production route or component in Slice 0.

## Consequences

Later slices have one source of truth for period cash flow and goal-gap language. A
historical selected-period net cannot serve as the current recurring margin. Monthly rows
must reconcile to their summary, excluded transfers remain auditable without becoming cash
in or out, and unavailable dependencies remain unavailable instead of becoming zero.

Slice 0 intentionally creates no service, endpoint, route, component, table, migration,
report, connection action, or version promotion. Runtime behavior stays v2.0.0 until a
later accepted slice implements the contract.
