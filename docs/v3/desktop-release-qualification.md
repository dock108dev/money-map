# Money Map Slice 6 installed release qualification

This contract qualifies one exact signed DMG from one exact clean source commit. It uses only
synthetic fixtures, private disposable macOS homes, and ignored sanitized evidence. It is
engineering acceptance, never owner acceptance, and it does not authorize Slice 7.

## Exact command and fail-closed identity

Run the source gates, commit the qualification implementation, and build the candidate from that
exact clean commit. Then run:

```sh
uv run --frozen python scripts/qualify_desktop_release.py \
  .slice8-evidence/<candidate>/Money\ Map-3.0.0-beta.1-arm64.dmg \
  --expected-sha256 <exact-64-lowercase-hex-dmg-sha256> \
  --expected-source-commit <exact-40-lowercase-hex-clean-commit> \
  --campaign-id <new-ignored-evidence-id> \
  --launch-cycles 10
```

The command stops before mounting on a hash mismatch. It refuses a missing or changed manifest,
wrong embedded About source, wrong version, schema, architecture, bundle identifier, deployment
target, signature class/team, entitlement policy, DMG name, or existing Money Map process. It also
refuses reused evidence IDs. The unaccepted candidate identity is version `3.0.0-beta.1`, schema
`0009_goal_persistence`, thin Apple Silicon, bundle `com.moneymap.desktop`, minimum macOS `13.0`,
and Apple Development team `E3G5D247ZN` with no entitlements.

The DMG is mounted read-only and must contain exactly `Money Map.app` and the standard
`Applications -> /Applications` link. The app is copied with resource forks disabled into the
command-created private Applications-like directory below `/private/tmp`; it is never copied into
`/Applications`. Strict signatures, every top-level Mach-O, the complete recorded nested-code
inventory, the extracted PyInstaller inventory, version/schema resources, and privacy rules are
verified before launch.

## Runtime isolation and observation

Each scenario receives a fresh mode-`0700` fake home below `/private/tmp`. The installed executable
is the only launched product process. Its environment contains only `/usr/bin:/bin`, the fake
`HOME`, and the bounded acceptance-home marker. Python and Node paths, repository imports,
development servers, inherited credential-bearing names, production application data, and
production Keychain namespaces are unavailable. The signed sidecar uses the accepted in-memory
synthetic secret store.

The signed qualification candidate is compiled with
`MONEY_MAP_REQUIRE_QUALIFICATION=1`. It refuses to start when either the exact versioned native
qualification contract or its matching disposable fake home is absent; it cannot fall back to
`production-v1`. A later production build must omit this compile-time requirement and the
acceptance-home capability together.

Before a financial WebView exists, native code validates exact disposable paths and starts the
signed sidecar. The sidecar prepares or verifies the synthetic `0009_goal_persistence` database,
opens it through the same SQLAlchemy engine used by the API, and returns a nonce-, session-, and
generation-bound attestation over the private bootstrap channel. Native code independently checks
canonical equality, file types, ownership, single-link files, `0700` directories, `0600` files,
schema, integrity, foreign keys, stable database identity, and exact application/cache/log roles.
Only after the attestation and authenticated health check pass may lifecycle become Ready and the
main financial window be constructed. Failure stops the sidecar and permits only the sanitized
recovery window.

The harness observes the descendant process topology, ephemeral IPv4 loopback listener class,
external connection count, writer-lock presence, safe event codes, readiness/shutdown durations,
second-launch behavior, and final process/listener/lock/session cleanup. It never records raw PIDs,
ports, sessions, environment dumps, absolute paths, or exceptions. Every normal quit must contain
`MM-DESKTOP-STOP` and remove the writer lock. Ten launch/quit cycles and second-launch attempts are
required. Any failed assertion fails the campaign; timing outliers are reported individually and
must be investigated rather than averaged away.

## State and route matrix

`tests/fixtures/synthetic/v1_2_1/release-qualification.json` is the release matrix. Its product
states are empty, loading, unavailable, partial coverage, recoverable failure, stale evidence,
complete/current, large history, negative recurring cash flow, cash below the protected floor,
missing source coverage, no Life Lab profile, profile without goals, one enabled goal with a
floor, multiple ambiguous enabled goals, stale saved scenario, and completed goal.

