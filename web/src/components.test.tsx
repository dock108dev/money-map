import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AccountsView,
  ActivityView,
  ConnectionsView,
  IncomeView,
  OverviewView,
  ReviewView,
} from "./components";
import type {
  AccountDetail,
  AccountsDashboard,
  Overview,
  PlaidStatus,
  PayrollHistory,
} from "./types";

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

afterEach(cleanup);

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
    employer_retirement: "255.77",
    employee_stock_purchase: "730.77",
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
      />,
    );
    expect(screen.getByText("$481,235")).toBeInTheDocument();
    expect(screen.getByText("$497,526")).toBeInTheDocument();
    expect(screen.getByText("$3,765.83")).toBeInTheDocument();
    expect(screen.queryByText(/unresolved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/second dated/i)).not.toBeInTheDocument();
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

  it("shows only actionable review issues", () => {
    render(
      <ReviewView
        issues={[
          {
            id: 1,
            entity_type: "account",
            entity_id: "1",
            rule: "account_balance",
            status: "unreconciled",
            residual: "2.00",
            details: { message: "Account balance does not match its activity." },
          },
        ]}
      />,
    );
    expect(screen.getByText("account balance")).toBeInTheDocument();
    expect(screen.getByText("Account balance does not match its activity.")).toBeInTheDocument();
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
