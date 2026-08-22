# Money Map v3 release contract

This contract defines the mandatory gates for `Money Map 3.0.0-beta.1` and later distributable
macOS builds. Slice 0 freezes the gates; it does not claim the beta release is complete.

## Release identity and artifacts

- One clean, reproducible release commit produces `Money Map.app` and an installable `Money
  Map-3.0.0-beta.1-arm64.dmg` through documented commands on the supported Apple Silicon builder.
- `pyproject.toml`, the FastAPI version response, Tauri configuration, `Info.plist`, About UI,
  DMG name, release notes, and local annotated tag must all equal `3.0.0-beta.1`. Until the release
  slice, every Slice 0 surface remains exactly `2.1.0`.
- The schema head remains `0009_goal_persistence` unless a separately planned, reviewed migration
  is proven. Packaging is never grounds for an implicit migration.
- Record SHA-256 hashes, byte sizes, build-tool versions, target triple, source commit, build time,
  and the exact release command for both artifacts.

## Signing, notarization, and publication

- The owner-only beta may use the installed Apple Development identity on the named target Mac.
- Distribution to any other person requires a Developer ID Application identity, hardened
  runtime, correct signatures for every nested executable/library, successful `codesign --deep
  --strict`, Apple notarization, stapling, and a successful Gatekeeper assessment of both the app
  and DMG from a clean downloaded copy.
- Absence of Developer ID is an explicit external release blocker, not permission to weaken the
  gate. Ad-hoc code is never accepted in a distributable artifact.
- Creating a tag, GitHub Release, upload, external DMG distribution, deployment, or publication is
  a separate authorized action after all evidence is accepted. Build work alone never authorizes
  it.

## Private-data and extracted-artifact inspection

- Build only from a clean checkout and synthetic fixtures. The active owner database, statements,
  reports, backups, credentials, tokens, identifiers, screenshots, and derived owner fixtures are
  forbidden build inputs.
- Before packaging, run the repository private-data scan. After packaging, mount/extract the DMG
  and recursively inspect filenames and bytes in the app, sidecar, resources, archives, metadata,
  and source maps. Reject databases, `.local`, statements, reports, backups, credentials, tokens,
  account identifiers, transaction text, absolute repository/private paths, and owner images.
- Verify the runtime inventory: all Python modules and locked dependencies, compiled React assets,
  Alembic environment and revisions through the declared head, package/version metadata, approved
  configuration, report/print resources, Keychain adapter, SQLite initialization, native
  libraries, and exactly the intended subprocesses are present.
- Launch the extracted signed app outside the checkout with Python, Node, repository paths, and
  inherited credentials unavailable. Any repository import or missing-resource fallback fails the
  release.

## Fresh installation and installed-app behavior

- Test on a fresh macOS user state: mount DMG, drag to `/Applications`, eject, launch by Finder,
  Dock, and Spotlight, quit, relaunch, and uninstall according to documented instructions.
- The installed app shows one native window, owns one sidecar, binds only `127.0.0.1` on an
  OS-selected port, completes an authenticated bounded readiness handshake, and needs no terminal,
  browser, checkout, Python, Node, or manual server.
- Exercise every top-level view, deep navigation plus reload, native print panel, file chooser,
  manual import, report creation, restart, offline behavior, and safe startup failure.
- Ten consecutive launch/quit cycles must leave no child, listener, temporary secret, or stale
  lock. A second launch must activate the existing instance and cannot create a concurrent SQLite
  writer.

## Existing-data migration, backup, and recovery

- Detect old data without opening it for write. Present source/destination, schema, required disk
  space, backup destination, and actions in a preview requiring explicit owner confirmation.
- Before migration, perform SQLite integrity and foreign-key checks and create a byte-verified,
  restorable backup. Never overwrite or mutate the source.
- Copy to staging, migrate only the copy, validate every domain with logical manifests and exact
  counts/totals/provenance/currentness, fsync as required, and atomically activate only a fully
  accepted destination. Preserve a rollback pointer.
- Inject interruption before and after every phase. Restart must deterministically resume or roll
  back without duplicate imports, observations, scenarios, goals, balances, or transactions.
- Prove backup creation, reveal-in-Finder, restore preview, destructive-replacement warning,
  restored logical equality, idempotent repeated restore, and recovery when the latest backup is
  corrupt. Keep an accepted prior database until the restored copy is verified.
- Slice 2 acceptance and all automated migration work use a build-time fake macOS home and checked-in
  synthetic factories only. The production Application Support home, active developer `.local`,
  owner database, and financial Keychain namespace are forbidden until Slice 7.
- The journal may contain only operation IDs/kinds, safe classifications, approved-root basenames,
  schema revisions, sizes, digests, logical-manifest digests, timestamps, failure codes, and
  activation state. Raw paths, rows, descriptions, identifiers, credentials, and exceptions are
  forbidden.

## Accessibility and product acceptance

- Complete keyboard-only navigation, visible focus, VoiceOver names/roles/state, Dynamic Type or
  supported zoom, contrast, reduced-motion behavior, error announcements, print usability, and
  file-panel accessibility for every release-critical flow.
- Run the complete backend/frontend/release gate plus desktop-specific unit, integration,
  security, packaging, migration, backup/restore, and installed-app suites. Automated results are
  build evidence, not owner acceptance.
- Perform a fresh installed-app synthetic walkthrough without patching during the run. Then the
  owner alone performs the bounded live acceptance, choosing every connection, import, support,
  and recovery action. Never simulate owner feedback or infer acceptance from automated traversal.

## Security gates

- Generate at least 256 bits of per-launch session entropy. Keep the value out of URLs, WebView
  storage, logs, crash reports, databases, artifacts, and process arguments; clear inherited
  credential-bearing environment variables before sidecar launch.
- Reject requests without the session, non-loopback hosts, hostile origins, unsupported methods,
  traversal/newline paths, oversized bodies, and unauthenticated mutations. Responses containing
  private data must be `no-store`.
- Confirm runtime network activity is loopback-only except for an owner-initiated Plaid sandbox or
  accepted production read-only action. Preserve the permanent manual-import fallback.
- Write/read/delete a release-specific synthetic Keychain item and independently prove deletion.
  Never read production Plaid entries as a test. Scan logs and evidence for secrets and raw
  identifiers.
- Test forced sidecar death, readiness timeout, corrupt configuration, unavailable Keychain,
  unavailable/corrupt database, malformed import, and interrupted report generation. Errors must
  be safe, visible, recoverable, and leave the last accepted data intact.

## Owner cutover and release evidence

- Freeze writes, create and verify the final backup, run the previewed migration, compare logical
  manifests, launch the installed app, and retain the old source and rollback instructions. The
  owner explicitly accepts or rolls back; no silent cutover is allowed.
- Evidence is synthetic and ignored by Git. It records commits, exact commands, versions, test
  totals, artifact hashes/sizes, signatures/notarization/Gatekeeper output, privacy scans,
  install/launch/readiness/shutdown timings, process/port snapshots, route/reload/print/file-panel
  checks, migration/restore results, accessibility/security results, known risks, and the owner's
  explicit acceptance result.
- Release notes contain installation, migration, backup, restore, recovery, rollback, known risks,
  financial-behavior preservation, Plaid/manual-import behavior, and support steps.
- Only after every gate is accepted may the release commit be annotated locally as
  `v3.0.0-beta.1`. Pushing the commit or tag, publishing a GitHub Release, notarization upload, or
  distributing the artifact externally still requires explicit authorization.
