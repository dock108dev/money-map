export type ExactDecimalString = `${number}.${number}${number}`;

export type EvidenceClass =
  | "observed"
  | "derived"
  | "user_entered"
  | "assumed"
  | "unavailable";

export type MoneyDerivation =
  | "accessible_now"
  | "available_above_floor"
  | "remaining_target"
  | "required_funding_pace"
  | "effective_recurring_take_home"
  | "recurring_cash_flow_gap"
  | "comparison_delta"
  | "unexplained_residual"
  | "milestone_amount"
  | "retirement_goal_snapshot";

export interface EvidencedMoney {
  amount: ExactDecimalString | null;
  evidence: EvidenceClass;
  source_refs: string[];
  derivation: MoneyDerivation | null;
  unavailable_reason: string | null;
}

export interface PrimaryGoalProgram {
  goal_program_id: string;
  name: string;
  target_date: string;
  target_amount: EvidencedMoney;
  protected_cash_floor: EvidencedMoney;
  reserved_for_goal: EvidencedMoney;
  primary: true;
  reservation_policy: "exclusive_primary_goal";
  source_life_goal_id: number | null;
}

export interface GoalProgramView {
  goal_program_id: string;
  name: string;
  target_date: string;
  target_amount: EvidencedMoney;
  protected_cash_floor: EvidencedMoney;
  reserved_for_goal: EvidencedMoney;
  status: "active" | "complete";
  is_primary: boolean;
  source_life_goal_id: number | null;
  edit_token: string;
  updated_at: string;
}

export type PrimaryGoalState =
  | { state: "primary"; goal: GoalProgramView }
  | { state: "no_primary"; goal: null };

export interface GoalCandidateList {
  state: "selection_required" | "no_candidates";
  candidates: GoalProgramView[];
}

export interface GoalEditRequest {
  expected_edit_token: string;
  name?: string | null;
  target_date?: string | null;
  target_amount?: ExactDecimalString | null;
  protected_cash_floor?: ExactDecimalString | null;
  reserved_for_goal?: ExactDecimalString | null;
}

export interface PrimaryGoalSelectionRequest {
  goal_program_id: string;
  expected_edit_token: string;
}

export type PaceStatus = "active" | "complete" | "expired";

export interface GoalPosition {
  goal_program_id: string;
  observed_on: string;
  target_date: string;
  accessible_cash: EvidencedMoney;
  accessible_investments: EvidencedMoney;
  retirement_assets_excluded: EvidencedMoney;
  tracked_debt: EvidencedMoney;
  accessible_now: EvidencedMoney;
  protected_cash_floor: EvidencedMoney;
  available_above_floor: EvidencedMoney;
  reserved_for_goal: EvidencedMoney;
  goal_target: EvidencedMoney;
  remaining_target: EvidencedMoney;
  effective_recurring_take_home: EvidencedMoney;
  observed_recurring_outflow: EvidencedMoney;
  recurring_cash_flow_gap: EvidencedMoney;
  funding_months: string;
  pace_status: PaceStatus;
  required_funding_pace: EvidencedMoney;
  calculation_version: "goal-arithmetic-v1";
}

export type GoalPositionState =
  | { state: "available"; position: GoalPosition; source_fingerprint: string }
  | { state: "no_primary"; position: null; source_fingerprint: null };

export interface GoalCheckIn {
  check_in_id: string;
  goal_program_id: string;
  source_fingerprint: string;
  effective_observation_date: string;
  position: GoalPosition;
  trigger:
    | "post_refresh"
    | "post_import"
    | "post_payroll"
    | "load_backfill"
    | "synthetic_test";
  created_at: string;
  contract_version: "money-map-v2-contract-v1";
}

export type GoalCheckInState =
  | { state: "available"; check_in: GoalCheckIn }
  | { state: "no_primary" | "no_check_in"; check_in: null };

export interface GoalCheckInTimelinePage {
  state: "available" | "no_primary";
  check_ins: GoalCheckIn[];
  comparisons: GoalComparison[];
  next_cursor: string | null;
}

export type GoalObservationResult = {
  status: "created" | "unchanged" | "no_primary" | "not_current" | "unavailable";
  trigger: "post_refresh" | "post_import" | "post_payroll" | "load_backfill";
  check_in: GoalCheckIn | null;
  retryable: boolean;
  message: string;
};

export type ComparisonComponentKind =
  | "accessible_now"
  | "accessible_cash"
  | "accessible_investments"
  | "tracked_debt"
  | "goal_target"
  | "protected_cash_floor"
  | "reserved_for_goal"
  | "supported_payroll"
  | "supported_transfer"
  | "supported_market_movement"
  | "unexplained_residual";

