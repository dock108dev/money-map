export type Money = string | null;

export interface Overview {
  period: { start: string; end: string };
  period_presets: Record<string, { start: string; end: string }>;
  coverage: {
    paychecks_in_period: number;
    all_imported_paychecks: number;
    months_present: string[];
    destination_detail_complete: number;
    is_complete: boolean;
  };
  totals: Record<string, Money>;
  percent_of_gross: Record<string, string>;
  latest_payroll_baseline: {
    payment_date: string;
    observed_deposit_date: string | null;
    annual_salary: Money;
    net_payment: Money;
    detail_complete: boolean;
    job_title: string | null;
  } | null;
  recurring_paycheck: {
    cadence: string;
    effective_from: string;
    next_expected_deposit: string;
    annual_salary: Money;
    gross_earnings: Money;
    net_payment: Money;
    employee_retirement: Money;
    employer_retirement: Money;
    employee_stock_purchase: Money;
    deposit_splits: Array<{ label: string; amount: Money }>;
  } | null;
  annual_snapshots: Array<{
    year: number;
    as_of: string;
    official_year_end: boolean;
    gross_earnings: Money;
    imputed_earnings: Money;
    tax_withholdings: Money;
    pretax_deductions: Money;
    after_tax_deductions: Money;
    net_payment: Money;
    employee_retirement: Money;
    employee_hsa: Money;
    health_premiums: Money;
    employee_stock_purchase: Money;
    stock_offset: Money;
    employer_contributions: Money;
  }>;
  allocation: {
    sections: Record<string, Money>;
    destinations: Array<{
      section: string;
      category: string;
      label: string;
      amount: Money;
    }>;
    reconciliation: {
      gross: Money;
      accounted_from_gross: Money;
      residual: Money;
      status: "reconciled" | "unreconciled";
      employer_additions: Money;
    };
  };
  cashflow: {
    coverage: { start: string | null; end: string | null; transactions: number };
    external_inflows: Money;
    external_outflows: Money;
    transfer_in: Money;
    transfer_out: Money;
    interest: Money;
    fees: Money;
    net_external: Money;
    matched_transfer_transactions: number;
  };
  investments: {
    coverage: { start: string | null; end: string | null; transactions: number };
    employee_contributions: Money;
    employer_contributions: Money;
    stock_plan_contributions: Money;
    other_contributions: Money;
    withdrawals: Money;
    investment_result: Money;
    bridge_count: number;
  };
  warnings: string[];
}

export interface Reconciliation {
  rule: string;
  status: string;
  residual: Money;
  details: Record<string, unknown>;
}

export interface Paycheck {
  id: number;
  payment_date: string;
  observed_deposit_date: string | null;
  period_start: string;
  period_end: string;
  employer: string;
  job_title: string | null;
  base_salary: Money;
  gross_earnings: Money;
  imputed_earnings: Money;
  pretax_deductions: Money;
  tax_withholdings: Money;
  after_tax_deductions: Money;
  federal_taxable_gross: Money;
  net_payment: Money;
  detail_complete: boolean;
  details: Array<{
    section: string;
    category: string;
    label: string;
    amount: Money;
    ytd_amount: Money;
    reduces_net: boolean;
  }>;
  source: { filename: string; hash: string; parser_version: string };
  evidence: Array<{
    field: string;
    location: string;
    label: string;
    confidence: string;
    review_status: string;
  }>;
  reconciliation: Reconciliation[];
}

export interface PayrollEntry {
  id: number;
  payment_date: string;
  observed_deposit_date: string;
  period_start: string;
  period_end: string;
  payroll_year: number;
  payroll_index: number;
  source_kind: "statement" | "calculated";
  calculation_version: string;
  employer: string;
  job_title: string | null;
  base_salary: Money;
  gross_earnings: Money;
  imputed_earnings: Money;
  pretax_deductions: Money;
  tax_withholdings: Money;
  after_tax_deductions: Money;
  federal_taxable_gross: Money;
  net_payment: Money;
  adjustments: Record<string, Money>;
  has_adjustments: boolean;
  deposit_splits: Array<{
    institution: string;
    account: string;
    last4: string | null;
    amount: string;
    source_kind: "statement" | "calculated";
  }>;
  plaid_match_status: "matched" | "not_available";
  plaid_transactions: Array<{
    transaction_id: number;
    date: string;
    amount: Money;
    account: string;
    institution: string;
    description: string;
  }>;
  previous_checkpoint_id: number | null;
  next_checkpoint_id: number | null;
  source_hash: string | null;
  fingerprint: string;
  allocations: Array<{
    section: string;
    category: string;
    label: string;
    amount: Money;
    source_kind: "statement" | "calculated";
  }>;
}

export interface PayrollHistory {
  period: { start: string; end: string };
  count: number;
  statement_count: number;
  calculated_count: number;
  totals: {
    gross_compensation: Money;
    imputed_earnings: Money;
    pretax_deductions: Money;
    tax_withholdings: Money;
    after_tax_deductions: Money;
    federal_taxable_gross: Money;
    net_payments: Money;
  };
  rows: PayrollEntry[];
}

export interface ReviewIssue {
  id: number;
  entity_type: string;
  entity_id: string;
  rule: string;
  status: string;
  residual: Money;
  details: Record<string, unknown>;
}

export interface TimelineRow {
  month: string;
  gross_pay: Money;
  taxes: Money;
  pretax: Money;
  after_tax: Money;
  employer_contributions: Money;
  net_pay: Money;
  cash_inflows: Money;
  cash_outflows: Money;
  transfers: Money;
  investment_contributions: Money;
  investment_result: Money;
  status: string;
}

