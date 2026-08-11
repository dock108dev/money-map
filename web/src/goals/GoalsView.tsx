import {
  type FormEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  ExactDecimalString,
  GoalCandidateList,
  GoalCheckInState,
  GoalCheckInTimelinePage,
  GoalComparison,
  GoalComparisonState,
  GoalEditRequest,
  GoalMilestoneState,
  GoalObservationResult,
  GoalPosition,
  GoalPositionState,
  GoalProgramView,
  GoalProvenanceState,
  PrimaryGoalState,
} from "../v2-contracts";
import {
  backfillGoalCheckIn,
  editGoal,
  GoalApiError,
  loadGoalCandidates,
  loadGoalCheckIns,
  loadGoalComparison,
  loadGoalMilestone,
  loadGoalPosition,
  loadGoalProvenance,
  loadLatestGoalCheckIn,
  loadPrimaryGoal,
  selectPrimaryGoal,
} from "./api";
import "./goals.css";

type DetailErrorKey = "position" | "latest" | "comparison" | "milestone";
type DetailErrors = Partial<Record<DetailErrorKey, string>>;

interface GoalsViewProps {
  reloadVersion: number;
}

interface EditDraft {
  name: string;
  targetDate: string;
  targetAmount: string;
  protectedCashFloor: string;
  reservedForGoal: string;
}

interface EditErrors {
  name?: string;
  targetDate?: string;
  targetAmount?: string;
  protectedCashFloor?: string;
  reservedForGoal?: string;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function briefReason(value: string | null | undefined, fallback: string): string {
  const reason = value?.trim().replace(/[.!]+$/, "");
  return reason || fallback;
}

function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined) return "Unavailable";
  const match = /^(-?)(\d+)\.(\d{2})$/.exec(value);
  if (!match) return "Unavailable";
  const [, sign, dollars, cents] = match;
  const grouped = dollars.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign ? "−" : ""}$${grouped}.${cents}`;
}

function formatDate(value: string): string {
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatShortDate(value: string): string {
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatSavedAt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Saved locally";
  return `Saved ${parsed.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

function decimalSign(value: string): -1 | 0 | 1 {
  if (/^-0\.00$/.test(value) || /^0\.00$/.test(value)) return 0;
  return value.startsWith("-") ? -1 : 1;
}

function absoluteDecimal(value: ExactDecimalString): ExactDecimalString {
  return (value.startsWith("-") ? value.slice(1) : value) as ExactDecimalString;
}

function formatMovement(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const sign = decimalSign(value);
  if (sign === 0) return "$0.00";
  const amount = formatMoney(absoluteDecimal(value as ExactDecimalString));
  return `${sign > 0 ? "+" : "−"}${amount}`;
}

function comparisonAmount(
  comparison: GoalComparison | undefined,
  component: GoalComparison["components"][number]["component"],
): string | null {
  return comparison?.components.find((item) => item.component === component)?.change.amount ?? null;
}

function triggerLabel(trigger: GoalCheckInTimelinePage["check_ins"][number]["trigger"]): string {
  if (trigger === "post_refresh") return "Account update";
  if (trigger === "post_import") return "Manual import";
  if (trigger === "post_payroll") return "Payroll rebuild";
  if (trigger === "load_backfill") return "Eligible load backfill";
  return "Synthetic validation";
}

export function verdictSentence(state: GoalComparisonState | null, failure?: string): string {
  if (failure) return `Comparison unavailable: ${briefReason(failure, "the comparison could not load")}.`;
  if (!state) return "Comparison unavailable: the comparison could not load.";
  if (state.state === "no_previous_check_in") return "No saved comparison exists yet.";
  if (state.state !== "available") {
    return `Comparison unavailable: ${briefReason(state.reason, "the evidence is incomplete")}.`;
  }
  const accessible = state.comparison.components.find(
    (component) => component.component === "accessible_now",
  );
  if (!accessible?.change.amount) {
    return `Comparison unavailable: ${briefReason(
      accessible?.change.unavailable_reason,
      "accessible-capital evidence is incomplete",
    )}.`;
  }
  const sign = decimalSign(accessible.change.amount);
  const previous = formatShortDate(state.comparison.previous_observation_date);
  if (sign > 0) {
    return `Accessible capital increased by ${formatMoney(accessible.change.amount)} since ${previous}.`;
  }
  if (sign < 0) {
    return `Accessible capital decreased by ${formatMoney(absoluteDecimal(accessible.change.amount))} since ${previous}.`;
  }
  return `Observed accessible capital is unchanged since ${previous}.`;
}

export function milestoneSentence(state: GoalMilestoneState | null, failure?: string): string {
  if (failure) return `Milestone unavailable: ${briefReason(failure, "the milestone could not load")}.`;
  if (!state?.milestone) return "Milestone unavailable: no primary goal is selected.";
  const { milestone } = state;
  if (milestone.kind === "data_unavailable") {
    return `Milestone unavailable: ${briefReason(
      milestone.amount.unavailable_reason,
      "required evidence is incomplete",
    )}.`;
  }
  const amount = formatMoney(milestone.amount.amount);
  if (milestone.kind === "restore_floor") return `Restore the protected cash floor by ${amount}.`;
  if (milestone.kind === "close_recurring_gap") return `Close the ${amount} monthly recurring gap.`;
  if (milestone.kind === "fund_goal") return `Fund this goal at ${amount} per month.`;
  return "This goal is fully reserved.";
}

function resultValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
}

