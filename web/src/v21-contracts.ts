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
  | "combined_monthly_improvement";

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
  const cashFlow = validateCashFlowResult(vector.cash_flow);
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

function validateCashFlowResult(value: unknown): CashFlowPeriodResult {
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