export interface GoalComparisonComponent {
  component: ComparisonComponentKind;
  change: EvidencedMoney;
  interpretation: "arithmetic_only" | "evidence_supported_event";
  supporting_evidence_refs: string[];
}

export interface GoalComparison {
  goal_program_id: string;
  previous_check_in_id: string;
  current_check_in_id: string;
  previous_source_fingerprint: string;
  current_source_fingerprint: string;
  previous_observation_date: string;
  current_observation_date: string;
  components: GoalComparisonComponent[];
}

export type GoalComparisonState =
  | { state: "available"; comparison: GoalComparison; reason: null }
  | {
      state: "no_primary" | "no_previous_check_in" | "unavailable";
      comparison: null;
      reason: string;
    };

export type GoalMilestoneKind =
  | "data_unavailable"
  | "restore_floor"
  | "close_recurring_gap"
  | "fund_goal"
  | "goal_complete";

export interface GoalMilestone {
  goal_program_id: string;
  kind: GoalMilestoneKind;
  sequence_rank: 0 | 1 | 2 | 3 | 4;
  amount: EvidencedMoney;
  position_fingerprint: string;
}

export type GoalMilestoneState =
  | { state: "available"; milestone: GoalMilestone }
  | { state: "no_primary"; milestone: null };

export interface RetirementGoalInclusion {
  goal_program_id: string;
  goal_source_fingerprint: string;
  target_amount: EvidencedMoney;
  reserved_for_goal: EvidencedMoney;
  remaining_target: EvidencedMoney;
  selection: "explicit";
}

export interface RetirementRunSelection {
  run_selection_id: string;
  include_operational_goal: boolean;
  included_goal: RetirementGoalInclusion | null;
  goal_default_policy: "excluded";
  operational_goal_mutation: false;
}

export type LabExperimentSeedKind = "blank" | "current_goal" | "retirement_result";

export interface LifeLabExperimentSeed {
  experiment_id: string;
  seed_kind: LabExperimentSeedKind;
  source_fingerprint: string | null;
  seeded_money: Record<string, EvidencedMoney>;
  edit_scope: "isolated_draft";
  goal_mutation: false;
  retirement_mutation: false;
}

export type PromotionTarget = "goals" | "retirement";
export type PromotionField =
  | "goal_target"
  | "reserved_for_goal"
  | "protected_cash_floor"
  | "retirement_monthly_spend";

export interface LifeLabPromotionChange {
  field: PromotionField;
  before: EvidencedMoney;
  after: EvidencedMoney;
}

export interface LifeLabPromotionPreview {
  experiment_id: string;
  experiment_fingerprint: string;
  target_surface: PromotionTarget;
  changes: LifeLabPromotionChange[];
  state: "preview_only";
  requires_explicit_confirmation: true;
  applied: false;
}

export type SourceRecordKind =
  | "balance"
  | "investment_access"
  | "payroll"
  | "recurring_outflow"
  | "goal_configuration";

export interface SourceMoneyFact {
  field: string;
  amount: ExactDecimalString;
  evidence: Exclude<EvidenceClass, "unavailable">;
}

export interface FingerprintSourceRecord {
  kind: SourceRecordKind;
  record_identity: string;
  record_hash: string | null;
  effective_date: string;
  money_facts: SourceMoneyFact[];
}

export interface FingerprintGoalConfiguration {
  goal_program_id: string;
  target_date: string;
  target_amount: EvidencedMoney;
  protected_cash_floor: EvidencedMoney;
  reserved_for_goal: EvidencedMoney;
}

export interface SourceFingerprintMaterial {
  fingerprint_version: "goal-source-fingerprint-v1";
  calculation_version: "goal-arithmetic-v1";
  goal_configuration: FingerprintGoalConfiguration;
  source_records: FingerprintSourceRecord[];
}

export type GoalProvenanceState =
  | {
      state: "available";
      source_fingerprint: string;
      source_material: SourceFingerprintMaterial;
    }
  | {
      state: "no_primary";
      source_fingerprint: null;
      source_material: null;
    };

export function isExactDecimalString(value: unknown): value is ExactDecimalString {
  return typeof value === "string" && /^-?\d+\.\d{2}$/.test(value);
}

export function isEvidencedMoney(value: unknown): value is EvidencedMoney {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<EvidencedMoney>;
  const classes: EvidenceClass[] = [
    "observed",
    "derived",
    "user_entered",
    "assumed",
    "unavailable",
  ];
  if (!candidate.evidence || !classes.includes(candidate.evidence)) return false;
  if (!Array.isArray(candidate.source_refs)) return false;
  if (candidate.evidence === "unavailable") {
    return candidate.amount === null && typeof candidate.unavailable_reason === "string";
  }
  return isExactDecimalString(candidate.amount) && candidate.unavailable_reason === null;
}
