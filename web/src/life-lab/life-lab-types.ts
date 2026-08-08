export type Money = string;

export interface LifePlanProfile {
  id: number;
  birth_date: string;
  state: string;
  end_age: number;
  current_monthly_outflow: Money;
  essential_monthly_spend: Money;
  flexible_monthly_spend: Money;
  cash_floor: Money;
  retirement_tax_rate_pct: string;
  target_ages: number[];
  notes: string;
  created_at: string;
  updated_at: string;
  provenance: Record<string, "observed" | "user_entered" | "assumed" | "unverified">;
}

export interface LifePlanProfileInput {
  birth_date: string;
  state: string;
  end_age: number;
  current_monthly_outflow: string;
  essential_monthly_spend: string;
  flexible_monthly_spend: string;
  cash_floor: string;
  retirement_tax_rate_pct: string;
  target_ages: number[];
  notes: string;
}

export interface LifeGoal {
  id: number;
  profile_id: number;
  name: string;
  target_date: string;
  target_amount: Money;
  reserved_amount: Money;
  annual_cost: Money;
  priority: "required" | "flexible";
  enabled: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
  provenance: "user_entered";
}

export interface LifeGoalInput {
  name: string;
  target_date: string;
  target_amount: string;
  reserved_amount: string;
  annual_cost: string;
  priority: "required" | "flexible";
  enabled: boolean;
  notes: string;
}

export interface LifeStartingPoint {
  as_of: string;
  cash: Money;
  accessible_investments: Money;
  pretax_retirement: Money;
  hsa: Money;
  restricted_assets: Money;
  debt: Money;
  accessible_total: Money;
  tracked_total: Money;
  observed_monthly_outflow: Money;
  outflow_months: string[];
  payroll: {
    payment_date: string;
    observed_deposit_date: string;
    annual_salary: Money;
    gross_per_paycheck: Money;
    net_per_paycheck: Money;
    employee_retirement_per_paycheck: Money;
    employer_retirement_per_paycheck: Money;
    employee_hsa_per_paycheck: Money;
    employer_hsa_per_paycheck: Money;
    stock_plan_per_paycheck: Money;
    provenance: "observed";
  } | null;
  accounts: Array<{
    name: string;
    type: string;
    value: Money;
    access_status: string;
    access_reason: string;
    as_of: string;
    provenance: string;
  }>;
  warnings: string[];
}

export interface IncomeBenchmarks {
  available: boolean;
  version?: string;
  definition?: string;
  source_year?: number;
  normalized_dollar_basis?: string;
  state?: string;
  state_name?: string;
  thresholds?: Record<string, { source_amount: Money; normalized_amount: Money }>;
  current_income?: Money | null;
  current_income_context?: string | null;
  warning: string;
  sources?: Record<string, string>;
}

export interface LifeProjectionPeriod {
  month: string;
  age_months: number;
  working: boolean;
  gross_income: Money;
  net_income: Money;
  additional_income?: Money;
  employee_retirement: Money;
  employer_retirement: Money;
  stock_plan: Money;
  essential_spend: Money;
  flexible_spend: Money;
  goal_spend: Money;
  cash: Money;
  accessible_investments: Money;
  pretax_retirement: Money;
  hsa: Money;
  restricted_assets: Money;
  debt: Money;
  investment_result: Money;
  total_spendable: Money;
}

export interface PathResult {
  target_age: number;
  path_key: "middle" | "rough" | "early_crash";
  path_label: string;
  status: "works" | "works_essentials_only" | "shortfall" | "insufficient_accessible_bridge";
  first_shortfall_month: string | null;
  work_stop_month: string;
  work_stop_assets: Record<string, Money>;
  end_assets: Record<string, Money>;
  goal_results: Record<string, { funded: boolean; shortfall: Money }>;
  make_it_happen: {
    additional_monthly_after_tax_income: Money | null;
    retirement_capital_needed: Money | null;
    retirement_deadline: string;
    pre_retirement_shortfall_month: string | null;
  };
  periods: LifeProjectionPeriod[];
}

export interface TargetResult {
  target_age: number;
  paths: PathResult[];
}

export interface GoalImpact {
  goal_id: number;
  name: string;
  required_monthly_saving: Money;
  cash_funded: boolean;
  end_asset_change: Money;
  first_shortfall_with_goal: string | null;
  first_shortfall_without_goal: string | null;
  creates_bridge_failure: boolean;
  work_optional_delay_years: number | null;
}

export interface LifeProjection {
  engine_version: string;
  source_fingerprint: string;
  generated_at: string;
  as_of: string;
  profile: LifePlanProfile;
  starting_point: LifeStartingPoint;
  benchmarks: IncomeBenchmarks;
  goals: LifeGoal[];
  assumptions: {
    version: string;
    today_dollars: boolean;
    cash_real_return_pct: string;
    retirement_access_age: string;
    paths: Record<string, Record<string, string>>;
    omissions: string[];
  };
  results: TargetResult[];
  goal_impacts: Record<string, GoalImpact[]>;
  warnings: string[];
}

export interface SavedLifeScenario {
  id: number;
  name: string;
  target_age: number;
  path_key: string;
  status: string;
  summary: Record<string, unknown>;
  warnings: string[];
  engine_version: string;
  assumption_version: string;
  benchmark_version: string;
  source_fingerprint: string;
  stale: boolean;
  created_at: string;
  periods: Array<{
    month: string;
    age_months: number;
    working: boolean;
    cash: Money;
    accessible_investments: Money;
    pretax_retirement: Money;
    total_spendable: Money;
  }>;
}
