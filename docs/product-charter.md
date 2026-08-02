# Product charter

## Purpose

Money Map reconstructs where gross compensation went, what happened after funds
reached the user’s accounts, and how a proposed payroll allocation would mechanically
change the next 12 months.

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