The existing `states.json` remains the authoritative invented financial fixture for Life Lab and
goal edge cases. Existing backend and React executable fixtures supply loading, refresh,
cash-flow, large-history, account, wealth, report, and recovery states. Owner-derived fixtures are
forbidden. A state passes only when the authoritative database/API facts, evidence class and
currentness, primary result, next action, caution/unavailable/recovery wording, reload state,
view-open nonmutation, and network observation all agree. A rendered zero, success message, or
visible screen is never authoritative by itself.

Every campaign covers Cash Flow, Goals, Activity, Accounts, Income, Wealth, Retirement, Life Lab,
Review/Overview, Add Account/connections, Data Home, Diagnostics, and Reports. Cash Flow must be the
initial route. Route state must survive reload and close/reopen. Finder/Dock-style reopen,
hide/show, minimize/restore, native menus, and one-app second launch are installed-shell facts.

Every ordinary Goals route path is query-only. Mount, navigation, reload, close/reopen, React
remount, loading-gate pending/release, detail expansion, history, provenance, and printing must use
only the accepted GET endpoints and leave the logical database unchanged. Goal check-in backfill is
permitted only after an explicit successful user-authorized goal or data command. Qualification
observations retain a bounded method/endpoint/count inventory, and any database-stability failure
reports exact affected table names and count deltas without retaining row values or identifiers.

## Mutation inventory

For every row in the checked-in mutation matrix, evidence maps:

```text
visible control or native menu
  -> typed native command and authenticated local API
  -> exact expected write
  -> database, manifest, digest, and permission verification
  -> reload and retained-state verification
  -> deliberate repeat or declared idempotency
  -> cancellation, stale-token, failure, rollback, or recovery result
```

Coverage includes fresh activation, manual selection, existing-data migration, private-inbox
import, duplicate re-import, rollback, account value, goal check-in/update, Retirement and Life Lab
profile/scenario work, accepted promotion, refresh preference, backup, restore cancellation and
confirmation, report, diagnostics export, and runtime restart. Tests assert exact rows, counts,
decimals, totals, provenance, fingerprints, currentness, and logical-manifest changes. Cancellation
performs zero writes; invalid, stale, replayed, or consumed confirmations fail closed; failures
retain the last accepted state; no operation moves money or contacts a provider.

## Migration, backup, restore, and recovery matrix

The checked-in matrix includes fresh `0009`, representative older v2 and `0008` upgrades, current
`0009`, repeated-current no-op, newer/missing revision, integrity/foreign-key/table failures,
unavailable/read-only source, insufficient/unwritable destination, interruptions at every durable
phase, resume, rollback, empty/multiple backup catalogs, cancellation, safety backup, corruption,
catalog/digest/journal tampering, TOCTOU replacement, one-use/expired/stale confirmation,
interrupted restore, corrupt-newest recovery, and repeat restore.

Every successful path proves the source byte hash and identity are unchanged, the source is
read-only, the backup and staging copy verify, only `0009_goal_persistence` is reached, complete
logical manifests agree, directories are `0700`, app-owned files are `0600`, activation is atomic,
and quit/relaunch retains the accepted destination. Repeated current-source migration creates no
database or backup write. Replacement keeps the prior accepted database until the candidate has
passed post-activation verification.

## Runtime, security, offline, and file boundaries

The runtime matrix covers sidecar death, failed/successful/repeated retry, startup/restart timeout
and cancellation, quit during startup/restart, missing/tampered/wrong-team sidecar, unavailable or
corrupt database, unsupported schema, unavailable synthetic secret service, hostile imports,
report/backup/restore failures, authenticated request timeout, safe-error presentation, healthy
close/reopen, and route preservation. Failures remove stale mutation controls, retain contractually
safe local evidence, use sanitized actionable copy, never create a second writer or restart loop,
and leave quit in control of final cleanup.

