import { useEffect, useMemo, useRef, useState } from "react";

import type { LifeProjection, PathResult } from "./life-lab-types";
import type {
  ExactDecimalString,
  LabExperimentSeedKind,
  LifeLabExperimentResult,
  LifeLabExperimentSeed,
  LifeLabPromotionApplied,
  LifeLabPromotionPreview,
  PromotionField,
  PromotionTarget,
} from "../v2-contracts";
import type { PlanningSnapshot } from "../retirement/api";
import { loadRetirementSnapshots } from "../retirement/api";
import {
  confirmLabPromotion,
  createLabExperiment,
  loadLabSnapshots,
  loadPrimaryPromotionGoal,
  loadRetirementPromotionProfile,
  openLabSnapshot,
  previewLabPromotion,
  projectLabExperiment,
  saveLabSnapshot,
} from "./api";
import { DriveCalculator } from "./DriveCalculator";
import "./life-lab.css";

function currency(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not solved";
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function fingerprintLabel(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "No copied source";
}

function missionOf(draft: Record<string, unknown>) {
  return draft.mission as Record<string, string | number>;
}

function PromotionDialog({
  preview,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  preview: LifeLabPromotionPreview;
  busy: boolean;
  error: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    const first = dialog?.querySelector<HTMLButtonElement>("button");
    first?.focus();
  }, []);
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const buttons = Array.from(dialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    if (buttons.length === 0) return;
    const first = buttons[0];
    const last = buttons.at(-1) ?? first;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="lab-dialog-backdrop" role="presentation">
      <div ref={dialogRef} className="lab-dialog" role="dialog" aria-modal="true" aria-labelledby="lab-confirm-title" aria-describedby="lab-confirm-description" onKeyDown={onKeyDown}>
        <span className="eyebrow">Explicit boundary crossing</span>
        <h2 id="lab-confirm-title">Confirm this exact promotion?</h2>
        <p id="lab-confirm-description">Only the stored fields in this diff will change. The experiment remains preserved if confirmation fails.</p>
        <dl className="lab-confirm-diff">
          {preview.changes.map((change) => <div key={change.field}><dt><code>{change.stored_target_field}</code></dt><dd><span>{currency(change.before.amount)}</span><b>→</b><strong>{currency(change.after.amount)}</strong></dd></div>)}
        </dl>
        {error && <p className="lab-promotion-error" role="alert">{error}</p>}
        <div className="lab-dialog-actions"><button className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary-button" disabled={busy} onClick={onConfirm}>{busy ? "Confirming…" : "Confirm promotion"}</button></div>
      </div>
    </div>
  );
}

