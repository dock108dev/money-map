/** Pure Money Map v2.1 cash-flow contracts. This module has no runtime API or UI wiring. */

import type { EvidenceClass, ExactDecimalString } from "./v2-contracts";

export const V21_CONTRACT_VERSION = "money-map-v2.1-contract-v1" as const;

export type PeriodKind =
  | "all_imported_history"
  | "trailing_12_months"
  | "year_to_date"
  | "custom_range";
export type PartialPeriodState = "full" | "partial";
export type CoverageCompleteness = "complete" | "incomplete";
export type FreshnessState = "current" | "stale" | "incomplete";
export type V21MoneyDerivation =
  | "effective_recurring_take_home"
  | "money_in"
  | "money_out"
  | "net_cash_flow"
  | "current_monthly_margin"
  | "stabilization_gap"
  | "remaining_target"
  | "required_goal_pace"
  | "combined_monthly_improvement"
  | "preview_total_reservation"
  | "preview_remaining_target"
  | "preview_required_goal_pace"
  | "adjusted_recurring_take_home"
  | "adjusted_recurring_outflow"
  | "adjusted_monthly_margin"
  | "adjusted_stabilization_gap"
  | "remaining_combined_monthly_improvement"
  | "estimated_monthly_gross_income"
  | "estimated_annual_gross_income"
  | "recurring_outflow_median"
  | "recurring_outflow_typical_monthly";

export interface V21EvidencedMoney {
  amount: ExactDecimalString | null;
  evidence: EvidenceClass;
  source_refs: string[];
  derivation: V21MoneyDerivation | null;
  unavailable_reason: string | null;
}

export interface SelectedPeriod {
  kind: PeriodKind;
  start_date: string;
  end_date: string;
  as_of_date: string;
}

export interface CoverageState {
  coverage_start: string;
  coverage_end: string;
  transaction_count: number;
  opening_month: PartialPeriodState;
  closing_month: PartialPeriodState;
  completeness: CoverageCompleteness;
  incomplete_reasons: string[];
}

export interface Freshness {
  state: FreshnessState;
  observed_at: string;
  stale_sources: string[];
  warnings: string[];
}

export interface ExcludedTransferTotals {
  matched_owned_account_amount: V21EvidencedMoney;
  matched_owned_account_count: number;
  internal_transfer_amount: V21EvidencedMoney;
  internal_transfer_count: number;
}

export interface CashFlowAmounts {
  external_cash_inflows: V21EvidencedMoney;
  interest_received: V21EvidencedMoney;
  money_in: V21EvidencedMoney;
  external_cash_outflows: V21EvidencedMoney;
  fees_paid: V21EvidencedMoney;
  money_out: V21EvidencedMoney;
  net_cash_flow: V21EvidencedMoney;
}

export interface MonthlyCashFlowPoint {
  month: string;
  start_date: string;
  end_date: string;
  partial: boolean;
  transaction_count: number;
  amounts: CashFlowAmounts;
  transfers_excluded: ExcludedTransferTotals;
}

export interface CashFlowPeriodResult {
  period: SelectedPeriod;
  coverage: CoverageState;
  totals: CashFlowAmounts;
  monthly_points: MonthlyCashFlowPoint[];
  transfers_excluded: ExcludedTransferTotals;
  freshness: Freshness;
  warnings: string[];
}

export type MarginState = "negative" | "zero" | "positive" | "unavailable";

export interface CurrentRecurringFacts {
  as_of_date: string;
  effective_recurring_take_home: V21EvidencedMoney;
  observed_recurring_monthly_outflow: V21EvidencedMoney;
  current_monthly_margin: V21EvidencedMoney;
  stabilization_gap: V21EvidencedMoney;
  margin_state: MarginState;
  warnings: string[];
}

export type GoalState =
  | "active"
  | "completed"
  | "expired_unfinished"
  | "cash_floor_breach"
  | "unavailable";

export interface RequiredGoalPaceReference {
  goal_program_id: string;
  observed_on: string;
  target_date: string;
  goal_target: V21EvidencedMoney;
  reserved_for_goal: V21EvidencedMoney;
  remaining_target: V21EvidencedMoney;
  accessible_cash: V21EvidencedMoney;
  protected_cash_floor: V21EvidencedMoney;
  funding_months: string;
  goal_state: GoalState;
  required_goal_pace: V21EvidencedMoney;
  calculation_version: "goal-arithmetic-v1";
}

export interface V21ContractVector {
  vector_id: string;
  covers: string[];
  cash_flow: CashFlowPeriodResult;
  recurring: CurrentRecurringFacts;
  goal: RequiredGoalPaceReference;
  combined_monthly_improvement: V21EvidencedMoney;
  contract_version: typeof V21_CONTRACT_VERSION;
}

export interface GoalGapPreviewRequest {
  target_date: string | null;
  additional_reservation: ExactDecimalString;
  monthly_spending_reduction: ExactDecimalString;
  monthly_after_tax_income: ExactDecimalString;
}

export interface GrossIncomeContextAvailable {
  state: "available";
  effective_take_home_ratio: string;
  ratio_precision: "0.000000000001";
  supporting_payroll_date: string;
  source_ref: string;
  estimated_monthly_gross_income_needed: V21EvidencedMoney;
  estimated_annual_gross_income_needed: V21EvidencedMoney;
  estimate_label: "Estimate based on the latest supported paycheck";
  disclaimer: "Not a tax-return estimate";
}

export interface GrossIncomeContextUnavailable {
  state: "unavailable";
  reason: string;
}

export type GrossIncomeContext =
  | GrossIncomeContextAvailable
  | GrossIncomeContextUnavailable;

