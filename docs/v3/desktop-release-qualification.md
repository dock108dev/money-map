# Money Map bounded owner-beta qualification

This contract replaces the former Campaigns A-J release qualification as the active owner-beta
plan. Money Map is being qualified for one owner on one daily-use Mac, not for broad external
distribution. Validation must therefore be bounded, interruptible, and headless wherever the
behavior does not require a native macOS surface.

The former 221-combination state/route runner and Campaigns C-J remain diagnostic tooling. They
are optional soak coverage for a dedicated runner or an explicitly scheduled idle window. They
are not required for owner-beta acceptance and must never be started implicitly on an interactive
machine.

## Non-negotiable operating limits

- Run no more than one native qualification step at a time.
- Spend at most 20 minutes of interactive-machine time on one installed smoke attempt.
- Use at most four successful ready-state app launches in the complete owner-beta qualification,
  including the owner's walkthrough. The automated installed smoke uses two launch/quit cycles;
  its bounded startup-rejection probes do not construct the financial window.
- Do not start a native matrix, retry loop, repeated rebuild, sleep/wake campaign, or long-lived
  observation without explicit owner approval for that exact run.
- A failure stops the current step. Preserve sanitized evidence, fix the defect, rerun the
  affected headless checks, and rerun only the two-cycle installed smoke. Do not restart an
  unrelated sequence from the beginning.
- Never monopolize the Mac. The owner can stop the run at any time without invalidating already
  passed, unaffected evidence.

These limits are execution controls, not targets to fill. If the required fact is already proven
headlessly, do not repeat it through the native UI.

## Acceptance levels

Money Map uses three distinct acceptance levels:

1. **Implementation ready** — changed-area tests and the complete headless repository gate pass.
2. **Owner-beta accepted** — one exact local candidate also passes the bounded installed smoke,
   the owner completes one short synthetic walkthrough, and any owner-data cutover is separately
   confirmed and reconciled.
3. **Externally distributable** — not in scope. Developer ID, hardened runtime, notarization,
   stapling, downloaded-copy Gatekeeper proof, broader compatibility, and optional soak coverage
   remain separate future work.

Passing one level must not be described as passing another.

## Step 0: make the bounded contract executable

Before another native run, replace the retired Campaigns A-J promotion fields with the bounded
gate names in this document and their fail-closed tests. Add a harness-enforced 1,200-second total
wall-clock limit to `qualify_desktop_release.py`; timeout must enter the existing safe cleanup path
and leave the candidate unaccepted. This is implementation-only work and is validated headlessly.
Do not run the installed smoke until the new option below exists and its timeout test passes.

## Step 1: headless implementation confidence

Run focused tests for the files and behavior changed since the last accepted checkpoint. Then run
the repository's complete headless gate once:

```sh
uv run paycheck-map verify
```

This step may exercise backend, frontend, Rust, security, migration, packaging-contract, and
private-data assertions without launching the installed app. Record PASS, FAIL, and NOT RUN
separately. A source change reruns the affected focused checks; the complete gate is rerun once
after the fix set is stable, not after every intermediate edit.

## Step 2: build one exact local candidate

Build one clean Apple Silicon owner-beta candidate from the exact local commit using the locked
packaging entrypoint in `desktop-packaging.md`. One candidate is sufficient for this local beta.
The second-build reproducibility comparison is deferred to external-distribution hardening or an
explicitly approved dedicated-runner job.

The build still uses synthetic fixtures, disposable roots, a filtered environment, strict signing
and artifact checks, schema `0009_goal_persistence`, and no owner database, production Keychain,
provider, `/Applications`, tag, push, upload, publication, or release action.

## Step 3: bounded installed smoke

Run the existing installed qualification harness for exactly two launch/quit cycles:

```sh
uv run --frozen python scripts/qualify_desktop_release.py \
  .slice8-evidence/<candidate>/Money\ Map-3.0.0-beta.1-arm64.dmg \
  --expected-sha256 <exact-64-lowercase-hex-dmg-sha256> \
  --expected-source-commit <exact-40-lowercase-hex-clean-commit> \
  --campaign-id <new-ignored-evidence-id> \
  --launch-cycles 2 \
  --max-wall-seconds 1200
```

The smoke remains synthetic and isolated. It verifies the frozen DMG identity, bundle and nested
signatures, artifact privacy, fake-home enforcement, attested database bootstrap, authenticated
loopback startup, one-app behavior, two clean launch/quit cycles, writer-lock cleanup, and no
owner/provider/production-Keychain access. It never copies into `/Applications`.

The smoke is not a route matrix. Route/state semantics, mutations, migration, backup/restore,
security rejection cases, and recovery behavior belong in deterministic headless tests unless a
specific native integration cannot be proven there.

## Step 4: short owner synthetic walkthrough

Using the same frozen candidate, the owner performs one coached setup followed by one uncoached
walkthrough, with a target duration of 10 minutes and one app launch. Check only the ordinary loop:

- launch and reach Cash Flow;
- open Goals and confirm the current result and next action;
- perform one synthetic goal update and verify it survives reload;
- open Data Home or Diagnostics and confirm the next safe action is understandable;
- quit normally and confirm no app or sidecar remains.

Capture only pass/fail, coaching required, blocking confusion, and sanitized defect classes. Do
not turn the walkthrough into exhaustive accessibility, zoom, print, route, or failure-state
inspection. Any defect is triaged by user impact; it does not automatically invalidate unrelated
headless proof.

## Step 5: owner cutover or stop

Owner-data cutover is a separate, explicit decision. If authorized, follow
`cutover-readiness.md`: select the source manually, keep it read-only, verify backup and rehearsal,
activate only a reconciled staging copy, relaunch, and let the owner accept or roll back. No owner
data, production Keychain, or provider is accessed before that authorization.

It is valid to stop after synthetic owner-beta acceptance and leave cutover pending. A local tag
is permitted only after the owner accepts the exact candidate and cutover state; pushing or
publishing remains separately authorized.

## Failure and rerun policy

A failure creates a small rerun boundary:

- source/test failure: affected focused tests, then one complete headless gate after fixes settle;
- build or identity failure: rebuild once after the relevant fix, then run the installed smoke;
- installed smoke failure: affected headless regression plus the two-cycle installed smoke;
- walkthrough failure: fix the blocking user path, run its focused checks, the two-cycle smoke,
  and only the affected walkthrough path;
- cutover failure: stop mutations and use the verified rollback path; do not resume automatically.

There are no numbered retry campaigns and no automatic restart from Step 1. Three failures with
the same cause require a written diagnosis and owner decision before another native attempt.

## Optional soak coverage

The sealed 17-state by 13-route matrix, ten-cycle lifecycle run, extended accessibility/zoom/print
inspection, sleep/wake, and Campaigns C-J may be useful before external distribution. Run them only
on a dedicated runner or during an owner-approved idle window with a time budget and stop time.
Their absence is a documented limitation of the owner beta, not a reason to keep the local
candidate permanently unaccepted.
