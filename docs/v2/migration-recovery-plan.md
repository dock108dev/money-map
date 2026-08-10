# Money Map v2 migration and recovery plan

## Safety boundary

This is the required design for Slice 1; migration `0009` does not exist in Slice 0.
The active `.local` database must not be opened for migration, copied for fixture creation,
or otherwise mutated until a fresh backup has been verified and an isolated restore has
passed the complete upgrade/downgrade/re-upgrade drill below.

All v2 changes are additive. Every pre-v2 table, row, primary key, foreign key, exact money
value, timestamp, JSON value, and evidence field remains logically identical. In particular,
the migration never updates or deletes `life_plan_profiles`, `life_goals`, `life_scenarios`,
or `life_projection_periods`.

## Proposed Slice 1 schema

The exact Alembic implementation may refine names, but not these invariants.

### `goal_programs`

- integer primary key and stable unique public key such as `goal_life_<life_goal_id>`;
- nullable, unique `source_life_goal_id` foreign key to `life_goals.id` using `RESTRICT`;
- copied name, target date, target amount, protected cash floor, and reserved amount;
- `is_primary`, status, and tracking mode;
- explicit reservation policy fixed to `exclusive_primary_goal`;
- per-field provenance/evidence metadata identifying the source v1.2.1 row and column;
- contract and migration versions; and
- created/updated timestamps that describe the v2 copy, not the original record.

Target, floor, and reserved amounts use the existing exact `Money` representation. A
SQLite partial unique index on a constant primary scope where `is_primary = 1` permits at
most one primary program. Checks reject negative target/floor/reserved values and reserved
amount greater than target. No ordinary program can claim retirement assets as its capital.

### `goal_check_ins`

- deterministic text primary key from goal public key plus source fingerprint;
- foreign key to `goal_programs` with `RESTRICT`;
- source fingerprint and effective observation date;
- exact position values and mandatory evidence metadata;
- versioned canonical position payload sufficient to reproduce the typed contract;
- trigger and timezone-aware creation timestamp kept outside fingerprint material; and
- unique constraint on `(goal_program_id, source_fingerprint)`.

Check-ins are append-only. Application code must expose inserts and reads only; updates or
deletes are recovery operations outside ordinary runtime. Slice 1 establishes shape and
constraints. Slice 2 owns creation/idempotency services.

### `goal_check_in_components`

- foreign key to `goal_check_ins` with `RESTRICT`;
- versioned component key;
- exact amount, evidence class, derivation, and stable supporting source references; and
- unique constraint on `(check_in_id, component_key)`.

This table, or a proven equivalently constrained canonical payload, must reproduce cash,
accessible investments, retirement-excluded assets, debt, target, floor, reserved amount,
comparison inputs, and unexplained residual without display text.

No check-in is backfilled by migration `0009`; Slice 2 creates the first source-fingerprinted
observation from the post-migration domain.

## Exact v1.2.1 mapping

Migration uses database values directly as `Decimal`; it never passes through float or
formatted copy.

| v2 value | v1.2.1 source | rule |
|---|---|---|
| source identity | `life_goals.id` | stable `goal_life_<id>` and FK |
| name | `life_goals.name` | exact copy |
| target date | `life_goals.target_date` | exact copy |
| target amount | `life_goals.target_amount` | exact copy, `user_entered` |
| reserved amount | `life_goals.reserved_amount` | exact copy, `user_entered` |
| protected floor | owning `life_plan_profiles.cash_floor` | exact copy, `user_entered` |
| primary state | enabled-goal cardinality | true only when exactly one enabled candidate exists |
| reservation policy | v2 constant | `exclusive_primary_goal` |

Cardinality behavior:

- No Life Lab profile: create no goal program.
- Profile with no enabled goal: create no goal program. Disabled v1 goals remain untouched.
- Exactly one enabled goal: copy that goal into one v2 program and mark it primary.
- More than one enabled goal: copy every enabled goal as a non-primary candidate, preserving
  each target and reserved amount exactly. Select none and require later explicit owner
  selection. Never choose by date, priority, amount, row order, or recency.
- A completed enabled goal is copied exactly and remains primary when it is the sole enabled
  candidate; completion is derived later from reserved amount versus target.

Every existing `life_*` record remains the historical v1.2.1 source of truth. Migration
copies supported inputs; it does not rename, disable, normalize, repair, or repurpose the
original records. Existing scenario fingerprints and monthly rows remain readable under
their original engine/assumption versions.

## Logical manifests

