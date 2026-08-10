# Money Map v2 source fingerprint contract

## Purpose and version

`goal-source-fingerprint-v1` identifies the complete canonical input state required to
reproduce one goal position. The same goal and source material always produce the same
SHA-256 digest. A goal/source pair has one deterministic check-in identity, so an unchanged
open or refresh cannot create a distinct check-in.

Persistence and concurrent check-in creation remain Slice 2 work. Slice 0 freezes material,
ordering, serialization, exclusions, and test vectors.

## Included canonical material

The fingerprint contains:

1. `fingerprint_version` and `calculation_version`.
2. Goal configuration:
   - stable goal-program identity;
   - target date;
   - exact unformatted target amount;
   - exact unformatted protected cash floor;
   - exact unformatted reserved amount; and
   - evidence class and stable source references for each monetary configuration value.
3. Every source record required for the position:
   - source kind (`balance`, `investment_access`, `payroll`, `recurring_outflow`, or
     `goal_configuration`);
   - stable source record identity and, where available, its SHA-256 content hash;
   - effective observation date;
   - exact unformatted monetary facts used from the record; and
   - the evidence class of each monetary fact.

Source selection must include the records that establish accessible cash, accessible
investment classification/value, separately excluded retirement assets, tracked debt,
effective recurring take-home, recurring outflow, and the goal configuration. A source
that did not contribute to the position is excluded.

## Stable ordering and serialization

The canonical payload is UTF-8 JSON with ASCII escaping, lexicographically sorted object
keys, and separators `,` and `:` with no whitespace.

- Source records sort by `(kind, effective_date, record_identity, record_hash-or-empty)`.
- Monetary facts within a record sort by `(field, evidence, amount)`.
- Evidence source references sort lexicographically and must be unique.
- Dates use ISO `YYYY-MM-DD`.
- Money uses a JSON string with exactly two decimal places, including trailing zeros.
- Missing optional hashes serialize as JSON `null`; missing monetary evidence is not
  fingerprintable as a numeric fact.

The fingerprint is lowercase hexadecimal
`sha256(canonical_json.encode("utf-8")).hexdigest()`.

The checked-in vector at `examples/synthetic/money-map-v2-contracts.json` fixes both the
canonical JSON bytes and expected digest. Tests prove source input order does not change the
result.

## Explicit exclusions

The following never enter fingerprint material:

- formatted display text, currency symbols, localized grouping, verdict copy, or labels;
- request, page-open, refresh-request, or check-in creation timestamps;
- API transport metadata, browser state, telemetry, or sort order supplied by a caller;
- institution display names or account display names when a stable source identity exists;
- credentials, access tokens, raw provider payloads, statements, screenshots, reports, or
  other private artifacts;
- derived UI-only status text; and
- records or values not used to produce the position.

Effective observation dates are included because they describe financial evidence. A
check-in `created_at` is excluded because it describes persistence timing.

## Duplicate and change semantics

- Equal canonical material means equal source fingerprint and equal deterministic check-in
  identity for a goal. Persistence must return the existing record, not insert a duplicate.
- A change to any included exact value, effective date, source identity/hash, evidence
  class, goal configuration, or contract/calculation version produces a different
  fingerprint.
- A display-copy edit, request retry, unchanged refresh, or reordered input collection does
  not produce a different fingerprint.
- Fingerprint equality proves source equivalence under this version; it does not prove that
  a provider is current or that omitted source coverage is sufficient.
