# Money Map 3.0.0-beta.1 candidate packaging

Slice 8 assembles an owner-machine candidate at public version `3.0.0-beta.1` (PEP 440 package
version `3.0.0b1`) and schema `0009_goal_persistence`. Its state is `candidate / not accepted`;
it is not notarized, stapled, tagged, accepted, or approved for external distribution.

## Clean build command and prerequisites

Run from a clean `main` checkout at the exact commit being packaged:

```sh
uv run --frozen python scripts/package_desktop_release.py \
  <exact-40-character-commit> \
  --identity "Apple Development: <installed identity>" \
  --build-id slice8-a \
  --canary <nonsecret-build-canary>
```

The command requires Apple Silicon (`aarch64-apple-darwin`), macOS 13 or later, Xcode command-line
tools, `uv`, locked Python dependencies, PyInstaller 6.x, Node, pnpm, Rust/Cargo, Tauri CLI 2.x,
`sips`, `iconutil`, `hdiutil`, OpenSSL, and an installed Apple Development identity whose team is
`E3G5D247ZN`. It refuses a wrong commit, dirty/untracked tree, absent tracked input, missing or
mutable lock, wrong version/schema, wrong architecture, or wrong signing identity. It does not
update a lock or fetch a dependency: frozen dependencies must already exist in local offline
caches.

The command removes credential-bearing inherited environment entries without printing values,
creates a mode-`0700` disposable build root, exports `SOURCE_DATE_EPOCH=0`, and builds from a fresh
`git archive`. Frontend, PyInstaller, Cargo/Tauri, icon, DMG staging, and manifests are new for
each build ID. Failure removes that build's incomplete evidence so it cannot resemble acceptance;
cleanup is restricted to paths the command created.

## Outputs, identity, and branding

Ignored outputs are under `.slice8-evidence/<build-id>/`:

- `Money Map.app`
- `Money Map-3.0.0-beta.1-arm64.dmg`
- `manifest.json`, `release-manifest.json`, `dependencies.json`, `nested-code.json`, and
  `dmg-listing.json`

The app is `Money Map`, bundle `com.moneymap.desktop`, version `3.0.0-beta.1`, minimum macOS `13.0`, and
thin `arm64`. The DMG volume is `Money Map` and contains only `Money Map.app` plus the standard
`Applications -> /Applications` link. Checked-in `icon.svg` and 1024px `icon.png` are public
sources. `scripts/generate_macos_icons.sh` creates the ten standard iconset representations and
`icon.icns`; Tauri embeds that ICNS for Finder, Dock, About, and DMG display.

## Signing and entitlements

Signing is inside-out: every nested Mach-O other than the main executable, then the main native
executable, then the app bundle, then the DMG. Every signature uses the selected Apple Development
identity with timestamping disabled. Strict deep verification and the exact team requirement run
automatically. The manifest records relative paths, thin architecture, digest, authority, team,
designated-requirement result, entitlement list, and verification result.

Slice 8 adds no entitlements. Hardened runtime is intentionally off for this owner-machine
candidate. Network server, debugger, JIT, unsigned memory, disabled library validation,
automation, contacts, camera, microphone, location, and broad file access entitlements are absent.
The Slice 8 qualification candidate is compiled with the bounded acceptance-home gate; it uses a runtime fake
home only when `MONEY_MAP_ACCEPTANCE_FAKE_HOME` names a disposable `/tmp` or `/private/tmp` root.
Production release builds must omit that compile gate.

## Manifest and reproducibility

`manifest.json` uses contract `money-map-v3-candidate-build-manifest-v1`. It records the commit and clean
result, product/schema/bundle/target identity, build ID and reproducible-time policy, sanitized
command, tool versions, lock and approved-input hashes, certificate class/team, relative artifact
names/sizes/digests, normalized unsigned app-tree digest, nested-code and entitlement inventory,
dependency-inventory digest, scan result, and reproducibility status. It never records a username,
temporary root, PID, port, environment dump, certificate private material, or credential.

`release-manifest.json` uses `money-map-v3-release-manifest-v1`, records
`candidate_not_accepted`, keeps bounded qualification, owner walkthrough, cutover, final-decision,
final-hash, tag, and release-date fields blank, and makes every acceptance/publication claim false.

Prepare Build A and Build B with different build IDs. Compare them with:

```sh
uv run --frozen python scripts/package_desktop_release.py --compare \
  .slice8-evidence/slice8-a .slice8-evidence/slice8-b \
  --comparison-output .slice8-evidence/reproducibility.json
```

Functional identity covers bundle identity, architecture, versions, resources, capabilities, CSP,
entitlements, migrations, locks, and approved inputs. Normalized payload identity removes only
Mach-O signatures and `_CodeSignature` resources. Complete signed app/DMG bytes may differ because
CMS signing uses nondeterministic signature values and HFS+ DMG creation assigns container and
filesystem metadata. Any difference in normalized payload is unexplained and fails closed.

## Mount, copy, verification, and privacy

The release command mounts the DMG read-only, confirms the exact two-entry layout, strictly
verifies the mounted app, recursively scans it and the PyInstaller archives, then ejects it. For
isolated engineering installation proof, copy the app into a fresh disposable Applications-like
directory outside the checkout. Launch only with a disposable fake home and
`acceptance-synthetic-v1`; remove credential-bearing environment entries and keep Python, Node,
and repository paths unavailable. Never copy into `/Applications` during Slice 8.

Verification includes strict signing, thin-architecture inventory, exact plist identity, complete
migrations through `0009`, no repository fallback, exact capabilities/CSP, dependency audits, app
and mounted-DMG scans, and manifest tests. Scans reject databases/journals, `.local`, statements,
reports, backups/imports, credentials/tokens/sessions, identifiers/descriptions, owner imagery,
absolute home/repository/build paths, development URLs/ports, source maps, debug symbols, links
within the app, unexpected archives, unapproved executables, prior evidence, and supplied canaries.

Safe cleanup means ejecting only the recorded mount and removing only the command-created build
root or selected ignored build-ID directory. Uninstall/recovery and owner data remain later owner-
authorized work; this slice neither installs over an app nor accesses Application Support.

## External distribution remains blocked

The first missing external-distribution requirement is a `Developer ID Application` identity.
After one is installed, a separately authorized future procedure must establish a compatible
nested-code layout, enable and prove hardened runtime with minimal entitlements, sign app and DMG
with Developer ID, submit to Apple notarization using credentials supplied outside source/logs,
wait for success, staple app and DMG, and pass Gatekeeper assessment on a clean downloaded copy.
No Slice 8 command notarizes, staples, uploads, publishes, deploys, tags, or releases anything.
