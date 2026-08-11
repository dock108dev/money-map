import { useEffect, useRef, useState, type RefObject } from "react";

import { FocusedDialog } from "../FocusedDialog";
import {
  loadRecurringOutflowCandidates,
  previewGoalGap,
} from "../api";
import type { ExactDecimalString } from "../v2-contracts";
import {
  parseExactMoneyCents,
  type GoalGapPreviewAvailable,
  type GoalGapPreviewRequest,
  type GoalGapPreviewResponse,
  type RecurringOutflowCandidate,
  type RecurringOutflowCandidateList,
  type V21EvidencedMoney,
} from "../v21-contracts";

interface GoalGapCardProps {
  result: GoalGapPreviewResponse | null;
  error: string;
  onOpenGoals: () => void;
}

function groupDigits(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/gu, ",");
}

function formatCents(cents: bigint, signed = false): string {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const dollars = groupDigits((absolute / 100n).toString());
  const remainder = (absolute % 100n).toString().padStart(2, "0");
  const sign = negative ? "−" : signed && cents > 0n ? "+" : "";
  return `${sign}$${dollars}.${remainder}`;
}

function formatMoney(value: V21EvidencedMoney, signed = false): string {
  return value.amount === null
    ? "Unavailable"
    : formatCents(parseExactMoneyCents(value.amount), signed);
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function baselineSupport(result: GoalGapPreviewAvailable): string {
  const recurring = result.baseline_current_recurring_facts;
  const pace = result.baseline_goal_pace_reference.required_goal_pace;
  const combined = result.baseline_combined_monthly_improvement;
  if (combined.amount === null) {
    if (pace.amount !== null) {
      return `${formatMoney(pace)} goal pace · combined improvement needs recurring evidence`;
    }
    if (recurring.stabilization_gap.amount !== null) {
      return `${formatMoney(recurring.stabilization_gap)} to stabilize · target-date math unavailable`;
    }
    return "Goal pace and recurring cash-flow evidence are unavailable.";
  }
  if (recurring.margin_state === "negative") {
    return `${formatMoney(recurring.stabilization_gap)} to stabilize + ${formatMoney(pace)} goal pace = ${formatMoney(combined)} combined`;
  }
  if (recurring.margin_state === "positive") {
    return `Current margin ${formatMoney(recurring.current_monthly_margin)} already offsets ${formatMoney(pace)} goal pace · ${formatMoney(combined)} combined`;
  }
  return `Current margin is even · ${formatMoney(pace)} goal pace = ${formatMoney(combined)} combined`;
}

export default function GoalGapCard({ result, error, onOpenGoals }: GoalGapCardProps) {
  const [open, setOpen] = useState(false);
  const exploreButtonRef = useRef<HTMLButtonElement>(null);

  if (!result || result.state !== "available") {
    return (
      <section className="goal-gap-card goal-gap-card-quiet" aria-label="Goal impact">
        <span>
          {result?.state === "no_primary"
            ? "No primary goal selected."
            : (result?.reason ?? error) || "Goal impact is loading."}
        </span>
        <button type="button" className="link-button" onClick={onOpenGoals}>Open Goals</button>
      </section>
    );
  }

  const goal = result.baseline_goal_pace_reference;
  const completed = goal.goal_state === "completed";
  const expired = goal.goal_state === "expired_unfinished";
  const floorBreach = goal.goal_state === "cash_floor_breach";
  const combined = result.baseline_combined_monthly_improvement;

  return (
    <>
      <section className="goal-gap-card" aria-labelledby="goal-gap-heading" data-print-goal-gap="current">
        <div className="goal-gap-copy">
          <span className="eyebrow">{result.goal_name} · {dateLabel(goal.target_date)}</span>
          <strong id="goal-gap-heading" data-prose>
            {completed
              ? "Goal funding is complete."
              : expired
                ? "This unfinished goal needs a new target date."
                : combined.amount === null
                  ? "Combined monthly improvement is unavailable."
                  : `Improve monthly cash flow by ${formatMoney(combined)} to match the current goal pace.`}
          </strong>
          {!completed && <span className="goal-gap-equation" data-prose>{baselineSupport(result)}</span>}
          {floorBreach && <span className="goal-gap-floor">Protected cash floor is currently breached.</span>}
        </div>
        <div className="goal-gap-actions">
          <button
            type="button"
            className="primary-button"
            ref={exploreButtonRef}
            onClick={() => setOpen(true)}
          >
            Explore options
          </button>
          <button type="button" className="link-button" onClick={onOpenGoals}>Open Goals</button>
        </div>
      </section>
      {open && (
        <GoalGapDialog
          baseline={result}
          returnFocusRef={exploreButtonRef}
          onClose={() => setOpen(false)}
          onOpenGoals={() => {
            setOpen(false);
            onOpenGoals();
          }}
        />
      )}
    </>
  );
}

function normalizeMoneyInput(value: string, label: string): ExactDecimalString {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d{0,2})?$/.test(trimmed)) {
    throw new Error(`${label} must be a nonnegative amount with no more than two decimals.`);
  }
  const [whole, fraction = ""] = trimmed.split(".");
  const normalizedWhole = BigInt(whole).toString();
  return `${normalizedWhole}.${fraction.padEnd(2, "0")}` as ExactDecimalString;
}

