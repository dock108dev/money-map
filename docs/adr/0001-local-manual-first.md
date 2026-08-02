# ADR 0001: local and manual-first

**Status:** accepted

The application binds only to loopback, keeps personal data under a Git-ignored local
directory, and retains manual file import as a permanent workflow.

Cloud identity, telemetry, provider credentials, and screen scraping add risks that are
not needed to answer the first product question. Future connectors must remain optional
and must normalize into the same evidence and reconciliation contracts.
