# Error handling and incident response

This is the current source contract for Money Map failure handling. It covers the Python API,
financial workflows, React UI, macOS shell, and operational scripts. All validation uses synthetic
inputs and disposable storage. Passing these checks does not qualify a signed application or
supersede the owner walkthrough recorded for an older candidate.

The desktop financial surface remains blocked until both the sidecar and private data home report
ready. Failed readiness is never converted into successful migration. Expected API validation
errors retain safe, explicit failure responses; unknown responses never become success.

## Implemented boundaries

| Area and severity | Behavior |
| --- | --- |
| Financial commit — High | `goal_observation.coordinate_goal_observation` commits the caller's pending operation before entering the optional observation boundary. A failure rolls back, records `MM-OPERATION-COMMIT-FAIL`, and propagates. It cannot return “financial operation completed.” A later currentness or check-in failure returns an explicit retryable `unavailable` observation while preserving the completed financial transaction. |
| Migration logging — Medium | Embedded Alembic migrations preserve host logging handlers and existing loggers. Standalone migration logging is configured only when no root handlers exist, with existing loggers left enabled. |
| Request capacity — High | Both security middleware implementations release their admission slot in `finally`, including body-read exceptions, cancellation, health-response failures, and downstream exceptions. Timeout and size limits remain enforced. Repeated disconnects cannot exhaust the 32-request admission limit. |
| Unexpected API errors — High | `RequestFailureMiddleware` records a private-safe failure and returns HTTP 500 with instructions to inspect the action's status before retrying. It does not automatically replay writes. If response transmission already started, it propagates a fixed-message failure instead of sending a second response. Cancellation and lifespan/startup failures still propagate. |
| Desktop data operations — Medium | Expected `DataHomeError` responses retain their explicit code and 409/422 handling. Unexpected failures retain the safe 500 wrapper and now record diagnostic code locations. Journal-managed failures remain explicit recoverable status objects, with diagnostics added. HTTP 200 alone is not proof that migration or recovery succeeded: inspect `ready`, `phase`, and `failure_code`. |
| Connection isolation — High | A failed connection rolls back pending session state before subsequent database queries or connections run. Each failure records `MM-SYNC-FAIL` and remains in the refresh result. Successful connections remain committed. Validation error messages no longer copy arbitrary exception text. |
| Provider history and normalization — High | Sync pagination requires valid arrays, a boolean continuation flag, and a nonempty progressing cursor. Offset pagination requires record arrays and nonnegative integer totals; premature empty pages and overrun fail. Each history call is capped at 100 pages. Required record collections reject malformed rows instead of dropping them. Missing account references, unavailable balances, and missing/non-finite required amounts fail normalization rather than becoming fresh or zero-valued evidence. The sync savepoint preserves prior transactions, holdings, balances, cursor, and last-success time on failure. |
| Provider error privacy — High | HTTP error responses expose an allowlisted provider code and fixed message. Arbitrary provider `display_message`, `error_message`, and unknown error codes are not copied into public error text. Invalid dates/timestamps use fixed validation messages. |
| Forecast resilience — Medium | Missing payroll raises `ForecastUnavailableError`, a `ValueError` subtype. Account refresh may continue and logs `MM-FORECAST-UNAVAILABLE`; the scenarios endpoint may return an empty list. Other calculation/validation errors propagate rather than disappearing under a generic `ValueError` catch. |
| Saved Retirement provenance — High | Missing provenance retains legacy profile-column references. Present but malformed JSON, version, field maps, or references fail validation and emit `MM-PROVENANCE-INVALID`. Reads do not invent provenance, and writes do not overwrite a damaged record with a blank replacement. |
| Credential deletion — High | An absent secret is an idempotent no-op after a successful lookup. A deletion failure for an existing secret raises `SecretStoreError`, including `PasswordDeleteError`; it is no longer mistaken for successful deletion. Tests mock Keychain entirely. |
| Native cleanup — High | Failed restart/shutdown cleanup retains the process handle, clears request credentials, and reports failed lifecycle state. A later deliberate cleanup can retry. Quit returns a nonzero exit status and fixed `MM-NATIVE-CLEANUP-FAIL` message when cleanup fails, instead of reporting normal completion. |
| UI render failures — Medium | `FailureBoundary` covers the application tree, including lazy render failures. It replaces the broken view with an explicit reload action and warns about unsaved edits. React's caught-error callback emits only `MM-UI-RENDER-FAIL`; it does not print the thrown object. Existing event-handler and fetch errors keep their local error surfaces. |
| Rejected imports — Medium | Per-file validation remains isolated using savepoints and explicit error counts. Each rejected file also emits `MM-IMPORT-REJECTED`, without a filename or parser message. Unexpected errors still abort the operation. |
| Database diagnostics — Medium | A completed integrity or foreign-key check reports `pass` or `fail`. `unavailable` is reserved for checks not performed because the data home is not ready. |

## Diagnostic records

Production desktop logs live in `~/Library/Logs/Money Map/`; synthetic runs use their explicitly
configured disposable log directory. `safe_events.record_failure` records two bounded local files:

- `desktop-events.jsonl`: the existing `money-map-safe-events-v1` record with `contract`, `code`,
  `classification`, and UTC `at` fields.
- `failure-events.jsonl`: `money-map-safe-failures-v1`, containing those fields plus `frames`.
  Frames are up to 16 Money Map Python filenames and line numbers from the traceback, in call
  order. They omit absolute paths, source lines, locals, exception text, and third-party frames.

