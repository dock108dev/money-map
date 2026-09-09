# Owner-local delivery contract

This contract adds an explicit delivery mode to the strict packager; it does not authorize signing,
installation, data access or cutover. Housing implementation and synthetic checks precede those gates.
No existing signed candidate is patched, rebuilt or accepted by these source changes.

## Two distinct artifacts

The strict command accepts `--build-mode qualification` (default) or `--build-mode owner-local`.
The owner-local command, in a separately authorized release session, is:

```bash
uv run --frozen python scripts/package_desktop_release.py <exact-40-character-commit> --identity '<Apple Development identity>' --build-id <unique-id> --build-mode owner-local
```

Both modes retain the existing clean-main/exact-commit preflight, frozen dependency inputs, clean
archive build, strict signing, inventory, privacy scans and identity-bound manifests. Build ID,
packaging manifest and reproducibility comparison include the mode. The release manifest uses the
existing `production` value for owner-local, and `qualification` for synthetic mode. Owner-local does
not mean production acceptance: release state is still `candidate_not_accepted`, and owner/final fields
remain blank. No automatic commit, push or signing runs as part of source validation.

The build environment removes all inherited `MONEY_MAP_*` and `PAYCHECK_MAP_*` settings before
setting the reviewed mode. Conflicting inherited compile flags are rejected. Qualification sets both
`MONEY_MAP_REQUIRE_QUALIFICATION=1` and `MONEY_MAP_ALLOW_ACCEPTANCE_HOME=1`; owner-local omits both.
The native startup rejects synthetic launch overrides for owner-local builds, and rejects inconsistent
qualification compile flags. Owner-local resolves normal macOS paths and retains the ordinary secret
store policy. It provides no fake-home or synthetic data-mode escape hatch.

Synthetic qualification remains fail-closed and its qualifier refuses a production-mode manifest.
The release manifest assigns owner-local distinct gates: `two_cycle_owner_local_installed_smoke` and
`short_owner_local_synthetic_walkthrough`. A synthetic artifact's PASS cannot fill those fields or
promote a different artifact. Historical signed evidence and owner answers remain untouched.

## Source integration and signing prerequisites

Source freeze uses a working branch and pull request with passing CI and CodeQL for its exact head.
Do not merge automatically. The strict packager requires branch `main`, a clean worktree and HEAD equal
to the supplied commit. A green unmerged PR is therefore ready for source review, not yet buildable by
this contract. Obtain separate integration authorization, merge through the repository PR workflow,
and record passing hosted checks for the resulting exact main commit before proposing signing.
Do not rename a checkout branch or weaken preflight to bypass this boundary.

The later build requires Apple Silicon, macOS 13+, Xcode command-line tools, uv, locked Python and
PyInstaller 6.x, Node/pnpm, Rust/Cargo, Tauri CLI 2.x, sips/iconutil/hdiutil/OpenSSL and populated offline
dependency caches. An installed Apple Development certificate and private key for team `E3G5D247ZN`
are required. Availability and signing access must be checked only in the separately authorized
session; source validation does not inspect Keychain. Prepare a disposable macOS identity or VM for
the installed qualification. Developer ID, notarization and distribution are outside this local mode.

## Exact qualification still required

1. Freeze the settled source on a clean exact commit; record local complete-source/native checks and
   matching hosted CI/CodeQL results. The old source candidate's hosted results do not carry forward.
2. With release authorization, build the selected mode using the strict command. Record commit,
   schema, mode, app digest, DMG SHA-256, release-manifest hash and dependency inventory. Verify each
   against the artifact before launching. Do not manufacture a qualified result from a source gate.
3. Qualify owner-local in a **separate disposable macOS user or disposable macOS VM**, using that
   identity's ordinary home, empty financial Keychain and disconnected providers. This exercises
   production path resolution without owner data and without compile-time overrides. Copy the exact
   signed app outside `/Applications`; do not recompile it for the test identity. The synthetic-only
   qualifier is not the owner-local installed runner. Perform exactly two bounded ready/quit cycles,
   at most 1200 seconds, recording actual start/end and failure. No automatic retry.
4. In that isolated identity, use manual synthetic imports and the Housing Move fixture-equivalent
   worksheet. Exercise empty goal creation, edited baseline, sale/timing, alternatives, save/reload,
   normal quit and reopening. Verify one app/sidecar tree, loopback-only listener, writable roots
   contained in that identity's Library, schema 0010 and no provider access. Record dated baseline
   and unknown-input behavior. Quit and verify no app, sidecar, listener, writer lock, session material
   or mounted image remains. Preserve only sanitized evidence. An owner-local installed-run record
   must include the exact artifact/mode, isolation identity reference, two cycle results, walkthrough
   observations and cleanup; all are still unperformed until that session.
5. Any failure ends the attempt at its first unmet gate. Diagnose the source, validate the fix, freeze
   a new candidate when changed, and qualify affected steps without relabeling old evidence.

A separate macOS identity/VM is a real remaining setup prerequisite; changing `HOME`, environment
flags or patching an installed binary is not an isolated installed test. This source change implements
the packaging path and headless policy validation; it does not claim that installed proof occurred.

## Owner data setup after artifact qualification

Request the owner's explicit data-access authorization at session start. For a fresh source, the
owner creates ordinary local data and manually selects supported imports. For an existing source,
follow [cutover readiness](cutover-readiness.md): owner-selected read-only source, verified backup,
isolated rehearsal, migration of a staging copy, integrity/relationships/reconciliation/idempotency,
verified activation, retained rollback and an explicit accept-or-rollback decision. No source search,
provider connection or financial Keychain access is implied by application implementation.

After setup, begin [the housing walkthrough](../housing-move.md) with Step 1 only. Capture feedback,
implement focused fixes, validate synthetically and return the affected steps for owner review.
Neither source tests nor installation qualify the user's financial inputs or imply owner acceptance.
