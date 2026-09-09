import { displayMessage } from "./presentation";
import { dataFormat, displayLabel } from "./presentation";
import { useCallback, useEffect, useRef, useState } from "react";

import { request } from "./api";

export type DataHomePhase =
  | "fresh_setup_available"
  | "confirmation_required"
  | "backup_in_progress"
  | "backup_verified"
  | "staging_copy_in_progress"
  | "staging_validation"
  | "schema_migration_in_progress"
  | "logical_manifest_validation"
  | "activation_pending"
  | "activation_complete"
  | "already_migrated"
  | "recoverable_failure"
  | "resume_available"
  | "rollback_available"
  | "restore_preview"
  | "restore_in_progress"
  | "restore_complete";

export type CutoverState =
  | "fresh_setup"
  | "eligible_legacy_source"
  | "current_0010_source"
  | "unsupported_newer_source"
  | "missing_or_unknown_revision"
  | "integrity_failure"
  | "foreign_key_failure"
  | "required_table_failure"
  | "source_unavailable"
  | "read_only_source"
  | "insufficient_destination_space"
  | "unwritable_destination"
  | "rehearsal_required"
  | "rehearsal_in_progress"
  | "rehearsal_passed"
  | "confirmation_required"
  | "activation_ready"
  | "recoverable_interruption"
  | "rollback_available"
  | "completed_cutover";

export interface DataHomeStatus {
  phase?: DataHomePhase;
  state?: CutoverState;
  ready?: boolean;
  schema_revision?: string;
  backup_count?: number;
  candidate_token?: string;
  confirmation_token?: string;
  source_classification?: string;
  destination_classification?: string;
  size?: number;
  required_space?: number;
  confirmation_required?: boolean;
  recoverable?: boolean;
  resume_available?: boolean;
  rollback_available?: boolean;
  failure_code?: string | null;
  replacement_warning?: string;
  backup_id?: string;
  source?: string;
  schema?: string;
  integrity?: string;
  foreign_keys?: string;
  backup?: string;
  destination?: string;
  rehearsal?: string;
  rollback?: string;
  candidate?: string;
  action?: string;
  expires_in_seconds?: number;
}

interface BackupStatus {
  backup_id: string;
  filename: string;
  label: string;
  created_at: string;
  schema_revision: string;
  size: number;
  verified: boolean;
}

export async function loadDataHomeStatus(): Promise<DataHomeStatus> {
  return request<DataHomeStatus>("/api/desktop/data-home/status");
}