Each file rotates at 256 KiB and retains up to three archives in addition to the current file.
A process-wide lock serializes rotation and writes. Files use mode 0600 and the log directory uses
0700. File opens reject symlink targets and nonregular or multiply linked files. Every reported
occurrence is recorded; failures are not deduplicated or rate-limited. Rotation means this is recent
incident history, not an audit ledger.

When no desktop log directory is configured, fixed codes and source locations go through the
`paycheck_map.failures` Python logger. Missing-payroll and rejected-import events are warnings;
other reported failures are errors. No remote telemetry or financial payload logging is added.
Log write failure emits the fixed `MM-TELEMETRY-UNAVAILABLE` stderr/logger message and cannot undo a
completed operation or replace the original failure. The native shell deliberately discards raw
sidecar stderr; if durable logging fails, rely on the operation's UI/result status and check log
permissions and free disk space. Absence of a log entry is not proof of success.

The existing Diagnostics export contains health categories, not these traceback-location records.
Collect the relevant fixed-code records locally when investigating. UI and native fixed codes are
console/exit signals, not durable backend event records. Use source locations with the exact source
commit that produced the running application; line numbers from another build may differ.

## Operating a failure

1. Record the operation, visible status, time, and running build identity. After a lost response or
   render error, reload and inspect persisted state before retrying: some source operations may
   already have committed even when a later observation or response failed.
2. For a partial refresh, inspect failed connection codes and source currentness. Successful
   connections remain usable; the result does not claim that every source is current. A missing
   balance or malformed provider record now requires a successful complete retry before freshness
   advances. Reconnect only when the connection status calls for it.
3. For `MM-GOAL-CURRENTNESS-FAIL` or `MM-GOAL-CHECKIN-FAIL`, inspect financial data first, then use
   Update data to retry observation. Do not repeat a financial mutation solely to create a check-in.
4. For a data-home failure, use the existing Data safety/recovery workflow. A failed integrity check
   or invalid saved provenance is not permission to edit the database or fabricate replacement
   evidence. Preserve the current database and verified backups for an authorized recovery.
5. For native cleanup failure, do not assume a zero-resource shutdown or launch another candidate.
   Inspect the local runtime state before retrying cleanup. A failure remains failed even if the
   window has closed. No automatic data repair is performed.
6. Consult the fixed event code and retained code locations. Keep raw provider payloads, credentials,
   financial files, private paths, and exception objects out of shared incident reports.

## Intentional resilience and suppression retained

- Per-connection refresh isolation and per-file import savepoints preserve independent successes.
  Both publish failure counts/status and diagnostic events. There is no server background scheduler
  or queue consumer: automatic refresh is requested by the UI and uses a nonblocking operation lock
  and one-attempt-per-business-day setting. A manual retry remains available.
- Goal observation is optional only after the source operation commits. Its failed status prevents
  an implied current observation and cannot roll back committed financial source data.
- The single retry for `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` starts a fresh history request.
  Other provider errors propagate. Provider request timeouts remain 45 seconds per HTTP call; the
  100-page cap is a count bound, not a total operation deadline.
- Frontend abort/generation guards intentionally ignore obsolete reads. Failed reloads retain the
  last accepted view with an error banner. Typed contract parsers reject invalid results; failed
  JSON parsing of error responses supplies a generic failure, not a successful empty result.
- PDF validation catches third-party parser exceptions to reject the untrusted container. Import
  errors remain safe summaries. Parser exception strings are intentionally excluded from telemetry.
- Writer-lock release tolerates an already absent marker, still unlocks/closes its held descriptor,
  and raises on other filesystem failures. Transaction and filesystem cleanup catches that re-raise
  remain in place. Credential setup rollback continues to report incomplete restoration explicitly.
- Data-home journal recovery and cutover readiness use typed unavailable/recoverable states and
  reject unverifiable state. Native shutdown escalates from its control channel to process signals,
  then verifies disappearance. Failure to send a graceful request is acceptable only if later
  cleanup verification succeeds.
- Native window focus/hide/show actions remain best effort; they do not authorize financial writes.
  Diagnostic metadata such as unavailable OS version remains explicitly `unavailable`. Qualification
  channel sends/cleanup and startup death use bounded timeouts and failed outcome contracts.
- Sidecar access logs and raw stderr remain suppressed to protect private data. Fatal startup still
  emits the fixed failed protocol signal and exits nonzero; optional fatal-event logging cannot
  make a failed startup successful.
- Synthetic fault injection remains restricted by the existing disposable-home mode checks. No
  production permissiveness flag was added. Static suppressions remain limited to existing SQLAlchemy
  DBAPI typing, FastAPI dependency defaults, packaging-library typing, and script import ordering.
  No new warning filter, lint suppression, test skip, or CI continue-on-error was added.
- Unknown/legacy snapshot contexts remain labeled legacy and non-promotable. Missing optional
  provider classification/display metadata may retain a neutral label; required financial evidence
  now fails closed.

## Validation and remaining boundaries

Use the full source gate and native gate in [Testing](../testing.md). Fault-injection coverage includes
commit versus observation failures, interrupted/cancelled requests beyond the admission limit,
private-safe API/log failures, repeated diagnostic records, failed secret deletion, corrupt
provenance, malformed/incomplete provider history, normalization rollback, retained native cleanup
handles, and render recovery.

Signed packaging and installed-app qualification must be repeated for any new candidate before its
owner acceptance; the previous signed artifact has not been changed. Live provider behavior and
real Keychain permission prompts require a separately authorized session. A total provider-operation
deadline and durable native/UI incident collection are possible follow-ups; this implementation
keeps the existing request timeout and local console/result contracts.
