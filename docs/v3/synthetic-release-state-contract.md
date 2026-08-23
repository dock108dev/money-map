# Synthetic installed release state contract

Status: Slice 6 Campaign B independent fixture authority.

## Boundary and authority

`tests/fixtures/synthetic/v1_2_1/release-state-contract.json` is the sealed source oracle for the
installed 17-state by 13-route matrix. It is reviewed and committed before a candidate is built.
The installed app, its API responses, screenshots, logs, and generated reports are observations
only; none may create or update an expected value.

Authority is intentionally one-way:

```text
frozen product contracts + explicit accepted tests + invented seed facts
  -> standalone Decimal oracle
  -> 221 resolved expectations + digest
  -> signed installed candidate observations
  -> comparison result
```

The oracle must not import `paycheck_map`, frontend code, production serializers, or production
calculation services. It does not launch the app, read installed evidence, use snapshots, or offer
a record/update mode. Its imports are restricted to the Python standard library. A static guard
test enforces that boundary.

## Frozen reference rules

- Reference instant: `2026-08-10T12:00:00-04:00`.
- Eastern business date: `2026-08-10`.
- Schema: `0009_goal_persistence`.
- Amounts: signed base-10 strings with two to four fractional digits.
- Arithmetic: `Decimal`; `ROUND_HALF_EVEN` only at an explicitly declared currency boundary.
- Currentness: evidence at most 32 calendar days old is current; older evidence is stale.
- Ordering: date then stable positive identifier; UI summaries reverse both for newest-first use.
- Networking: authenticated OS-selected IPv4 loopback only. Opening Add Account never contacts a
  provider, and no state permits telemetry, analytics, update, or crash-upload traffic.
- Opening any route writes zero rows and zero files. Mutations belong to Campaign C or a later
  explicit campaign.

No wall clock, owner value, owner identifier, provider response, or production Keychain namespace
is an input.

## State drivers

Persistent states seed a fresh activated `0009` database. `loading` uses a harness-controlled
pre-response gate with an explicit release and bounded timeout; it is never a sleep race.
`unavailable` uses a declared controlled API classification. `recoverable_failure` fails exactly
one declared read and then returns the last accepted state on deliberate retry. `stale_evidence`
uses the frozen reference date. `large_history` uses a bounded month-index generator with frozen
counts, date range, aggregates, disclosure counts, chart points, and report-page expectation.

`states.json` retains the accepted Life Lab and goal rows and now includes deterministic driver
specifications for the eight former gaps. The release-state contract adds full table-count,
logical-fact, exact-total, provenance, currentness, evidence, operation, networking, cleanup, and
authority expectations.

## Resolution and validation

Run:

```text
uv run --frozen python scripts/materialize_release_state_contract.py \
  --output .slice6-evidence/campaign-b-resolved-contract.json
```

The materializer merges a route's reviewed defaults, a state's reviewed defaults, and any explicit
state-route override. The output contains 221 explicit combinations; the resolved file contains no
inheritance. Every combination must include the database/API/UI assertions enumerated by the
Campaign B handoff, a zero view-open write count, forbidden-material classes, and at least one
registered authority reference.

Validation rejects missing/duplicate states, missing/duplicate combinations, unknown routes,
undefined inheritance, binary floats, malformed decimal strings, failed reconciliations, missing
authority references, wall-clock dependencies, and candidate-output/update modes. Canonical JSON
uses sorted keys and compact separators. Its SHA-256 digest is deterministic.

The validator is deliberately sensitive to seed/expectation drift: changing an arithmetic fact
without updating its independently reviewed reconciliation fails. Changing an expectation without
a registered authority reference also fails. Two independent materializations must be
byte-identical before packaging.

## Installed comparison

Campaign B creates a fresh disposable fake macOS home per combination, materializes the sealed
driver without candidate observation, launches the copied signed app under the native attestation
contract, opens the requested deep surface, and compares UI, authenticated API, database manifest,
reload, view-open nonmutation, networking, sanitization, and cleanup observations with the sealed
combination. A mismatch fails the candidate. The oracle is never rewritten to match actual output.

`overview`, `data-home`, `diagnostics`, and `reports` are installed surfaces even when reached by a
supporting control rather than the primary navigation rail. Requesting them still requires an
explicit safe installed result; none may be silently skipped.
