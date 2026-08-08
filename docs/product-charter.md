# Product charter

## Purpose

Money Map reconstructs where gross compensation went, what happened after funds
reached the user’s accounts, how a proposed payroll allocation would mechanically
change the next 12 months, and what observed money plus explicit assumptions imply for
a user-defined life timeline.

The product is an evidence and reconciliation system, not a transaction categorizer,
financial advisor, tax-return engine, broker, or money-movement tool.

## v1.0 commitments

- Local-only server bound to `127.0.0.1`.
- Permanent manual file-import path with source hashes and idempotency.
- Exact-decimal accounting and explicit reconciliation residuals.
- Payroll, SoFi, and Fidelity adapters that preserve source provenance.
- Detailed payroll categories, employer benefits, masked pay destinations, annual YTD
  snapshots, and distinct official/early-deposit dates without retaining unrelated PII.
- Optional, read-only Plaid connections for SoFi and Fidelity with Keychain-backed
  credentials and revocation.
- Trailing 12 complete months and a separate latest-payroll forecast baseline.
- Contributions-only baseline forecast; optional return scenarios remain separate.
- Account-first navigation with generic bank, investment, and debt drill-downs.
- Deterministic paycheck-category allocation across every completed payroll period.
- Transaction-derived bank balance history and dated investment performance bridges.
- A separate Life Lab engine with arbitrary work-optional ages, deterministic real-return
  paths, generic dated goals, accessible-money bridge checks, and reproducible snapshots.
- Public state-income context with source year, dollar basis, version, definition, and
  an explicit salary-versus-AGI warning.
- Only contradictions in connected money data remain visible in the review queue.
- No application cloud account, telemetry, stored bank password, screen scraping,
  trading, or transfers. Plaid data transit occurs only after explicit opt-in.

## Evidence policy

A figure may appear as reconciled only when the available source fields satisfy its
accounting equation to the cent. Historical payroll files are archived inputs rather
than a completeness-validation queue.

## Current private-document decision

The latest detailed paycheck defines the recurring baseline until the user replaces
it. Older payroll files are retained only as archived source evidence.
The July 31, 2026 statement is the latest salary baseline and is used for forecasts even
though July is not a complete historical statement month.

## Life Lab boundary

Life Lab is an assumption-driven solvency model, not financial advice, a tax-return
engine, or a probabilistic investment forecast. It must keep observed, user-entered,
assumed, and unverified values distinguishable. It never treats inaccessible retirement,
HSA, restricted equity, or home value as an ordinary spending bridge without an explicit
future model change.

Its Drive Calculator is allowed to be aggressive in tone and unbounded in ambition, but
not vague in arithmetic. It must state the exact income, compounding, exit, or borrowing
requirement; distinguish the mathematical requirement from evidence that it is achievable;
and keep every borrowing path explicit rather than quietly repairing the solvency result.
All drive routes must share the selected mission's target and deadline by default, remain
freely editable, and keep a pre-retirement runway failure separate from retirement-date math.
