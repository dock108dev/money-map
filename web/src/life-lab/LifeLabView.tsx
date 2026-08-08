import { useCallback, useEffect, useMemo, useState } from "react";

import {
  addLifeGoal,
  deleteLifeGoal,
  loadLifeGoals,
  loadLifeProfile,
  loadLifeScenarios,
  loadLifeStartingPoint,
  projectLifePlan,
  saveLifeGoal,
  saveLifeProfile,
  saveLifeScenario,
} from "./api";
import { DriveCalculator } from "./DriveCalculator";
import { GoalEditor } from "./GoalEditor";
import { LifeProfileForm } from "./LifeProfileForm";
import type {
  LifeGoal,
  LifeGoalInput,
  LifePlanProfile,
  LifePlanProfileInput,
  LifeProjection,
  LifeStartingPoint,
  PathResult,
  SavedLifeScenario,
} from "./life-lab-types";
import { ProjectionChart } from "./ProjectionChart";
import { ProjectionTable } from "./ProjectionTable";
import "./life-lab.css";

function currency(value: string | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "Not solved";
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  });
}

function statusCopy(path: PathResult) {
  if (path.status === "works") return { label: "Works", detail: "Essential and flexible life stays funded.", tone: "works" };
  if (path.status === "works_essentials_only") return { label: "Essentials hold", detail: "Optional spending or goals run short.", tone: "essentials" };
  if (path.status === "insufficient_accessible_bridge") return { label: "Bridge breaks", detail: "Retirement money exists, but accessible money runs out first.", tone: "bridge" };
  return { label: "Shortfall", detail: "Required spending cannot remain funded through the plan.", tone: "shortfall" };
}

function monthDistance(start: string, end: string | null) {
  if (!end) return null;
  const from = new Date(`${start}T12:00:00`);
  const to = new Date(`${end}T12:00:00`);
  return Math.max(0, (to.getFullYear() - from.getFullYear()) * 12 + to.getMonth() - from.getMonth());
}

function LoadingPlan() {
  return (
    <div className="life-loading panel">
      <span className="loading-mark">M</span>
      <div><strong>Building the life paths…</strong><small>Balances stay on this device.</small></div>
    </div>
  );
}