export interface GoalGapPreviewAvailable {
  state: "available";
  goal_program_id: string;
  goal_name: string;
  observed_on: string;
  baseline_current_recurring_facts: CurrentRecurringFacts;
  baseline_goal_pace_reference: RequiredGoalPaceReference;
  baseline_combined_monthly_improvement: V21EvidencedMoney;
  preview_target_date: string;
  existing_explicit_reservation: V21EvidencedMoney;
  additional_draft_reservation: V21EvidencedMoney;
  preview_total_reservation: V21EvidencedMoney;
  preview_remaining_target: V21EvidencedMoney;
  exact_funding_months: string;
  preview_required_goal_pace: V21EvidencedMoney;
  draft_spending_reduction: V21EvidencedMoney;
  draft_after_tax_income: V21EvidencedMoney;
  adjusted_recurring_take_home: V21EvidencedMoney;
  adjusted_recurring_outflow: V21EvidencedMoney;
  adjusted_monthly_margin: V21EvidencedMoney;
  adjusted_stabilization_gap: V21EvidencedMoney;
  remaining_combined_monthly_improvement: V21EvidencedMoney;
  gross_income_context: GrossIncomeContext;
  warnings: string[];
  calculation_version: "goal-arithmetic-v1";
  contract_version: typeof V21_CONTRACT_VERSION;
}

export interface GoalGapPreviewUnavailable {
  state: "no_primary" | "unavailable";
  observed_on: string;
  reason: string;
  warnings: string[];
  calculation_version: "goal-arithmetic-v1";
  contract_version: typeof V21_CONTRACT_VERSION;
}

export type GoalGapPreviewResponse =
  | GoalGapPreviewAvailable
  | GoalGapPreviewUnavailable;

export type RecurringOutflowCadence = "monthly" | "biweekly" | "weekly";

export interface RecurringOutflowAmountRange {
  minimum: V21EvidencedMoney;
  maximum: V21EvidencedMoney;
}

export interface RecurringOutflowCandidate {
  candidate_id: string;
  observed_description: string;
  safe_account_label: string;
  cadence: RecurringOutflowCadence;
  occurrence_count: number;
  first_observed_date: string;
  last_observed_date: string;
  median_observed_amount: V21EvidencedMoney;
  typical_monthly_amount: V21EvidencedMoney;
  amount_range: RecurringOutflowAmountRange;
  confidence: "high";
  source_refs: string[];
  coverage_months: string[];
}

export interface RecurringOutflowCandidateList {
  state: "available" | "empty" | "unavailable";
  observed_on: string;
  candidates: RecurringOutflowCandidate[];
  reason: string | null;
  warnings: string[];
  contract_version: typeof V21_CONTRACT_VERSION;
}

const evidenceClasses: EvidenceClass[] = [
  "observed",
  "derived",
  "user_entered",
  "assumed",
  "unavailable",
];
const derivations: V21MoneyDerivation[] = [
  "effective_recurring_take_home",
  "money_in",
  "money_out",
  "net_cash_flow",
  "current_monthly_margin",
  "stabilization_gap",
  "remaining_target",
  "required_goal_pace",
  "combined_monthly_improvement",
  "preview_total_reservation",
  "preview_remaining_target",
  "preview_required_goal_pace",
  "adjusted_recurring_take_home",
  "adjusted_recurring_outflow",
  "adjusted_monthly_margin",
  "adjusted_stabilization_gap",
  "remaining_combined_monthly_improvement",
  "estimated_monthly_gross_income",
  "estimated_annual_gross_income",
  "recurring_outflow_median",
  "recurring_outflow_typical_monthly",
];
const moneyPattern = /^-?(?:0|[1-9]\d*)\.\d{2}$/;
const datePattern = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;

export function parseExactMoneyCents(value: unknown): bigint {
  if (typeof value !== "string" || !moneyPattern.test(value)) {
    throw new Error("Money must be a finite exact two-place decimal string");
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, cents] = unsigned.split(".");
  const result = BigInt(whole) * 100n + BigInt(cents);
  return negative ? -result : result;
}

export function validateV21ContractVector(value: unknown): V21ContractVector {
  const vector = record(value, "contract vector");
  expectString(vector.vector_id, "vector_id");
  const covers = stringArray(vector.covers, "covers");
  if (covers.length === 0) throw new Error("covers must not be empty");
  if (vector.contract_version !== V21_CONTRACT_VERSION) {
    throw new Error("Unexpected v2.1 contract version");
  }
  const cashFlow = validateCashFlowPeriodResult(vector.cash_flow);
  const recurring = validateRecurringFacts(vector.recurring);
  const goal = validateGoal(vector.goal);
  const combined = validateMoney(
    vector.combined_monthly_improvement,
    "combined_monthly_improvement",
  );

  const margin = optionalCents(recurring.current_monthly_margin);
  const pace = optionalCents(goal.required_goal_pace);
  if (margin === null || pace === null) {
    requireUnavailable(combined, "combined_monthly_improvement");
  } else {
    requireDerived(combined, "combined_monthly_improvement", "combined_monthly_improvement");
    if (requiredCents(combined, "combined_monthly_improvement") !== max(pace - margin, 0n)) {
      throw new Error("Combined monthly improvement must use pace minus recurring margin");
    }
  }

  return {
    vector_id: vector.vector_id as string,
    covers,
    cash_flow: cashFlow,
    recurring,
    goal,
    combined_monthly_improvement: combined,
    contract_version: V21_CONTRACT_VERSION,
  };
}

export function isV21ContractVector(value: unknown): value is V21ContractVector {
  try {
    validateV21ContractVector(value);
    return true;
  } catch {
    return false;
  }
}

