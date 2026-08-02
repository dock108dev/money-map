# ADR 0002: exact evidence accounting

**Status:** accepted

Money is stored as exact decimal numerics. Every normalized value links to an artifact,
source location, original label, extraction method, parser version, and review status.

Reconciliation residuals and unresolved evidence are first-class domain records. The
system will not insert balancing amounts or infer missing payroll detail.
