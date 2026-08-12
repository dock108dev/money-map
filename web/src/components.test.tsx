import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AccountsView,
  ActivityView,
  ConnectionsView,
  IncomeView,
  OverviewView,
  ReviewView,
  WealthView,
} from "./components";
import type {
  AccountDetail,
  AccountsDashboard,
  Overview,
  PlaidStatus,
  PayrollHistory,
  WealthDashboard,
} from "./types";
import { COPY_BUDGETS, proseWordCount } from "./copy-budget";
import { retiredDuplicateCopy } from "./test-fixtures/slice6-state-matrix";

const accountDetail: AccountDetail = {
  id: 2,
  name: "Investment ••4251",
  institution: "Fidelity",
  institution_kind: "investment",
  type: "401k",
  period: { start: "2026-06-29", end: "2026-07-29" },
  current_balance: "385970.26",
  balance_as_of: "2026-07-29",
  balance_points: [],
  monthly: [],
  activity: [],
  holdings: [
    {
      name: "Vanguard 500 Index",
      ticker: "VANG500",
      type: "mutual fund",
      quantity: "612.054",
      value: "177312.04",
      cost_basis: null,
      as_of: "2026-07-29",
    },
  ],
  cost_basis: null,
  unrealized_gain: null,
  bridges: [],
  performance_status: "tracking",
};

