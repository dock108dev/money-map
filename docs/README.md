# Documentation index

Start with the guides that describe the current tree:

- [Development](development.md): install, run, repository layout, and validation
- [Configuration](configuration.md): environment variables, static inputs, runtime modes, and secrets
- [Testing](testing.md): local checks, CI jobs, test isolation, and release-only gates
- [Operations](operations.md): private paths, imports, refresh, payroll, backup, restore, and reports
- [Known limitations](known-limitations.md): unsupported use cases and validation requiring external access
- [Architecture](architecture.md) and [single sources of truth](v3/single-source-of-truth.md)
- [Security model](security-model.md), [desktop threat model](v3/desktop-threat-model.md), and
  [error handling](v3/error-handling.md)
- [Product charter](product-charter.md), [data sources](data-source-strategy.md), and
  [accounting rules](accounting-rules.md)

Money Map has no hosted deployment. The production-relevant delivery path is the signed arm64 macOS
application; start with the development and testing guides for source work and use the versioned
packaging, qualification, and release contracts only for explicitly authorized release work.

## Current versioned contracts

- [Cash Flow and goal-gap contract](v2.1/cash-flow-and-goal-gap-contract.md)
- [Desktop architecture](v3/desktop-architecture.md)
- [Desktop product experience](v3/desktop-product-experience.md)
- [Cutover readiness](v3/cutover-readiness.md)
- [Synthetic release-state contract](v3/synthetic-release-state-contract.md)
- [Release contract](v3/release-contract.md)
- [Packaging](v3/desktop-packaging.md) and [installed qualification](v3/desktop-release-qualification.md)
- [Security acceptance](v3/security-acceptance.md) and [hardening status](v3/security-hardening.md)

## Decision and historical records

- `adr/` contains durable architecture decisions.
- `releases/` contains version-specific release notes and campaign records.
- `v2/` contains historical v2 contracts, recovery plans, and accepted checklists that remain useful
  for compatibility and evidence review. They are not general setup instructions.
- [API roadmap](api-roadmap.md) is planning context; implemented behavior is defined by current routes,
  tests, and the SSOT map.

Do not copy command counts or acceptance claims from historical documents into current handoffs.
Re-run the commands in the development guide and report fresh results.