Offline engineering uses deterministic injected provider unavailability; it does not alter global
network or firewall settings and does not satisfy `OV-01`. It proves local data, manual import,
backup and restore remain local, while telemetry, analytics, update checks, crash uploads, Plaid,
and undocumented requests remain absent. Unauthorized-loopback and hostile-origin attacks are
rerun, the signed UI remains healthy, and port `8765` is untouched.

Native file coverage includes print-panel cancel, file-chooser cancel, valid manual selection,
symlink/traversal/hostile rejection, approved report open/reveal, rejected report identity,
diagnostics preview, export cancel, and approved synthetic export. Reports and diagnostics are
atomic mode `0600` files below approved disposable roots.

## Print, accessibility, and presentation

Cash Flow, Goals, Retirement, Life Lab, and trailing-12-month outputs are rendered page by page.
Inspect content, margins, page breaks, clipping, transient-control removal, evidence-disclosure
expansion, screen-state restoration, and absence of paths or identifiers. Retained images and
rendered output must be synthetic and remain under `.slice6-evidence/`.

Installed UI inspection covers keyboard-only navigation, menu shortcuts, visible and restored
focus, modal containment, safe Escape cancellation, VoiceOver names/roles/states/alerts/progress,
reduced motion, contrast, minimum/standard/narrow windows, 100/125/150/175/200 percent zoom,
large-history tables/charts, long safe errors, 44-pixel constrained controls, live-region noise,
horizontal overflow, overlap, fixed-navigation occlusion, and print layout. Automated assertions
support but never replace installed UI and rendered-page inspection.

## Evidence format and privacy

Ignored evidence is written below `.slice6-evidence/<campaign-id>/`. The harness emits sanitized
artifact, cycle, and lifecycle results. The final campaign also records command exit results,
state/route/mutation/migration/recovery matrices, exact synthetic assertions, network classification,
accessibility/zoom/print inspection, test totals, artifact scans, final hashes, limitations, and
owner deferrals in `acceptance.md`.

Evidence may include artifact hashes, byte sizes, source commit, schema, version, safe counts,
durations, classifications, and pass/fail results. It must not include owner data, credentials,
tokens, financial identifiers, raw transaction descriptions, usernames, private absolute paths,
raw PIDs/ports/sessions, environment dumps, exceptions, or unredacted application output. Run the
repository private-data scanner and an independent evidence scan before acceptance.

## Failure, rebuild, and safe cleanup

An identity mismatch stops before mount. A product, semantic, migration, privacy, security,
lifecycle, reproducibility, or cleanup failure ends the current installed campaign and writes only
a sanitized failure classification. Never patch an installed copy or repair a synthetic database
by hand. Fix the product in a new local commit, rerun all affected source/security/packaging gates,
build two new candidates, prove normalized payload reproducibility, freeze a new DMG hash, and
restart the entire campaign from fresh disposable roots.

The command detaches only its recorded mount and removes only its generated `/private/tmp`
campaign. It never removes an owner location. Failed ignored evidence remains for diagnosis; an
evidence ID is never reused. Cleanup failure blocks acceptance.

`OV-01` through `OV-11`, actual sleep/wake, ordinary `/Applications` installation, production
Keychain behavior, provider credentials, owner data, and owner cutover remain pending. No command
in this contract pushes, tags, uploads, publishes, deploys, notarizes, staples, distributes, or
releases an artifact. Slice 7 remains blocked until explicit owner participation and authorization.

## Slice 7 implementation-only qualification

Slice 7 runs focused and complete source gates against invented databases and disposable fake homes.
Its cutover driver proves every preflight state, read-only source bytes, complete logical-manifest
equality, one-use confirmation and drift rejection, cancellation zero-write behavior, interruption
and resume, rollback, retained state after authority restart, permissions, blank owner responses,
sanitized evidence, no automatic discovery, no provider/Keychain access, and no migration beyond
`0009_goal_persistence`.

Evidence is stored only under ignored `.slice7-evidence/` and is implementation proof. It does not
restart Campaign A or B, run Campaigns C-J, run the focused `loading::overview` installed probe,
access owner data, or perform owner validation. The recorded Overview rejection and the entire
installed/owner campaign remain deferred until the exact post-Slice-8 candidate is frozen.