export function validateCashFlowPeriodResult(value: unknown): CashFlowPeriodResult {
  const result = record(value, "cash_flow");
  const period = validatePeriod(result.period);
  const coverage = validateCoverage(result.coverage);
  const totals = validateAmounts(result.totals, "totals");
  const points = array(result.monthly_points, "monthly_points").map((point, index) =>
    validateMonthlyPoint(point, `monthly_points[${index}]`),
  );
  if (points.length === 0) throw new Error("monthly_points must not be empty");
  const transfers = validateTransfers(result.transfers_excluded, "transfers_excluded");
  const freshness = validateFreshness(result.freshness);
  const warnings = stringArray(result.warnings, "cash_flow.warnings");

  if (
    dateOrdinal(period.start_date) > dateOrdinal(coverage.coverage_start) ||
    dateOrdinal(coverage.coverage_start) > dateOrdinal(coverage.coverage_end) ||
    dateOrdinal(coverage.coverage_end) > dateOrdinal(period.end_date)
  ) {
    throw new Error("Coverage dates must be inside the selected period");
  }
  if (
    period.kind === "all_imported_history" &&
    (coverage.coverage_start !== period.start_date || coverage.coverage_end !== period.end_date)
  ) {
    throw new Error("All imported history must use reported coverage boundaries");
  }
  points.forEach((point, index) => {
    if (
      dateOrdinal(point.start_date) < dateOrdinal(period.start_date) ||
      dateOrdinal(point.end_date) > dateOrdinal(period.end_date)
    ) {
      throw new Error("Monthly points must stay inside the selected period");
    }
    if (index > 0 && dateOrdinal(point.start_date) <= dateOrdinal(points[index - 1].end_date)) {
      throw new Error("Monthly points must be ordered and non-overlapping");
    }
  });
  if (coverage.opening_month !== (period.start_date.endsWith("-01") ? "full" : "partial")) {
    throw new Error("Opening partial state must match the first monthly point");
  }
  const periodEnd = new Date(`${period.end_date}T00:00:00Z`);
  const periodEndLastDay = new Date(
    Date.UTC(periodEnd.getUTCFullYear(), periodEnd.getUTCMonth() + 1, 0),
  ).getUTCDate();
  if (
    coverage.closing_month !==
    (Number(period.end_date.slice(8, 10)) === periodEndLastDay ? "full" : "partial")
  ) {
    throw new Error("Closing partial state must match the last monthly point");
  }

  const amountFields: (keyof CashFlowAmounts)[] = [
    "external_cash_inflows",
    "interest_received",
    "money_in",
    "external_cash_outflows",
    "fees_paid",
    "money_out",
    "net_cash_flow",
  ];
  amountFields.forEach((field) => {
    const monthly = points.reduce((sum, point) => sum + requiredCents(point.amounts[field], field), 0n);
    if (monthly !== requiredCents(totals[field], field)) {
      throw new Error(`Monthly ${field} values must reconcile exactly to period totals`);
    }
  });
  reconcileTransfers(points, transfers);
  if (points.reduce((sum, point) => sum + point.transaction_count, 0) !== coverage.transaction_count) {
    throw new Error("Monthly transaction counts must reconcile to coverage");
  }
  return {
    period,
    coverage,
    totals,
    monthly_points: points,
    transfers_excluded: transfers,
    freshness,
    warnings,
  };
}

export function isCashFlowPeriodResult(value: unknown): value is CashFlowPeriodResult {
  try {
    validateCashFlowPeriodResult(value);
    return true;
  } catch {
    return false;
  }
}

