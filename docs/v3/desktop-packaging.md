# Optional local Mac app update

Updated October 7, 2026. Scope: personal use and a handful of users. [Working approach](../personal-use.md).

The current local server and existing installed Mac app are supported personal-use paths. Do not build a new installer just to try an ordinary product feature.

If a concrete native app update is needed, use the existing build tooling with a real sidecar and current frontend assets. Preserve app/Keychain identity, back up personal data and check that the updated app opens and the changed flow works. Do not use the compile-only CI sidecar fixture as a runnable app.

The retained `scripts/package_desktop_release.py` is an optional strict packaging tool, not a required step in the current plan. Installer/DMG production, public signing/notarization, reproducibility/manifests and release campaigns are deferred. This documentation change does not alter script behavior.

[Local development](../development.md) · [Local app use](owner-local-delivery.md).
