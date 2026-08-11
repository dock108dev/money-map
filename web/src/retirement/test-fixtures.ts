import { evidenced, goalProgram } from "../goals/fixtures";
import type { LifeProjection, LifeProjectionPeriod, PathResult } from "../life-lab/life-lab-types";
import type {
  LabExperimentSeedKind,
  LifeLabExperimentResult,
  LifeLabExperimentSeed,
  LifeLabPromotionApplied,
  LifeLabPromotionPreview,
  RetirementProfileView,
  RetirementProjectionResult,
} from "../v2-contracts";
import type { PlanningSnapshot } from "./api";

export const retirementProfile: RetirementProfileView = {
  profile_id: 1,
  birth_date: "1991-01-01",
  state: "NJ",
  plan_through_age: 95,
  current_monthly_outflow: evidenced("6000.00", "user_entered"),
  retirement_essential_monthly_spend: evidenced("4000.00", "user_entered"),
  retirement_flexible_monthly_spend: evidenced("2000.00", "user_entered"),
  protected_cash_floor: evidenced("10000.00", "user_entered"),
  retirement_tax_haircut_pct: "20.0000",
  work_optional_ages: [43, 57, 73],
  notes: "Synthetic profile",
  edit_token: "r".repeat(64),
  updated_at: "2026-08-10T12:00:00Z",
};

export const retirementStartingPoint = {
  as_of: "2026-08-10",
  cash: "20000.00",
  accessible_investments: "50000.00",
  pretax_retirement: "400000.00",
  hsa: "12000.00",
  restricted_assets: "30000.00",
  debt: "0.00",
  accessible_total: "70000.00",
  tracked_total: "512000.00",
  observed_monthly_outflow: "5750.00",
  outflow_months: ["2026-06", "2026-07"],
  payroll: null,
  accounts: [],
  warnings: [],
  evidence_classification: { cash: "observed", accessible_investments: "observed" },
  read_only: true as const,
};

function period(month: string, ageMonths: number, working: boolean, total: string): LifeProjectionPeriod {
  return {
    month,
    age_months: ageMonths,
    working,
    gross_income: working ? "17916.67" : "0.00",
    net_income: working ? "9316.67" : "0.00",
    employee_retirement: working ? "1083.33" : "0.00",
    employer_retirement: working ? "541.67" : "0.00",
    stock_plan: working ? "1733.33" : "0.00",
    essential_spend: working ? "5750.00" : "4000.00",
    flexible_spend: working ? "0.00" : "2000.00",
    goal_spend: "0.00",
    cash: "10000.00",
    accessible_investments: working ? "70000.00" : "90000.00",
    pretax_retirement: working ? "400000.00" : "650000.00",
    hsa: "12000.00",
    restricted_assets: "30000.00",
    debt: "0.00",
    investment_result: "1000.00",
    total_spendable: total,
  };
}

export function retirementPath(
  key: PathResult["path_key"] = "middle",
  status: PathResult["status"] = "works",
): PathResult {
  return {
    target_age: 43,
    path_key: key,
    path_label: key === "middle" ? "Middle path" : key === "rough" ? "Rough path" : "Early-crash path",
    status,
    first_shortfall_month: status === "works" ? null : "2038-03-01",
    work_stop_month: "2034-01-01",
    work_stop_assets: { cash: "10000.00", accessible_investments: "90000.00", pretax_retirement: "650000.00" },
    end_assets: { cash: "10000.00", accessible_investments: "120000.00", pretax_retirement: "350000.00", total_spendable: "410000.00" },
    goal_results: {},
    make_it_happen: {
      additional_monthly_after_tax_income: "12500.00",
      retirement_capital_needed: "1000000.00",
      retirement_deadline: "2034-01-01",
      pre_retirement_shortfall_month: status === "works" ? null : "2029-04-01",
    },
    periods: [period("2026-08-01", 427, true, "400000.00"), period("2034-01-01", 516, false, "620000.00")],
  };
}