function centsToExact(cents: bigint): ExactDecimalString {
  if (cents < 0n) throw new Error("Draft total cannot be negative");
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, "0")}` as ExactDecimalString;
}

function sameMonthDayIn2035(current: string): string {
  const candidate = `2035-${current.slice(5)}`;
  const parsed = new Date(`${candidate}T00:00:00Z`);
  return parsed.toISOString().slice(0, 10) === candidate ? candidate : "2035-02-28";
}

function candidateEnteredTotal(values: Record<string, string>): bigint | null {
  try {
    return Object.values(values).reduce(
      (total, value) => total + parseExactMoneyCents(normalizeMoneyInput(value || "0", "Candidate reduction")),
      0n,
    );
  } catch {
    return null;
  }
}

function GoalGapDialog({
  baseline,
  returnFocusRef,
  onClose,
  onOpenGoals,
}: {
  baseline: GoalGapPreviewAvailable;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onOpenGoals: () => void;
}) {
  const [targetDate, setTargetDate] = useState(baseline.preview_target_date);
  const [reservation, setReservation] = useState("0.00");
  const [genericReduction, setGenericReduction] = useState("0.00");
  const [afterTaxIncome, setAfterTaxIncome] = useState("0.00");
  const [candidateReductions, setCandidateReductions] = useState<Record<string, string>>({});
  const [candidateResult, setCandidateResult] = useState<RecurringOutflowCandidateList | null>(null);
  const [candidateError, setCandidateError] = useState("");
  const [scenario, setScenario] = useState<GoalGapPreviewResponse>(baseline);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);

  useEffect(() => {
    let current = true;
    void loadRecurringOutflowCandidates()
      .then((next) => {
        if (current) setCandidateResult(next);
      })
      .catch((reason: unknown) => {
        if (current) {
          setCandidateError(
            reason instanceof Error ? reason.message : "Repeated-outflow evidence could not load.",
          );
        }
      });
    return () => {
      current = false;
    };
  }, []);

  const recalculate = async () => {
    try {
      const additional = normalizeMoneyInput(reservation || "0", "Additional reservation");
      const generic = normalizeMoneyInput(genericReduction || "0", "Generic reduction");
      const income = normalizeMoneyInput(afterTaxIncome || "0", "After-tax income");
      let explicitCandidateTotal = 0n;
      for (const candidate of candidateResult?.candidates ?? []) {
        const raw = candidateReductions[candidate.candidate_id];
        if (!raw) continue;
        const exact = normalizeMoneyInput(raw, `Proposed reduction for ${candidate.observed_description}`);
        const cents = parseExactMoneyCents(exact);
        const cap = parseExactMoneyCents(candidate.typical_monthly_amount.amount ?? "0.00");
        if (cents > cap) {
          throw new Error(
            `Proposed reduction for ${candidate.observed_description} cannot exceed ${formatCents(cap)}.`,
          );
        }
        explicitCandidateTotal += cents;
      }
      const spending = centsToExact(parseExactMoneyCents(generic) + explicitCandidateTotal);
      const payload: GoalGapPreviewRequest = {
        target_date: targetDate,
        additional_reservation: additional,
        monthly_spending_reduction: spending,
        monthly_after_tax_income: income,
      };
      const requestSequence = ++sequence.current;
      setBusy(true);
      setError("");
      try {
        const next = await previewGoalGap(payload);
        if (requestSequence === sequence.current) setScenario(next);
      } catch (reason) {
        if (requestSequence === sequence.current) {
          setError(reason instanceof Error ? reason.message : "Preview could not be recalculated.");
        }
      } finally {
        if (requestSequence === sequence.current) setBusy(false);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Draft values are invalid.");
    }
  };

  const reset = () => {
    sequence.current += 1;
    setTargetDate(baseline.preview_target_date);
    setReservation("0.00");
    setGenericReduction("0.00");
    setAfterTaxIncome("0.00");
    setCandidateReductions({});
    setScenario(baseline);
    setError("");
    setBusy(false);
  };
  const enteredCandidateTotal = candidateEnteredTotal(candidateReductions);

  return (
    <FocusedDialog
      title="Explore goal options"
      description="Draft only. Nothing here changes Goals. No money is reserved or moved."
      returnFocusRef={returnFocusRef}
      onClose={onClose}
      tone="boundary"
      className="goal-gap-dialog"
    >
      <div className="goal-gap-boundary" role="note">
        <strong>Draft only</strong>
        <span>Nothing here changes Goals.</span>
        <span>No money is reserved or moved.</span>
      </div>
      <div className="goal-gap-layout">
        <section className="goal-gap-controls" aria-label="Draft goal options">
          <label>
            Target date
            <input
              data-autofocus
              type="date"
              value={targetDate}
              onChange={(event) => setTargetDate(event.currentTarget.value)}
            />
          </label>
          <button
            type="button"
            className="goal-gap-quick-date"
            onClick={() => setTargetDate(sameMonthDayIn2035(baseline.preview_target_date))}
          >
            Compare same month/day in 2035
          </button>
          <label>
            Additional one-time goal reservation
            <input inputMode="decimal" value={reservation} onChange={(event) => setReservation(event.currentTarget.value)} />
          </label>
          <label>
            Generic monthly spending reduction
            <input inputMode="decimal" value={genericReduction} onChange={(event) => setGenericReduction(event.currentTarget.value)} />
          </label>
          <label>
            Monthly after-tax income increase
            <input inputMode="decimal" value={afterTaxIncome} onChange={(event) => setAfterTaxIncome(event.currentTarget.value)} />
          </label>
          <RepeatedOutflowCandidates
            result={candidateResult}
            error={candidateError}
            values={candidateReductions}
            onChange={(candidateId, value) =>
              setCandidateReductions((current) => ({ ...current, [candidateId]: value }))
            }
          />
          <p className="goal-gap-draft-total">
            Explicit candidate reductions: {enteredCandidateTotal === null ? "Check entries" : formatCents(enteredCandidateTotal)}
          </p>
          {error && <p className="goal-gap-preview-error" role="alert">{error}</p>}
          <div className="goal-gap-dialog-actions">
            <button type="button" className="primary-button" disabled={busy} onClick={() => void recalculate()}>
              {busy ? "Recalculating…" : "Recalculate"}
            </button>
            <button type="button" className="secondary-button" onClick={reset}>Reset to current</button>
          </div>
        </section>
        <ScenarioResult result={scenario} />
      </div>
      <footer className="goal-gap-dialog-footer">
        <button type="button" className="link-button" onClick={onOpenGoals}>Open Goals</button>
        <button type="button" className="secondary-button" onClick={onClose}>Close</button>
      </footer>
    </FocusedDialog>
  );
}

function RepeatedOutflowCandidates({
  result,
  error,
  values,
  onChange,
}: {
  result: RecurringOutflowCandidateList | null;
  error: string;
  values: Record<string, string>;
  onChange: (candidateId: string, value: string) => void;
}) {
  return (
    <details className="repeated-outflow-candidates">
      <summary>Repeated outflow candidates</summary>
      <p>Evidence only—not savings recommendations. Expanding a candidate changes nothing.</p>
      {error && <p role="status">{error}</p>}
      {!result && !error && <p>Loading repeated-outflow evidence…</p>}
      {result?.state === "unavailable" && <p>{result.reason}</p>}
      {result?.state === "empty" && <p>No high-confidence repeated outflows were found.</p>}
      {result?.candidates.map((candidate) => (
        <CandidateDraft
          key={candidate.candidate_id}
          candidate={candidate}
          value={values[candidate.candidate_id] ?? ""}
          onChange={(value) => onChange(candidate.candidate_id, value)}
        />
      ))}
    </details>
  );
}

function CandidateDraft({
  candidate,
  value,
  onChange,
}: {
  candidate: RecurringOutflowCandidate;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="repeated-outflow-row">
      <strong>{candidate.observed_description}</strong>
      <span>{candidate.safe_account_label} · {candidate.cadence} · {candidate.occurrence_count} occurrences</span>
      <span>{formatMoney(candidate.median_observed_amount)} observed median · {dateLabel(candidate.first_observed_date)}–{dateLabel(candidate.last_observed_date)} · high confidence</span>
      <label>
        Proposed monthly reduction (max {formatMoney(candidate.typical_monthly_amount)})
        <input inputMode="decimal" value={value} placeholder="0.00" onChange={(event) => onChange(event.currentTarget.value)} />
      </label>
    </div>
  );
}

function ScenarioResult({ result }: { result: GoalGapPreviewResponse }) {
  if (result.state !== "available") {
    return <section className="goal-gap-results" aria-label="Scenario result"><p>{result.reason}</p></section>;
  }
  const margin = result.adjusted_monthly_margin;
  const marginCents = margin.amount === null ? null : parseExactMoneyCents(margin.amount);
  const gross = result.gross_income_context;
  return (
    <section className="goal-gap-results" aria-labelledby="goal-gap-results-heading">
      <span className="eyebrow">Scenario result</span>
      <h3 id="goal-gap-results-heading">Remaining monthly improvement</h3>
      <strong className="goal-gap-result-headline">{formatMoney(result.remaining_combined_monthly_improvement)}</strong>
      <dl>
        <div>
          <dt>{marginCents !== null && marginCents < 0n ? "Adjusted monthly gap" : "Adjusted monthly margin"}</dt>
          <dd>{marginCents === null ? "Unavailable" : formatCents(marginCents < 0n ? -marginCents : marginCents)}</dd>
        </div>
        <div><dt>Required goal pace</dt><dd>{formatMoney(result.preview_required_goal_pace)}</dd></div>
        <div><dt>Preview remaining target</dt><dd>{formatMoney(result.preview_remaining_target)}</dd></div>
        <div><dt>Target date</dt><dd>{dateLabel(result.preview_target_date)} · {result.exact_funding_months} months</dd></div>
        <div>
          <dt>Gross-income context</dt>
          <dd>
            {gross.state === "available"
              ? `${formatMoney(gross.estimated_monthly_gross_income_needed)}/month · ${formatMoney(gross.estimated_annual_gross_income_needed)}/year`
              : gross.reason}
          </dd>
        </div>
      </dl>
      {gross.state === "available" && (
        <p className="goal-gap-gross-note">
          {gross.estimate_label}; latest supported paycheck {dateLabel(gross.supporting_payroll_date)} at ratio {gross.effective_take_home_ratio}. {gross.disclaimer}.
        </p>
      )}
      <details className="goal-gap-time-evidence">
        <summary>Time-basis evidence</summary>
        <p>
          {result.calculation_version} uses inclusive actual-calendar fractional months. Exact funding months: {result.exact_funding_months}. Exact target date: {result.preview_target_date}.
        </p>
      </details>
    </section>
  );
}