export default function LifeLabView() {
  const [seed, setSeed] = useState<LifeLabExperimentSeed | null>(null);
  const [result, setResult] = useState<LifeLabExperimentResult | null>(null);
  const [snapshots, setSnapshots] = useState<PlanningSnapshot[]>([]);
  const [retirementSnapshots, setRetirementSnapshots] = useState<PlanningSnapshot[]>([]);
  const [retirementSnapshotId, setRetirementSnapshotId] = useState("");
  const [openedSnapshot, setOpenedSnapshot] = useState<PlanningSnapshot | null>(null);
  const [snapshotName, setSnapshotName] = useState("");
  const [currentGoal, setCurrentGoal] = useState<{ goal_program_id: string; name: string } | null>(null);
  const [retirementTargetId, setRetirementTargetId] = useState<string | null>(null);
  const [promotionSurface, setPromotionSurface] = useState<PromotionTarget>("goals");
  const [promotionField, setPromotionField] = useState<PromotionField>("goal_target");
  const [promotionValue, setPromotionValue] = useState("0.00");
  const [preview, setPreview] = useState<LifeLabPromotionPreview | null>(null);
  const [applied, setApplied] = useState<LifeLabPromotionApplied | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [promotionError, setPromotionError] = useState("");
  const [message, setMessage] = useState("");
  const confirmTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    void Promise.all([
      loadLabSnapshots(),
      loadRetirementSnapshots(),
      loadPrimaryPromotionGoal(),
      loadRetirementPromotionProfile(),
    ]).then(([nextSnapshots, nextRetirementSnapshots, goalState, retirementProfile]) => {
      setSnapshots(nextSnapshots);
      setRetirementSnapshots(nextRetirementSnapshots);
      setCurrentGoal(goalState.goal);
      setRetirementTargetId(retirementProfile ? `retirement_profile_${retirementProfile.profile_id}` : null);
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "Lab evidence could not load."));
  }, []);

  const begin = async (kind: LabExperimentSeedKind) => {
    setBusy(true);
    setError("");
    setMessage("");
    setOpenedSnapshot(null);
    try {
      const nextSeed = await createLabExperiment({
        seed_kind: kind,
        retirement_snapshot_id: kind === "retirement_result" ? Number(retirementSnapshotId) : null,
      });
      const nextResult = await projectLabExperiment({
        experiment_id: nextSeed.experiment_id,
        expected_experiment_fingerprint: nextSeed.experiment_fingerprint,
        draft: nextSeed.draft,
      });
      setSeed(nextSeed);
      setResult(nextResult);
      setPromotionValue(String((nextResult.draft.promotable_values as Record<string, string>)?.goal_target ?? missionOf(nextResult.draft).target_amount ?? "0.00"));
      setDirty(false);
      setPreview(null);
      setApplied(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The isolated experiment could not start.");
    } finally {
      setBusy(false);
    }
  };

  const updateMission = (field: string, value: string | number) => {
    if (!result) return;
    const draft = structuredClone(result.draft);
    const mission = missionOf(draft);
    mission[field] = value;
    draft.mission = mission;
    setResult({ ...result, draft });
    setDirty(true);
    setPreview(null);
    setApplied(null);
  };

  const recalculate = async (draft = result?.draft) => {
    if (!result || !draft) return null;
    setBusy(true);
    setError("");
    try {
      const next = await projectLabExperiment({
        experiment_id: result.experiment_id,
        expected_experiment_fingerprint: result.experiment_fingerprint,
        draft,
      });
      setResult(next);
      setDirty(false);
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The isolated draft could not be projected.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const saveExperiment = async () => {
    if (!result) return;
    setBusy(true);
    setError("");
    try {
      const accepted = dirty ? await recalculate() : result;
      if (!accepted) return;
      const name = snapshotName.trim() || `${accepted.seed_kind.replace("_", " ")} experiment`;
      await saveLabSnapshot(name, accepted);
      setSnapshots(await loadLabSnapshots());
      setSnapshotName("");
      setMessage("Reproducible experiment snapshot saved. Goals and Retirement were unchanged.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The experiment snapshot could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const preparePreview = async () => {
    if (!result) return;
    setBusy(true);
    setPromotionError("");
    setApplied(null);
    try {
      const draft = structuredClone(result.draft);
      const values = (draft.promotable_values as Record<string, string> | undefined) ?? {};
      values[promotionField] = promotionValue;
      draft.promotable_values = values;
      const projected = await projectLabExperiment({
        experiment_id: result.experiment_id,
        expected_experiment_fingerprint: result.experiment_fingerprint,
        draft,
      });
      setResult(projected);
      setDirty(false);
      const targetId = promotionSurface === "goals" ? currentGoal?.goal_program_id : retirementTargetId;
      if (!targetId) throw new Error(`A ${promotionSurface === "goals" ? "current Goal" : "Retirement profile"} is required for promotion.`);
      const nextPreview = await previewLabPromotion({
        experiment_id: projected.experiment_id,
        expected_experiment_fingerprint: projected.experiment_fingerprint,
        draft: projected.draft,
        target_surface: promotionSurface,
        target_id: targetId,
        changes: [{ field: promotionField, after: promotionValue as ExactDecimalString }],
      });
      setPreview(nextPreview);
    } catch (reason) {
      setPromotionError(reason instanceof Error ? reason.message : "Promotion preview could not be created.");
    } finally {
      setBusy(false);
    }
  };

  const confirmPromotion = async () => {
    if (!preview || !result) return;
    setBusy(true);
    setPromotionError("");
    try {
      const next = await confirmLabPromotion({ preview, draft: result.draft });
      setApplied(next);
      setConfirmOpen(false);
      setMessage(`Promotion applied to ${next.target_surface}. Only the previewed field changed.`);
      setPreview(null);
      confirmTriggerRef.current?.focus();
    } catch (reason) {
      setPromotionError(reason instanceof Error ? reason.message : "Promotion confirmation failed. The experiment is preserved.");
    } finally {
      setBusy(false);
    }
  };

  const promotionFields = promotionSurface === "goals"
    ? [
        ["goal_target", "Goal target"],
        ["reserved_for_goal", "Reserved for goal"],
        ["protected_cash_floor", "Protected cash floor"],
      ] as const
    : [
        ["retirement_essential_monthly_spend", "Retirement essential monthly spend"],
        ["retirement_flexible_monthly_spend", "Retirement flexible monthly spend"],
      ] as const;

  const projection = result?.projection as unknown as LifeProjection | undefined;
  const selected = result?.reverse_solver.selected_result as unknown as PathResult | undefined;
  const mission = result ? missionOf(result.draft) : null;
  const benchmarkRows = useMemo(() => Object.entries(projection?.benchmarks.thresholds ?? {}), [projection]);

  if (!seed || !result || !mission) {
    return (
      <div className="view-stack life-lab isolated-lab">
        <header className="page-heading life-hero"><div><span className="eyebrow">Experimental workspace</span><h1>Life Lab</h1><p>Explore what an extreme or alternative path would mathematically require.</p></div></header>
        {error && <div className="error-banner" role="alert">{error}</div>}
        <section className="panel lab-seed-chooser" aria-labelledby="lab-seed-heading">
          <span className="eyebrow">Choose the boundary first</span>
          <h2 id="lab-seed-heading">How should this isolated experiment begin?</h2>
          <p>No persistent state is copied until you choose a seed. Draft edits never save back automatically.</p>
          <div className="lab-seed-options">
            <button disabled={busy} onClick={() => void begin("blank")}><strong>Start blank</strong><span>Use explicit zero/default inputs and no source provenance.</span></button>
            <button disabled={busy || !currentGoal} onClick={() => void begin("current_goal")}><strong>Start from current goal</strong><span>{currentGoal ? `Copy ${currentGoal.name} once.` : "No primary Goal is available."}</span></button>
            <div className="lab-retirement-seed"><label>Retirement result<select aria-label="Retirement result seed" value={retirementSnapshotId} onChange={(event) => setRetirementSnapshotId(event.target.value)}><option value="">Choose a saved run</option>{retirementSnapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>{snapshot.name} · age {snapshot.target_age}</option>)}</select></label><button disabled={busy || !retirementSnapshotId} onClick={() => void begin("retirement_result")}><strong>Start from retirement result</strong><span>Copy one immutable saved run once.</span></button></div>
          </div>
        </section>
        <details className="panel lab-legacy-on-entry"><summary>Stored experiment and legacy evidence</summary><div className="scenario-list">{snapshots.length === 0 ? <p>No stored evidence yet.</p> : snapshots.filter((snapshot) => !snapshot.snapshot_context.startsWith("retirement_")).map((snapshot) => <button key={snapshot.id} onClick={() => void openLabSnapshot(snapshot.id).then(setOpenedSnapshot)}><strong>{snapshot.name}</strong><span>{snapshot.context_label}</span></button>)}</div>{openedSnapshot && <article><h2>{openedSnapshot.name}</h2><p>{openedSnapshot.context_label}. Stored inputs, result, warnings, and {openedSnapshot.periods.length} monthly rows are shown without rerunning current inputs.</p><code>{openedSnapshot.source_fingerprint}</code></article>}</details>
      </div>
    );
  }

  return (
    <div className="view-stack life-lab isolated-lab">
      <header className="page-heading life-hero"><div><span className="eyebrow">Experimental workspace</span><h1>Life Lab</h1><p>Reverse-solve an alternative path inside an isolated draft.</p></div><button className="secondary-button" onClick={() => { setSeed(null); setResult(null); setPreview(null); }}>Choose another seed</button></header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {message && <div className="life-message" role="status">{message}</div>}

      <section className="panel lab-source-evidence" aria-labelledby="lab-source-heading">
        <div><span className="eyebrow">Copied once · isolated draft</span><h2 id="lab-source-heading">{seed.source_label ?? "Blank experiment"}</h2><p>{seed.seed_kind === "blank" ? "No Goal or Retirement money was copied." : "Later source edits do not alter this experiment."}</p></div>
        <code title={seed.source_fingerprint ?? "No copied source fingerprint"}>{fingerprintLabel(seed.source_fingerprint)}</code>
      </section>

      <section className="panel lab-mission-editor" aria-labelledby="lab-mission-heading">
        <header><div><span className="eyebrow">Isolated experiment fields</span><h2 id="lab-mission-heading">Dated mission</h2></div><span className="provenance-chip assumed">goal_mutation=false · retirement_mutation=false</span></header>
        <div className="lab-mission-fields">
          <label>Mission capital<input aria-label="Isolated mission capital" type="number" min="0" step="0.01" value={String(mission.target_amount)} onChange={(event) => updateMission("target_amount", event.target.value)} /></label>
          <label>Mission deadline<input aria-label="Isolated mission deadline" type="date" value={String(mission.target_date).slice(0, 10)} onChange={(event) => updateMission("target_date", event.target.value)} /></label>
          <label>Work-optional age<input aria-label="Isolated work-optional age" type="number" min="18" max="110" value={Number(mission.selected_age)} onChange={(event) => updateMission("selected_age", Number(event.target.value))} /></label>
          <label>Deterministic path<select aria-label="Isolated deterministic path" value={String(mission.path)} onChange={(event) => updateMission("path", event.target.value)}><option value="middle">Middle</option><option value="rough">Rough</option><option value="early_crash">Early crash</option></select></label>
          <button className="primary-button" disabled={busy} onClick={() => void recalculate()}>{busy ? "Recalculating…" : dirty ? "Recalculate changed draft" : "Recalculate draft"}</button>
        </div>
        <p className="lab-fingerprint">Experiment fingerprint <code>{fingerprintLabel(result.experiment_fingerprint)}</code>{dirty && <strong> · draft changed locally</strong>}</p>
      </section>

      {selected && projection && (
        <>
          <section className="panel lab-reverse-summary"><span className="eyebrow">Reverse-solved mission capital</span><h2>{currency(result.reverse_solver.mission_capital)} by {String(mission.target_date).slice(0, 10)}</h2><p>Selected result: {selected.status.replaceAll("_", " ")}. This is deterministic arithmetic, not a probability or recommendation.</p></section>
          <DriveCalculator projection={projection} path={selected} goals={projection.goals} startingPoint={projection.starting_point} />
        </>
      )}

      <details className="panel income-context-panel"><summary>{projection?.benchmarks.state_name ?? "State"} income context and formulas</summary>{projection?.benchmarks.available ? <div className="benchmark-list">{benchmarkRows.map(([key, row]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{currency(row.normalized_amount)}</strong></div>)}</div> : <div className="life-empty">Benchmark unavailable for this draft.</div>}<p className="benchmark-note">Income thresholds are context only. Compound returns, business value, borrowing capacity, and loan eligibility are not promotable.</p></details>

      <section className="panel lab-promotion-panel" aria-labelledby="lab-promotion-heading">
        <header><div><span className="eyebrow">Only explicit mutation path</span><h2 id="lab-promotion-heading">Promotion preview</h2></div></header>
        <div className="lab-promotion-controls">
          <label>Target surface<select aria-label="Promotion target surface" value={promotionSurface} onChange={(event) => { const surface = event.target.value as PromotionTarget; setPromotionSurface(surface); const field = surface === "goals" ? "goal_target" : "retirement_essential_monthly_spend"; setPromotionField(field); setPreview(null); }}><option value="goals">Goals</option><option value="retirement">Retirement</option></select></label>
          <label>Exact stored field<select aria-label="Promotion stored field" value={promotionField} onChange={(event) => { setPromotionField(event.target.value as PromotionField); setPreview(null); }}>{promotionFields.map(([field, label]) => <option key={field} value={field}>{label}</option>)}</select></label>
          <label>Exact promoted value<input aria-label="Promotion exact value" type="number" min="0" step="0.01" value={promotionValue} onChange={(event) => { setPromotionValue(event.target.value); setPreview(null); }} /></label>
          <button className="secondary-button" disabled={busy} onClick={() => void preparePreview()}>Generate zero-write preview</button>
        </div>
        {promotionError && <p className="lab-promotion-error" role="alert">{promotionError}</p>}
        {preview && <div className="lab-preview"><p><strong>Preview only · applied=false</strong> · target token {fingerprintLabel(preview.target_stale_write_token)}</p><table><thead><tr><th>Stored field</th><th>Before</th><th>After</th></tr></thead><tbody>{preview.changes.map((change) => <tr key={change.field}><td><code>{change.stored_target_field}</code></td><td>{currency(change.before.amount)}</td><td>{currency(change.after.amount)}</td></tr>)}</tbody></table><button ref={confirmTriggerRef} className="primary-button" onClick={() => setConfirmOpen(true)}>Review confirmation</button></div>}
        {applied && <p className="lab-applied" role="status">Applied to {applied.target_surface}. Observation: {applied.goal_observation?.status ?? "not required"}.</p>}
      </section>

      <section className="panel scenario-panel"><header className="life-section-heading"><div><span className="eyebrow">Reproducible evidence</span><h2>Experiment snapshots</h2></div></header><div className="scenario-save"><input aria-label="Experiment snapshot name" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} placeholder="Name this experiment" maxLength={120} /><button className="primary-button" disabled={busy} onClick={() => void saveExperiment()}>Save experiment</button></div><div className="scenario-list">{snapshots.filter((snapshot) => !snapshot.snapshot_context.startsWith("retirement_")).map((snapshot) => <button key={snapshot.id} onClick={() => void openLabSnapshot(snapshot.id).then(setOpenedSnapshot)}><span><strong>{snapshot.name}</strong><small>{snapshot.context_label} · {new Date(snapshot.created_at).toLocaleDateString()}</small></span><em>{snapshot.stale ? "Inputs changed" : "Open stored evidence"}</em></button>)}</div>{openedSnapshot && <article className="lab-stored-evidence"><h3>{openedSnapshot.name}</h3><p>{openedSnapshot.context_label}. The saved result, warnings, fingerprint, and {openedSnapshot.periods.length} monthly rows are rendered without a current-input rerun.</p><code>{openedSnapshot.source_fingerprint}</code></article>}</section>

      {confirmOpen && preview && <PromotionDialog preview={preview} busy={busy} error={promotionError} onConfirm={() => void confirmPromotion()} onCancel={() => { setConfirmOpen(false); setPromotionError(""); requestAnimationFrame(() => confirmTriggerRef.current?.focus()); }} />}
    </div>
  );
}
