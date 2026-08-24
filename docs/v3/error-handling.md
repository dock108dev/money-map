# Production error handling

This document is the source of truth for Money Map production failure behavior. Error handling is
fail closed around private-data readiness, authentication, validation, database integrity, and
write ownership. Resilience is retained only where the application can identify partial or
secondary failure without misreporting success.

## User-visible behavior

- The desktop financial surface remains unavailable until both the local sidecar and private data
  home report ready. A failed data-home status request is never converted into a ready or migrated
  state. The app shows a safe blocking error and requires an explicit retry.
- FastAPI string, validation-array, and allowlisted object error details retain their safe message.
  Unknown or malformed responses use the HTTP status fallback and never become success.
- Connected refreshes isolate one connection from another. Each failed connection returns a
  `failed` result with a bounded code/message, the aggregate reports the failed count, and no goal
  observation is saved for incomplete currentness. Successful connection data remains committed.
- Goal observations are secondary to completed financial operations. Currentness or check-in write
  failure returns `unavailable` and `retryable`, preserves committed financial data, and records a
  private-safe event.
- Startup, integrity, migration, restore, and authentication failures stop the affected operation.
  They do not silently repair, activate, or replace financial data.
- Plaid configuration attempts restore every prior Keychain value after a multi-write failure. If
  any restoration step also fails, setup raises an explicit safe Keychain error instead of masking
  the ambiguity as an ordinary setup failure; the connection must not proceed.

## Private-safe events

Desktop events are JSON Lines records under `~/Library/Logs/Money Map/desktop-events.jsonl`. Each
record contains only the contract, fixed code, fixed classification, and UTC timestamp. Files are
mode `0600`, directories are mode `0700`, logs rotate at 256 KiB, and three prior files are kept.
No exception text, financial value, identifier, credential, request body, path, or environment
value is recorded.

Operational failure codes added to the existing lifecycle contract are:

| Code | Meaning | Operator action |
| --- | --- | --- |
| `MM-DESKTOP-FAIL` | The sidecar exited through its fatal boundary. | Restart once; if repeated, inspect diagnostics and recent fixed-code events. |
| `MM-GOAL-CURRENTNESS-FAIL` | Financial work completed but goal-source currentness did not persist. | Use Update data; do not treat the latest goal observation as current. |
| `MM-GOAL-CHECKIN-FAIL` | Current financial data was preserved but the derived goal check-in did not persist. | Retry Update data; investigate repeated events. |

Repeated events remain separate timestamped records so recurrence is distinguishable from one
failure. Failure to write secondary telemetry does not roll back an already committed financial
operation.

## Intentional resilience

- Per-connection refresh catches unexpected connection-local failures only at the orchestration
  boundary. It records the connection as failed, uses the durable sync-run error state where
  available, reports partial aggregate status, and continues other connections.
- Goal-observation coordination catches unexpected persistence failures because the observation is
  derived evidence. It rolls back only its transaction, returns an explicit retryable status, and
  emits a fixed safe event; it does not undo source financial data.
- Process cleanup ignores only already-exited processes, missing temporary files, and equivalent
  idempotent teardown conditions. These paths do not convert startup or qualification failure into
  acceptance.
- Diagnostics omit unavailable backend fields. Missing backup evidence is explicitly
  `status: unavailable` and `all_verified: false`; an empty observed backup catalog may still be
  verified when the backend itself was reached successfully.
- Exception text and stack traces are intentionally excluded from desktop output and safe-event
  files because they can contain private paths or provider details. Durable typed status, fixed
  event codes, and sanitized diagnostics are the supported production evidence surfaces.

## Incident check

1. Keep the app stopped if private-data readiness, integrity, migration, or writer ownership fails.
2. Use the in-app sanitized diagnostics preview; export it only to an owner-approved location.
3. Inspect recent fixed event codes and timestamps. Never copy the private database, Keychain
   values, provider responses, raw imports, or unrestricted process output into an issue.
4. Retry only the operation named above. Repeated failure after one deliberate retry is an
   investigation signal, not permission to bypass the check.
5. Run `uv run paycheck-map verify` before handing off any repair.