export function validateGoalGapPreviewResponse(value: unknown): GoalGapPreviewResponse {
  const result = record(value, "goal-gap preview");
  const state = oneOf(result.state, ["available", "no_primary", "unavailable"], "state");
  const observedOn = dateString(result.observed_on, "observed_on");
  if (result.calculation_version !== "goal-arithmetic-v1") {
    throw new Error("Unexpected goal-gap calculation version");
  }
  if (result.contract_version !== V21_CONTRACT_VERSION) {
    throw new Error("Unexpected v2.1 contract version");
  }
  const warnings = stringArray(result.warnings, "goal-gap warnings");
  if (state !== "available") {
    return {
      state,
      observed_on: observedOn,
      reason: expectString(result.reason, "goal-gap unavailable reason"),
      warnings,
      calculation_version: "goal-arithmetic-v1",
      contract_version: V21_CONTRACT_VERSION,
    };
  }

  const goalProgramId = expectString(result.goal_program_id, "goal_program_id");
  if (!/^goal_[a-z0-9_]+$/.test(goalProgramId)) throw new Error("Invalid goal program ID");
  const recurring = validateRecurringFacts(result.baseline_current_recurring_facts);
  const goal = validateGoal(result.baseline_goal_pace_reference);
  if (goal.goal_program_id !== goalProgramId || goal.observed_on !== observedOn) {
    throw new Error("Preview and baseline goal identity must agree");
  }
  const baselineCombined = validateMoney(
    result.baseline_combined_monthly_improvement,
    "baseline combined monthly improvement",
  );
  const margin = optionalCents(recurring.current_monthly_margin);
  const baselinePace = optionalCents(goal.required_goal_pace);
  validateOptionalDerivedExact(
    baselineCombined,
    "combined_monthly_improvement",
    margin === null || baselinePace === null ? null : max(baselinePace - margin, 0n),
    "baseline combined monthly improvement",
  );

  const existing = validateMoney(result.existing_explicit_reservation, "existing reservation");
  const additional = validateMoney(result.additional_draft_reservation, "additional reservation");
  const total = validateMoney(result.preview_total_reservation, "preview total reservation");
  const remaining = validateMoney(result.preview_remaining_target, "preview remaining target");
  const previewPace = validateMoney(result.preview_required_goal_pace, "preview required pace");
  const reduction = validateMoney(result.draft_spending_reduction, "draft spending reduction");
  const income = validateMoney(result.draft_after_tax_income, "draft after-tax income");
  const adjustedTakeHome = validateMoney(
    result.adjusted_recurring_take_home,
    "adjusted recurring take-home",
  );
  const adjustedOutflow = validateMoney(
    result.adjusted_recurring_outflow,
    "adjusted recurring outflow",
  );
  const adjustedMargin = validateMoney(result.adjusted_monthly_margin, "adjusted monthly margin");
  const adjustedGap = validateMoney(
    result.adjusted_stabilization_gap,
    "adjusted stabilization gap",
  );
  const remainingCombined = validateMoney(
    result.remaining_combined_monthly_improvement,
    "remaining combined monthly improvement",
  );
  [existing, additional, reduction, income].forEach((item) =>
    requireEvidence(item, "user_entered", "goal-gap draft"),
  );
  const existingCents = requiredCents(existing, "existing reservation");
  const additionalCents = requiredCents(additional, "additional reservation");
  const reductionCents = requiredCents(reduction, "draft spending reduction");
  const incomeCents = requiredCents(income, "draft after-tax income");
  if ([existingCents, additionalCents, reductionCents, incomeCents].some((item) => item < 0n)) {
    throw new Error("Goal-gap draft values cannot be negative");
  }
  validateOptionalDerivedExact(
    total,
    "preview_total_reservation",
    existingCents + additionalCents,
    "preview total reservation",
  );
  const targetCents = requiredCents(goal.goal_target, "goal target");
  validateOptionalDerivedExact(
    remaining,
    "preview_remaining_target",
    max(targetCents - requiredCents(total, "preview total reservation"), 0n),
    "preview remaining target",
  );
  const previewPaceCents = optionalCents(previewPace);
  if (previewPaceCents === null) requireUnavailable(previewPace, "preview required pace");
  else requireDerived(previewPace, "preview_required_goal_pace", "preview required pace");

  const takeHomeCents = optionalCents(recurring.effective_recurring_take_home);
  const outflowCents = optionalCents(recurring.observed_recurring_monthly_outflow);
  const adjustedTakeHomeExpected =
    takeHomeCents === null ? null : takeHomeCents + incomeCents;
  const adjustedOutflowExpected =
    outflowCents === null ? null : outflowCents - reductionCents;
  if (adjustedOutflowExpected !== null && adjustedOutflowExpected < 0n) {
    throw new Error("Draft spending reduction exceeds recurring outflow");
  }
  validateOptionalDerivedExact(
    adjustedTakeHome,
    "adjusted_recurring_take_home",
    adjustedTakeHomeExpected,
    "adjusted recurring take-home",
  );
  validateOptionalDerivedExact(
    adjustedOutflow,
    "adjusted_recurring_outflow",
    adjustedOutflowExpected,
    "adjusted recurring outflow",
  );
  const adjustedMarginExpected =
    adjustedTakeHomeExpected === null || adjustedOutflowExpected === null
      ? null
      : adjustedTakeHomeExpected - adjustedOutflowExpected;
  validateOptionalDerivedExact(
    adjustedMargin,
    "adjusted_monthly_margin",
    adjustedMarginExpected,
    "adjusted monthly margin",
  );
  validateOptionalDerivedExact(
    adjustedGap,
    "adjusted_stabilization_gap",
    adjustedMarginExpected === null ? null : max(-adjustedMarginExpected, 0n),
    "adjusted stabilization gap",
  );
  validateOptionalDerivedExact(
    remainingCombined,
    "remaining_combined_monthly_improvement",
    previewPaceCents === null || adjustedMarginExpected === null
      ? null
      : max(previewPaceCents - adjustedMarginExpected, 0n),
    "remaining combined monthly improvement",
  );

  const grossIncomeContext = validateGrossIncomeContext(result.gross_income_context);
  return {
    state: "available",
    goal_program_id: goalProgramId,
    goal_name: expectString(result.goal_name, "goal_name"),
    observed_on: observedOn,
    baseline_current_recurring_facts: recurring,
    baseline_goal_pace_reference: goal,
    baseline_combined_monthly_improvement: baselineCombined,
    preview_target_date: dateString(result.preview_target_date, "preview_target_date"),
    existing_explicit_reservation: existing,
    additional_draft_reservation: additional,
    preview_total_reservation: total,
    preview_remaining_target: remaining,
    exact_funding_months: decimal12String(result.exact_funding_months, "exact_funding_months"),
    preview_required_goal_pace: previewPace,
    draft_spending_reduction: reduction,
    draft_after_tax_income: income,
    adjusted_recurring_take_home: adjustedTakeHome,
    adjusted_recurring_outflow: adjustedOutflow,
    adjusted_monthly_margin: adjustedMargin,
    adjusted_stabilization_gap: adjustedGap,
    remaining_combined_monthly_improvement: remainingCombined,
    gross_income_context: grossIncomeContext,
    warnings,
    calculation_version: "goal-arithmetic-v1",
    contract_version: V21_CONTRACT_VERSION,
  };
}

export function isGoalGapPreviewResponse(value: unknown): value is GoalGapPreviewResponse {
  try {
    validateGoalGapPreviewResponse(value);
    return true;
  } catch {
    return false;
  }
}

export function validateRecurringOutflowCandidateList(
  value: unknown,
): RecurringOutflowCandidateList {
  const result = record(value, "recurring outflow candidates");
  const state = oneOf(result.state, ["available", "empty", "unavailable"], "candidate state");
  if (result.contract_version !== V21_CONTRACT_VERSION) {
    throw new Error("Unexpected v2.1 contract version");
  }
  const rawCandidates = array(result.candidates, "candidates");
  const candidates = rawCandidates.map((item, index) => validateRecurringCandidate(item, index));
  const reason = result.reason === null ? null : expectString(result.reason, "candidate reason");
  if (state === "available" && (candidates.length === 0 || reason !== null)) {
    throw new Error("Available candidate state is malformed");
  }
  if (state === "empty" && (candidates.length > 0 || reason !== null)) {
    throw new Error("Empty candidate state is malformed");
  }
  if (state === "unavailable" && (candidates.length > 0 || reason === null)) {
    throw new Error("Unavailable candidate state is malformed");
  }
  if (new Set(candidates.map((item) => item.candidate_id)).size !== candidates.length) {
    throw new Error("Candidate IDs must be unique");
  }
  return {
    state,
    observed_on: dateString(result.observed_on, "candidate observed_on"),
    candidates,
    reason,
    warnings: stringArray(result.warnings, "candidate warnings"),
    contract_version: V21_CONTRACT_VERSION,
  };
}

export function isRecurringOutflowCandidateList(
  value: unknown,
): value is RecurringOutflowCandidateList {
  try {
    validateRecurringOutflowCandidateList(value);
    return true;
  } catch {
    return false;
  }
}

