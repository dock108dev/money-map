# Focused personal-data checks

Updated October 7, 2026. Scope: personal use and a handful of users. [Working approach](../personal-use.md).

For a change affecting private paths, credentials, browser admission, native bridge or backup/restore, run the relevant existing security/regression checks and inspect that ordinary flow. Tests use synthetic disposable state; real data stays private and credentials remain in the existing Keychain route.

The current app remains local and read-only with respect to connected financial accounts. Public deployment, penetration/release campaigns and broad platform certification are outside current scope. Preserve existing controls; fix a demonstrated privacy or data-integrity failure before relying on the affected path.

[Security model](../security-model.md) · [Focused checks](../testing.md) · [Personal use](../personal-use.md).
