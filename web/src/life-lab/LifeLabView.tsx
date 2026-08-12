import { useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";

import { FocusedDialog } from "../FocusedDialog";
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
import { DriveCalculator, wholeMonthIntervals } from "./DriveCalculator";
import { availableMissionOptions, missionSelectionContext } from "./mission-selection";
import "./life-lab.css";

function currency(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not solved";
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function missionOf(draft: Record<string, unknown>) {
  return draft.mission as Record<string, string | number>;
}

function recentFirst(snapshots: PlanningSnapshot[]) {
  return [...snapshots]
    .filter((snapshot) => !snapshot.snapshot_context.startsWith("retirement_"))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
}

function LabSnapshotEvidence({
  snapshots,
  openedSnapshot,
  onOpen,
}: {
  snapshots: PlanningSnapshot[];
  openedSnapshot: PlanningSnapshot | null;
  onOpen: (snapshot: PlanningSnapshot) => void;
}) {
  const [search, setSearch] = useState("");
  const [showOlder, setShowOlder] = useState(false);
  const normalized = search.trim().toLocaleLowerCase();
  const rows = recentFirst(snapshots).filter(
    (snapshot) => !normalized || `${snapshot.name} ${snapshot.context_label}`.toLocaleLowerCase().includes(normalized),
  );
  const visible = rows.slice(0, showOlder || normalized ? rows.length : 3);

  return (
    <details className="panel lab-snapshot-evidence evidence-disclosure">
      <summary>Experiment and legacy evidence</summary>
      <div className="snapshot-tools print-hidden">
        <label htmlFor="lab-snapshot-search">Search saved Lab evidence</label>
        <input id="lab-snapshot-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search names or context" />
      </div>
      <div className="scenario-list" data-default-visible-count="3">
        {rows.length === 0 ? <p>{normalized ? "No saved Lab evidence matches this search." : "No stored Lab evidence yet."}</p> : visible.map((snapshot) => (
          <button key={snapshot.id} onClick={() => void openLabSnapshot(snapshot.id).then(onOpen)}>
            <span>
              <strong>{snapshot.name}</strong>
              <small>{snapshot.context_label} · {new Date(snapshot.created_at).toLocaleDateString()}</small>
              <code className="print-only" aria-hidden="true">Fingerprint: {snapshot.source_fingerprint}</code>
            </span>
            <em>{snapshot.legacy ? "Legacy combined scenario" : snapshot.stale ? "Inputs changed" : "Open stored evidence"}</em>
          </button>
        ))}
      </div>
      {!showOlder && !normalized && rows.length > 3 && <button className="secondary-button show-older-button print-hidden" onClick={() => setShowOlder(true)}>Show older evidence</button>}
      {openedSnapshot && (
        <article className="lab-stored-evidence">
          <h3>{openedSnapshot.name}</h3>
          <p>Stored snapshot · original evidence with {openedSnapshot.periods.length} monthly rows.</p>
          <dl><div><dt>Context</dt><dd>{openedSnapshot.context_label}</dd></div><div><dt>Status</dt><dd>{openedSnapshot.status}</dd></div></dl>
          {openedSnapshot.warnings.length > 0 && <ul>{openedSnapshot.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
          <code>{openedSnapshot.source_fingerprint}</code>
        </article>
      )}
    </details>
  );
}

function MissionDialog({
  result,
  busy,
  error,
  returnFocusRef,
  onSave,
  onCancel,
}: {
  result: LifeLabExperimentResult;
  busy: boolean;
  error: string;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onSave: (draft: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [mission, setMission] = useState(() => ({ ...missionOf(result.draft) }));
  const update = (field: string, value: string | number) => setMission((current) => ({ ...current, [field]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const draft = structuredClone(result.draft);
    draft.mission = mission;
    onSave(draft);
  };
  return (
    <FocusedDialog title="Edit experiment" description="Change this experiment only, then recalculate its result." returnFocusRef={returnFocusRef} onClose={onCancel} className="lab-mission-dialog">
      <form className="lab-focused-form" onSubmit={submit} aria-describedby={error ? "lab-mission-error" : undefined}>
        <label>Mission capital<input data-autofocus aria-label="Mission capital" type="number" min="0" step="0.01" value={String(mission.target_amount)} onChange={(event) => update("target_amount", event.target.value)} /></label>
        <label>Mission deadline<input aria-label="Mission deadline" type="date" value={String(mission.target_date).slice(0, 10)} onChange={(event) => update("target_date", event.target.value)} /></label>
        <label>Work-optional age<input aria-label="Work-optional age" type="number" min="18" max="110" value={Number(mission.selected_age)} onChange={(event) => update("selected_age", Number(event.target.value))} /></label>
        <label>Deterministic path<select aria-label="Deterministic path" value={String(mission.path)} onChange={(event) => update("path", event.target.value)}><option value="middle">Middle</option><option value="rough">Rough</option><option value="early_crash">Early crash</option></select></label>
        {error && <p id="lab-mission-error" className="lab-promotion-error" role="alert">{error}</p>}
        <div className="focused-form-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? "Recalculating…" : "Save experiment"}</button></div>
      </form>
    </FocusedDialog>
  );
}

function PromotionWorkflowDialog({
  promotionSurface,
  promotionField,
  promotionValue,
  preview,
  busy,
  error,
  returnFocusRef,
  onSurfaceChange,
  onFieldChange,
  onValueChange,
  onPreview,
  onConfirm,
  onCancel,
}: {
  promotionSurface: PromotionTarget;
  promotionField: PromotionField;
  promotionValue: string;
  preview: LifeLabPromotionPreview | null;
  busy: boolean;
  error: string;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onSurfaceChange: (surface: PromotionTarget) => void;
  onFieldChange: (field: PromotionField) => void;
  onValueChange: (value: string) => void;
  onPreview: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const fields = promotionSurface === "goals"
    ? [["goal_target", "Goal target"], ["reserved_for_goal", "Reserved for goal"], ["protected_cash_floor", "Protected cash floor"]] as const
    : [["retirement_essential_monthly_spend", "Essential monthly spend"], ["retirement_flexible_monthly_spend", "Flexible monthly spend"]] as const;
  return (
    <FocusedDialog title="Promote a value" description="Preview one supported value before it crosses into Goals or Retirement." returnFocusRef={returnFocusRef} onClose={onCancel} tone="boundary" className="lab-promotion-dialog">
      <div className="lab-focused-form" aria-describedby={error ? "lab-promotion-workflow-error" : undefined}>
        <label>Target surface<select data-autofocus aria-label="Promotion target surface" value={promotionSurface} onChange={(event) => onSurfaceChange(event.target.value as PromotionTarget)}><option value="goals">Goals</option><option value="retirement">Retirement</option></select></label>
        <label>Stored value<select aria-label="Promotion stored field" value={promotionField} onChange={(event) => onFieldChange(event.target.value as PromotionField)}>{fields.map(([field, label]) => <option key={field} value={field}>{label}</option>)}</select></label>
        <label>New value<input aria-label="Promotion exact value" type="number" min="0" step="0.01" value={promotionValue} onChange={(event) => onValueChange(event.target.value)} /></label>
        {!preview && <button className="secondary-button preview-button" disabled={busy} onClick={onPreview}>{busy ? "Preparing…" : "Preview change"}</button>}
        {error && <p id="lab-promotion-workflow-error" className="lab-promotion-error" role="alert">{error}</p>}
        {preview && (
          <div className="lab-preview">
            <strong>Review the exact change</strong>
            <table><thead><tr><th>Stored field</th><th>Before</th><th>After</th></tr></thead><tbody>{preview.changes.map((change) => <tr key={change.field}><td><code>{change.stored_target_field}</code></td><td>{currency(change.before.amount)}</td><td>{currency(change.after.amount)}</td></tr>)}</tbody></table>
            <details><summary>Preview evidence</summary><code>{preview.target_stale_write_token}</code></details>
            <div className="boundary-confirmation"><p>This confirmation changes only the value shown above.</p><button className="primary-button" disabled={busy} onClick={onConfirm}>{busy ? "Confirming…" : "Confirm promotion"}</button></div>
          </div>
        )}
      </div>
    </FocusedDialog>
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
  const [missionOpen, setMissionOpen] = useState(false);
  const [promotionOpen, setPromotionOpen] = useState(false);
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [missionError, setMissionError] = useState("");
  const [promotionError, setPromotionError] = useState("");
  const [snapshotError, setSnapshotError] = useState("");
  const [message, setMessage] = useState("");
  const missionButtonRef = useRef<HTMLButtonElement>(null);
  const promotionButtonRef = useRef<HTMLButtonElement>(null);
  const snapshotButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    void Promise.all([loadLabSnapshots(), loadRetirementSnapshots(), loadPrimaryPromotionGoal(), loadRetirementPromotionProfile()])
      .then(([nextSnapshots, nextRetirementSnapshots, goalState, retirementProfile]) => {
        setSnapshots(recentFirst(nextSnapshots));
        setRetirementSnapshots(nextRetirementSnapshots);
        setCurrentGoal(goalState.goal);
        setRetirementTargetId(retirementProfile ? `retirement_profile_${retirementProfile.profile_id}` : null);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Lab evidence could not load."));
  }, []);

  const begin = async (kind: LabExperimentSeedKind) => {
    setBusy(true);
    setError("");
    setMessage("");
    setOpenedSnapshot(null);
    try {
      const nextSeed = await createLabExperiment({ seed_kind: kind, retirement_snapshot_id: kind === "retirement_result" ? Number(retirementSnapshotId) : null });
      const nextResult = await projectLabExperiment({ experiment_id: nextSeed.experiment_id, expected_experiment_fingerprint: nextSeed.experiment_fingerprint, draft: nextSeed.draft });
      setSeed(nextSeed);
      setResult(nextResult);
      setPromotionValue(String((nextResult.draft.promotable_values as Record<string, string>)?.goal_target ?? missionOf(nextResult.draft).target_amount ?? "0.00"));
      setPreview(null);
      setApplied(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The experiment could not start.");
    } finally {
      setBusy(false);
    }
  };

  const saveMission = async (draft: Record<string, unknown>) => {
    if (!result) return;
    setBusy(true);
    setMissionError("");
    try {
      const next = await projectLabExperiment({ experiment_id: result.experiment_id, expected_experiment_fingerprint: result.experiment_fingerprint, draft });
      setResult(next);
      setPreview(null);
      setApplied(null);
      setMissionOpen(false);
      setMessage("Experiment updated.");
    } catch (reason) {
      setMissionError(reason instanceof Error ? reason.message : "The experiment could not be recalculated.");
    } finally {
      setBusy(false);
    }
  };

  const saveExperiment = async () => {
    if (!result) return;
    setBusy(true);
    setSnapshotError("");
    try {
      const name = snapshotName.trim() || `${result.seed_kind.replace("_", " ")} experiment`;
      await saveLabSnapshot(name, result);
      setSnapshots(recentFirst(await loadLabSnapshots()));
      setSnapshotName("");
      setSnapshotOpen(false);
      setMessage("Experiment snapshot saved.");
    } catch (reason) {
      setSnapshotError(reason instanceof Error ? reason.message : "The experiment snapshot could not be saved.");
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
      const projected = await projectLabExperiment({ experiment_id: result.experiment_id, expected_experiment_fingerprint: result.experiment_fingerprint, draft });
      setResult(projected);
      const targetId = promotionSurface === "goals" ? currentGoal?.goal_program_id : retirementTargetId;
      if (!targetId) throw new Error(`A ${promotionSurface === "goals" ? "current Goal" : "Retirement profile"} is required for promotion.`);
      setPreview(await previewLabPromotion({ experiment_id: projected.experiment_id, expected_experiment_fingerprint: projected.experiment_fingerprint, draft: projected.draft, target_surface: promotionSurface, target_id: targetId, changes: [{ field: promotionField, after: promotionValue as ExactDecimalString }] }));
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
      setPromotionOpen(false);
      setPreview(null);
      setMessage(`Promotion confirmed for ${next.target_surface === "goals" ? "Goals" : "Retirement"}.`);
    } catch (reason) {
      setPromotionError(reason instanceof Error ? reason.message : "Promotion confirmation failed. The experiment is preserved.");
    } finally {
      setBusy(false);
    }
  };

  const projection = result?.projection as unknown as LifeProjection | undefined;
  const selected = result?.reverse_solver.selected_result as unknown as PathResult | undefined;
  const mission = result ? missionOf(result.draft) : null;
  const missionTargetDate = mission ? String(mission.target_date).slice(0, 10) : "";
  const missionMonths = projection && missionTargetDate
    ? wholeMonthIntervals(projection.as_of, missionTargetDate)
    : 0;
  const benchmarkRows = useMemo(() => Object.entries(projection?.benchmarks.thresholds ?? {}), [projection]);
  const routeSelectionContext = useMemo(() => {
    if (!result || !seed || !projection || !selected) return "";
    const options = availableMissionOptions(projection.goals, selected);
    return missionSelectionContext({
      experimentId: result.experiment_id,
      experimentFingerprint: result.experiment_fingerprint,
      seedKind: seed.seed_kind,
      projectionFingerprint: projection.source_fingerprint,
      path: selected,
      options,
    });
  }, [projection, result, seed, selected]);

  if (!seed || !result || !mission) {
    return (
      <div className="view-stack life-lab isolated-lab" data-copy-budget="lab-seed-chooser">
        <header className="page-heading life-hero"><div><span className="eyebrow">Experimental workspace</span><h1 data-prose>Life Lab</h1><p data-prose>Reverse-solve an extreme or alternative path.</p></div><button className="secondary-button print-hidden" onClick={() => window.print()}>Print evidence</button></header>
        <p className="print-only print-evidence-header" aria-hidden="true">Life Lab seed evidence · {new Date().toLocaleDateString()}</p>
        {error && <div className="error-banner" role="alert">{error}</div>}
        <section className="panel lab-seed-chooser" aria-labelledby="lab-seed-heading">
          <span className="eyebrow">Choose a source</span>
          <h2 id="lab-seed-heading" data-prose>Start an experiment</h2>
          <p data-prose>Each seed is copied once into an isolated experiment.</p>
          <div className="lab-seed-options">
            <button disabled={busy} onClick={() => void begin("blank")}><strong>Start blank</strong><span>Begin with explicit defaults.</span></button>
            <button disabled={busy || !currentGoal} onClick={() => void begin("current_goal")}><strong>Start from current goal</strong><span>{currentGoal ? `Copy ${currentGoal.name} once.` : "No primary Goal is available."}</span></button>
            <div className="lab-retirement-seed"><label>Retirement result<select aria-label="Retirement result seed" value={retirementSnapshotId} onChange={(event) => setRetirementSnapshotId(event.target.value)}><option value="">Choose a saved run</option>{retirementSnapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>{snapshot.name} · age {snapshot.target_age}</option>)}</select></label><button disabled={busy || !retirementSnapshotId} onClick={() => void begin("retirement_result")}><strong>Start from retirement result</strong><span>Copy one saved result.</span></button></div>
          </div>
        </section>
        <LabSnapshotEvidence snapshots={snapshots} openedSnapshot={openedSnapshot} onOpen={setOpenedSnapshot} />
      </div>
    );
  }

  return (
    <div className="view-stack life-lab isolated-lab" data-copy-budget="lab-active-summary">
      <header className="page-heading life-hero"><div><span className="eyebrow">Experimental workspace</span><h1 data-prose>Life Lab</h1><p data-prose>Reverse-solve one alternative path.</p></div><div className="surface-actions print-hidden"><button className="secondary-button" onClick={() => { setSeed(null); setResult(null); setPreview(null); }}>Choose another seed</button><button className="secondary-button" onClick={() => window.print()}>Print evidence</button></div></header>
      <p className="print-only print-evidence-header" aria-hidden="true">Life Lab evidence · {projection?.as_of ?? "Date unavailable"}</p>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {message && <div className="life-message" role="status">{message}</div>}

      <section className="panel lab-source-evidence" aria-labelledby="lab-source-heading">
        <div><span className="lab-isolation-status" data-prose>Isolated experiment</span><h2 id="lab-source-heading">{seed.source_label ?? "Blank experiment"}</h2></div>
        <details><summary>Source evidence</summary><p>{seed.seed_kind === "blank" ? "No Goal or Retirement money was copied." : "The source was copied once; later edits do not alter this experiment."}</p><dl><div><dt>Source fingerprint</dt><dd><code>{seed.source_fingerprint ?? "No copied source"}</code></dd></div><div><dt>Experiment fingerprint</dt><dd><code>{result.experiment_fingerprint}</code></dd></div></dl></details>
      </section>

      {selected && projection && (
        <>
          <section className="panel lab-mission-summary lab-primary-result" aria-labelledby="lab-mission-heading">
            <header><div><span className="eyebrow">Experiment result</span><h2 id="lab-mission-heading">{currency(mission.target_amount)} by {missionTargetDate}</h2><p data-prose>{selected.status.replaceAll("_", " ")}. Deterministic arithmetic, not a probability or recommendation.</p>{Number(mission.target_amount) > 0 && missionMonths > 0 && <p className="lab-summary-convention">Life Lab route convention · {missionMonths} whole-month intervals</p>}</div><button ref={missionButtonRef} className="secondary-button print-hidden" onClick={() => setMissionOpen(true)}>Edit experiment</button></header>
            <dl><div><dt>Work-optional age</dt><dd>{mission.selected_age}</dd></div><div><dt>Path</dt><dd>{String(mission.path).replaceAll("_", " ")}</dd></div></dl>
          </section>
          <details className="panel lab-paths evidence-disclosure"><summary>Route formulas and time convention</summary><DriveCalculator projection={projection} path={selected} goals={projection.goals} startingPoint={projection.starting_point} seedKind={seed.seed_kind} seededGoalLabel={seed.source_label} selectionContext={routeSelectionContext} /></details>
        </>
      )}

      <details className="panel income-context-panel evidence-disclosure"><summary>{projection?.benchmarks.state_name ?? "State"} income context and formulas</summary>{projection?.benchmarks.available ? <div className="benchmark-list">{benchmarkRows.map(([key, row]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{currency(row.normalized_amount)}</strong></div>)}</div> : <div className="life-empty">Benchmark unavailable for this experiment.</div>}<p className="benchmark-note">Income thresholds are context only. Speculative outputs remain Lab-only.</p></details>

      <div className="lab-primary-actions print-hidden">
        <button ref={promotionButtonRef} className="primary-button boundary-action" onClick={() => { setPromotionOpen(true); setPromotionError(""); }}>Promote a value</button>
        <button ref={snapshotButtonRef} className="secondary-button" onClick={() => setSnapshotOpen(true)}>Save experiment</button>
      </div>
      {applied && <p className="lab-applied" role="status">Promotion confirmed. Observation: {applied.goal_observation?.status ?? "not required"}.</p>}
      <LabSnapshotEvidence snapshots={snapshots} openedSnapshot={openedSnapshot} onOpen={setOpenedSnapshot} />

      {missionOpen && <MissionDialog result={result} busy={busy} error={missionError} returnFocusRef={missionButtonRef} onSave={(draft) => void saveMission(draft)} onCancel={() => { setMissionOpen(false); setMissionError(""); }} />}
      {promotionOpen && <PromotionWorkflowDialog promotionSurface={promotionSurface} promotionField={promotionField} promotionValue={promotionValue} preview={preview} busy={busy} error={promotionError} returnFocusRef={promotionButtonRef} onSurfaceChange={(surface) => { setPromotionSurface(surface); setPromotionField(surface === "goals" ? "goal_target" : "retirement_essential_monthly_spend"); setPreview(null); }} onFieldChange={(field) => { setPromotionField(field); setPreview(null); }} onValueChange={(value) => { setPromotionValue(value); setPreview(null); }} onPreview={() => void preparePreview()} onConfirm={() => void confirmPromotion()} onCancel={() => { setPromotionOpen(false); setPromotionError(""); setPreview(null); }} />}
      {snapshotOpen && <FocusedDialog title="Save experiment" description="Name this result for later evidence review." returnFocusRef={snapshotButtonRef} onClose={() => { setSnapshotOpen(false); setSnapshotError(""); }} className="snapshot-dialog"><form onSubmit={(event) => { event.preventDefault(); void saveExperiment(); }} aria-describedby={snapshotError ? "lab-snapshot-error" : undefined}><label htmlFor="lab-snapshot-name">Snapshot name</label><input data-autofocus id="lab-snapshot-name" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} placeholder={`${result.seed_kind.replace("_", " ")} experiment`} maxLength={120} />{snapshotError && <p id="lab-snapshot-error" className="lab-promotion-error" role="alert">{snapshotError}</p>}<div className="focused-form-actions"><button type="button" className="secondary-button" onClick={() => setSnapshotOpen(false)}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save experiment"}</button></div></form></FocusedDialog>}
    </div>
  );
}
