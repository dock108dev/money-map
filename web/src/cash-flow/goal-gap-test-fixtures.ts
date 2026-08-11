import type {
  GoalGapPreviewAvailable,
  RecurringOutflowCandidateList,
  V21EvidencedMoney,
  V21MoneyDerivation,
} from "../v21-contracts";

const observed = (amount: string, ref: string): V21EvidencedMoney => ({
  amount: amount as `${number}.${number}${number}`,
  evidence: "observed",
  source_refs: [ref],
  derivation: null,
  unavailable_reason: null,
});

const entered = (amount: string, ref: string): V21EvidencedMoney => ({
  amount: amount as `${number}.${number}${number}`,
  evidence: "user_entered",
  source_refs: [ref],
  derivation: null,
  unavailable_reason: null,
});

const derived = (
  amount: string,
  derivation: V21MoneyDerivation,
  ...refs: string[]
): V21EvidencedMoney => ({
  amount: amount as `${number}.${number}${number}`,
  evidence: "derived",
  source_refs: refs,
  derivation,
  unavailable_reason: null,
});

export const unavailableMoney = (reason: string): V21EvidencedMoney => ({
  amount: null,
  evidence: "unavailable",
  source_refs: [],
  derivation: null,
  unavailable_reason: reason,
});

export function goalGapFixture(): GoalGapPreviewAvailable {
  return {
    state: "available",
    goal_program_id: "goal_harbor_studio",
    goal_name: "Invented Harbor Studio",
    observed_on: "2026-08-11",
    baseline_current_recurring_facts: {
      as_of_date: "2026-08-11",
      effective_recurring_take_home: derived(
        "4200.00",
        "effective_recurring_take_home",
        "payroll:invented",
      ),
      observed_recurring_monthly_outflow: observed("9802.98", "outflow:invented"),
      current_monthly_margin: derived(
        "-5602.98",
        "current_monthly_margin",
        "payroll:invented",
        "outflow:invented",
      ),
      stabilization_gap: derived("5602.98", "stabilization_gap", "margin:invented"),
      margin_state: "negative",
      warnings: [],
    },
    baseline_goal_pace_reference: {
      goal_program_id: "goal_harbor_studio",
      observed_on: "2026-08-11",
      target_date: "2030-08-10",
      goal_target: entered("1872168.96", "goal:target"),
      reserved_for_goal: entered("0.00", "goal:reservation"),
      remaining_target: derived("1872168.96", "remaining_target", "goal:remaining"),
      accessible_cash: observed("5000.00", "balance:cash"),
      protected_cash_floor: entered("3000.00", "goal:floor"),
      funding_months: "48.000000000000",
      goal_state: "active",
      required_goal_pace: derived("39003.52", "required_goal_pace", "goal:pace"),
      calculation_version: "goal-arithmetic-v1",
    },
    baseline_combined_monthly_improvement: derived(
      "44606.50",
      "combined_monthly_improvement",
      "goal:pace",
      "margin:invented",
    ),
    preview_target_date: "2030-08-10",
    existing_explicit_reservation: entered("0.00", "goal:reservation"),
    additional_draft_reservation: entered("0.00", "draft:reservation"),
    preview_total_reservation: derived(
      "0.00",
      "preview_total_reservation",
      "goal:reservation",
      "draft:reservation",
    ),
    preview_remaining_target: derived(
      "1872168.96",
      "preview_remaining_target",
      "goal:target",
      "goal:reservation",
    ),
    exact_funding_months: "48.000000000000",
    preview_required_goal_pace: derived(
      "39003.52",
      "preview_required_goal_pace",
      "goal:remaining",
      "calendar:invented",
    ),
    draft_spending_reduction: entered("0.00", "draft:spending"),
    draft_after_tax_income: entered("0.00", "draft:income"),
    adjusted_recurring_take_home: derived(
      "4200.00",
      "adjusted_recurring_take_home",
      "payroll:invented",
      "draft:income",
    ),
    adjusted_recurring_outflow: derived(
      "9802.98",
      "adjusted_recurring_outflow",
      "outflow:invented",
      "draft:spending",
    ),
    adjusted_monthly_margin: derived(
      "-5602.98",
      "adjusted_monthly_margin",
      "payroll:invented",
      "outflow:invented",
    ),
    adjusted_stabilization_gap: derived(
      "5602.98",
      "adjusted_stabilization_gap",
      "margin:invented",
    ),
    remaining_combined_monthly_improvement: derived(
      "44606.50",
      "remaining_combined_monthly_improvement",
      "goal:pace",
      "margin:invented",
    ),
    gross_income_context: {
      state: "available",
      effective_take_home_ratio: "0.646153333333",
      ratio_precision: "0.000000000001",
      supporting_payroll_date: "2026-08-07",
      source_ref: "payroll_schedule:invented",
      estimated_monthly_gross_income_needed: derived(
        "69033.92",
        "estimated_monthly_gross_income",
        "payroll_schedule:invented",
        "goal:pace",
      ),
      estimated_annual_gross_income_needed: derived(
        "828407.04",
        "estimated_annual_gross_income",
        "payroll_schedule:invented",
        "goal:pace",
      ),
      estimate_label: "Estimate based on the latest supported paycheck",
      disclaimer: "Not a tax-return estimate",
    },
    warnings: ["Arithmetic only; not financial advice or a claim that the change is achievable."],
    calculation_version: "goal-arithmetic-v1",
    contract_version: "money-map-v2.1-contract-v1",
  };
}

export function candidateFixture(): RecurringOutflowCandidateList {
  const refs = [
    "account_transaction:invented-a",
    "account_transaction:invented-b",
    "account_transaction:invented-c",
  ];
  return {
    state: "available",
    observed_on: "2026-08-11",
    candidates: [
      {
        candidate_id: "candidate_0123456789abcdef01234567",
        observed_description: "Invented Media Plan",
        safe_account_label: "Checking account 1",
        cadence: "monthly",
        occurrence_count: 3,
        first_observed_date: "2026-05-05",
        last_observed_date: "2026-07-04",
        median_observed_amount: derived("10.00", "recurring_outflow_median", ...refs),
        typical_monthly_amount: derived(
          "10.00",
          "recurring_outflow_typical_monthly",
          ...refs,
        ),
        amount_range: {
          minimum: {
            amount: "10.00",
            evidence: "observed",
            source_refs: refs,
            derivation: null,
            unavailable_reason: null,
          },
          maximum: {
            amount: "10.00",
            evidence: "observed",
            source_refs: refs,
            derivation: null,
            unavailable_reason: null,
          },
        },
        confidence: "high",
        source_refs: refs,
        coverage_months: ["2026-05", "2026-06", "2026-07"],
      },
    ],
    reason: null,
    warnings: [],
    contract_version: "money-map-v2.1-contract-v1",
  };
}