function validateGrossIncomeContext(value: unknown): GrossIncomeContext {
  const context = record(value, "gross-income context");
  const state = oneOf(context.state, ["available", "unavailable"], "gross-income state");
  if (state === "unavailable") {
    return { state, reason: expectString(context.reason, "gross-income unavailable reason") };
  }
  const ratio = decimal12String(context.effective_take_home_ratio, "take-home ratio");
  const ratioUnits = BigInt(ratio.replace(".", ""));
  if (ratioUnits <= 0n) {
    throw new Error("Take-home ratio must be positive");
  }
  if (context.ratio_precision !== "0.000000000001") {
    throw new Error("Unexpected take-home ratio precision");
  }
  const monthly = validateMoney(
    context.estimated_monthly_gross_income_needed,
    "estimated monthly gross income",
  );
  const annual = validateMoney(
    context.estimated_annual_gross_income_needed,
    "estimated annual gross income",
  );
  requireDerived(monthly, "estimated_monthly_gross_income", "estimated monthly gross income");
  requireDerived(annual, "estimated_annual_gross_income", "estimated annual gross income");
  if (requiredCents(annual, "annual gross") !== requiredCents(monthly, "monthly gross") * 12n) {
    throw new Error("Annual gross estimate must equal monthly gross times twelve");
  }
  const sourceRef = expectString(context.source_ref, "gross-income source_ref");
  if (!monthly.source_refs.includes(sourceRef)) {
    throw new Error("Gross estimate must retain its payroll source reference");
  }
  if (
    context.estimate_label !== "Estimate based on the latest supported paycheck" ||
    context.disclaimer !== "Not a tax-return estimate"
  ) {
    throw new Error("Gross-income estimate labels are invalid");
  }
  return {
    state,
    effective_take_home_ratio: ratio,
    ratio_precision: "0.000000000001",
    supporting_payroll_date: dateString(
      context.supporting_payroll_date,
      "supporting_payroll_date",
    ),
    source_ref: sourceRef,
    estimated_monthly_gross_income_needed: monthly,
    estimated_annual_gross_income_needed: annual,
    estimate_label: "Estimate based on the latest supported paycheck",
    disclaimer: "Not a tax-return estimate",
  };
}

function validateRecurringCandidate(
  value: unknown,
  index: number,
): RecurringOutflowCandidate {
  const candidate = record(value, `candidates[${index}]`);
  const candidateId = expectString(candidate.candidate_id, "candidate_id");
  if (!/^candidate_[0-9a-f]{24}$/.test(candidateId)) throw new Error("Invalid candidate ID");
  const cadence = oneOf(candidate.cadence, ["monthly", "biweekly", "weekly"], "cadence");
  const sourceRefs = stringArray(candidate.source_refs, "candidate source_refs");
  const coverageMonths = stringArray(candidate.coverage_months, "candidate coverage_months");
  if (coverageMonths.length < 3 || coverageMonths.some((month) => !/^\d{4}-(?:0[1-9]|1[0-2])$/.test(month))) {
    throw new Error("Candidate needs at least three valid coverage months");
  }
  const occurrenceCount = nonnegativeInteger(candidate.occurrence_count, "occurrence_count");
  if (occurrenceCount !== sourceRefs.length) {
    throw new Error("Candidate occurrence count must match source evidence");
  }
  const median = validateMoney(candidate.median_observed_amount, "candidate median");
  const typical = validateMoney(candidate.typical_monthly_amount, "candidate typical monthly");
  requireDerived(median, "recurring_outflow_median", "candidate median");
  requireDerived(typical, "recurring_outflow_typical_monthly", "candidate typical monthly");
  const amountRange = record(candidate.amount_range, "candidate amount range");
  const minimum = validateMoney(amountRange.minimum, "candidate minimum");
  const maximum = validateMoney(amountRange.maximum, "candidate maximum");
  requireEvidence(minimum, "observed", "candidate minimum");
  requireEvidence(maximum, "observed", "candidate maximum");
  const medianCents = requiredCents(median, "candidate median");
  if (
    requiredCents(minimum, "candidate minimum") > medianCents ||
    medianCents > requiredCents(maximum, "candidate maximum")
  ) {
    throw new Error("Candidate median must be inside its amount range");
  }
  const expectedTypical =
    cadence === "monthly"
      ? medianCents
      : roundDivideHalfUp(medianCents * (cadence === "biweekly" ? 26n : 52n), 12n);
  if (requiredCents(typical, "candidate typical monthly") !== expectedTypical) {
    throw new Error("Candidate typical monthly amount does not match cadence");
  }
  if (candidate.confidence !== "high") throw new Error("Only high-confidence candidates are valid");
  const first = dateString(candidate.first_observed_date, "first_observed_date");
  const last = dateString(candidate.last_observed_date, "last_observed_date");
  if (dateOrdinal(first) > dateOrdinal(last)) throw new Error("Candidate dates are reversed");
  return {
    candidate_id: candidateId,
    observed_description: expectString(candidate.observed_description, "observed_description"),
    safe_account_label: expectString(candidate.safe_account_label, "safe_account_label"),
    cadence,
    occurrence_count: occurrenceCount,
    first_observed_date: first,
    last_observed_date: last,
    median_observed_amount: median,
    typical_monthly_amount: typical,
    amount_range: { minimum, maximum },
    confidence: "high",
    source_refs: sourceRefs,
    coverage_months: coverageMonths,
  };
}

function validateOptionalDerivedExact(
  value: V21EvidencedMoney,
  derivation: V21MoneyDerivation,
  expected: bigint | null,
  label: string,
): void {
  if (expected === null) {
    requireUnavailable(value, label);
    return;
  }
  requireDerived(value, derivation, label);
  if (requiredCents(value, label) !== expected) {
    throw new Error(`${label} does not reconcile`);
  }
}

function decimal12String(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d*)\.\d{12}$/.test(value)) {
    throw new Error(`${label} must be a nonnegative twelve-place decimal string`);
  }
  return value;
}

function roundDivideHalfUp(numerator: bigint, denominator: bigint): bigint {
  if (numerator < 0n || denominator <= 0n) throw new Error("Positive exact division required");
  return (numerator * 2n + denominator) / (denominator * 2n);
}