function action(path: string, body?: unknown) {
  return request<DataHomeStatus>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export default function DataHomePanel({
  initial,
  onStatus,
  onClose,
}: {
  initial: DataHomeStatus;
  onStatus(status: DataHomeStatus): void;
  onClose?: () => void;
}) {
  const [status, setStatus] = useState(initial);
  const [backups, setBackups] = useState<BackupStatus[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [restore, setRestore] = useState<DataHomeStatus | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const restoreRef = useRef<HTMLDivElement>(null);
  const needsSetup = !status.ready;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>("button:not([disabled])")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && onClose && !busy && !restore) {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not([disabled])"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      if (onClose) previous?.focus();
    };
  }, [busy, needsSetup, onClose, restore]);

  useEffect(() => {
    if (!restore) return;
    restoreRef.current?.querySelector<HTMLElement>("button")?.focus();
  }, [restore]);

  const update = useCallback(
    (next: DataHomeStatus) => {
      setStatus(next);
      onStatus(next);
    },
    [onStatus],
  );

  const refreshBackups = useCallback(async () => {
    if (!status.ready) return;
    const result = await request<{ backups: BackupStatus[] }>("/api/desktop/data-home/backups");
    setBackups(result.backups);
  }, [status.ready]);

  useEffect(() => {
    void refreshBackups().catch(() => setError("Backup status is unavailable."));
  }, [refreshBackups]);

  const run = async (operation: () => Promise<DataHomeStatus>) => {
    setBusy(true);
    setError("");
    try {
      const result = await operation();
      update(result);
      if (
        (result.phase === "activation_complete" || result.phase === "restore_complete" || result.state === "completed_cutover") &&
        window.__MONEY_MAP_DESKTOP__?.mode
      ) {
        await window.__MONEY_MAP_DESKTOP__.restart();
        await window.__MONEY_MAP_DESKTOP__.reload();
        return;
      }
      if (result.ready) await refreshBackups();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The data operation stopped safely.");
    } finally {
      setBusy(false);
    }
  };

  const chooseExisting = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await window.__MONEY_MAP_DESKTOP__?.selectImport();
      if (result) update(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The selected data was rejected safely.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      ref={dialogRef}
      className={needsSetup ? "data-home-setup" : "data-home-dialog"}
      role={needsSetup ? "main" : "dialog"}
      aria-modal={needsSetup ? undefined : true}
      aria-labelledby="data-home-title"
      aria-busy={busy}
    >
      <div className="data-home-card">
        <span className="eyebrow">Private data</span>
        <h1 id="data-home-title">{needsSetup ? "Set up Money Map" : "Data safety"}</h1>
        <p>
          Money Map keeps your records, imports, reports, and checked backups in private macOS
          locations. It never scans for existing data.
        </p>
        {error && <div className="error-banner" role="alert">{displayMessage(error)}</div>}
        {busy && <div className="data-operation-state" role="status" aria-live="polite">Working… Please wait until the checks finish.</div>}
        {!busy && status.phase === "backup_verified" && <div className="data-operation-state success" role="status">Verified backup created.</div>}
        {!busy && status.phase === "restore_complete" && <div className="data-operation-state success" role="status">Restore verified and complete.</div>}

        {status.phase === "fresh_setup_available" && (
          <div className="data-home-actions">
            <button className="primary-button" disabled={busy} onClick={() => void run(() => action("/api/desktop/data-home/fresh"))}>
              Start fresh
            </button>
            <button disabled={busy} onClick={() => void chooseExisting()}>
              Import existing Money Map data
            </button>
          </div>
        )}

        {status.state && status.candidate_token && status.state !== "confirmation_required" && (
          <div className="data-home-preview">
            <h2>Review existing data</h2>
            <dl>
              <div><dt>Source</dt><dd>{status.source}</dd></div>
              <div><dt>Data format</dt><dd>{dataFormat(status.schema)}</dd></div>
              <div><dt>File size</dt><dd>{status.size}</dd></div>
              <div><dt>File checks</dt><dd>{displayLabel(status.integrity)}</dd></div>
              <div><dt>Record links</dt><dd>{displayLabel(status.foreign_keys)}</dd></div>
              <div><dt>Backup</dt><dd>{displayMessage(displayLabel(status.backup))}</dd></div>
              <div><dt>Destination</dt><dd>{displayMessage(displayLabel(status.destination))}</dd></div>
              <div><dt>Test copy</dt><dd>{displayMessage(displayLabel(status.rehearsal))}</dd></div>
              <div><dt>Recovery</dt><dd>{displayMessage(displayLabel(status.rollback))}</dd></div>
              <div><dt>App check</dt><dd>{displayMessage(displayLabel(status.candidate))}</dd></div>
            </dl>
            <p><strong>Next action:</strong> {status.action && displayMessage(status.action)}</p>
            <p>Your original file stays unchanged. The test uses a temporary copy.</p>
            <div className="data-home-actions">
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void run(async () => {
                  await action("/api/desktop/data-home/cutover/rehearsal");
                  return action("/api/desktop/data-home/cutover/prepare");
                })}
              >
                Test a copy and review confirmation
              </button>
              <button disabled={busy} onClick={() => update({ phase: "fresh_setup_available", ready: false })}>Cancel</button>
            </div>
          </div>
        )}

        {status.state === "confirmation_required" && status.confirmation_token && (
          <div className="data-home-preview">
            <h2>Confirm switching data</h2>
            <dl>
              <div><dt>Source</dt><dd>{status.source}</dd></div>
              <div><dt>Data format</dt><dd>{dataFormat(status.schema)}</dd></div>
              <div><dt>Backup</dt><dd>{displayMessage(displayLabel(status.backup))}</dd></div>
              <div><dt>Destination</dt><dd>{displayMessage(displayLabel(status.destination))}</dd></div>
              <div><dt>Test copy</dt><dd>{displayMessage(displayLabel(status.rehearsal))}</dd></div>
              <div><dt>Recovery</dt><dd>{displayMessage(displayLabel(status.rollback))}</dd></div>
              <div><dt>App check</dt><dd>{displayMessage(displayLabel(status.candidate))}</dd></div>
            </dl>
            <p>This one-use confirmation expires in {status.expires_in_seconds ?? 300} seconds.</p>
            <p><strong>Next action:</strong> {status.action && displayMessage(status.action)}</p>
            <div className="data-home-actions">
              <button className="primary-button" disabled={busy} onClick={() => void run(() => action(
                "/api/desktop/data-home/cutover/confirm",
                { confirmation_token: status.confirmation_token, requested_action: "activate_reviewed_source" },
              ))}>Use reviewed data</button>
              <button disabled={busy} onClick={() => update({ phase: "fresh_setup_available", ready: false })}>Cancel</button>
            </div>
          </div>
        )}

        {status.phase === "recoverable_failure" && (
          <div role="alert" className="data-home-recovery">
            <h2>The operation paused safely.</h2>
            <p>Your original file and previously approved data have not been repaired or replaced.</p>
            <div className="data-home-actions">
              {status.resume_available && <button disabled={busy} onClick={() => void run(() => action("/api/desktop/data-home/resume"))}>Resume</button>}
              {status.rollback_available && <button disabled={busy} onClick={() => void run(() => action("/api/desktop/data-home/rollback"))}>Return to previous data</button>}
            </div>
          </div>
        )}

        {status.ready && (
          <>
            <div className="data-home-status" role="status">
              <strong>Your saved data passed its checks</strong>
              <span>{dataFormat(status.schema_revision ?? "unavailable")}</span>
            </div>
            <div className="data-home-actions">
              <button className="primary-button" disabled={busy} onClick={() => void run(() => action("/api/desktop/data-home/backup"))}>
                Create backup
              </button>
              <button disabled={busy} onClick={() => void chooseExisting()}>Import existing data</button>
            </div>
            <h2>Verified backups</h2>
            {backups.length === 0 ? <p>No verified backups yet.</p> : (
              <ul className="backup-list">
                {backups.map((backup) => (
                  <li key={backup.backup_id}>
                    <div><strong>{backup.filename}</strong><span>{new Date(backup.created_at).toLocaleString()} · {backup.size.toLocaleString()} bytes</span></div>
                    <div>
                      <button disabled={busy} onClick={() => void window.__MONEY_MAP_DESKTOP__?.revealBackup(backup.backup_id)}>Reveal in Finder</button>
                      <button disabled={busy} onClick={() => void run(async () => {
                        const preview = await action("/api/desktop/data-home/restore-preview", { backup_id: backup.backup_id });
                        setRestore(preview);
                        return status;
                      })}>Preview restore</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {restore?.backup_id && restore.confirmation_token && (
          <div ref={restoreRef} className="restore-warning" role="alertdialog" aria-modal="true" aria-labelledby="restore-title">
            <h2 id="restore-title">Replace your current data?</h2>
            <p>{restore.replacement_warning && displayMessage(restore.replacement_warning)}</p>
            <p>A checked backup of your current data will be created first. You can return to it if needed.</p>
            <div className="data-home-actions">
              <button disabled={busy} onClick={() => setRestore(null)}>Cancel</button>
              <button className="danger-button" disabled={busy} onClick={() => void run(async () => {
                const result = await action("/api/desktop/data-home/restore", {
                  backup_id: restore.backup_id,
                  confirmation_token: restore.confirmation_token,
                });
                setRestore(null);
                return result;
              })}>Replace with verified backup</button>
            </div>
          </div>
        )}

        {!needsSetup && onClose && <button className="dialog-close" aria-label="Close data safety" onClick={onClose}>×</button>}
      </div>
    </section>
  );
}
