import { useState, type FormEvent } from "react";
import type { GoalImpact, LifeGoal, LifeGoalInput } from "./life-lab-types";

function currency(value: string | null | undefined) {
  const amount = Number(value ?? 0);
  return amount.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function GoalEditor({
  goals,
  impacts,
  busy,
  onAdd,
  onUpdate,
  onDelete,
}: {
  goals: LifeGoal[];
  impacts: GoalImpact[];
  busy: boolean;
  onAdd: (payload: LifeGoalInput) => void;
  onUpdate: (id: number, payload: LifeGoalInput) => void;
  onDelete: (id: number) => void;
}) {
  const [editing, setEditing] = useState<LifeGoal | null>(null);
  const [adding, setAdding] = useState(false);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const payload: LifeGoalInput = {
      name: String(values.get("name")),
      target_date: String(values.get("target_date")),
      target_amount: String(values.get("target_amount")),
      reserved_amount: String(values.get("reserved_amount") ?? "0"),
      annual_cost: String(values.get("annual_cost") ?? "0"),
      priority: String(values.get("priority")) as "required" | "flexible",
      enabled: true,
      notes: String(values.get("notes") ?? ""),
    };
    if (editing) onUpdate(editing.id, payload);
    else onAdd(payload);
    setEditing(null);
    setAdding(false);
  };
  const formGoal = editing;

  return (
    <section className="panel life-goals-panel">
      <header className="life-section-heading">
        <div>
          <span className="eyebrow">Generic dated goals</span>
          <h2>Make room for a real life</h2>
        </div>
        <button className="primary-button" onClick={() => setAdding(true)} disabled={busy}>Add goal</button>
      </header>
      <p>Trips, a home fund, a sabbatical, family help—each is simply money, timing, priority, and an optional continuing cost.</p>

      {(adding || editing) && (
        <form className="goal-form" onSubmit={submit}>
          <div className="life-form-grid">
            <label>Goal name<input name="name" defaultValue={formGoal?.name} placeholder="Ten-day trip" required /></label>
            <label>Target date<input name="target_date" type="date" defaultValue={formGoal?.target_date} required /></label>
            <label>Target amount<input name="target_amount" type="number" min="0" step="0.01" defaultValue={formGoal?.target_amount ?? "10000"} required /></label>
            <label>Already reserved<input name="reserved_amount" type="number" min="0" step="0.01" defaultValue={formGoal?.reserved_amount ?? "0"} /></label>
            <label>Continuing annual cost<input name="annual_cost" type="number" min="0" step="0.01" defaultValue={formGoal?.annual_cost ?? "0"} /></label>
            <label>Priority<select name="priority" defaultValue={formGoal?.priority ?? "required"}><option value="required">Required</option><option value="flexible">Flexible</option></select></label>
            <label className="life-form-wide">Notes<textarea name="notes" defaultValue={formGoal?.notes} maxLength={500} /></label>
          </div>
          <div className="life-form-actions">
            <button type="button" className="secondary-button" onClick={() => { setAdding(false); setEditing(null); }}>Cancel</button>
            <button className="primary-button" disabled={busy}>{editing ? "Save goal" : "Add to plan"}</button>
          </div>
        </form>
      )}

      <div className="goal-list">
        {goals.length === 0 && <div className="life-empty">No goals yet. Your plan currently models lifestyle only.</div>}
        {goals.map((goal) => {
          const impact = impacts.find((row) => row.goal_id === goal.id);
          return (
            <article className={`goal-card ${goal.enabled ? "" : "disabled"}`} key={goal.id}>
              <div>
                <span className="eyebrow">{goal.priority} · {new Date(`${goal.target_date}T12:00:00`).toLocaleDateString()}</span>
                <h3>{goal.name}</h3>
                <p>{currency(goal.target_amount)} target{Number(goal.annual_cost) ? ` · ${currency(goal.annual_cost)}/yr after` : ""}</p>
              </div>
              {impact && (
                <div className="goal-impact">
                  <strong>{currency(impact.required_monthly_saving)}/mo</strong>
                  <span>{impact.cash_funded ? "Cash-funded in this path" : "Creates a funding gap"}</span>
                  {impact.work_optional_delay_years ? <span>Delays work-optional age {impact.work_optional_delay_years} year{impact.work_optional_delay_years === 1 ? "" : "s"}</span> : null}
                </div>
              )}
              <div className="goal-actions">
                <button onClick={() => setEditing(goal)}>Edit</button>
                <button onClick={() => onUpdate(goal.id, { name: goal.name, target_date: goal.target_date, target_amount: goal.target_amount, reserved_amount: goal.reserved_amount, annual_cost: goal.annual_cost, priority: goal.priority, enabled: !goal.enabled, notes: goal.notes })}>{goal.enabled ? "Pause" : "Include"}</button>
                <button className="danger-text" onClick={() => onDelete(goal.id)}>Delete</button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
