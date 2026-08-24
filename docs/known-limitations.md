# Known limitations

These are implemented boundaries, not hidden setup steps.

- Version `3.0.0-beta.1` remains a candidate and is not accepted for release. Source and native test
  success do not replace signed packaging, installed-app qualification, or owner acceptance.
- The supported packaged runtime is an Apple-silicon macOS application. There is no Windows, Linux,
  Intel macOS, mobile, hosted, container, or multi-user deployment workflow.
- Repository mode is a local developer/manual-import surface on IPv4 loopback. It must not be
  reverse-proxied, exposed to a LAN, or treated as an authenticated shared web service.
- Automatic Plaid refresh runs only when the application is open, at most once per local business
  day when connected data is stale. There is no daemon, queue worker, cron task, or launch agent.
- Plaid is optional and externally dependent on provider availability, institution support, consent,
  and credentials. Manual import, reconciliation, forecasts, reports, backup, and restore remain
  local and do not require Plaid.
- The payroll PDF adapter supports the verified text-based Oracle/UnitedHealth Group summary layout.
  Scanned PDFs have no OCR implementation. Institution-native SoFi or Fidelity layouts that have not
  been supplied and tested are unsupported; use the canonical CSV/XLSX contract instead.
- Money Map does not move money, initiate transfers, trade, scrape screens, categorize purchases,
  provide financial advice, or send telemetry.
- The repository CLI restore path requires an existing active database so it can make the mandatory
  pre-restore safety backup. Fresh-install selection and cutover belong to the packaged data-home
  workflow.
- A fully compromised logged-in macOS account is outside the protection boundary. FileVault, login
  security, malware prevention, physical custody, and external backups remain operator
  responsibilities.

Broader platform support, OCR, hosted access, background scheduling, or a different restore contract
would require explicit product and architecture decisions rather than documentation-only changes.