vi.mock("./api", () => ({
  addAccountValue: vi.fn(),
  loadAccountDetail: vi.fn(async () => accountDetail),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const overview: Overview = {
  period: { start: "2025-07-01", end: "2026-06-30" },
  period_presets: {
    trailing_12: { start: "2025-07-01", end: "2026-06-30" },
    current_year: { start: "2026-01-01", end: "2026-07-29" },
  },
  coverage: {
    paychecks_in_period: 1,
    all_imported_paychecks: 1,
    months_present: ["2026-06"],
    destination_detail_complete: 1,
    is_complete: false,
  },
  totals: {},
  percent_of_gross: {},
  latest_payroll_baseline: {
    payment_date: "2026-07-31",
    observed_deposit_date: "2026-07-29",
    annual_salary: "190000.00",
    net_payment: "3765.83",
    detail_complete: true,
    job_title: "Principal SRE",
  },
  recurring_paycheck: {
    cadence: "Every other Wednesday",
    effective_from: "2026-07-29",
    next_expected_deposit: "2026-08-12",
    annual_salary: "190000.00",
    gross_earnings: "7321.31",
    net_payment: "3765.83",
    employee_retirement: "438.46",
    employee_hsa: "34.61",
    employer_retirement: "255.77",
    employer_hsa: "19.23",
    employee_stock_purchase: "730.77",
    employee_fidelity_funding: "1169.23",
    employee_account_funding: "1203.84",
    employer_account_funding: "275.00",
    all_account_value: "5244.67",
    deposit_splits: [],
  },
  annual_snapshots: [],
  allocation: {
    sections: {},
    destinations: [],
    reconciliation: {
      gross: "0.00",
      accounted_from_gross: "0.00",
      residual: "0.00",
      status: "reconciled",
      employer_additions: "0.00",
    },
  },
  cashflow: {
    coverage: { start: "2026-06-29", end: "2026-07-29", transactions: 23 },
    external_inflows: "18107.52",
    external_outflows: "5037.71",
    transfer_in: "0.00",
    transfer_out: "0.00",
    interest: "0.00",
    fees: "0.00",
    net_external: "13069.81",
    matched_transfer_transactions: 0,
  },
  investments: {
    coverage: { start: null, end: null, transactions: 0 },
    employee_contributions: "0.00",
    employer_contributions: "0.00",
    stock_plan_contributions: "0.00",
    employee_fidelity_contributions: "25560.66",
    total_payroll_fidelity_contributions: "33946.57",
    other_contributions: "0.00",
    withdrawals: "0.00",
    investment_result: "0.00",
    bridge_count: 0,
  },
  warnings: [],
};

const accounts: AccountsDashboard = {
  as_of: "2026-07-29",
  activity_period: { start: "2026-06-29", end: "2026-07-29" },
  totals: {
    net_worth: "481235.36",
    assets: "517741.54",
    debts: "36506.18",
    cash: "20215.87",
    investments: "497525.67",
    money_in: "24912.17",
    money_out: "9018.08",
    net_cash_flow: "15894.09",
  },
  accounts: [
    {
      id: 1,
      institution: "SoFi",
      name: "SoFi Checking ••1206",
      type: "checking",
      category: "cash",
      current_balance: "15356.13",
      balance_as_of: "2026-07-29",
      starting_balance: "15356.13",
      starting_balance_as_of: "2026-07-29",
      change: null,
      inflows: "18107.52",
      outflows: "5037.71",
      contributions: "0.00",
      withdrawals: "0.00",
      investment_result: null,
      performance_status: "tracking",
      cost_basis: null,
      unrealized_gain: null,
      balance_point_count: 1,
      transaction_count: 23,
      holding_count: 0,
      holdings: [],
      source: "Plaid",
      last_synced_at: "2026-07-29T23:08:14Z",
      status: "active",
    },
    {
      id: 2,
      institution: "Fidelity",
      name: "Investment ••4251",
      type: "401k",
      category: "investment",
      current_balance: "385970.26",
      balance_as_of: "2026-07-29",
      starting_balance: "385970.26",
      starting_balance_as_of: "2026-07-29",
      change: null,
      inflows: "0.00",
      outflows: "0.00",
      contributions: "88000.00",
      withdrawals: "0.00",
      investment_result: null,
      performance_status: "tracking",
      cost_basis: null,
      unrealized_gain: null,
      balance_point_count: 0,
      transaction_count: 157,
      holding_count: 1,
      holdings: [
        {
          name: "Vanguard 500 Index",
          ticker: "VANG500",
          type: "mutual fund",
          quantity: "612.054",
          value: "177312.04",
          cost_basis: null,
          as_of: "2026-07-29",
        },
      ],
      source: "Plaid",
      last_synced_at: "2026-07-29T23:11:16Z",
      status: "active",
    },
    {
      id: 3,
      institution: "SoFi",
      name: "SoFi Personal Loan ••3776",
      type: "consumer",
      category: "debt",
      current_balance: "36506.18",
      balance_as_of: "2026-07-29",
      starting_balance: "36506.18",
      starting_balance_as_of: "2026-07-29",
      change: null,
      inflows: "0.00",
      outflows: "0.00",
      contributions: "0.00",
      withdrawals: "0.00",
      investment_result: null,
      performance_status: "tracking",
      cost_basis: null,
      unrealized_gain: null,
      balance_point_count: 1,
      transaction_count: 0,
      holding_count: 0,
      holdings: [],
      source: "Plaid",
      last_synced_at: "2026-07-29T23:08:14Z",
      status: "active",
    },
  ],
  activity: [
    {
      id: 10,
      account_id: 1,
      account: "SoFi Checking ••1206",
      institution: "SoFi",
      account_category: "cash",
      date: "2026-07-29",
      description: "OPTUM PAYROLL",
      role: "payroll_deposit",
      direction: "in",
      amount: "3765.83",
      matched_transfer: false,
      source: "Plaid",
    },
    {
      id: 11,
      account_id: 1,
      account: "SoFi Checking ••1206",
      institution: "SoFi",
      account_category: "cash",
      date: "2026-07-28",
      description: "Mortgage payment",
      role: "external_outflow",
      direction: "out",
      amount: "-2100.00",
      matched_transfer: false,
      source: "Plaid",
    },
  ],
};

const wealth: WealthDashboard = {
  as_of: "2026-08-03",
  accessible: {
    total: "33014.92",
    cash: "6761.75",
    sellable_investments: "26253.17",
    accounts: [],
  },
  excluded: {
    total: "459830.08",
    message: "Tracked for performance, excluded from accessible wealth.",
  },
  fidelity: {
    current_value: "486083.25",
    accounts: [
      {
        id: 7,
        name: "Investment ••4251",
        type: "401k",
        current_value: "390408.00",
        accessible_value: "0.00",
        excluded_value: "390408.00",
        access_status: "retirement",
        access_reason: "Retirement or tax-advantaged",
        recent_change: "3560.01",
        performance_status: "tracking",
        investment_result: null,
        return_pct: null,
        performance_message: "Collecting 7 more clean days.",
      },
      {
        id: 8,
        name: "Investment ••5908",
        type: "stock plan",
        current_value: "20974.40",
        accessible_value: "20974.40",
        excluded_value: "0.00",
        access_status: "accessible",
        access_reason: "Sellable stock-plan shares",
        recent_change: "-356.66",
        performance_status: "tracking",
        investment_result: null,
        return_pct: null,
        performance_message: "Collecting 7 more clean days.",
      },
      {
        id: 10,
        name: "Investment ••9228",
        type: "stock plan",
        current_value: "67229.77",
        accessible_value: "0.00",
        excluded_value: "67229.77",
        access_status: "restricted",
        access_reason: "Restricted equity",
        recent_change: "-1146.99",
        performance_status: "tracking",
        investment_result: null,
        return_pct: null,
        performance_message: "Collecting 7 more clean days.",
      },
    ],
    history: [
      { date: "2026-07-31", value: "483989.27" },
      { date: "2026-08-03", value: "486083.25" },
    ],
    recent_observation: {
      period_start: "2026-07-31",
      period_end: "2026-08-03",
      opening_value: "483989.27",
      closing_value: "486083.25",
      change: "2093.98",
      change_pct: "0.43",
      message: "Observed balance movement; not yet a contribution-adjusted return.",
    },
    performance_periods: [
      {
        key: "observed",
        label: "Observed",
        status: "tracking",
        period_start: "2026-08-03",
        period_end: "2026-08-03",
        observation_days: 0,
        required_days: 7,
        opening_value: "486083.25",
        deposits: "0.00",
        withdrawals: "0.00",
        investment_result: null,
        return_pct: null,
        closing_value: "486083.25",
        message: "Collecting 7 more clean days.",
      },
      {
        key: "one_month",
        label: "1 month",
        status: "tracking",
        period_start: "2026-08-03",
        period_end: "2026-08-03",
        observation_days: 0,
        required_days: 30,
        opening_value: "486083.25",
        deposits: "0.00",
        withdrawals: "0.00",
        investment_result: null,
        return_pct: null,
        closing_value: "486083.25",
        message: "Collecting 30 more clean days.",
      },
    ],
    funding: {
      period_start: "2025-08-03",
      period_end: "2026-08-03",
      you_contributed: "25560.66",
      employer_contributed: "8385.91",
      total_payroll_funding: "33946.57",
    },
  },
  paycheck: {
    spendable_cash: "3765.83",
    accessible_stock_funding: "730.77",
    accessible_value_before_spending: "4496.60",
    locked_account_funding: "748.07",
    total_paycheck_value: "5244.67",
  },
};

const plaid: PlaidStatus = {
  configuration: {
    sandbox: { configured: true, client_id_hint: "••••dbox" },
    production: { configured: true, client_id_hint: "••••live" },
  },
  refresh: {
    last_successful_refresh: "2026-07-29T23:11:16Z",
    local_refresh_date: "2026-07-29",
    refresh_needed: false,
    automatic_refresh_due: false,
    refresh_in_progress: false,
    active_connections: 1,
    connections_current: 1,
    connections_needing_attention: false,
    auto_refresh_enabled: true,
    last_auto_refresh_attempt_date: "2026-07-29",
  },
  connections: [
    {
      id: 1,
      environment: "production",
      target: "sofi",
      institution_name: "SoFi",
      status: "active",
      products: ["transactions"],
      consent_expires_at: null,
      last_synced_at: "2026-07-29T23:08:14Z",
      last_error: null,
      account_count: 3,
      history_start: "2026-06-29",
      history_end: "2026-07-29",
      latest_sync: null,
    },
  ],
  security: {
    credentials: "macOS Keychain",
    bank_passwords_stored: false,
    money_movement_enabled: false,
    data_transit: "Plaid",
  },
};

const payroll: PayrollHistory = {
  period: { start: "2025-01-01", end: "2026-07-29" },
  count: 2,
  statement_count: 1,
  calculated_count: 1,
  totals: {
    gross_compensation: "13806.47",
    imputed_earnings: "27.24",
    pretax_deductions: "1140.00",
    tax_withholdings: "4482.17",
    after_tax_deductions: "1461.54",
    federal_taxable_gross: "12739.00",
    net_payments: "7531.67",
    employee_retirement: "876.92",
    employee_hsa: "69.22",
    employee_stock_purchase: "1461.54",
    employee_account_funding: "2407.68",
    employer_retirement: "511.54",
    employer_hsa: "38.46",
    employer_account_funding: "550.00",
    employee_owned_value: "9939.35",
    accessible_value_before_spending: "8993.21",
    locked_account_funding: "1496.14",
    total_paycheck_value: "10489.35",
  },
  rows: [
    {
      id: 2,
      payment_date: "2026-07-31",
      observed_deposit_date: "2026-07-29",
      period_start: "2026-07-12",
      period_end: "2026-07-25",
      payroll_year: 2026,
      payroll_index: 16,
      source_kind: "statement",
      calculation_version: "payroll-history-v1",
      employer: "Optum Services, Inc",
      job_title: "Principal Site Reliability Engineer",
      base_salary: "190000.00",
      gross_earnings: "7321.31",
      imputed_earnings: "13.62",
      pretax_deductions: "570.00",
      tax_withholdings: "2241.09",
      after_tax_deductions: "730.77",
      federal_taxable_gross: "6751.31",
      net_payment: "3765.83",
      employee_retirement: "438.46",
      employee_hsa: "34.61",
      employee_stock_purchase: "730.77",
      employee_account_funding: "1203.84",
      employer_retirement: "255.77",
      employer_hsa: "19.23",
      employer_account_funding: "275.00",
      employee_owned_value: "4969.67",
      accessible_value_before_spending: "4496.60",
      locked_account_funding: "748.07",
      total_paycheck_value: "5244.67",
      adjustments: {},
      has_adjustments: false,
      deposit_splits: [
        { institution: "SoFi", account: "SoFi Checking ••1206", last4: "1206", amount: "1500.00", source_kind: "statement" },
        { institution: "SoFi", account: "SoFi Savings ••0697", last4: "0697", amount: "2265.83", source_kind: "statement" },
      ],
      plaid_match_status: "matched",
      plaid_transactions: [
        { transaction_id: 1, date: "2026-07-29", amount: "1500.00", account: "SoFi Checking ••1206", institution: "SoFi", description: "Optum Services" },
        { transaction_id: 2, date: "2026-07-29", amount: "2265.83", account: "SoFi Savings ••0697", institution: "SoFi", description: "Optum Services" },
      ],
      previous_checkpoint_id: 7,
      next_checkpoint_id: 8,
      source_hash: "abc",
      fingerprint: "def",
      allocations: [],
    },
    {
      id: 1,
      payment_date: "2026-07-17",
      observed_deposit_date: "2026-07-15",
      period_start: "2026-06-28",
      period_end: "2026-07-11",
      payroll_year: 2026,
      payroll_index: 15,
      source_kind: "calculated",
      calculation_version: "payroll-history-v1",
      employer: "Optum Services, Inc",
      job_title: "Principal Site Reliability Engineer",
      base_salary: "190000.00",
      gross_earnings: "6485.16",
      imputed_earnings: "13.62",
      pretax_deductions: "570.00",
      tax_withholdings: "2241.08",
      after_tax_deductions: "730.77",
      federal_taxable_gross: "5987.69",
      net_payment: "3765.84",
      employee_retirement: "438.46",
      employee_hsa: "34.61",
      employee_stock_purchase: "730.77",
      employee_account_funding: "1203.84",
      employer_retirement: "255.77",
      employer_hsa: "19.23",
      employer_account_funding: "275.00",
      employee_owned_value: "4969.68",
      accessible_value_before_spending: "4496.61",
      locked_account_funding: "748.07",
      total_paycheck_value: "5244.68",
      adjustments: { tax: "-0.01", net_payment: "0.01" },
      has_adjustments: true,
      deposit_splits: [
        { institution: "SoFi", account: "SoFi Checking ••1206", last4: "1206", amount: "1500.00", source_kind: "calculated" },
        { institution: "SoFi", account: "SoFi Savings ••0697", last4: "0697", amount: "2265.84", source_kind: "calculated" },
      ],
      plaid_match_status: "not_available",
      plaid_transactions: [],
      previous_checkpoint_id: 7,
      next_checkpoint_id: 8,
      source_hash: null,
      fingerprint: "ghi",
      allocations: [],
    },
  ],
};

describe("account-first views", () => {
  it("separates accessible wealth from contribution-adjusted Fidelity tracking", () => {
    render(<WealthView data={wealth} />);
    expect(screen.getByText("$33,014.92")).toBeInTheDocument();
    expect(screen.getAllByText("$486,083.25")).toHaveLength(3);
    expect(screen.getByText("+$2,093.98")).toBeInTheDocument();
    expect(screen.getByText("Collecting 7 more clean days.")).toBeInTheDocument();
    expect(screen.getByText("Restricted")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1 month" }));
    expect(screen.getByText("Collecting 30 more clean days.")).toBeInTheDocument();
    const budget = document.querySelector('[data-copy-budget="wealth-hero-result"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["wealth-hero-result"]);
    for (const phrase of retiredDuplicateCopy) expect(document.body).not.toHaveTextContent(phrase);
  });

  it("keeps available investment performance textual and visible", () => {
    const available: WealthDashboard = {
      ...wealth,
      fidelity: {
        ...wealth.fidelity,
        performance_periods: [{
          ...wealth.fidelity.performance_periods[0],
          status: "available",
          investment_result: "2093.98",
          return_pct: "0.4300",
          message: "Contribution-adjusted result is available.",
        }],
      },
    };
    render(<WealthView data={available} />);
    expect(screen.getByText("Investment result")).toBeInTheDocument();
    expect(within(screen.getByText("Investment result").closest(".performance-result")!).getByText("+$2,093.98")).toBeInTheDocument();
    expect(screen.getByText("0.43% after contributions")).toBeInTheDocument();
  });

  it("shows the full financial position and quiet paycheck baseline", () => {
    render(
      <OverviewView
        overview={overview}
        accounts={accounts}
        timeline={[]}
        busy={false}
        onPeriodChange={vi.fn()}
        onShowAccounts={vi.fn()}
        onShowActivity={vi.fn()}
        onShowIncome={vi.fn()}
        onShowWealth={vi.fn()}
      />,
    );
    expect(screen.getByText("$481,235")).toBeInTheDocument();
    expect(screen.getByText("$497,526")).toBeInTheDocument();
    expect(screen.getByText("$3,765.83")).toBeInTheDocument();
    expect(screen.getByText("$5,244.67")).toBeInTheDocument();
    expect(screen.getByText(/\$5,244.67 to your accounts/)).toBeInTheDocument();
    expect(screen.getByText("Fidelity funded by you")).toBeInTheDocument();
    expect(screen.getByText("$25,560.66")).toBeInTheDocument();
    expect(screen.getByText("$385,970.26 now")).toBeInTheDocument();
    expect(screen.getByText("Tracking")).toBeInTheDocument();
    expect(screen.queryByText(/unresolved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/second dated/i)).not.toBeInTheDocument();
    expect(document.querySelector('[data-copy-budget="overview-hero-summary"]')).toBeNull();
  });

  it("limits Overview recent activity to five rows", () => {
    const manyActivity = Array.from({ length: 7 }, (_, index) => ({
      ...accounts.activity[0],
      id: 100 + index,
      description: `Synthetic activity ${index + 1}`,
    }));
    render(<OverviewView overview={overview} accounts={{ ...accounts, activity: manyActivity }} timeline={[]} busy={false} onPeriodChange={vi.fn()} onShowAccounts={vi.fn()} onShowActivity={vi.fn()} onShowIncome={vi.fn()} onShowWealth={vi.fn()} />);
    fireEvent.click(screen.getByText("Detailed period evidence"));
    expect(document.querySelectorAll(".overview-evidence .activity-row")).toHaveLength(5);
  });

  it("shows an explicit empty Accounts state", () => {
    render(<AccountsView data={{ ...accounts, accounts: [] }} />);
    expect(screen.getByRole("status")).toHaveTextContent("No accounts are connected");
    const budget = document.querySelector('[data-copy-budget="utility-page-heading"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["utility-page-heading"]);
  });

  it("prints dated Overview and Wealth evidence with collapsed detail still present", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const view = render(<OverviewView overview={overview} accounts={accounts} timeline={[]} busy={false} onPeriodChange={vi.fn()} onShowAccounts={vi.fn()} onShowActivity={vi.fn()} onShowIncome={vi.fn()} onShowWealth={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("Overview evidence · Jul 29");
    expect(screen.getByText("Detailed period evidence").closest("details")).not.toHaveAttribute("open");
    view.unmount();
    render(<WealthView data={wealth} />);
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    expect(print).toHaveBeenCalledTimes(2);
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("Wealth evidence · Aug 3");
    expect(screen.getByText("Fidelity evidence and methodology").closest("details")).not.toHaveAttribute("open");
  });

  it("shows two SoFi payroll destinations with an exact gross reconciliation", () => {
    const flowOverview: Overview = {
      ...overview,
      totals: { gross_compensation: "130264.02" },
      allocation: {
        sections: {},
        destinations: [
          { section: "net", category: "net.0697", label: "SoFi Savings", amount: "56133.09" },
          { section: "net", category: "net.1206", label: "SoFi Checking", amount: "7500.00" },
          { section: "imputed", category: "imputed.non_cash", label: "Non-cash taxable benefits", amount: "1121.13" },
          { section: "employer", category: "employer_benefit.employer_retirement", label: "Employer retirement", amount: "4224.47" },
        ],
        reconciliation: {
          gross: "130264.02",
          accounted_from_gross: "130264.02",
          residual: "0.00",
          status: "reconciled",
          employer_additions: "4224.47",
        },
      },
    };
    render(
      <OverviewView
        overview={flowOverview}
        accounts={accounts}
        timeline={[]}
        busy={false}
        onPeriodChange={vi.fn()}
        onShowAccounts={vi.fn()}
        onShowActivity={vi.fn()}
        onShowIncome={vi.fn()}
        onShowWealth={vi.fn()}
      />,
    );
    expect(screen.getByText("SoFi Savings")).toBeInTheDocument();
    expect(screen.getByText("SoFi Checking")).toBeInTheDocument();
    expect(screen.queryByText("SoFi payroll")).not.toBeInTheDocument();
    expect(screen.getByText("Gross pay accounted for")).toBeInTheDocument();
    expect(screen.getByText("Difference $0.00")).toBeInTheDocument();
    expect(screen.getByText("Employer-paid additions")).toBeInTheDocument();
  });

  it("opens any account without an institution-specific page", async () => {
    render(<AccountsView data={accounts} />);
    fireEvent.click(screen.getByRole("button", { name: /Investment ••4251/ }));
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Investment ••4251 details" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Vanguard 500 Index")).toBeInTheDocument();
    expect(screen.getByText("$177,312")).toBeInTheDocument();
  });

  it("filters activity by where money went", () => {
    render(<ActivityView data={accounts} />);
    expect(screen.getByText("OPTUM PAYROLL")).toBeInTheDocument();
    expect(screen.getByText("Mortgage payment")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Money out" }));
    expect(screen.queryByText("OPTUM PAYROLL")).not.toBeInTheDocument();
    expect(screen.getByText("Mortgage payment")).toBeInTheDocument();
  });

  it("filters already-loaded Activity rows to an inclusive Cash Flow handoff period", () => {
    render(
      <ActivityView
        data={accounts}
        period={{ startDate: "2026-07-29", endDate: "2026-07-29" }}
      />,
    );
    expect(screen.getByText("Jul 29–Jul 29 · inclusive")).toBeInTheDocument();
    expect(screen.getByText("OPTUM PAYROLL")).toBeInTheDocument();
    expect(screen.queryByText("Mortgage payment")).not.toBeInTheDocument();
  });

  it("shows only actionable review issues", () => {
    const onUpdateData = vi.fn();
    const onOpenAccounts = vi.fn();
    render(
      <ReviewView
        onUpdateData={onUpdateData}
        onOpenAccounts={onOpenAccounts}
        issues={[
          {
            id: 1,
            entity_type: "account",
            entity_id: "1",
            rule: "account_balance",
            status: "unreconciled",
            residual: "2153.51",
            details: {
              account_name: "SoFi Personal Loan",
              message: "Account balance does not match its activity.",
              opening_balance: "46071.56",
              accounted_activity: "0.00",
              expected_closing_balance: "46071.56",
              closing_balance: "43918.05",
              likely_cause: "interest_or_balance_adjustment",
              next_steps: ["Update the connection.", "Compare the statement."],
            },
          },
        ]}
      />,
    );
    expect(screen.getByText("account balance")).toBeInTheDocument();
    expect(screen.getByText("Account balance does not match its activity.")).toBeInTheDocument();
    expect(screen.getByText("SoFi Personal Loan")).toBeInTheDocument();
    expect(screen.getByText("$2,153.51")).toBeInTheDocument();
    expect(screen.getByText("account balance").closest(".review-card")).toHaveTextContent("Unexplained difference$2,153.51");
    expect(screen.getByText("Compare the statement.")).toBeInTheDocument();
    expect(proseWordCount(document.querySelector('[data-copy-budget="utility-page-heading"]')!)).toBeLessThanOrEqual(COPY_BUDGETS["utility-page-heading"]);
    fireEvent.click(screen.getByRole("button", { name: "Update data" }));
    fireEvent.click(screen.getByRole("button", { name: "Open accounts" }));
    expect(onUpdateData).toHaveBeenCalledOnce();
    expect(onOpenAccounts).toHaveBeenCalledOnce();
  });

  it("adds generic account types and lists the actual institution", () => {
    const onConnect = vi.fn();
    const onSync = vi.fn();
    const onAutoRefreshChange = vi.fn();
    render(
      <ConnectionsView
        plaid={plaid}
        busy={false}
        message=""
        onConfigure={vi.fn()}
        onConnect={onConnect}
        onSync={onSync}
        onRepair={vi.fn()}
        onDisconnect={vi.fn()}
        imports={[]}
        onImport={vi.fn()}
        onReport={vi.fn()}
        onAutoRefreshChange={onAutoRefreshChange}
      />,
    );
    expect(screen.getByText("SoFi")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Bank, credit or loan/ }));
    expect(onConnect).toHaveBeenCalledWith("sofi", "production");
    fireEvent.click(screen.getByRole("button", { name: /Investment account/ }));
    expect(onConnect).toHaveBeenCalledWith("fidelity", "production");
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    expect(onSync).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("checkbox", { name: /Update automatically/ }));
    expect(onAutoRefreshChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("button", { name: "Connect SoFi" })).not.toBeInTheDocument();
  });

  it("shows five recent imports before older evidence is requested", () => {
    const imports = Array.from({ length: 7 }, (_, index) => ({
      id: index + 1,
      created_at: `2026-08-${String(index + 1).padStart(2, "0")}T12:00:00Z`,
      status: "complete",
      discovered: 1,
      imported: 1,
      duplicates: 0,
      errors: 0,
    }));
    render(<ConnectionsView plaid={plaid} busy={false} message="" onConfigure={vi.fn()} onConnect={vi.fn()} onSync={vi.fn()} onRepair={vi.fn()} onDisconnect={vi.fn()} imports={imports} onImport={vi.fn()} onReport={vi.fn()} onAutoRefreshChange={vi.fn()} />);
    expect(document.querySelectorAll(".import-history-compact > div")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Show older evidence" }));
    expect(document.querySelectorAll(".import-history-compact > div")).toHaveLength(7);
  });

  it("filters completed income and opens concise paycheck details", () => {
    render(<IncomeView data={payroll} />);
    expect(screen.getByText("2 paychecks")).toBeInTheDocument();
    expect(screen.getByText("$7,531.67")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-07-29" } });
    expect(screen.getByText("1 paychecks")).toBeInTheDocument();
    expect(screen.getAllByText("$3,765.83")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /Jul 29/ }));
    expect(screen.getByRole("complementary", { name: "Paycheck details" })).toBeInTheDocument();
    expect(screen.getByText("Matched to 2 Plaid deposits.")).toBeInTheDocument();
    expect(screen.queryByText(/unresolved/i)).not.toBeInTheDocument();
  });
});
