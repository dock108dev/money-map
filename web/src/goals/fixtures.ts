import type {
  EvidencedMoney,
  ExactDecimalString,
  GoalCandidateList,
  GoalCheckIn,
  GoalCheckInState,
  GoalCheckInTimelinePage,
  GoalComparisonState,
  GoalMilestoneKind,
  GoalMilestoneState,
  GoalObservationResult,
  GoalPosition,
  GoalPositionState,
  GoalProgramView,
  GoalProvenanceState,
  PrimaryGoalState,
} from "../v2-contracts";

export const goalHash = "a".repeat(64);
export const previousGoalHash = "b".repeat(64);
export const editToken = "c".repeat(64);

export function evidenced(
  amount: string | null,
  evidence: EvidencedMoney["evidence"] = "observed",
  unavailableReason: string | null = null,
  derivation: EvidencedMoney["derivation"] = null,
): EvidencedMoney {
  return {
    amount: amount as ExactDecimalString | null,
    evidence,
    source_refs: amount === null ? [] : ["synthetic:source"],
    derivation,
    unavailable_reason: unavailableReason,
  };
}

export function derived(amount: string, derivation: NonNullable<EvidencedMoney["derivation"]>) {
  return evidenced(amount, "derived", null, derivation);
}

export const goalProgram: GoalProgramView = {
  goal_program_id: "goal_beach_house",
  name: "Quiet place by the water",
  target_date: "2027-08-10",
  target_amount: evidenced("14000.00", "user_entered"),
  protected_cash_floor: evidenced("3000.00", "user_entered"),
  reserved_for_goal: evidenced("2000.00", "user_entered"),
  status: "active",
  is_primary: true,
  source_life_goal_id: 1,
  edit_token: editToken,
  updated_at: "2026-08-10T12:00:00Z",
};

export const candidateProgram: GoalProgramView = {
  ...goalProgram,
  goal_program_id: "goal_second",
  name: "A second clear goal",
  target_date: "2028-06-01",
  target_amount: evidenced("9000.00", "user_entered"),
  reserved_for_goal: evidenced("750.00", "user_entered"),
  is_primary: false,
  source_life_goal_id: 2,
};

export const goalPosition: GoalPosition = {
  goal_program_id: goalProgram.goal_program_id,
  observed_on: "2026-08-10",
  target_date: goalProgram.target_date,
  accessible_cash: evidenced("6000.00"),
  accessible_investments: evidenced("1500.00"),
  retirement_assets_excluded: evidenced("400000.00"),
  tracked_debt: evidenced("500.00"),
  accessible_now: derived("7500.00", "accessible_now"),
  protected_cash_floor: evidenced("3000.00", "user_entered"),
  available_above_floor: derived("4500.00", "available_above_floor"),
  reserved_for_goal: evidenced("2000.00", "user_entered"),
  goal_target: evidenced("14000.00", "user_entered"),
  remaining_target: derived("12000.00", "remaining_target"),
  effective_recurring_take_home: derived("4200.00", "effective_recurring_take_home"),
  observed_recurring_outflow: evidenced("3900.00"),
  recurring_cash_flow_gap: derived("0.00", "recurring_cash_flow_gap"),
  funding_months: "12.000000000000",
  pace_status: "active",
  required_funding_pace: derived("1000.00", "required_funding_pace"),
  calculation_version: "goal-arithmetic-v1",
};

export function comparisonState(change: string): GoalComparisonState {
  return {
    state: "available",
    reason: null,
    comparison: {
      goal_program_id: goalProgram.goal_program_id,
      previous_check_in_id: "previous-check-in",
      current_check_in_id: "current-check-in",
      previous_source_fingerprint: previousGoalHash,
      current_source_fingerprint: goalHash,
      previous_observation_date: "2026-07-10",
      current_observation_date: "2026-08-10",
      components: [
        {
          component: "accessible_now",
          change: derived(change, "comparison_delta"),
          interpretation: "arithmetic_only",
          supporting_evidence_refs: [],
        },
      ],
    },
  };
}

export function milestoneState(
  kind: GoalMilestoneKind = "fund_goal",
  amount = "1000.00",
  reason: string | null = null,
): GoalMilestoneState {
  return {
    state: "available",
    milestone: {
      goal_program_id: goalProgram.goal_program_id,
      kind,
      sequence_rank: kind === "data_unavailable" ? 0 : kind === "restore_floor" ? 1 : kind === "close_recurring_gap" ? 2 : kind === "fund_goal" ? 3 : 4,
      amount: kind === "data_unavailable"
        ? evidenced(null, "unavailable", reason ?? "Current cash evidence is unavailable")
        : derived(amount, "milestone_amount"),
      position_fingerprint: goalHash,
    },
  };
}

export const primaryState: PrimaryGoalState = { state: "primary", goal: goalProgram };
export const noPrimaryState: PrimaryGoalState = { state: "no_primary", goal: null };
export const positionState: GoalPositionState = {
  state: "available",
  position: goalPosition,
  source_fingerprint: goalHash,
};
export const latestState: GoalCheckInState = { state: "no_check_in", check_in: null };
export const noComparisonState: GoalComparisonState = {
  state: "no_previous_check_in",
  comparison: null,
  reason: "Only one saved check-in exists",
};
export const unavailableComparisonState: GoalComparisonState = {
  state: "unavailable",
  comparison: null,
  reason: "Source fingerprints do not support a comparison",
};
export const candidatesState: GoalCandidateList = {
  state: "selection_required",
  candidates: [candidateProgram],
};
export const noCandidatesState: GoalCandidateList = { state: "no_candidates", candidates: [] };

export const checkIn: GoalCheckIn = {
  check_in_id: "current-check-in",
  goal_program_id: goalProgram.goal_program_id,
  source_fingerprint: goalHash,
  effective_observation_date: "2026-08-10",
  position: goalPosition,
  trigger: "post_refresh",
  created_at: "2026-08-10T12:00:00Z",
  contract_version: "money-map-v2-contract-v1",
};

export const unchangedObservation: GoalObservationResult = {
  status: "unchanged",
  trigger: "load_backfill",
  check_in: checkIn,
  retryable: false,
  message: "The current financial evidence already has a saved observation.",
};

export const historyPage: GoalCheckInTimelinePage = {
  state: "available",
  check_ins: [checkIn],
  comparisons: [],
  next_cursor: "older-cursor",
};

export const olderHistoryPage: GoalCheckInTimelinePage = {
  state: "available",
  check_ins: [{ ...checkIn, check_in_id: "older-check-in", effective_observation_date: "2026-07-10" }],
  comparisons: [],
  next_cursor: null,
};

export const provenanceState: GoalProvenanceState = {
  state: "available",
  source_fingerprint: goalHash,
  source_material: {
    fingerprint_version: "goal-source-fingerprint-v1",
    calculation_version: "goal-arithmetic-v1",
    goal_configuration: {
      goal_program_id: goalProgram.goal_program_id,
      target_date: goalProgram.target_date,
      target_amount: goalProgram.target_amount,
      protected_cash_floor: goalProgram.protected_cash_floor,
      reserved_for_goal: goalProgram.reserved_for_goal,
    },
    source_records: [
      {
        kind: "balance",
        record_identity: "balance:synthetic:1",
        record_hash: previousGoalHash,
        effective_date: "2026-08-10",
        money_facts: [{ field: "accessible_cash", amount: "6000.00", evidence: "observed" }],
      },
    ],
  },
};
