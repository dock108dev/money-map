import { useCallback, useEffect, useRef, useState } from "react";

import { FocusedDialog } from "../FocusedDialog";
import type { LifeProjection, PathResult } from "../life-lab/life-lab-types";
import type { GoalProgramView, RetirementPath, RetirementProfileEditRequest, RetirementProfileView, RetirementProjectionResult } from "../v2-contracts";
import type { LifeStartingPoint } from "../life-lab/life-lab-types";
import { ProjectionChart } from "./ProjectionChart";
import { ProjectionTable } from "./ProjectionTable";
import { RetirementProfileForm } from "./RetirementProfileForm";
import {
  loadRetirementOperationalGoals,
  loadRetirementProfile,
  loadRetirementSnapshots,
  loadRetirementStartingPoint,
  openRetirementSnapshot,
  projectRetirement,
  saveRetirementProfile,
  saveRetirementSnapshot,
  type PlanningSnapshot,
} from "./api";
import "./retirement.css";

function currency(value: string | null | undefined) {
  if (value === null || value === undefined) return "Unavailable";
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function verdict(status: RetirementProjectionResult["bridge_verdict"]) {
  if (status === "works") return { title: "Works", detail: "Essential and flexible retirement life stays funded.", next: "Save this run if you want a durable checkpoint.", tone: "works" };
  if (status === "works_essentials_only") return { title: "Essentials hold", detail: "Flexible retirement spending runs short.", next: "Test another age, path, or assumption.", tone: "essentials" };
  if (status === "insufficient_accessible_bridge") return { title: "Bridge breaks", detail: "Accessible money runs out before retirement assets can carry the plan.", next: "Test another age, path, or assumption.", tone: "bridge" };
  return { title: "Shortfall", detail: "Required retirement spending cannot remain funded.", next: "Test another age, path, or assumption.", tone: "shortfall" };
}

function recentFirst(snapshots: PlanningSnapshot[]) {
  return [...snapshots].sort((left, right) => right.created_at.localeCompare(left.created_at));
}

export default function RetirementView() {
  const [profile, setProfile] = useState<RetirementProfileView | null>(null);
  const [startingPoint, setStartingPoint] = useState<LifeStartingPoint | null>(null);
  const [goals, setGoals] = useState<GoalProgramView[]>([]);
  const [run, setRun] = useState<RetirementProjectionResult | null>(null);
  const [snapshots, setSnapshots] = useState<PlanningSnapshot[]>([]);
  const [openedSnapshot, setOpenedSnapshot] = useState<PlanningSnapshot | null>(null);
  const [selectedAge, setSelectedAge] = useState(65);
  const [selectedPath, setSelectedPath] = useState<RetirementPath>("middle");
  const [goalId, setGoalId] = useState("");
  const [display, setDisplay] = useState<"chart" | "table">("chart");
  const [editing, setEditing] = useState(false);
  const [snapshotDialogOpen, setSnapshotDialogOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState("");
  const [snapshotError, setSnapshotError] = useState("");
  const [snapshotSearch, setSnapshotSearch] = useState("");
  const [showOlderSnapshots, setShowOlderSnapshots] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [editError, setEditError] = useState("");
  const [message, setMessage] = useState("");
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const snapshotButtonRef = useRef<HTMLButtonElement>(null);

  const calculate = useCallback(async (age: number, path: RetirementPath, selectedGoal = "") => {
    const next = await projectRetirement({
      work_optional_age: age,
      path,
      goal_program_id: selectedGoal || null,
    });
    setRun(next);
    setOpenedSnapshot(null);
    return next;
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [nextProfile, nextStart, nextGoals, nextSnapshots] = await Promise.all([
        loadRetirementProfile(),
        loadRetirementStartingPoint(),
        loadRetirementOperationalGoals(),
        loadRetirementSnapshots(),
      ]);
      setProfile(nextProfile);
      setStartingPoint(nextStart);
      setGoals(nextGoals);
      setSnapshots(recentFirst(nextSnapshots));
      if (nextProfile) {
        const age = nextProfile.work_optional_ages[0];
        setSelectedAge(age);
        await calculate(age, "middle");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retirement could not load.");
    } finally {
      setBusy(false);
    }
  }, [calculate]);

  useEffect(() => { void load(); }, [load]);

  const rerun = async () => {
    setBusy(true);
    setError("");
    try {
      await calculate(selectedAge, selectedPath, goalId);
      setMessage("Projection updated.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The Retirement run could not be calculated.");
    } finally {
      setBusy(false);
    }
  };

  const saveProfile = async (payload: RetirementProfileEditRequest) => {
    setBusy(true);
    setEditError("");
    try {
      const next = await saveRetirementProfile(payload);
      setProfile(next);
      setEditing(false);
      setSelectedAge(next.work_optional_ages[0]);
      await calculate(next.work_optional_ages[0], selectedPath, goalId);
      setMessage("Retirement assumptions updated.");
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : "Retirement assumptions could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const saveSnapshot = async () => {
    if (!run) return;
    setBusy(true);
    setSnapshotError("");
    try {
      const name = snapshotName.trim() || `Age ${run.run_selection.work_optional_age} · ${run.run_selection.path.replace("_", " ")}`;
      await saveRetirementSnapshot(name, run);
      setSnapshots(recentFirst(await loadRetirementSnapshots()));
      setSnapshotName("");
      setSnapshotDialogOpen(false);
      setMessage("Retirement snapshot saved.");
    } catch (reason) {
      setSnapshotError(reason instanceof Error ? reason.message : "The snapshot could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  if (busy && !profile && !error) return <div className="retirement-loading"><span className="loading-mark">M</span><p>Opening Retirement…</p></div>;
  if (!profile) return <div className="notice critical-notice"><span className="notice-mark">!</span><div><h1>Retirement is unavailable.</h1><p>{error || "The durable Retirement profile has not been created."}</p></div></div>;

  const projection = run?.projection as unknown as LifeProjection | undefined;
  const target = projection?.results.find((row) => row.target_age === selectedAge);
  const path = target?.paths.find((row) => row.path_key === selectedPath) as PathResult | undefined;
  const status = run ? verdict(run.bridge_verdict) : null;
  const search = snapshotSearch.trim().toLocaleLowerCase();
  const filteredSnapshots = snapshots.filter(
    (snapshot) => !search || `${snapshot.name} ${snapshot.context_label}`.toLocaleLowerCase().includes(search),
  );
  const visibleSnapshots = filteredSnapshots.slice(0, showOlderSnapshots || search ? filteredSnapshots.length : 3);

  return (
    <div className="view-stack retirement-view" data-copy-budget="retirement-before-chart">
      <header className="page-heading retirement-heading">
        <div><span className="eyebrow">Solvency planning</span><h1 data-prose>Retirement</h1><p data-prose>Test when work can become optional.</p></div>
        <div className="surface-actions print-hidden">
          <button ref={editButtonRef} className="secondary-button" onClick={() => setEditing(true)}>Edit assumptions</button>
          <button className="secondary-button" onClick={() => window.print()}>Print evidence</button>
        </div>
      </header>
      <p className="print-only print-evidence-header" aria-hidden="true">Retirement evidence · {projection?.as_of ?? "Date unavailable"}</p>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {message && <div className="retirement-message" role="status">{message}</div>}

      <section className="panel retirement-control-panel" aria-labelledby="retirement-run-heading">
        <h2 id="retirement-run-heading" className="sr-only">Retirement run</h2>
        <div className="retirement-controls print-hidden">
          <label>Work becomes optional at<select aria-label="Work-optional age" value={selectedAge} onChange={(event) => setSelectedAge(Number(event.target.value))}>{profile.work_optional_ages.map((age) => <option key={age} value={age}>Age {age}</option>)}</select></label>
          <label>Deterministic path<select aria-label="Retirement path" value={selectedPath} onChange={(event) => setSelectedPath(event.target.value as RetirementPath)}><option value="middle">Middle path</option><option value="rough">Rough path</option><option value="early_crash">Early-crash path</option></select></label>
          <label>Goal snapshot<select aria-label="Operational goal inclusion" value={goalId} onChange={(event) => setGoalId(event.target.value)}><option value="">Do not include a goal</option>{goals.map((goal) => <option key={goal.goal_program_id} value={goal.goal_program_id}>Include {goal.name}</option>)}</select></label>
          <button className="primary-button" disabled={busy} onClick={() => void rerun()}>{busy ? "Running…" : "Run projection"}</button>
        </div>
        {run && status && (
          <div className={`retirement-verdict ${status.tone}`}>
            <div>
              <span className="eyebrow">Age {run.run_selection.work_optional_age} · {run.run_selection.path.replace("_", " ")}</span>
              <h2 data-prose>{status.title}</h2>
              <p data-prose>{status.detail}</p>
              <strong className="retirement-goal-state" data-prose>{run.run_selection.included_goal ? `${run.run_selection.included_goal.name} · immutable goal snapshot` : "Operational goals excluded"}</strong>
              <p className="retirement-next" data-prose><strong>Next:</strong> {status.next}</p>
              <code className="print-only" aria-hidden="true">Run fingerprint: {run.run_fingerprint}</code>
            </div>
            <dl>
              <div><dt>Accessible at work stop</dt><dd>{currency(run.accessible_assets_at_work_stop)}</dd></div>
              <div><dt>Retirement at work stop</dt><dd>{currency(run.retirement_assets_at_work_stop)}</dd></div>
              <div><dt>End spendable assets</dt><dd>{currency(run.end_spendable_assets)}</dd></div>
              <div><dt>Required-money runway</dt><dd>{run.required_money_runway_months === null ? "Through plan" : `${run.required_money_runway_months} month${run.required_money_runway_months === 1 ? "" : "s"}`}</dd></div>
            </dl>
          </div>
        )}
      </section>

      {run && target && path && (
        <section className="panel retirement-projection-panel">
          <header><div><span className="eyebrow">Today’s dollars</span><h2>Lifetime projection</h2></div><div className="retirement-display-toggle print-hidden" aria-label="Projection display"><button className={display === "chart" ? "active" : ""} onClick={() => setDisplay("chart")}>Chart</button><button className={display === "table" ? "active" : ""} onClick={() => setDisplay("table")}>Table</button></div></header>
          {display === "chart" ? <ProjectionChart paths={target.paths} /> : <ProjectionTable path={path} />}
          <div className="print-only" aria-hidden="true"><ProjectionTable path={path} /></div>
        </section>
      )}

      <div className="retirement-evidence-actions print-hidden">
        <button ref={snapshotButtonRef} className="secondary-button" disabled={!run} onClick={() => setSnapshotDialogOpen(true)}>Save snapshot</button>
      </div>

      <details className="panel retirement-assumptions evidence-disclosure">
        <summary>Assumptions and starting evidence</summary>
        <div className="retirement-assumption-grid">
          <p><strong>Essential life</strong>{currency(profile.retirement_essential_monthly_spend.amount)}/month</p>
          <p><strong>Flexible life</strong>{currency(profile.retirement_flexible_monthly_spend.amount)}/month</p>
          <p><strong>Protected cash floor</strong>{currency(profile.protected_cash_floor.amount)}</p>
          <p><strong>Pretax haircut</strong>{profile.retirement_tax_haircut_pct}%</p>
          <p><strong>Observed accessible</strong>{currency(startingPoint?.accessible_total)}</p>
          <p><strong>Observed retirement</strong>{currency(startingPoint?.pretax_retirement)}</p>
        </div>
        {run && run.warnings.length > 0 && <div className="critical-warning"><strong>Run warnings</strong><ul>{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      </details>

      <details className="panel retirement-snapshots evidence-disclosure">
        <summary>Retirement snapshot evidence</summary>
        <div className="snapshot-tools print-hidden">
          <label htmlFor="retirement-snapshot-search">Search saved Retirement evidence</label>
          <input id="retirement-snapshot-search" type="search" value={snapshotSearch} onChange={(event) => setSnapshotSearch(event.target.value)} placeholder="Search names or context" />
        </div>
        <div className="retirement-snapshot-list" data-default-visible-count="3">
          {filteredSnapshots.length === 0 ? <p>{search ? "No saved Retirement evidence matches this search." : "No Retirement snapshots yet."}</p> : visibleSnapshots.map((snapshot) => (
            <button key={snapshot.id} onClick={() => void openRetirementSnapshot(snapshot.id).then(setOpenedSnapshot)}>
              <span><strong>{snapshot.name}</strong><small>{snapshot.context_label} · age {snapshot.target_age} · {snapshot.path_key.replace("_", " ")}</small><code className="print-only" aria-hidden="true">Fingerprint: {snapshot.source_fingerprint}</code></span>
              <em>{snapshot.stale ? "Source changed · open stored evidence" : "Open stored evidence"}</em>
            </button>
          ))}
        </div>
        {!showOlderSnapshots && !search && filteredSnapshots.length > 3 && <button className="secondary-button show-older-button print-hidden" onClick={() => setShowOlderSnapshots(true)}>Show older evidence</button>}
        {openedSnapshot && (
          <article className="retirement-stored-evidence">
            <h3>{openedSnapshot.name}</h3>
            <p>Stored snapshot · original result with {openedSnapshot.periods.length} monthly rows.</p>
            <dl><div><dt>Context</dt><dd>{openedSnapshot.context_label}</dd></div><div><dt>Status</dt><dd>{openedSnapshot.status}</dd></div></dl>
            {openedSnapshot.warnings.length > 0 && <ul>{openedSnapshot.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
            <code>{openedSnapshot.source_fingerprint}</code>
          </article>
        )}
      </details>

      {editing && <RetirementProfileForm profile={profile} busy={busy} error={editError} returnFocusRef={editButtonRef} onSave={(payload) => void saveProfile(payload)} onCancel={() => { setEditing(false); setEditError(""); }} />}
      {snapshotDialogOpen && run && (
        <FocusedDialog title="Save Retirement snapshot" description="Name this immutable run for later evidence review." returnFocusRef={snapshotButtonRef} onClose={() => { setSnapshotDialogOpen(false); setSnapshotError(""); }} className="snapshot-dialog">
          <form onSubmit={(event) => { event.preventDefault(); void saveSnapshot(); }} aria-describedby={snapshotError ? "retirement-snapshot-error" : undefined}>
            <label htmlFor="retirement-snapshot-name">Snapshot name</label>
            <input data-autofocus id="retirement-snapshot-name" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} placeholder={`Age ${run.run_selection.work_optional_age} · ${run.run_selection.path.replace("_", " ")}`} maxLength={120} />
            {snapshotError && <p id="retirement-snapshot-error" className="retirement-form-error" role="alert">{snapshotError}</p>}
            <div className="focused-form-actions"><button type="button" className="secondary-button" onClick={() => setSnapshotDialogOpen(false)}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save snapshot"}</button></div>
          </form>
        </FocusedDialog>
      )}
    </div>
  );
}