The drill captures machine-readable manifests before upgrade, after upgrade, after
downgrade, and after re-upgrade. Manifests are stored only under an ignored temporary
directory and never contain credentials or raw provider payloads.

For every pre-v2 table, the manifest records:

- schema name and ordered column definitions;
- indexes, unique constraints, and foreign keys;
- row count;
- stable primary-key ordering;
- a canonical row digest built from typed values (exact decimal text, ISO dates/timestamps,
  sorted-key JSON, explicit nulls, and unmodified text); and
- the database Alembic revision separately from logical row equality.

The post-upgrade pre-v2 manifest must equal the pre-upgrade manifest byte for byte except
for the expected Alembic revision. A separate v2 manifest proves the mapping table above,
zero initial check-ins, primary cardinality, exact values, and provenance. After downgrade,
the full logical manifest and pre-v2 schema must equal the original; only v2 tables and
indexes may be absent. Re-upgrade must reproduce the same v2 manifest except explicitly
allowed v2 creation timestamps, which are compared by invariant rather than equality.

## Upgrade paths

All paths run without network access, provider calls, imports, refreshes, or UI actions.

1. **Empty database:** upgrade from base to v1.2.1 head, capture manifest, upgrade to v2,
   verify zero goal rows and constraints, downgrade, compare, and re-upgrade.
2. **Synthetic databases:** materialize every state in
   `tests/fixtures/synthetic/v1_2_1/states.json`, upgrade each, assert its declared primary
   selection outcome and exact mappings, downgrade and compare, then re-upgrade.
3. **Isolated restored database:** create and verify a fresh backup of the active database;
   restore the backup to a new isolated directory; prove the restored file is not the active
   path or inode; run the full drill against only that restored copy.
4. **Active database:** eligible only after all prior paths pass and only in the separately
   authorized release slice. Capture another immediately current verified backup before the
   active upgrade.

## Backup and restore verification

A valid backup requires all of the following:

- SQLite online backup completes to an explicit non-active path under `.local/backups/`;
- source and backup paths/inodes differ;
- backup size is nonzero and a SHA-256 digest is recorded locally;
- `PRAGMA integrity_check` returns exactly `ok`;
- `PRAGMA foreign_key_check` returns zero rows with foreign keys enabled;
- the backup Alembic revision is the expected v1.2.1 head `0008_life_lab_v01`;
- the backup logical manifest equals the source logical manifest; and
- restoring the backup to a second isolated path reproduces the same integrity, foreign-key,
  revision, and logical-manifest results.

Never log manifest row content from private state. Local release evidence records counts,
digests, pass/fail results, paths inside ignored `.local`, and versions only.

## Idempotency and failure recovery

- A successful `alembic upgrade head` followed by the same command is a no-op with unchanged
  v2 row counts, primary selection, copied amounts, and source mappings.
- Deterministic public keys plus unique `source_life_goal_id` prevent duplicate copies.
- Migration operates in one Alembic transaction where SQLite permits. Tests inject a
  failure after table creation and during row copy; neither may leave a database that is
  reported at the new revision with a partial logical mapping.
- On any isolated failure, retain the failure evidence, discard only the isolated working
  copy, restore again from the verified backup, and rerun after correction.
- On any active failure, stop the application and make no repair guesses. Preserve the
  failed file for diagnosis, restore the verified pre-upgrade backup through the existing
  recoverable restore workflow, and rerun integrity, foreign-key, revision, and logical
  equality checks before reopening.
- Never rerun imports, Plaid sync, payroll generation, or corrective SQL to make a migration
  comparison pass.

## Downgrade

Downgrade removes only v2 goal check-in component, check-in, and goal-program tables plus
their v2 indexes/constraints, in foreign-key-safe order. It does not project edits back into
`life_*`, because v2 cross-surface edits require explicit promotion and v1.2.1 history is
immutable. Before downgrade, export a local v2-only logical manifest so rollback evidence
can describe what becomes unreadable under v1.2.1.

After downgrade, all pre-v2 logical data and schema must equal the original v1.2.1 manifest,
`PRAGMA integrity_check` must be `ok`, `PRAGMA foreign_key_check` must return no rows, and
Alembic must report `0008_life_lab_v01`.

## Slice 1 exit evidence

Slice 1 is not complete until empty, all synthetic, and isolated-restored paths pass focused
and full tests; upgrade/downgrade/re-upgrade and injected-failure tests pass; manifests prove
lossless v1.2.1 preservation; backups and restores verify; privacy scan passes; no active
database was touched; and the repository is clean at one local checkpoint.