export const lifeProjection: LifeProjection = {
  engine_version: "life-lab-v0.3.0",
  source_fingerprint: "p".repeat(64),
  generated_at: "2026-08-10T12:00:00Z",
  as_of: "2026-08-10",
  profile: {
    id: 1,
    birth_date: retirementProfile.birth_date,
    state: retirementProfile.state,
    end_age: retirementProfile.plan_through_age,
    current_monthly_outflow: "6000.00",
    essential_monthly_spend: "4000.00",
    flexible_monthly_spend: "2000.00",
    cash_floor: "10000.00",
    retirement_tax_rate_pct: "20.00",
    target_ages: retirementProfile.work_optional_ages,
    notes: "Synthetic profile",
    created_at: "2026-08-10T12:00:00Z",
    updated_at: "2026-08-10T12:00:00Z",
    provenance: {
      birth_date: "user_entered", state: "user_entered", end_age: "assumed",
      current_monthly_outflow: "user_entered", essential_monthly_spend: "user_entered",
      flexible_monthly_spend: "user_entered", cash_floor: "user_entered",
      retirement_tax_rate_pct: "assumed", target_ages: "user_entered",
    },
  },
  starting_point: retirementStartingPoint,
  benchmarks: {
    available: true,
    version: "benchmark-v1",
    definition: "AGI threshold",
    source_year: 2022,
    normalized_dollar_basis: "June 2026",
    state: "NJ",
    state_name: "New Jersey",
    thresholds: {
      top_50: { source_amount: "55000.00", normalized_amount: "61000.00" },
      top_25: { source_amount: "105000.00", normalized_amount: "116000.00" },
      top_10: { source_amount: "190000.00", normalized_amount: "210000.00" },
      top_5: { source_amount: "280000.00", normalized_amount: "309000.00" },
      top_1: { source_amount: "820000.00", normalized_amount: "904000.00" },
    },
    current_income: "215000.00",
    current_income_context: "top_10",
    warning: "Salary and AGI definitions differ.",
  },
  goals: [],
  assumptions: { version: "life-lab-drive-paths-v3", today_dollars: true, cash_real_return_pct: "0.00", retirement_access_age: "59.5", paths: {}, omissions: ["probability of success"] },
  results: [{ target_age: 43, paths: [retirementPath(), retirementPath("rough", "works_essentials_only"), retirementPath("early_crash", "insufficient_accessible_bridge")] }],
  goal_impacts: { "43": [] },
  warnings: ["Assumption-driven planning model."],
};

export function retirementRun(
  status: RetirementProjectionResult["bridge_verdict"] = "works",
  included = false,
): RetirementProjectionResult {
  const selected = retirementPath(
    status === "works_essentials_only" ? "rough" : status === "insufficient_accessible_bridge" ? "early_crash" : "middle",
    status,
  );
  const projection = { ...lifeProjection, results: [{ target_age: 43, paths: lifeProjection.results[0].paths.map((row) => row.path_key === selected.path_key ? selected : row) }] };
  return {
    run_selection: {
      run_selection_id: "selection-1",
      work_optional_age: 43,
      path: selected.path_key,
      include_operational_goal: included,
      included_goal: included ? {
        goal_program_id: goalProgram.goal_program_id,
        name: goalProgram.name,
        target_date: goalProgram.target_date,
        goal_source_fingerprint: "g".repeat(64),
        target_amount: goalProgram.target_amount,
        reserved_for_goal: goalProgram.reserved_for_goal,
        remaining_target: evidenced("12000.00", "derived", null, "retirement_goal_snapshot"),
        evidence_refs: ["goal:synthetic"],
        selection: "explicit",
      } : null,
      goal_default_policy: "excluded",
      operational_goal_mutation: false,
    },
    run_fingerprint: (included ? "i" : "d").repeat(64),
    profile: retirementProfile,
    snapshot_context: included ? "retirement_with_goal" : "retirement_default",
    bridge_verdict: status,
    accessible_assets_at_work_stop: "100000.00",
    retirement_assets_at_work_stop: "650000.00",
    end_spendable_assets: "410000.00",
    required_money_runway_months: status === "works" ? null : 48,
    warnings: lifeProjection.warnings,
    selected_result: selected as unknown as Record<string, unknown>,
    projection: projection as unknown as Record<string, unknown>,
  };
}

