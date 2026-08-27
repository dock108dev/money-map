# Money Map cutover readiness

Status: Slice 7 implementation proof only. Live owner rehearsal, owner data, owner decisions, the
bounded installed smoke and final acceptance are deferred until after Slice 8. The former
Campaigns A-J matrix is optional dedicated-runner soak coverage, not a cutover prerequisite.

## Reused authority

Cutover readiness extends the Slice 2 `DataHomeManager`; it is not a second migration system. The
same authority owns explicit native selection, read-only/query-only inspection, SQLite online
backup, isolated staging, packaged Alembic execution through `0009_goal_persistence`, complete
logical-manifest comparison, digest-only journaling, fsync and atomic activation, verified restore,
rollback, restart recovery, and `0700` directory / `0600` file enforcement. There is no migration
`0010` and no automatic filesystem discovery.

## Preflight classifications

The owner-facing flow distinguishes fresh setup; eligible legacy and current `0009` sources;
unsupported newer, missing/unknown, integrity, foreign-key, and required-table failures;
unavailable and read-only sources; insufficient space and unwritable destinations; rehearsal
required/in progress/passed; confirmation required; activation ready; recoverable interruption;
rollback available; and completed cutover.

The reviewed summary contains only source and schema classes, size class, integrity and
foreign-key status, backup and destination readiness, rehearsal status, rollback availability,
candidate identity status, and the exact next owner action. It excludes paths, filenames, raw
hashes, accounts, institutions, transactions, identifiers, and exception text.

## Rehearsal and confirmation

The deterministic rehearsal opens only the explicitly selected source read-only, snapshots its byte
identity and complete logical manifest, creates a verified online backup, migrates an isolated copy
only through `0009`, verifies integrity and foreign keys, and activates only inside a disposable
fake macOS home. A recreated data-home authority verifies retained state. Safety backup,
replacement rollback, interruption/resume phases, source-byte preservation, permission ownership,
and cleanup are covered by the Slice 2 authority and Slice 7 regression campaigns.

After rehearsal, a one-use five-minute confirmation binds the reviewed source identity and class,
destination identity, verified backup, rehearsal commitment, logical manifest, candidate source
commit, optional artifact identity, requested action, and creation/expiration state. Replay,
expiration, stale preview, source replacement, symlink/hard-link substitution, TOCTOU change,
candidate or destination drift, changed backup or manifest, wrong action, and an unresolved prior
operation fail closed. Preview and cancellation perform no filesystem writes.

## Eventual live owner procedure

1. Freeze the exact post-Slice-8 candidate and complete the bounded headless and installed smoke.
2. The owner explicitly selects the source. Never search for it.
3. Review every sanitized preflight classification and abort on any failed or unknown state.
4. Run rehearsal and review its result. Abort if the original identity changes or cleanup fails.
5. Review the verified backup and exact next action, then provide the one-use confirmation.
6. Activate, restart the sidecar, relaunch, and verify retained state without coaching.
7. The owner alone chooses accept or rollback. Keep the source and verified backups unchanged.
8. Record owner decisions only in a fresh worksheet during the live run.

Abort on private output, candidate drift, any data or manifest mismatch, a non-loopback request,
provider or Keychain access without explicit owner choice, inability to verify backup/destination,
interruption without deterministic resume/rollback, cleanup failure, or any request to migrate past
`0009`. Recovery begins from the digest-verified journal: resume only a verified staging copy or
roll back to the retained accepted database. Never hand-edit or silently repair financial data.

## Evidence and decision boundary

Slice 7 evidence is synthetic, sanitized, ignored, and non-promotable. It may record safe counts,
classifications, test results, schema, and source commit; it may not contain private paths, raw
identities, data values, credentials, sessions, provider responses, or owner answers. The checked-in
`owner-cutover-worksheet.json` keeps every owner-controlled response blank and validation rejects
prepopulation or inference.

Implementation proof establishes that the workflow and deterministic drivers exist. It does not
establish the bounded installed smoke, owner usability, owner cutover success, beta acceptance, or
release approval. Those remain in the post-Slice-8 owner-beta plan.
