# ADR 0004: Optional read-only Plaid connector

Status: accepted
Date: 2026-07-25

## Context

Manual SoFi and Fidelity exports are private and dependable but require repeated
operator work. Direct retail-member APIs are not available as a practical
self-service route for both institutions. Plaid offers a common authorization and
read-only data path, but it introduces third-party data transit, external availability,
plan eligibility, consent lifecycle, and possible billing.

## Decision

Add Plaid as an opt-in source while preserving manual import permanently.

- Use Plaid Transactions plus current balances for SoFi.
- Use Plaid Investments holdings, current values, and transactions for Fidelity.
- Never request Auth, Identity, Transfer, payments, trading, or money movement.
- Store Plaid API credentials, the local Plaid user identifier, and item access tokens
  in macOS Keychain.
- Store connection metadata, normalized records, item-namespaced hashes of account and
  transaction identifiers, and hashed endpoint evidence only in the private SQLite
  database.
- Load Plaid Link only when the operator begins connection or reauthorization.
- Make sync explicit, idempotent, and all-or-nothing for normalized records.
- Keep investment contributions separate from market result and never infer return
  from a single current value.
- Revoke the Plaid item and delete the Keychain token on disconnect; delete normalized
  local rows by default.
- Keep live controls disabled until Production/Trial credentials exist.

## Consequences

Sandbox supports complete synthetic workflow testing without financial credentials.
Real SoFi and Fidelity coverage cannot be claimed until Plaid grants production access
and both intended account types pass live authorization. The app remains local-first,
not strictly local-only, whenever Plaid is enabled because authorized data transits
Plaid. Manual import and every downstream accounting contract remain usable without
Plaid.