export default function LifeLabView() {
  const [profile, setProfile] = useState<LifePlanProfile | null>(null);
  const [startingPoint, setStartingPoint] = useState<LifeStartingPoint | null>(null);
  const [goals, setGoals] = useState<LifeGoal[]>([]);
  const [scenarios, setScenarios] = useState<SavedLifeScenario[]>([]);
  const [projection, setProjection] = useState<LifeProjection | null>(null);
  const [selectedAge, setSelectedAge] = useState<number | null>(null);
  const [selectedPath, setSelectedPath] = useState<PathResult["path_key"]>("middle");
  const [display, setDisplay] = useState<"chart" | "table">("chart");
  const [editingProfile, setEditingProfile] = useState(false);
  const [scenarioName, setScenarioName] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const calculate = useCallback(async (ages?: number[]) => {
    const next = await projectLifePlan(ages);
    setProjection(next);
    setProfile(next.profile);
    setGoals(next.goals);
    setSelectedAge((current) => current && next.results.some((row) => row.target_age === current) ? current : next.results[0]?.target_age ?? null);
    return next;
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [nextProfile, nextStart, nextGoals, nextScenarios] = await Promise.all([
        loadLifeProfile(),
        loadLifeStartingPoint(),
        loadLifeGoals(),
        loadLifeScenarios(),
      ]);
      setProfile(nextProfile);
      setStartingPoint(nextStart);
      setGoals(nextGoals);
      setScenarios(nextScenarios);
      if (nextProfile) await calculate(nextProfile.target_ages);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Life Lab could not load.");
    } finally {
      setBusy(false);
    }
  }, [calculate]);

  useEffect(() => { void load(); }, [load]);

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      const [nextGoals, nextScenarios] = await Promise.all([loadLifeGoals(), loadLifeScenarios()]);
      setGoals(nextGoals);
      setScenarios(nextScenarios);
      if (profile) await calculate(profile.target_ages);
      setMessage(success);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The plan could not be updated.");
    } finally {
      setBusy(false);
    }
  };

  const saveProfile = async (payload: LifePlanProfileInput) => {
    setBusy(true);
    setError("");
    try {
      const next = await saveLifeProfile(payload);
      setProfile(next);
      setEditingProfile(false);
      await calculate(next.target_ages);
      setMessage("Plan assumptions updated.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The plan could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const target = projection?.results.find((row) => row.target_age === selectedAge) ?? null;
  const path = target?.paths.find((row) => row.path_key === selectedPath) ?? null;
  const pathStatus = path ? statusCopy(path) : null;
  const runway = path ? monthDistance(path.work_stop_month, path.first_shortfall_month) : null;
  const impacts = selectedAge && projection ? projection.goal_impacts[String(selectedAge)] ?? [] : [];
  const benchmarkRows = useMemo(() => {
    const thresholds = projection?.benchmarks.thresholds ?? {};
    return [
      ["top_50", "Top 50% threshold"],
      ["top_25", "Top 25% threshold"],
      ["top_10", "Top 10% threshold"],
      ["top_5", "Top 5% threshold"],
      ["top_1", "Top 1% threshold"],
    ].map(([key, label]) => ({ key, label, amount: thresholds[key]?.normalized_amount }));
  }, [projection]);

  if (!startingPoint && busy) return <LoadingPlan />;
  if (!startingPoint) return <div className="notice"><span className="notice-mark">!</span><div><strong>Life Lab could not start.</strong><p>{error}</p><button className="secondary-button" onClick={() => void load()}>Try again</button></div></div>;
  if (!profile) {
    return (
      <div className="view-stack life-lab">
        <header className="page-heading life-hero"><div><span className="eyebrow">Plan · Life Lab</span><h1>Turn the numbers into a life.</h1><p>Try any work-optional age, protect the splurges that matter, and see exactly where accessible money—not total net worth—becomes the constraint.</p></div></header>
        {error && <div className="error-banner">{error}</div>}
        <LifeProfileForm profile={null} startingPoint={startingPoint} busy={busy} onSave={(payload) => void saveProfile(payload)} />
      </div>
    );
  }

  return (
    <div className="view-stack life-lab">
      <header className="page-heading life-hero">
        <div><span className="eyebrow">Plan · Life Lab</span><h1>What would it take?</h1><p>Deterministic paths in today’s dollars. No probability theater—just visible assumptions, accessible-money constraints, and concrete levers.</p></div>
        <button className="secondary-button" onClick={() => setEditingProfile(true)}>Edit assumptions</button>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {message && <div className="life-message">{message}</div>}
      {editingProfile && <LifeProfileForm profile={profile} startingPoint={startingPoint} busy={busy} onSave={(payload) => void saveProfile(payload)} onCancel={() => setEditingProfile(false)} />}

      <section className="metric-grid life-start-grid" aria-label="Observed starting point">
        <article className="metric-card green"><span className="eyebrow">Accessible now</span><strong>{currency(startingPoint.accessible_total)}</strong><small>Cash plus confirmed sellable investments</small></article>
        <article className="metric-card"><span className="eyebrow">Retirement</span><strong>{currency(startingPoint.pretax_retirement)}</strong><small>Shown separately until age 59½</small></article>
        <article className="metric-card"><span className="eyebrow">Current outflow</span><strong>{currency(profile.current_monthly_outflow)}/mo</strong><small>User-entered; observed suggestion was {currency(startingPoint.observed_monthly_outflow)}</small></article>
        <article className="metric-card ink"><span className="eyebrow">Salary baseline</span><strong>{startingPoint.payroll ? currency(startingPoint.payroll.annual_salary) : "Unavailable"}</strong><small>{startingPoint.payroll ? `Observed ${startingPoint.payroll.payment_date}` : "Add completed payroll"}</small></article>
      </section>

      {busy && !projection ? <LoadingPlan /> : projection && target && path && pathStatus ? (
        <>
          <section className="panel life-control-panel">
            <div className="life-control-row">
              <div><span className="eyebrow">Make work optional at</span><div className="age-pills">{projection.results.map((row) => <button key={row.target_age} className={selectedAge === row.target_age ? "active" : ""} onClick={() => setSelectedAge(row.target_age)}>Age {row.target_age}</button>)}</div></div>
              <div><span className="eyebrow">Read the path</span><div className="path-pills">{target.paths.map((row) => <button key={row.path_key} className={selectedPath === row.path_key ? "active" : ""} onClick={() => setSelectedPath(row.path_key)}>{row.path_label}</button>)}</div></div>
            </div>
            <div className={`life-verdict ${pathStatus.tone}`}>
              <div><span className="eyebrow">Age {selectedAge} · {path.path_label}</span><h2>{pathStatus.label}</h2><p>{pathStatus.detail}</p></div>
              <div className="verdict-metrics">
                <span><small>Accessible at work stop</small><strong>{currency(path.work_stop_assets.accessible_total ?? path.work_stop_assets.accessible_investments)}</strong></span>
                <span><small>End spendable assets</small><strong>{currency(path.end_assets.total_spendable)}</strong></span>
                <span><small>Required-money runway</small><strong>{runway === null ? "Through plan" : `${runway} months`}</strong></span>
              </div>
            </div>
            {path.status === "insufficient_accessible_bridge" && <div className="bridge-callout"><strong>{currency(path.work_stop_assets.pretax_retirement)} is sitting in retirement at work stop.</strong><span>Life Lab does not assume a 401(k) loan or early-withdrawal exception. It marks the month your accessible bridge breaks so that any borrowing or tax strategy stays an explicit decision.</span></div>}
          </section>

          <section className="panel projection-panel">
            <header className="life-section-heading"><div><span className="eyebrow">Today’s dollars · age {selectedAge}</span><h2>All three paths</h2></div><div className="display-toggle"><button className={display === "chart" ? "active" : ""} onClick={() => setDisplay("chart")}>Chart</button><button className={display === "table" ? "active" : ""} onClick={() => setDisplay("table")}>Table</button></div></header>
            {display === "chart" ? <ProjectionChart paths={target.paths} /> : <ProjectionTable path={path} />}
          </section>

          <DriveCalculator projection={projection} path={path} goals={goals} startingPoint={startingPoint} />

          <GoalEditor goals={goals} impacts={impacts} busy={busy} onAdd={(payload: LifeGoalInput) => void mutate(() => addLifeGoal(payload), "Goal added.")} onUpdate={(id, payload) => void mutate(() => saveLifeGoal(id, payload), "Goal updated.")} onDelete={(id) => void mutate(() => deleteLifeGoal(id), "Goal deleted.")} />

          <details className="panel income-context-panel">
            <summary>{projection.benchmarks.state_name ?? profile.state} income context</summary>
            {projection.benchmarks.available ? <div className="benchmark-list">{benchmarkRows.map((row) => <div key={row.key} className={projection.benchmarks.current_income_context === row.key ? "current" : ""}><span>{row.label}</span><strong>{currency(row.amount)}</strong></div>)}</div> : <div className="life-empty">Benchmark unavailable for this state.</div>}
            <p className="benchmark-note">{projection.benchmarks.warning} Source: IRS {projection.benchmarks.source_year} state AGI thresholds, normalized to {projection.benchmarks.normalized_dollar_basis}. This is context, not a spending prescription.</p>
          </details>

          <section className="panel scenario-panel">
            <header className="life-section-heading"><div><span className="eyebrow">Reproducible snapshots</span><h2>Save a path before assumptions move</h2></div></header>
            <div className="scenario-save"><input aria-label="Scenario name" value={scenarioName} onChange={(event) => setScenarioName(event.target.value)} placeholder={`Age ${target.target_age} · ${path.path_label}`} maxLength={120} /><button className="primary-button" disabled={busy} onClick={() => { const name = scenarioName.trim() || `Age ${target.target_age} · ${path.path_label}`; void mutate(() => saveLifeScenario({ name, target_age: target.target_age, path_key: selectedPath }), "Scenario snapshot saved.").then(() => setScenarioName("")); }}>Save this view</button></div>
            <div className="scenario-list">{scenarios.length === 0 ? <div className="life-empty">No saved scenarios yet.</div> : scenarios.map((scenario) => <article key={scenario.id}><div><strong>{scenario.name}</strong><small>Age {scenario.target_age} · {scenario.path_key.replace("_", " ")} · {new Date(scenario.created_at).toLocaleDateString()}</small></div><span className={scenario.stale ? "stale" : "current"}>{scenario.stale ? "Inputs changed" : scenario.status.replaceAll("_", " ")}</span></article>)}</div>
          </section>

          <details className="panel assumption-panel"><summary>Assumptions, exclusions, and warnings</summary><div className="assumption-content"><div><h3>Deterministic paths</h3><p>Middle: 4% real. Rough: 2% real. Early crash: 35% loss at work stop, two flat years, then 3% real. Cash earns 0% real.</p><p>Pretax retirement withdrawals receive a {profile.retirement_tax_rate_pct}% visible haircut and are unavailable before age 59½. HSA and restricted assets are not used for ordinary spending.</p></div><div><h3>Not modeled in v0.2</h3><p>{projection.assumptions.omissions.join(", ")}.</p><ul>{projection.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></div></details>
        </>
      ) : null}
    </div>
  );
}