export interface ForecastPeriod {
  month: string;
  gross_pay: Money;
  taxes: Money;
  benefits_and_other: Money;
  employee_retirement: Money;
  employee_hsa: Money;
  stock_plan: Money;
  employer_retirement: Money;
  employer_hsa: Money;
  sofi_checking: Money;
  sofi_savings: Money;
  external_outflow: Money;
  ending_checking: Money;
  ending_savings: Money;
  ending_cash: Money;
  cash_redirect_to_investments: Money;
  assumed_investment_result: Money;
}

export interface Scenario {
  id: number;
  name: string;
  is_baseline: boolean;
  inputs: Record<string, unknown>;
  periods: ForecastPeriod[];
}

export interface ImportBatch {
  id: number;
  created_at: string;
  status: string;
  discovered: number;
  imported: number;
  duplicates: number;
  errors: number;
}

export interface SofiSummary {
  accounts: Array<Record<string, Money | string | number>>;
  consolidated_external_net: Money;
  internal_transfer_pairs: number;
  warnings: string[];
}

export interface FidelitySummary {
  accounts: Array<Record<string, unknown>>;
  consolidated: Record<string, Money>;
  warnings: string[];
}

export interface PlaidConnection {
  id: number;
  environment: "sandbox" | "production";
  target: "sofi" | "fidelity";
  institution_name: string;
  status: string;
  products: string[];
  consent_expires_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  account_count: number;
  history_start: string | null;
  history_end: string | null;
  latest_sync: {
    status: string;
    accounts: number;
    transactions: number;
    holdings: number;
    started_at: string;
    finished_at: string | null;
  } | null;
}

export interface PlaidStatus {
  configuration: Record<
    "sandbox" | "production",
    { configured: boolean; client_id_hint: string | null }
  >;
  connections: PlaidConnection[];
  refresh: {
    last_successful_refresh: string | null;
    local_refresh_date: string;
    refresh_needed: boolean;
    automatic_refresh_due: boolean;
    refresh_in_progress: boolean;
    active_connections: number;
    connections_current: number;
    connections_needing_attention: boolean;
    auto_refresh_enabled: boolean;
    last_auto_refresh_attempt_date: string | null;
  };
  security: {
    credentials: string;
    bank_passwords_stored: boolean;
    money_movement_enabled: boolean;
    data_transit: string;
  };
}

export interface PlaidRefreshResult {
  status: "complete" | "partial" | "skipped";
  reason?: string;
  started_at: string;
  finished_at: string;
  requested: number;
  succeeded: number;
  failed: number;
  connections: Array<{
    connection_id: number;
    institution: string;
    status: "complete" | "failed";
    accounts: number;
    transactions: number;
    holdings: number;
    balance_snapshot_date: string | null;
    started_at: string;
    finished_at: string;
    last_synced_at: string | null;
    error_code: string | null;
    message: string | null;
  }>;
  freshness: PlaidStatus["refresh"];
}

export interface AccountHolding {
  name: string;
  ticker: string | null;
  type: string;
  quantity: string;
  value: Money;
  cost_basis: Money;
  as_of: string;
}

export interface ConnectedAccount {
  id: number;
  institution: string;
  name: string;
  type: string;
  category: "cash" | "investment" | "debt" | "other";
  current_balance: Money;
  balance_as_of: string | null;
  starting_balance: Money;
  starting_balance_as_of: string | null;
  change: Money;
  inflows: Money;
  outflows: Money;
  contributions: Money;
  withdrawals: Money;
  investment_result: Money;
  performance_status: "available" | "tracking";
  cost_basis: Money;
  unrealized_gain: Money;
  balance_point_count: number;
  transaction_count: number;
  holding_count: number;
  holdings: AccountHolding[];
  source: string;
  last_synced_at: string | null;
  status: string;
}

export interface AccountDetail {
  id: number;
  name: string;
  institution: string;
  institution_kind: "bank" | "investment" | string;
  type: string;
  period: { start: string; end: string };
  current_balance: Money;
  balance_as_of: string | null;
  balance_points: Array<{
    date: string;
    kind: string;
    amount: Money;
    source_kind: "observed" | "calculated";
  }>;
  monthly: Array<{
    month: string;
    opening: Money;
    inflows: Money;
    outflows: Money;
    closing: Money;
  }>;
  activity: Array<{
    id: number;
    date: string;
    description: string;
    role: string;
    amount: Money;
    matched_transfer: boolean;
  }>;
  holdings: AccountHolding[];
  cost_basis: Money;
  unrealized_gain: Money;
  bridges: Array<Record<string, Money | string>>;
  performance_status: "available" | "tracking";
}

export interface AccountActivity {
  id: number;
  account_id: number;
  account: string;
  institution: string;
  account_category: ConnectedAccount["category"];
  date: string;
  description: string;
  role: string;
  direction: "in" | "out" | "transfer" | "neutral";
  amount: Money;
  matched_transfer: boolean;
  source: string;
}

export interface AccountsDashboard {
  as_of: string | null;
  activity_period: { start: string | null; end: string | null };
  totals: {
    net_worth: Money;
    assets: Money;
    debts: Money;
    cash: Money;
    investments: Money;
    money_in: Money;
    money_out: Money;
    net_cash_flow: Money;
  };
  accounts: ConnectedAccount[];
  activity: AccountActivity[];
}

export interface DashboardData {
  overview: Overview;
  accounts: AccountsDashboard;
  paychecks: Paycheck[];
  issues: ReviewIssue[];
  timeline: TimelineRow[];
  scenarios: Scenario[];
  imports: ImportBatch[];
  sofi: SofiSummary;
  fidelity: FidelitySummary;
  plaid: PlaidStatus;
  payroll: PayrollHistory;
}