function validatePeriod(value: unknown): SelectedPeriod {
  const period = record(value, "period");
  const kinds: PeriodKind[] = [
    "all_imported_history",
    "trailing_12_months",
    "year_to_date",
    "custom_range",
  ];
  if (!kinds.includes(period.kind as PeriodKind)) throw new Error("Unknown period kind");
  const start = dateString(period.start_date, "start_date");
  const end = dateString(period.end_date, "end_date");
  const asOf = dateString(period.as_of_date, "as_of_date");
  if (dateOrdinal(start) > dateOrdinal(end) || dateOrdinal(end) > dateOrdinal(asOf)) {
    throw new Error("Selected period dates are invalid");
  }
  if (period.kind === "trailing_12_months") {
    const asOfDate = new Date(`${asOf}T00:00:00Z`);
    const expected = new Date(Date.UTC(asOfDate.getUTCFullYear(), asOfDate.getUTCMonth() - 11, 1));
    if (start !== expected.toISOString().slice(0, 10) || end !== asOf) {
      throw new Error("Trailing-12 period must cover twelve calendar-month rows");
    }
  }
  if (period.kind === "year_to_date" && start !== `${asOf.slice(0, 4)}-01-01`) {
    throw new Error("Year-to-date period must begin January 1");
  }
  return { kind: period.kind as PeriodKind, start_date: start, end_date: end, as_of_date: asOf };
}

function validateCoverage(value: unknown): CoverageState {
  const coverage = record(value, "coverage");
  const start = dateString(coverage.coverage_start, "coverage_start");
  const end = dateString(coverage.coverage_end, "coverage_end");
  if (dateOrdinal(start) > dateOrdinal(end)) throw new Error("Coverage dates are invalid");
  const transactionCount = nonnegativeInteger(coverage.transaction_count, "transaction_count");
  const opening = oneOf(coverage.opening_month, ["full", "partial"], "opening_month");
  const closing = oneOf(coverage.closing_month, ["full", "partial"], "closing_month");
  const completeness = oneOf(
    coverage.completeness,
    ["complete", "incomplete"],
    "completeness",
  );
  const reasons = stringArray(coverage.incomplete_reasons, "incomplete_reasons");
  if (completeness === "complete" && reasons.length > 0) {
    throw new Error("Complete coverage cannot have incomplete reasons");
  }
  if (completeness === "incomplete" && reasons.length === 0) {
    throw new Error("Incomplete coverage requires a reason");
  }
  return {
    coverage_start: start,
    coverage_end: end,
    transaction_count: transactionCount,
    opening_month: opening,
    closing_month: closing,
    completeness,
    incomplete_reasons: reasons,
  };
}

function validateFreshness(value: unknown): Freshness {
  const freshness = record(value, "freshness");
  const state = oneOf(freshness.state, ["current", "stale", "incomplete"], "freshness.state");
  const observedAt = expectString(freshness.observed_at, "observed_at");
  if (Number.isNaN(Date.parse(observedAt)) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(observedAt)) {
    throw new Error("Freshness time must be timezone-aware");
  }
  const stale = stringArray(freshness.stale_sources, "stale_sources");
  const warnings = stringArray(freshness.warnings, "freshness.warnings");
  if (state === "current" && stale.length > 0) throw new Error("Current evidence cannot be stale");
  if (state === "stale" && stale.length === 0) throw new Error("Stale evidence requires a source");
  return { state, observed_at: observedAt, stale_sources: stale, warnings };
}

function validateMonthlyPoint(value: unknown, label: string): MonthlyCashFlowPoint {
  const point = record(value, label);
  const month = expectString(point.month, `${label}.month`);
  if (!/^\d{4}-(?:0[1-9]|1[0-2])$/.test(month)) throw new Error("Invalid monthly label");
  const start = dateString(point.start_date, `${label}.start_date`);
  const end = dateString(point.end_date, `${label}.end_date`);
  if (start.slice(0, 7) !== month || end.slice(0, 7) !== month || dateOrdinal(start) > dateOrdinal(end)) {
    throw new Error("Monthly point must stay within its labeled calendar month");
  }
  if (typeof point.partial !== "boolean") throw new Error("partial must be boolean");
  const endDate = new Date(`${end}T00:00:00Z`);
  const lastDay = new Date(
    Date.UTC(endDate.getUTCFullYear(), endDate.getUTCMonth() + 1, 0),
  ).getUTCDate();
  const whole = start.endsWith("-01") && Number(end.slice(8, 10)) === lastDay;
  if (point.partial === whole) throw new Error("Partial flag must match covered dates");
  const transactionCount = nonnegativeInteger(point.transaction_count, "transaction_count");
  const transfers = validateTransfers(point.transfers_excluded, `${label}.transfers_excluded`);
  if (
    transfers.matched_owned_account_count + transfers.internal_transfer_count >
    transactionCount
  ) {
    throw new Error("Excluded transfer count cannot exceed transaction count");
  }
  return {
    month,
    start_date: start,
    end_date: end,
    partial: point.partial,
    transaction_count: transactionCount,
    amounts: validateAmounts(point.amounts, `${label}.amounts`),
    transfers_excluded: transfers,
  };
}

function validateAmounts(value: unknown, label: string): CashFlowAmounts {
  const amounts = record(value, label);
  const externalIn = validateMoney(amounts.external_cash_inflows, `${label}.external_cash_inflows`);
  const interest = validateMoney(amounts.interest_received, `${label}.interest_received`);
  const moneyIn = validateMoney(amounts.money_in, `${label}.money_in`);
  const externalOut = validateMoney(amounts.external_cash_outflows, `${label}.external_cash_outflows`);
  const fees = validateMoney(amounts.fees_paid, `${label}.fees_paid`);
  const moneyOut = validateMoney(amounts.money_out, `${label}.money_out`);
  const net = validateMoney(amounts.net_cash_flow, `${label}.net_cash_flow`);
  [externalIn, interest, externalOut, fees].forEach((item) => requireEvidence(item, "observed", label));
  [externalIn, interest, externalOut, fees].forEach((item) => {
    if (requiredCents(item, label) < 0n) throw new Error("Absolute cash-flow inputs cannot be negative");
  });
  requireDerived(moneyIn, "money_in", label);
  requireDerived(moneyOut, "money_out", label);
  requireDerived(net, "net_cash_flow", label);
  const expectedIn = requiredCents(externalIn, label) + requiredCents(interest, label);
  const expectedOut = requiredCents(externalOut, label) + requiredCents(fees, label);
  if (requiredCents(moneyIn, label) !== expectedIn) throw new Error("Money in does not reconcile");
  if (requiredCents(moneyOut, label) !== expectedOut) throw new Error("Money out does not reconcile");
  if (requiredCents(net, label) !== expectedIn - expectedOut) throw new Error("Net does not reconcile");
  return {
    external_cash_inflows: externalIn,
    interest_received: interest,
    money_in: moneyIn,
    external_cash_outflows: externalOut,
    fees_paid: fees,
    money_out: moneyOut,
    net_cash_flow: net,
  };
}

