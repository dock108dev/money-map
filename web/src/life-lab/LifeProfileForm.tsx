import type { FormEvent } from "react";
import type {
  LifePlanProfile,
  LifePlanProfileInput,
  LifeStartingPoint,
} from "./life-lab-types";

export function LifeProfileForm({
  profile,
  startingPoint,
  busy,
  onSave,
  onCancel,
}: {
  profile: LifePlanProfile | null;
  startingPoint: LifeStartingPoint;
  busy: boolean;
  onSave: (payload: LifePlanProfileInput) => void;
  onCancel?: () => void;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const targetAges = String(values.get("target_ages") ?? "")
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isInteger(value));
    onSave({
      birth_date: String(values.get("birth_date")),
      state: String(values.get("state")).toUpperCase(),
      end_age: Number(values.get("end_age")),
      current_monthly_outflow: String(values.get("current_monthly_outflow")),
      essential_monthly_spend: String(values.get("essential_monthly_spend")),
      flexible_monthly_spend: String(values.get("flexible_monthly_spend")),
      cash_floor: String(values.get("cash_floor")),
      retirement_tax_rate_pct: String(values.get("retirement_tax_rate_pct")),
      target_ages: targetAges,
      notes: String(values.get("notes") ?? ""),
    });
  };

  return (
    <form className="life-form panel" onSubmit={submit}>
      <header className="life-section-heading">
        <div>
          <span className="eyebrow">Your assumptions</span>
          <h2>{profile ? "Edit the life you want" : "Set up Life Lab"}</h2>
        </div>
        <span className="provenance-chip assumed">Assumption-driven</span>
      </header>
      <p className="life-form-intro">
        Money Map supplies balances and payroll. You supply the life, timing, and spending.
      </p>
      <div className="life-form-grid">
        <label>
          Date of birth
          <input name="birth_date" type="date" defaultValue={profile?.birth_date} required />
        </label>
        <label>
          State
          <input name="state" maxLength={2} defaultValue={profile?.state ?? "NJ"} required />
        </label>
        <label>
          Plan through age
          <input name="end_age" type="number" min="40" max="120" defaultValue={profile?.end_age ?? 95} required />
        </label>
        <label>
          Work-optional ages
          <input
            name="target_ages"
            defaultValue={profile?.target_ages.join(", ") ?? "40, 50, 55, 65"}
            placeholder="40, 50, 55"
            required
          />
          <small>Comma-separated; every age uses the same engine.</small>
        </label>
        <label>
          Current monthly outflow
          <input
            name="current_monthly_outflow"
            type="number"
            min="0"
            step="0.01"
            defaultValue={profile?.current_monthly_outflow ?? startingPoint.observed_monthly_outflow}
            required
          />
          <small>Suggested from complete observed cash months; review it.</small>
        </label>
        <label>
          Essential monthly life
          <input
            name="essential_monthly_spend"
            type="number"
            min="0"
            step="0.01"
            defaultValue={profile?.essential_monthly_spend ?? "4000"}
            required
          />
        </label>
        <label>
          Flexible monthly life
          <input
            name="flexible_monthly_spend"
            type="number"
            min="0"
            step="0.01"
            defaultValue={profile?.flexible_monthly_spend ?? "1500"}
            required
          />
        </label>
        <label>
          Protected cash floor
          <input
            name="cash_floor"
            type="number"
            min="0"
            step="0.01"
            defaultValue={profile?.cash_floor ?? "0"}
            required
          />
        </label>
        <label>
          Pretax withdrawal haircut %
          <input
            name="retirement_tax_rate_pct"
            type="number"
            min="0"
            max="60"
            step="0.1"
            defaultValue={profile?.retirement_tax_rate_pct ?? "20"}
            required
          />
          <small>Visible estimate, not a tax-return calculation.</small>
        </label>
        <label className="life-form-wide">
          Notes
          <textarea name="notes" maxLength={500} defaultValue={profile?.notes} />
        </label>
      </div>
      <div className="life-form-actions">
        {onCancel && <button type="button" className="secondary-button" onClick={onCancel}>Cancel</button>}
        <button className="primary-button" disabled={busy}>
          {busy ? "Calculating…" : profile ? "Update plan" : "Build my Life Lab"}
        </button>
      </div>
    </form>
  );
}