function resultError(result: PromiseSettledResult<unknown>, fallback: string): string | undefined {
  return result.status === "rejected" ? errorMessage(result.reason, fallback) : undefined;
}

function usePrefersReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

function moneyField(value: GoalPosition[keyof GoalPosition] | undefined): string {
  if (!value || typeof value !== "object" || !("amount" in value)) return "Unavailable";
  return formatMoney(value.amount);
}

function CandidateCard({
  candidate,
  busy,
  onSelect,
}: {
  candidate: GoalProgramView;
  busy: boolean;
  onSelect: (candidate: GoalProgramView) => void;
}) {
  return (
    <article className="goal-candidate">
      <div>
        <span className="goal-status">{candidate.status === "complete" ? "Complete" : "Active"}</span>
        <h2>{candidate.name}</h2>
        <p>
          {formatMoney(candidate.target_amount.amount)} by {formatDate(candidate.target_date)}
        </p>
      </div>
      <div className="candidate-reserved">
        <span>Reserved</span>
        <strong>{formatMoney(candidate.reserved_for_goal.amount)}</strong>
      </div>
      <button className="secondary-button" disabled={busy} onClick={() => onSelect(candidate)}>
        Make primary
      </button>
    </article>
  );
}

function GoalMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="goal-metric" aria-label={`${label}: ${value}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function validateDraft(draft: EditDraft): EditErrors {
  const errors: EditErrors = {};
  const exactMoney = /^\d+\.\d{2}$/;
  if (!draft.name.trim()) errors.name = "Enter a goal name.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.targetDate)) errors.targetDate = "Enter a target date.";
  for (const [key, value, label] of [
    ["targetAmount", draft.targetAmount, "target amount"],
    ["protectedCashFloor", draft.protectedCashFloor, "protected cash floor"],
    ["reservedForGoal", draft.reservedForGoal, "reserved amount"],
  ] as const) {
    if (!exactMoney.test(value)) errors[key] = `Enter the ${label} in dollars and cents.`;
  }
  const exactCents = (value: string) => BigInt(value.replace(".", ""));
  if (!errors.targetAmount && exactCents(draft.targetAmount) <= 0n) {
    errors.targetAmount = "Target amount must be greater than zero.";
  }
  if (
    !errors.targetAmount &&
    !errors.reservedForGoal &&
    exactCents(draft.reservedForGoal) > exactCents(draft.targetAmount)
  ) {
    errors.reservedForGoal = "Reserved money cannot exceed the target amount.";
  }
  return errors;
}

function GoalEditDialog({
  goal,
  invoker,
  onClose,
  onSaved,
  onReloadConflict,
}: {
  goal: GoalProgramView;
  invoker: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onReloadConflict: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<EditDraft>({
    name: goal.name,
    targetDate: goal.target_date,
    targetAmount: goal.target_amount.amount ?? "",
    protectedCashFloor: goal.protected_cash_floor.amount ?? "",
    reservedForGoal: goal.reserved_for_goal.amount ?? "",
  });
  const [errors, setErrors] = useState<EditErrors>({});
  const [submitError, setSubmitError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const previous = invoker.current;
    const dialog = dialogRef.current;
    const first = dialog?.querySelector<HTMLElement>("input");
    first?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      const firstFocusable = focusable[0];
      const lastFocusable = focusable.at(-1);
      if (event.shiftKey && document.activeElement === firstFocusable) {
        event.preventDefault();
        lastFocusable?.focus();
      } else if (!event.shiftKey && document.activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [invoker]);

  const update = (field: keyof EditDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextErrors = validateDraft(draft);
    setErrors(nextErrors);
    setSubmitError("");
    if (Object.keys(nextErrors).length > 0) return;
    const payload: GoalEditRequest = {
      expected_edit_token: goal.edit_token,
      name: draft.name.trim(),
      target_date: draft.targetDate,
      target_amount: draft.targetAmount as ExactDecimalString,
      protected_cash_floor: draft.protectedCashFloor as ExactDecimalString,
      reserved_for_goal: draft.reservedForGoal as ExactDecimalString,
    };
    setBusy(true);
    try {
      await editGoal(goal.goal_program_id, payload);
      await onSaved();
    } catch (reason) {
      if (reason instanceof GoalApiError && reason.status === 409) {
        setConflict(true);
        setSubmitError("This goal changed elsewhere. Your entries are preserved.");
      } else {
        setSubmitError(errorMessage(reason, "The goal could not be saved."));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="goal-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        className="goal-dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="goal-edit-title"
        aria-describedby={submitError ? "goal-edit-error" : undefined}
      >
        <button className="icon-button" onClick={onClose} aria-label="Close goal editor">×</button>
        <span className="eyebrow">Primary goal</span>
        <h2 id="goal-edit-title">Edit goal</h2>
        <form onSubmit={(event) => void submit(event)} noValidate>
          <label>
            Goal name
            <input
              autoComplete="off"
              value={draft.name}
              onChange={(event) => update("name", event.target.value)}
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? "goal-name-error" : undefined}
            />
            {errors.name && <span className="field-error" id="goal-name-error">{errors.name}</span>}
          </label>
          <label>
            Target date
            <input
              type="date"
              value={draft.targetDate}
              onChange={(event) => update("targetDate", event.target.value)}
              aria-invalid={Boolean(errors.targetDate)}
              aria-describedby={errors.targetDate ? "goal-date-error" : undefined}
            />
            {errors.targetDate && <span className="field-error" id="goal-date-error">{errors.targetDate}</span>}
          </label>
          <label>
            Target amount
            <input
              inputMode="decimal"
              value={draft.targetAmount}
              onChange={(event) => update("targetAmount", event.target.value)}
              aria-invalid={Boolean(errors.targetAmount)}
              aria-describedby={errors.targetAmount ? "goal-target-error" : undefined}
            />
            {errors.targetAmount && <span className="field-error" id="goal-target-error">{errors.targetAmount}</span>}
          </label>
          <label>
            Protected cash floor
            <input
              inputMode="decimal"
              value={draft.protectedCashFloor}
              onChange={(event) => update("protectedCashFloor", event.target.value)}
              aria-invalid={Boolean(errors.protectedCashFloor)}
              aria-describedby={errors.protectedCashFloor ? "goal-floor-error" : undefined}
            />
            {errors.protectedCashFloor && <span className="field-error" id="goal-floor-error">{errors.protectedCashFloor}</span>}
          </label>
          <label>
            Reserved amount
            <input
              inputMode="decimal"
              value={draft.reservedForGoal}
              onChange={(event) => update("reservedForGoal", event.target.value)}
              aria-invalid={Boolean(errors.reservedForGoal)}
              aria-describedby={errors.reservedForGoal ? "goal-reserved-error" : undefined}
            />
            {errors.reservedForGoal && <span className="field-error" id="goal-reserved-error">{errors.reservedForGoal}</span>}
          </label>
          {submitError && <div className="goal-form-error" id="goal-edit-error" role="alert">{submitError}</div>}
          {conflict && (
            <button
              className="secondary-button conflict-reload"
              type="button"
              disabled={busy}
              onClick={() => void onReloadConflict()}
            >
              Reload current goal
            </button>
          )}
          <div className="goal-dialog-actions">
            <button className="secondary-button" type="button" onClick={onClose}>Cancel</button>
            <button className="primary-button" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save goal"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function PositionDetails({ position }: { position: GoalPosition | null }) {
  if (!position) return <p className="goal-detail-message">Current position evidence is unavailable.</p>;
  return (
    <div className="goal-detail-body">
      <dl className="goal-evidence-grid">
        <div><dt>Accessible cash</dt><dd>{moneyField(position.accessible_cash)}</dd></div>
        <div><dt>Sellable investments</dt><dd>{moneyField(position.accessible_investments)}</dd></div>
        <div><dt>Tracked debt</dt><dd>{moneyField(position.tracked_debt)}</dd></div>
        <div><dt>Retirement excluded</dt><dd>{moneyField(position.retirement_assets_excluded)}</dd></div>
        <div><dt>Protected floor</dt><dd>{moneyField(position.protected_cash_floor)}</dd></div>
        <div><dt>Remaining target</dt><dd>{moneyField(position.remaining_target)}</dd></div>
      </dl>
      <div className="goal-formulas" aria-label="Goal formulas">
        <p><strong>Accessible now</strong> = observed cash + confirmed sellable investments.</p>
        <p><strong>Available above floor</strong> = accessible now minus the protected floor, never below zero.</p>
        <p><strong>Required pace</strong> = remaining target divided across the remaining calendar months.</p>
      </div>
    </div>
  );
}

export default function GoalsView({ reloadVersion }: GoalsViewProps) {
  const reducedMotion = usePrefersReducedMotion();
  const [primaryState, setPrimaryState] = useState<PrimaryGoalState | null>(null);
  const [positionState, setPositionState] = useState<GoalPositionState | null>(null);
  const [latestState, setLatestState] = useState<GoalCheckInState | null>(null);
  const [comparisonState, setComparisonState] = useState<GoalComparisonState | null>(null);
  const [milestoneState, setMilestoneState] = useState<GoalMilestoneState | null>(null);
  const [observationState, setObservationState] = useState<GoalObservationResult | null>(null);
  const [observationError, setObservationError] = useState("");
  const [detailErrors, setDetailErrors] = useState<DetailErrors>({});
  const [candidates, setCandidates] = useState<GoalCandidateList | null>(null);
  const [candidateError, setCandidateError] = useState("");
  const [history, setHistory] = useState<GoalCheckInTimelinePage | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [historyBusy, setHistoryBusy] = useState(false);
  const [provenance, setProvenance] = useState<GoalProvenanceState | null>(null);
  const [provenanceError, setProvenanceError] = useState("");
  const [provenanceBusy, setProvenanceBusy] = useState(false);
  const [busy, setBusy] = useState(true);
  const [pageError, setPageError] = useState("");
  const [message, setMessage] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const loadSequence = useRef(0);
  const historyOpened = useRef(false);
  const provenanceOpened = useRef(false);
  const candidatesOpened = useRef(false);

  const loadSurface = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setBusy(true);
    setPageError("");
    let nextPrimary: PrimaryGoalState;
    try {
      nextPrimary = await loadPrimaryGoal();
    } catch (reason) {
      if (sequence !== loadSequence.current) return;
      setPageError(errorMessage(reason, "The primary goal could not load."));
      setBusy(false);
      return;
    }
    if (sequence !== loadSequence.current) return;
    setPrimaryState(nextPrimary);
    setObservationState(null);
    setObservationError("");
    if (nextPrimary.state === "primary") {
      try {
        const observation = await backfillGoalCheckIn();
        if (sequence === loadSequence.current) setObservationState(observation);
      } catch (reason) {
        if (sequence === loadSequence.current) {
          setObservationError(errorMessage(reason, "The goal observation could not be saved."));
        }
      }
    }
    const results = await Promise.allSettled([
      loadGoalPosition(),
      loadLatestGoalCheckIn(),
      loadGoalComparison(),
      loadGoalMilestone(),
    ] as const);
    if (sequence !== loadSequence.current) return;
    setPositionState(resultValue(results[0]));
    setLatestState(resultValue(results[1]));
    setComparisonState(resultValue(results[2]));
    setMilestoneState(resultValue(results[3]));
    setDetailErrors({
      position: resultError(results[0], "The current position could not load."),
      latest: resultError(results[1], "The latest check-in could not load."),
      comparison: resultError(results[2], "The comparison could not load."),
      milestone: resultError(results[3], "The milestone could not load."),
    });
    setCandidates(null);
    setCandidateError("");
    if (nextPrimary.state === "no_primary") {
      try {
        const nextCandidates = await loadGoalCandidates();
        if (sequence === loadSequence.current) setCandidates(nextCandidates);
      } catch (reason) {
        if (sequence === loadSequence.current) {
          setCandidateError(errorMessage(reason, "Goal candidates could not load."));
        }
      }
    }
    if (sequence === loadSequence.current) setBusy(false);
  }, []);

  const loadOpenedDetails = useCallback(async () => {
    const results = await Promise.allSettled([
      historyOpened.current ? loadGoalCheckIns() : Promise.resolve(null),
      provenanceOpened.current ? loadGoalProvenance() : Promise.resolve(null),
      candidatesOpened.current ? loadGoalCandidates() : Promise.resolve(null),
    ] as const);
    const [nextHistory, nextProvenance, nextCandidates] = results;
    if (nextHistory.status === "fulfilled" && nextHistory.value) {
      setHistory(nextHistory.value);
      setHistoryError("");
    } else if (nextHistory.status === "rejected") {
      setHistoryError(errorMessage(nextHistory.reason, "Check-in history could not load."));
    }
    if (nextProvenance.status === "fulfilled" && nextProvenance.value) {
      setProvenance(nextProvenance.value);
      setProvenanceError("");
    } else if (nextProvenance.status === "rejected") {
      setProvenanceError(errorMessage(nextProvenance.reason, "Source provenance could not load."));
    }
    if (nextCandidates.status === "fulfilled" && nextCandidates.value) {
      setCandidates(nextCandidates.value);
      setCandidateError("");
    } else if (nextCandidates.status === "rejected") {
      setCandidateError(errorMessage(nextCandidates.reason, "Other goals could not load."));
    }
  }, []);

  const reloadCompleteSurface = useCallback(async () => {
    await loadSurface();
    await loadOpenedDetails();
  }, [loadOpenedDetails, loadSurface]);

  useEffect(() => {
    void reloadCompleteSurface();
  }, [reloadCompleteSurface, reloadVersion]);

  const loadCandidateDetails = async () => {
    if (candidates) return;
    setCandidateError("");
    try {
      setCandidates(await loadGoalCandidates());
    } catch (reason) {
      setCandidateError(errorMessage(reason, "Other goals could not load."));
    }
  };

  const loadHistory = async (cursor?: string) => {
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const page = await loadGoalCheckIns(cursor);
      setHistory((current) => {
        if (!cursor || !current) {
          const checkIns = page.check_ins.slice(0, 25);
          const retained = new Set(checkIns.map((item) => item.check_in_id));
          return {
            ...page,
            check_ins: checkIns,
            comparisons: page.comparisons.filter((item) =>
              retained.has(item.current_check_in_id),
            ),
          };
        }
        const checkIns = [...current.check_ins, ...page.check_ins].slice(0, 25);
        const retained = new Set(checkIns.map((item) => item.check_in_id));
        return {
          ...page,
          check_ins: checkIns,
          comparisons: [...current.comparisons, ...page.comparisons].filter((item) =>
            retained.has(item.current_check_in_id),
          ),
        };
      });
    } catch (reason) {
      setHistoryError(errorMessage(reason, "Check-in history could not load."));
    } finally {
      setHistoryBusy(false);
    }
  };

  const loadProvenance = async () => {
    if (provenance || provenanceBusy) return;
    setProvenanceBusy(true);
    setProvenanceError("");
    try {
      setProvenance(await loadGoalProvenance());
    } catch (reason) {
      setProvenanceError(errorMessage(reason, "Source provenance could not load."));
    } finally {
      setProvenanceBusy(false);
    }
  };

  const choosePrimary = async (candidate: GoalProgramView) => {
    setSelectionBusy(true);
    setSelectionError("");
    setMessage("");
    try {
      await selectPrimaryGoal({
        goal_program_id: candidate.goal_program_id,
        expected_edit_token: candidate.edit_token,
      });
      await reloadCompleteSurface();
      setMessage("Primary goal selected.");
    } catch (reason) {
      if (reason instanceof GoalApiError && reason.status === 409) {
        setSelectionError("This goal changed before selection. Reload the choices and review them again.");
      } else {
        setSelectionError(errorMessage(reason, "The primary goal could not be selected."));
      }
    } finally {
      setSelectionBusy(false);
    }
  };

  const primary = primaryState?.state === "primary" ? primaryState.goal : null;
  const position = positionState?.state === "available" ? positionState.position : null;

  if (busy && !primaryState) {
    return (
      <section className="goals-loading panel" aria-labelledby="goals-loading-title">
        <span className="loading-mark">M</span>
        <div><h1 id="goals-loading-title">Goals</h1><p>Loading the current goal…</p></div>
      </section>
    );
  }

  if (pageError && !primaryState) {
    return (
      <section className="goals-recoverable panel" aria-labelledby="goals-error-title">
        <span className="eyebrow">Local goal data</span>
        <h1 id="goals-error-title">Goals could not load.</h1>
        <p>{pageError}</p>
        <button className="primary-button" onClick={() => void loadSurface()}>Try again</button>
      </section>
    );
  }

  if (primaryState?.state === "no_primary") {
    return (
      <div className="goals-view view-stack" aria-busy={busy} data-reduced-motion={reducedMotion}>
        <header className="goals-page-heading"><span className="eyebrow">Money Map</span><h1>Goals</h1></header>
        {message && <p className="goal-status-message" role="status">{message}</p>}
        {candidateError ? (
          <section className="goals-recoverable panel" aria-labelledby="candidate-error-title">
            <h2 id="candidate-error-title">Goal choices are unavailable.</h2>
            <p>{candidateError}</p>
            <button className="secondary-button" onClick={() => void loadSurface()}>Try again</button>
          </section>
        ) : candidates?.state === "selection_required" ? (
          <section className="goal-selection" aria-labelledby="goal-selection-title">
            <div className="goal-selection-heading">
              <h2 id="goal-selection-title">Choose the primary goal</h2>
              <p>Only one goal can be primary. Nothing is selected automatically.</p>
            </div>
            {selectionError && (
              <div className="goal-form-error" role="alert">
                {selectionError}
                <button className="text-button" onClick={() => void loadSurface()}>Reload goals</button>
              </div>
            )}
            <div className="goal-candidate-grid">
              {candidates.candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.goal_program_id}
                  candidate={candidate}
                  busy={selectionBusy}
                  onSelect={(next) => void choosePrimary(next)}
                />
              ))}
            </div>
          </section>
        ) : (
          <section className="goal-empty panel" aria-labelledby="goal-empty-title">
            <span className="empty-icon" aria-hidden="true">◎</span>
            <h2 id="goal-empty-title">No goal is ready to select.</h2>
            <p>Goals will stay here when an accepted goal program becomes available.</p>
          </section>
        )}
      </div>
    );
  }

  if (!primary) return null;

  const reserved = position?.reserved_for_goal.amount ?? primary.reserved_for_goal.amount;
  const available = position?.available_above_floor.amount ?? null;
  const pace = position?.required_funding_pace.amount ?? null;
  const observation = position ? `Observed ${formatDate(position.observed_on)}` : "Observation unavailable";

  return (
    <div className="goals-view view-stack" aria-busy={busy} data-reduced-motion={reducedMotion}>
      <header className="goals-page-heading"><span className="eyebrow">Money Map</span><h1>Goals</h1></header>
      {message && <p className="goal-status-message" role="status">{message}</p>}
      {(observationError || observationState) && (
        <p
          className={`goal-currentness goal-currentness-${observationError ? "unavailable" : observationState?.status}`}
          role={observationError || observationState?.retryable ? "alert" : "status"}
          data-observation-status={observationError ? "unavailable" : observationState?.status}
        >
          {observationError
            ? `${observationError} No new goal observation was saved. Use Update data to retry.`
            : observationState?.message}
        </p>
      )}
      <section className="goal-primary-card panel" aria-labelledby="primary-goal-title">
        <div className="goal-primary-heading">
          <div>
            <span className="goal-status">Primary goal</span>
            <h2 id="primary-goal-title">{primary.name}</h2>
            <p>{formatMoney(primary.target_amount.amount)} by {formatDate(primary.target_date)}</p>
          </div>
          <span className="goal-observation">{observation}</span>
        </div>
        <div className="goal-comparison-summary">
          <span>Since last financial change</span>
          <p className="goal-verdict">{verdictSentence(comparisonState, detailErrors.comparison)}</p>
        </div>
        <div className="goal-metrics" aria-label="Primary goal metrics">
          <GoalMetric label="Explicitly reserved" value={formatMoney(reserved)} />
          <GoalMetric label="Above protected floor" value={formatMoney(available)} />
          <GoalMetric label="Required monthly pace" value={formatMoney(pace)} />
        </div>
        <div className="goal-milestone">
          <span>Binding milestone</span>
          <strong>{milestoneSentence(milestoneState, detailErrors.milestone)}</strong>
        </div>
      </section>

      <section className="goals-disclosures" aria-label="Goal details and actions">
        <button ref={editButtonRef} className="secondary-button goal-edit-button" onClick={() => setEditing(true)}>
          Edit goal
        </button>
        <details className="goal-detail panel">
          <summary>Position and formulas</summary>
          {detailErrors.position && <p className="goal-detail-error">{detailErrors.position}</p>}
          <PositionDetails position={position} />
        </details>
        <details className="goal-detail panel">
          <summary>Comparison evidence</summary>
          <div className="goal-detail-body">
            {detailErrors.comparison && <p className="goal-detail-error">{detailErrors.comparison}</p>}
            {comparisonState?.state === "available" ? (
              <dl className="goal-component-list">
                {comparisonState.comparison.components.map((component) => (
                  <div key={component.component}>
                    <dt>{component.component.replaceAll("_", " ")}</dt>
                    <dd>{formatMoney(component.change.amount)}</dd>
                  </div>
                ))}
              </dl>
            ) : <p className="goal-detail-message">{verdictSentence(comparisonState, detailErrors.comparison)}</p>}
          </div>
        </details>
        <details
          className="goal-detail panel"
          onToggle={(event) => {
            if (event.currentTarget.open) historyOpened.current = true;
            if (event.currentTarget.open && !history && !historyBusy) void loadHistory();
          }}
        >
          <summary>Financial change timeline</summary>
          <div className="goal-detail-body">
            {detailErrors.latest && <p className="goal-detail-error">{detailErrors.latest}</p>}
            {historyError && <p className="goal-detail-error">{historyError}</p>}
            {history?.check_ins.length === 0 && <p className="goal-detail-message">No saved check-ins exist yet.</p>}
            {history && history.check_ins.length > 0 && (
              <ol className="goal-timeline">
                {history.check_ins.map((checkIn) => {
                  const comparison = history.comparisons.find(
                    (item) => item.current_check_in_id === checkIn.check_in_id,
                  );
                  return (
                    <li key={checkIn.check_in_id}>
                      <details className="goal-timeline-entry">
                        <summary>
                          <strong>{formatDate(checkIn.effective_observation_date)}</strong>
                          <span>
                            Accessible {comparison
                              ? formatMovement(comparisonAmount(comparison, "accessible_now"))
                              : "first saved observation"}
                          </span>
                          <span>
                            Goal {comparison
                              ? formatMovement(comparisonAmount(comparison, "goal_target"))
                              : formatMoney(checkIn.position.goal_target.amount)}
                            {" · "}Reserved {comparison
                              ? formatMovement(comparisonAmount(comparison, "reserved_for_goal"))
                              : formatMoney(checkIn.position.reserved_for_goal.amount)}
                          </span>
                          <small>{triggerLabel(checkIn.trigger)} · {formatSavedAt(checkIn.created_at)}</small>
                        </summary>
                        <div className="goal-timeline-evidence">
                          <dl className="goal-evidence-grid">
                            <div><dt>Accessible cash</dt><dd>{formatMoney(checkIn.position.accessible_cash.amount)}</dd></div>
                            <div><dt>Accessible investments</dt><dd>{formatMoney(checkIn.position.accessible_investments.amount)}</dd></div>
                            <div><dt>Tracked debt</dt><dd>{formatMoney(checkIn.position.tracked_debt.amount)}</dd></div>
                            <div><dt>Goal target</dt><dd>{formatMoney(checkIn.position.goal_target.amount)}</dd></div>
                            <div><dt>Protected floor</dt><dd>{formatMoney(checkIn.position.protected_cash_floor.amount)}</dd></div>
                            <div><dt>Reservation</dt><dd>{formatMoney(checkIn.position.reserved_for_goal.amount)}</dd></div>
                          </dl>
                          {comparison && (
                            <dl className="goal-component-list" aria-label={`Comparison components for ${formatDate(checkIn.effective_observation_date)}`}>
                              {comparison.components.map((component) => (
                                <div key={component.component}>
                                  <dt>{component.component.replaceAll("_", " ")}</dt>
                                  <dd>{formatMovement(component.change.amount)}</dd>
                                </div>
                              ))}
                            </dl>
                          )}
                        </div>
                      </details>
                    </li>
                  );
                })}
              </ol>
            )}
            {history?.next_cursor && history.check_ins.length < 25 && (
              <button className="secondary-button" disabled={historyBusy} onClick={() => void loadHistory(history.next_cursor ?? undefined)}>
                {historyBusy ? "Loading…" : "Load older check-ins"}
              </button>
            )}
            {historyBusy && !history && <p className="goal-detail-message">Loading check-ins…</p>}
          </div>
        </details>
        <details
          className="goal-detail panel"
          onToggle={(event) => {
            if (event.currentTarget.open) provenanceOpened.current = true;
            if (event.currentTarget.open) void loadProvenance();
          }}
        >
          <summary>Source provenance</summary>
          <div className="goal-detail-body">
            {provenanceError && <p className="goal-detail-error">{provenanceError}</p>}
            {provenanceBusy && !provenance && <p className="goal-detail-message">Loading source evidence…</p>}
            {provenance?.state === "available" && (
              <>
                <div className="goal-fingerprint"><span>Source fingerprint</span><code>{provenance.source_fingerprint}</code></div>
                <ul className="goal-source-records">
                  {provenance.source_material.source_records.map((record, index) => (
                    <li key={`${record.kind}-${record.effective_date}-${index}`}>
                      <strong>{record.kind.replaceAll("_", " ")}</strong>
                      <span>{formatDate(record.effective_date)}</span>
                      <ul>
                        {record.money_facts.map((fact) => (
                          <li key={`${fact.field}-${fact.amount}`}>{fact.field.replaceAll("_", " ")}: {formatMoney(fact.amount)}</li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </details>
        <details
          className="goal-detail panel"
          onToggle={(event) => {
            if (event.currentTarget.open) candidatesOpened.current = true;
            if (event.currentTarget.open) void loadCandidateDetails();
          }}
        >
          <summary>Other goals</summary>
          <div className="goal-detail-body">
            {candidateError && <p className="goal-detail-error">{candidateError}</p>}
            {candidates?.state === "no_candidates" && <p className="goal-detail-message">No other active goals are available.</p>}
            {candidates?.candidates.map((candidate) => (
              <CandidateCard
                key={candidate.goal_program_id}
                candidate={candidate}
                busy={selectionBusy}
                onSelect={(next) => void choosePrimary(next)}
              />
            ))}
          </div>
        </details>
      </section>

      {editing && (
        <GoalEditDialog
          goal={primary}
          invoker={editButtonRef}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            await reloadCompleteSurface();
            setEditing(false);
            setMessage("Goal updated.");
          }}
          onReloadConflict={reloadCompleteSurface}
        />
      )}
    </div>
  );
}
