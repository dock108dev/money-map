import { useCallback, useEffect, useState } from "react";

import type { LifeProjection, PathResult } from "../life-lab/life-lab-types";
import type {
  RetirementPath,
  RetirementProfileEditRequest,
  RetirementProfileView,
  RetirementProjectionResult,
} from "../v2-contracts";
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
import type { GoalProgramView } from "../v2-contracts";
import type { LifeStartingPoint } from "../life-lab/life-lab-types";
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
  if (status === "works") return { title: "Works", detail: "Essential and flexible retirement life stays funded.", tone: "works" };
  if (status === "works_essentials_only") return { title: "Essentials hold", detail: "Flexible retirement spending runs short.", tone: "essentials" };
  if (status === "insufficient_accessible_bridge") return { title: "Bridge breaks", detail: "Retirement assets remain, but accessible money runs out first.", tone: "bridge" };
  return { title: "Shortfall", detail: "Required retirement spending cannot remain funded through the plan.", tone: "shortfall" };
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
  const [snapshotName, setSnapshotName] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [editError, setEditError] = useState("");
  const [message, setMessage] = useState("");

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
      setSnapshots(nextSnapshots);
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
      setMessage(goalId ? "Named operational-goal snapshot included in this run." : "Operational goals excluded.");
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
      setMessage("Retirement assumptions updated. Goals and Lab drafts were not changed.");
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : "Retirement assumptions could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const saveSnapshot = async () => {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      const name = snapshotName.trim() || `Age ${run.run_selection.work_optional_age} · ${run.run_selection.path.replace("_", " ")}`;
      await saveRetirementSnapshot(name, run);
      setSnapshots(await loadRetirementSnapshots());
      setSnapshotName("");
      setMessage("Reproducible Retirement snapshot saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The snapshot could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  if (busy && !profile && !error) return <div className="retirement-loading"><span className="loading-mark">M</span><p>Opening Retirement…</p></div>;
  if (!profile) return <div className="notice"><span className="notice-mark">!</span><div><h1>Retirement is unavailable.</h1><p>{error || "The durable Retirement profile has not been created."}</p></div></div>;

  const projection = run?.projection as unknown as LifeProjection | undefined;
  const target = projection?.results.find((row) => row.target_age === selectedAge);
  const path = target?.paths.find((row) => row.path_key === selectedPath) as PathResult | undefined;
  const status = run ? verdict(run.bridge_verdict) : null;

  return (
    <div className="view-stack retirement-view">
      <header className="page-heading retirement-heading">
        <div><span className="eyebrow">Occasional solvency planning</span><h1>Retirement</h1><p>See when work can become optional under explicit assumptions.</p></div>
        <button className="secondary-button" onClick={() => setEditing(true)}>Edit assumptions</button>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {message && <div className="retirement-message" role="status">{message}</div>}

      <section className="panel retirement-control-panel" aria-labelledby="retirement-run-heading">
        <h2 id="retirement-run-heading" className="sr-only">Retirement run</h2>
        <div className="retirement-controls">
          <label>Work becomes optional at<select aria-label="Work-optional age" value={selectedAge} onChange={(event) => setSelectedAge(Number(event.target.value))}>{profile.work_optional_ages.map((age) => <option key={age} value={age}>Age {age}</option>)}</select></label>
          <label>Deterministic path<select aria-label="Retirement path" value={selectedPath} onChange={(event) => setSelectedPath(event.target.value as RetirementPath)}><option value="middle">Middle path</option><option value="rough">Rough path</option><option value="early_crash">Early-crash path</option></select></label>
          <label>Operational-goal treatment<select aria-label="Operational goal inclusion" value={goalId} onChange={(event) => setGoalId(event.target.value)}><option value="">Operational goals excluded</option>{goals.map((goal) => <option key={goal.goal_program_id} value={goal.goal_program_id}>Include {goal.name} snapshot</option>)}</select></label>
          <button className="primary-button" disabled={busy} onClick={() => void rerun()}>{busy ? "Running…" : "Run projection"}</button>
        </div>
        {run && status && (
          <div className={`retirement-verdict ${status.tone}`}>
            <div><span className="eyebrow">Age {run.run_selection.work_optional_age} · {run.run_selection.path.replace("_", " ")}</span><h2>{status.title}</h2><p>{status.detail}</p><strong className="retirement-goal-state">{run.run_selection.included_goal ? `${run.run_selection.included_goal.name} · immutable goal snapshot` : "Operational goals excluded"}</strong></div>
            <dl>
              <div><dt>Accessible assets at work stop</dt><dd>{currency(run.accessible_assets_at_work_stop)}</dd></div>
              <div><dt>Retirement assets at work stop</dt><dd>{currency(run.retirement_assets_at_work_stop)}</dd></div>
              <div><dt>End spendable assets</dt><dd>{currency(run.end_spendable_assets)}</dd></div>
              <div><dt>Required-money runway</dt><dd>{run.required_money_runway_months === null ? "Through plan" : `${run.required_money_runway_months} months`}</dd></div>
            </dl>
          </div>
        )}
      </section>

      {run && target && path && (
        <section className="panel retirement-projection-panel">
          <header><div><span className="eyebrow">Today’s dollars</span><h2>Lifetime projection</h2></div><div className="retirement-display-toggle" aria-label="Projection display"><button className={display === "chart" ? "active" : ""} onClick={() => setDisplay("chart")}>Chart</button><button className={display === "table" ? "active" : ""} onClick={() => setDisplay("table")}>Table</button></div></header>
          {display === "chart" ? <ProjectionChart paths={target.paths} /> : <ProjectionTable path={path} />}
        </section>
      )}

      <details className="panel retirement-assumptions">
        <summary>Assumptions and starting-point evidence</summary>
        <div className="retirement-assumption-grid">
          <p><strong>Essential life</strong>{currency(profile.retirement_essential_monthly_spend.amount)}/month</p>
          <p><strong>Flexible life</strong>{currency(profile.retirement_flexible_monthly_spend.amount)}/month</p>
          <p><strong>Protected cash floor</strong>{currency(profile.protected_cash_floor.amount)}</p>
          <p><strong>Pretax haircut</strong>{profile.retirement_tax_haircut_pct}%</p>
          <p><strong>Observed accessible</strong>{currency(startingPoint?.accessible_total)}</p>
          <p><strong>Observed retirement</strong>{currency(startingPoint?.pretax_retirement)}</p>
        </div>
        {run && <ul>{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
      </details>

      <section className="panel retirement-snapshots">
        <header><div><span className="eyebrow">Stored evidence</span><h2>Reproducible snapshots</h2></div></header>
        <div className="retirement-snapshot-save"><input aria-label="Retirement snapshot name" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} placeholder="Name this run" maxLength={120} /><button className="primary-button" disabled={!run || busy} onClick={() => void saveSnapshot()}>Save snapshot</button></div>
        <div className="retirement-snapshot-list">{snapshots.length === 0 ? <p>No Retirement snapshots yet.</p> : snapshots.map((snapshot) => <button key={snapshot.id} onClick={() => void openRetirementSnapshot(snapshot.id).then(setOpenedSnapshot)}><span><strong>{snapshot.name}</strong><small>{snapshot.context_label} · age {snapshot.target_age} · {snapshot.path_key.replace("_", " ")}</small></span><em>Open stored evidence</em></button>)}</div>
        {openedSnapshot && <article className="retirement-stored-evidence"><h3>{openedSnapshot.name}</h3><p>{openedSnapshot.context_label}. This view uses the saved result and {openedSnapshot.periods.length} saved monthly rows; it was not rerun.</p><code>{openedSnapshot.source_fingerprint}</code></article>}
      </section>

      {editing && <RetirementProfileForm profile={profile} busy={busy} error={editError} onSave={(payload) => void saveProfile(payload)} onCancel={() => { setEditing(false); setEditError(""); }} />}
    </div>
  );
}