function validateTransfers(value: unknown, label: string): ExcludedTransferTotals {
  const transfers = record(value, label);
  const matched = validateMoney(transfers.matched_owned_account_amount, `${label}.matched`);
  const internal = validateMoney(transfers.internal_transfer_amount, `${label}.internal`);
  requireEvidence(matched, "observed", label);
  requireEvidence(internal, "observed", label);
  if (requiredCents(matched, label) < 0n || requiredCents(internal, label) < 0n) {
    throw new Error("Excluded transfers cannot be negative");
  }
  return {
    matched_owned_account_amount: matched,
    matched_owned_account_count: nonnegativeInteger(
      transfers.matched_owned_account_count,
      "matched_owned_account_count",
    ),
    internal_transfer_amount: internal,
    internal_transfer_count: nonnegativeInteger(
      transfers.internal_transfer_count,
      "internal_transfer_count",
    ),
  };
}

function validateRecurringFacts(value: unknown): CurrentRecurringFacts {
  const recurring = record(value, "recurring");
  const takeHome = validateMoney(recurring.effective_recurring_take_home, "effective take-home");
  const outflow = validateMoney(recurring.observed_recurring_monthly_outflow, "recurring outflow");
  const margin = validateMoney(recurring.current_monthly_margin, "current monthly margin");
  const gap = validateMoney(recurring.stabilization_gap, "stabilization gap");
  requireEvidenceOrUnavailable(takeHome, "derived", "effective take-home");
  requireEvidenceOrUnavailable(outflow, "observed", "recurring outflow");
  const state = oneOf(recurring.margin_state, ["negative", "zero", "positive", "unavailable"], "margin_state");
  const takeHomeCents = optionalCents(takeHome);
  const outflowCents = optionalCents(outflow);
  if (takeHomeCents === null || outflowCents === null) {
    requireUnavailable(margin, "current monthly margin");
    requireUnavailable(gap, "stabilization gap");
    if (state !== "unavailable") throw new Error("Missing recurring evidence requires unavailable state");
  } else {
    if (takeHomeCents < 0n || outflowCents < 0n) throw new Error("Recurring inputs cannot be negative");
    requireDerived(takeHome, "effective_recurring_take_home", "effective take-home");
    requireDerived(margin, "current_monthly_margin", "current monthly margin");
    requireDerived(gap, "stabilization_gap", "stabilization gap");
    const expectedMargin = takeHomeCents - outflowCents;
    if (requiredCents(margin, "margin") !== expectedMargin) throw new Error("Recurring margin does not reconcile");
    if (requiredCents(gap, "gap") !== max(-expectedMargin, 0n)) throw new Error("Stabilization gap does not reconcile");
    const expectedState: MarginState = expectedMargin < 0n ? "negative" : expectedMargin > 0n ? "positive" : "zero";
    if (state !== expectedState) throw new Error("Margin state does not match recurring margin");
  }
  return {
    as_of_date: dateString(recurring.as_of_date, "recurring.as_of_date"),
    effective_recurring_take_home: takeHome,
    observed_recurring_monthly_outflow: outflow,
    current_monthly_margin: margin,
    stabilization_gap: gap,
    margin_state: state,
    warnings: stringArray(recurring.warnings, "recurring.warnings"),
  };
}

function validateGoal(value: unknown): RequiredGoalPaceReference {
  const goal = record(value, "goal");
  const target = validateMoney(goal.goal_target, "goal_target");
  const reserved = validateMoney(goal.reserved_for_goal, "reserved_for_goal");
  const remaining = validateMoney(goal.remaining_target, "remaining_target");
  const cash = validateMoney(goal.accessible_cash, "accessible_cash");
  const floor = validateMoney(goal.protected_cash_floor, "protected_cash_floor");
  const pace = validateMoney(goal.required_goal_pace, "required_goal_pace");
  requireEvidenceOrUnavailable(target, "user_entered", "goal_target");
  requireEvidenceOrUnavailable(reserved, "user_entered", "reserved_for_goal");
  requireEvidenceOrUnavailable(cash, "observed", "accessible_cash");
  requireEvidenceOrUnavailable(floor, "user_entered", "protected_cash_floor");
  const state = oneOf(
    goal.goal_state,
    ["active", "completed", "expired_unfinished", "cash_floor_breach", "unavailable"],
    "goal_state",
  );
  const observedOn = dateString(goal.observed_on, "observed_on");
  const targetDate = dateString(goal.target_date, "target_date");
  const fundingMonths = expectString(goal.funding_months, "funding_months");
  if (!/^\d+\.\d{12}$/.test(fundingMonths)) throw new Error("Funding months must use twelve decimal places");
  if (goal.calculation_version !== "goal-arithmetic-v1") throw new Error("Goal arithmetic version changed");
  const targetCents = optionalCents(target);
  const reservedCents = optionalCents(reserved);
  if (targetCents === null || reservedCents === null) {
    requireUnavailable(remaining, "remaining_target");
    requireUnavailable(pace, "required_goal_pace");
    if (state !== "unavailable") throw new Error("Missing goal configuration requires unavailable state");
  } else {
    if (targetCents < 0n || reservedCents < 0n || reservedCents > targetCents) {
      throw new Error("Goal target and reservation are invalid");
    }
    requireDerived(remaining, "remaining_target", "remaining_target");
    const remainingCents = max(targetCents - reservedCents, 0n);
    if (requiredCents(remaining, "remaining_target") !== remainingCents) {
      throw new Error("Remaining target must use the explicit owner reservation");
    }
    const cashCents = optionalCents(cash);
    const floorCents = optionalCents(floor);
    const expectedState: GoalState =
      remainingCents === 0n
        ? "completed"
        : dateOrdinal(targetDate) < dateOrdinal(observedOn)
          ? "expired_unfinished"
          : cashCents !== null && floorCents !== null && cashCents < floorCents
            ? "cash_floor_breach"
            : "active";
    if (state !== expectedState) throw new Error("Goal state does not distinguish completion, expiry, and floor breach");
    if (state === "expired_unfinished") {
      requireUnavailable(pace, "required_goal_pace");
    } else {
      requireDerived(pace, "required_goal_pace", "required_goal_pace");
      if (requiredCents(pace, "required_goal_pace") < 0n) throw new Error("Goal pace cannot be negative");
      if (state === "completed" && requiredCents(pace, "required_goal_pace") !== 0n) {
        throw new Error("Completed goal pace must be zero");
      }
    }
  }
  return {
    goal_program_id: expectString(goal.goal_program_id, "goal_program_id"),
    observed_on: observedOn,
    target_date: targetDate,
    goal_target: target,
    reserved_for_goal: reserved,
    remaining_target: remaining,
    accessible_cash: cash,
    protected_cash_floor: floor,
    funding_months: fundingMonths,
    goal_state: state,
    required_goal_pace: pace,
    calculation_version: "goal-arithmetic-v1",
  };
}