export const retirementSnapshot: PlanningSnapshot = {
  id: 11,
  name: "Age 43 middle",
  snapshot_context: "retirement_default",
  context_label: "retirement default",
  legacy: false,
  target_age: 43,
  path_key: "middle",
  status: "works",
  summary: {}, input_snapshot: {}, warnings: [],
  engine_version: "life-lab-v0.3.0", assumption_version: "life-lab-drive-paths-v3", benchmark_version: "benchmark-v1",
  source_fingerprint: "d".repeat(64), stale: false, created_at: "2026-08-10T12:00:00Z", periods: lifeProjection.results[0].paths[0].periods as unknown as Array<Record<string, unknown>>,
};

export const legacySnapshot: PlanningSnapshot = {
  ...retirementSnapshot,
  id: 3,
  name: "Accepted combined scenario",
  snapshot_context: "legacy_combined",
  context_label: "Legacy combined plan · v1.2.1 inputs",
  legacy: true,
  source_fingerprint: "l".repeat(64),
};

export function labSeed(kind: LabExperimentSeedKind = "blank"): LifeLabExperimentSeed {
  return {
    experiment_id: `lab-${kind}`,
    seed_kind: kind,
    source_fingerprint: kind === "blank" ? null : (kind === "current_goal" ? "g" : "d").repeat(64),
    seeded_money: kind === "blank" ? {} : { goal_target: evidenced("14000.00", "user_entered") },
    source_label: kind === "blank" ? null : kind === "current_goal" ? goalProgram.name : retirementSnapshot.name,
    draft: {
      profile: lifeProjection.profile,
      starting_point: lifeProjection.starting_point,
      goals: lifeProjection.goals,
      mission: { target_amount: "1000000.00", target_date: "2034-01-01", selected_age: 43, path: "middle", starting_stake: "5000.00" },
      promotable_values: { goal_target: "14000.00", retirement_essential_monthly_spend: "4000.00" },
    },
    experiment_fingerprint: "e".repeat(64),
    edit_scope: "isolated_draft",
    goal_mutation: false,
    retirement_mutation: false,
  };
}

export function labResult(seed = labSeed()): LifeLabExperimentResult {
  return {
    experiment_id: seed.experiment_id,
    experiment_fingerprint: seed.experiment_fingerprint,
    seed_kind: seed.seed_kind,
    snapshot_context: seed.seed_kind === "blank" ? "lab_blank" : seed.seed_kind === "current_goal" ? "lab_current_goal" : "lab_retirement_result",
    draft: seed.draft,
    projection: lifeProjection as unknown as Record<string, unknown>,
    reverse_solver: { mission_capital: "1000000.00", selected_result: retirementPath() },
    snapshot_context_evidence: {},
    edit_scope: "isolated_draft",
    goal_mutation: false,
    retirement_mutation: false,
  };
}

export const promotionPreview: LifeLabPromotionPreview = {
  preview_id: "preview-1",
  experiment_id: "lab-current_goal",
  experiment_fingerprint: "e".repeat(64),
  target_surface: "goals",
  target_id: goalProgram.goal_program_id,
  target_stale_write_token: goalProgram.edit_token,
  changes: [{
    field: "goal_target",
    stored_target_field: "goal_programs.target_amount",
    before: goalProgram.target_amount,
    after: evidenced("15000.00", "user_entered"),
    source_provenance: ["lab:e"],
    target_provenance: ["goal:synthetic"],
  }],
  state: "preview_only",
  requires_explicit_confirmation: true,
  applied: false,
};

export const promotionApplied: LifeLabPromotionApplied = {
  ...promotionPreview,
  target_stale_write_token: "n".repeat(64),
  state: "applied",
  applied: true,
  goal_observation: { status: "created", trigger: "lab_promotion", check_in: null, retryable: false, message: "Observed" },
};
