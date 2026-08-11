import type { FormEvent, RefObject } from "react";

import { FocusedDialog } from "../FocusedDialog";
import type {
  ExactDecimalString,
  RetirementProfileEditRequest,
  RetirementProfileView,
} from "../v2-contracts";

function amount(value: { amount: ExactDecimalString | null }) {
  return value.amount ?? "0.00";
}

export function RetirementProfileForm({
  profile,
  busy,
  error,
  onSave,
  onCancel,
  returnFocusRef,
}: {
  profile: RetirementProfileView;
  busy: boolean;
  error: string;
  onSave: (payload: RetirementProfileEditRequest) => void;
  onCancel: () => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const ages = String(values.get("work_optional_ages") ?? "")
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isInteger(value));
    onSave({
      expected_edit_token: profile.edit_token,
      birth_date: String(values.get("birth_date")),
      state: String(values.get("state")).toUpperCase(),
      plan_through_age: Number(values.get("plan_through_age")),
      current_monthly_outflow: String(values.get("current_monthly_outflow")) as ExactDecimalString,
      retirement_essential_monthly_spend: String(values.get("retirement_essential_monthly_spend")) as ExactDecimalString,
      retirement_flexible_monthly_spend: String(values.get("retirement_flexible_monthly_spend")) as ExactDecimalString,
      protected_cash_floor: String(values.get("protected_cash_floor")) as ExactDecimalString,
      retirement_tax_haircut_pct: String(values.get("retirement_tax_haircut_pct")),
      work_optional_ages: ages,
      notes: String(values.get("notes") ?? ""),
    });
  };

  return (
    <FocusedDialog
      title="Edit Retirement assumptions"
      description="These durable assumptions affect future Retirement runs only."
      returnFocusRef={returnFocusRef}
      onClose={onCancel}
      className="retirement-sheet"
    >
        {error && <p id="retirement-form-error" className="retirement-form-error" role="alert">{error}</p>}
        <form aria-label="Retirement profile assumptions" aria-describedby={error ? "retirement-form-error" : undefined} onSubmit={submit} className="retirement-profile-form">
          <label>Date of birth<input data-autofocus name="birth_date" type="date" defaultValue={profile.birth_date} required /></label>
          <label>State<input name="state" maxLength={2} defaultValue={profile.state} required /></label>
          <label>Plan through age<input name="plan_through_age" type="number" min="40" max="120" defaultValue={profile.plan_through_age} required /></label>
          <label>Work-optional ages<input name="work_optional_ages" defaultValue={profile.work_optional_ages.join(", ")} required /><small>Comma-separated, after current age and before plan end.</small></label>
          <label>Current monthly outflow<input name="current_monthly_outflow" type="number" min="0" step="0.01" defaultValue={amount(profile.current_monthly_outflow)} required /></label>
          <label>Essential monthly retirement life<input name="retirement_essential_monthly_spend" type="number" min="0" step="0.01" defaultValue={amount(profile.retirement_essential_monthly_spend)} required /></label>
          <label>Flexible monthly retirement life<input name="retirement_flexible_monthly_spend" type="number" min="0" step="0.01" defaultValue={amount(profile.retirement_flexible_monthly_spend)} required /></label>
          <label>Protected cash floor<input name="protected_cash_floor" type="number" min="0" step="0.01" defaultValue={amount(profile.protected_cash_floor)} required /></label>
          <label>Pretax withdrawal haircut %<input name="retirement_tax_haircut_pct" type="number" min="0" max="60" step="0.1" defaultValue={profile.retirement_tax_haircut_pct} required /><small>Visible estimate, not a tax-return calculation.</small></label>
          <label className="wide">Notes<textarea name="notes" maxLength={500} defaultValue={profile.notes} /></label>
          <div className="retirement-form-actions wide">
            <button type="button" className="secondary-button" onClick={onCancel}>Cancel</button>
            <button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save assumptions"}</button>
          </div>
        </form>
    </FocusedDialog>
  );
}