function validateMoney(value: unknown, label: string): V21EvidencedMoney {
  const item = record(value, label);
  if (!evidenceClasses.includes(item.evidence as EvidenceClass)) throw new Error(`${label} has invalid evidence`);
  const evidence = item.evidence as EvidenceClass;
  const refs = stringArray(item.source_refs, `${label}.source_refs`);
  const derivation = item.derivation;
  if (derivation !== null && !derivations.includes(derivation as V21MoneyDerivation)) {
    throw new Error(`${label} has invalid derivation`);
  }
  if (evidence === "unavailable") {
    if (item.amount !== null || derivation !== null || refs.length > 0 || typeof item.unavailable_reason !== "string" || item.unavailable_reason.length === 0) {
      throw new Error(`${label} unavailable evidence is malformed`);
    }
  } else {
    parseExactMoneyCents(item.amount);
    if (refs.length === 0 || item.unavailable_reason !== null) throw new Error(`${label} available evidence is malformed`);
    if ((evidence === "derived") !== (derivation !== null)) throw new Error(`${label} derivation does not match evidence`);
  }
  return {
    amount: item.amount as ExactDecimalString | null,
    evidence,
    source_refs: [...refs].sort(),
    derivation: derivation as V21MoneyDerivation | null,
    unavailable_reason: item.unavailable_reason as string | null,
  };
}

function reconcileTransfers(points: MonthlyCashFlowPoint[], totals: ExcludedTransferTotals): void {
  const matchedAmount = points.reduce(
    (sum, point) => sum + requiredCents(point.transfers_excluded.matched_owned_account_amount, "matched"),
    0n,
  );
  const internalAmount = points.reduce(
    (sum, point) => sum + requiredCents(point.transfers_excluded.internal_transfer_amount, "internal"),
    0n,
  );
  if (
    matchedAmount !== requiredCents(totals.matched_owned_account_amount, "matched total") ||
    internalAmount !== requiredCents(totals.internal_transfer_amount, "internal total") ||
    points.reduce((sum, point) => sum + point.transfers_excluded.matched_owned_account_count, 0) !== totals.matched_owned_account_count ||
    points.reduce((sum, point) => sum + point.transfers_excluded.internal_transfer_count, 0) !== totals.internal_transfer_count
  ) {
    throw new Error("Monthly excluded transfers must reconcile to period totals");
  }
}

function requireEvidence(value: V21EvidencedMoney, evidence: EvidenceClass, label: string): void {
  if (value.evidence !== evidence) throw new Error(`${label} must use ${evidence} evidence`);
}

function requireEvidenceOrUnavailable(value: V21EvidencedMoney, evidence: EvidenceClass, label: string): void {
  if (value.evidence !== evidence && value.evidence !== "unavailable") {
    throw new Error(`${label} must use ${evidence} or unavailable evidence`);
  }
}

function requireDerived(value: V21EvidencedMoney, derivation: V21MoneyDerivation, label: string): void {
  requireEvidence(value, "derived", label);
  if (value.derivation !== derivation) throw new Error(`${label} must use ${derivation}`);
}

function requireUnavailable(value: V21EvidencedMoney, label: string): void {
  requireEvidence(value, "unavailable", label);
}

function optionalCents(value: V21EvidencedMoney): bigint | null {
  return value.amount === null ? null : parseExactMoneyCents(value.amount);
}

function requiredCents(value: V21EvidencedMoney, label: string | number | symbol): bigint {
  if (value.amount === null) throw new Error(`${String(label)} must be available`);
  return parseExactMoneyCents(value.amount);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  const values = array(value, label);
  if (!values.every((item) => typeof item === "string" && item.length > 0)) {
    throw new Error(`${label} must contain non-empty strings`);
  }
  if (new Set(values).size !== values.length) throw new Error(`${label} must be unique`);
  return values as string[];
}

function expectString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} must be a string`);
  return value;
}

function dateString(value: unknown, label: string): string {
  const result = expectString(value, label);
  if (!datePattern.test(result) || new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) {
    throw new Error(`${label} must be a real ISO date`);
  }
  return result;
}

function dateOrdinal(value: string): number {
  return Date.parse(`${value}T00:00:00Z`) / 86_400_000;
}

function nonnegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a nonnegative integer`);
  }
  return value;
}

function oneOf<const T extends readonly string[]>(value: unknown, choices: T, label: string): T[number] {
  if (typeof value !== "string" || !choices.includes(value)) throw new Error(`${label} is invalid`);
  return value as T[number];
}

function max(left: bigint, right: bigint): bigint {
  return left > right ? left : right;
}
