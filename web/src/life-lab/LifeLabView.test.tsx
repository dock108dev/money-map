import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GoalEditor } from "./GoalEditor";
import { exitMath, loanMath, weeklySprint } from "./DriveCalculator";
import LifeLabView from "./LifeLabView";
import type { LifeProjection, PathResult } from "./life-lab-types";

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

const profile = {
  id: 1,
  birth_date: "1991-01-01",
  state: "NJ",
  end_age: 95,
  current_monthly_outflow: "6000.00",
  essential_monthly_spend: "4000.00",
  flexible_monthly_spend: "2000.00",
  cash_floor: "10000.00",
  retirement_tax_rate_pct: "20.00",
  target_ages: [43, 57, 73],
  notes: "",
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
  provenance: {
    birth_date: "user_entered" as const,
    state: "user_entered" as const,
    end_age: "assumed" as const,
    current_monthly_outflow: "user_entered" as const,
    essential_monthly_spend: "user_entered" as const,
    flexible_monthly_spend: "user_entered" as const,
    cash_floor: "user_entered" as const,
    retirement_tax_rate_pct: "assumed" as const,
    target_ages: "user_entered" as const,
  },
};

const startingPoint = {
  as_of: "2026-08-03",
  cash: "20000.00",
  accessible_investments: "50000.00",
  pretax_retirement: "400000.00",
  hsa: "12000.00",
  restricted_assets: "30000.00",
  debt: "0.00",
  accessible_total: "70000.00",
  tracked_total: "512000.00",
  observed_monthly_outflow: "5750.00",
  outflow_months: ["2026-05", "2026-06"],
  payroll: {
    payment_date: "2026-07-31",
    observed_deposit_date: "2026-07-31",
    annual_salary: "215000.00",
    gross_per_paycheck: "8269.23",
    net_per_paycheck: "4300.00",
    employee_retirement_per_paycheck: "500.00",
    employer_retirement_per_paycheck: "250.00",
    employee_hsa_per_paycheck: "50.00",
    employer_hsa_per_paycheck: "20.00",
    stock_plan_per_paycheck: "800.00",
    provenance: "observed" as const,
  },
  accounts: [],
  warnings: [],
};

function path(
  targetAge: number,
  key: PathResult["path_key"],
  status: PathResult["status"],
): PathResult {
  return {
    target_age: targetAge,
    path_key: key,
    path_label: key === "middle" ? "Middle path" : key === "rough" ? "Rough path" : "Early-crash path",
    status,
    first_shortfall_month: status === "insufficient_accessible_bridge" ? "2038-03-01" : null,
    work_stop_month: `${1991 + targetAge}-01-01`,
    work_stop_assets: { cash: "10000.00", accessible_investments: "90000.00", pretax_retirement: "650000.00", hsa: "12000.00", restricted_assets: "30000.00" },
    end_assets: { cash: "10000.00", accessible_investments: "120000.00", pretax_retirement: "350000.00", hsa: "12000.00", restricted_assets: "30000.00", debt: "0.00", total_spendable: "410000.00" },
    goal_results: {},
    make_it_happen: {
      additional_monthly_after_tax_income: "12500.00",
      retirement_capital_needed: "1000000.00",
      retirement_deadline: `${1991 + targetAge}-01-01`,
      pre_retirement_shortfall_month: targetAge === 43 ? "2029-04-01" : null,
    },
    periods: [
      { month: "2026-08-01", age_months: 427, working: true, gross_income: "17916.67", net_income: "9316.67", employee_retirement: "1083.33", employer_retirement: "541.67", stock_plan: "1733.33", essential_spend: "5750.00", flexible_spend: "0.00", goal_spend: "0.00", cash: "10000.00", accessible_investments: "70000.00", pretax_retirement: "400000.00", hsa: "12000.00", restricted_assets: "30000.00", debt: "0.00", investment_result: "0.00", total_spendable: "400000.00" },
      { month: "2034-01-01", age_months: targetAge * 12, working: false, gross_income: "0.00", net_income: "0.00", employee_retirement: "0.00", employer_retirement: "0.00", stock_plan: "0.00", essential_spend: "4000.00", flexible_spend: "2000.00", goal_spend: "0.00", cash: "10000.00", accessible_investments: "90000.00", pretax_retirement: "650000.00", hsa: "12000.00", restricted_assets: "30000.00", debt: "0.00", investment_result: "1000.00", total_spendable: "620000.00" },
    ],
  };
}

const projection: LifeProjection = {
  engine_version: "life-lab-v0.3.0",
  source_fingerprint: "fingerprint",
  generated_at: "2026-08-03T00:00:00Z",
  as_of: "2026-08-03",
  profile,
  starting_point: startingPoint,
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
  assumptions: {
    version: "assumptions-v1",
    today_dollars: true,
    cash_real_return_pct: "0.00",
    retirement_access_age: "59.5",
    paths: {},
    omissions: ["Social Security", "early-withdrawal exceptions", "probability of success"],
  },
  results: [43, 57, 73].map((targetAge) => ({
    target_age: targetAge,
    paths: [
      path(targetAge, "middle", "works"),
      path(targetAge, "rough", "works_essentials_only"),
      path(targetAge, "early_crash", "insufficient_accessible_bridge"),
    ],
  })),
  goal_impacts: { "43": [], "57": [], "73": [] },
  warnings: ["Assumption-driven planning model."],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Life Lab", () => {
  it("explores arbitrary ages, deterministic paths, and annual table data", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/life-plan/profile") return json(profile);
      if (url === "/api/life-plan/starting-point") return json(startingPoint);
      if (url === "/api/life-plan/goals" || url === "/api/life-plan/scenarios") return json([]);
      if (url === "/api/life-plan/project") return json(projection);
      return new Response("Not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);

    expect(await screen.findByRole("heading", { name: "What would it take?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Age 43" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Age 57" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Age 73" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Works" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Build $1,000,000 by Jan 1, 2034." })).toBeInTheDocument();
    expect(screen.getByText(/Turn \$5,000 into \$1,000,000 in 387 weeks/)).toBeInTheDocument();
    expect(screen.getByText(/Separate runway problem/)).toBeInTheDocument();
    expect(screen.getByText(/0.9%\/week compounds to 59.3%\/year/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Current IRS boundary" })).toHaveAttribute(
      "href",
      "https://www.irs.gov/retirement-plans/retirement-plans-faqs-regarding-loans",
    );
    expect(screen.getByText("Top 10% threshold").parentElement).toHaveClass("current");
    expect(screen.queryByRole("heading", { name: /probability of success/i })).not.toBeInTheDocument();
    expect(screen.queryByText("17%")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("spinbutton", { name: /^Starting stake/ }), { target: { value: "20000" } });
    expect(screen.getByText(/Turn \$20,000 into \$1,000,000 in 387 weeks/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Capital target"), { target: { value: "2000000" } });
    fireEvent.change(screen.getByLabelText("Build / exit deadline"), { target: { value: "2035-01-01" } });
    expect(screen.getByRole("heading", { name: "Build $2,000,000 by Jan 1, 2035." })).toBeInTheDocument();
    expect(screen.getByText(/Custom math mode/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Early-crash path" }));
    expect(screen.getByRole("heading", { name: "Bridge breaks" })).toBeInTheDocument();
    expect(screen.getByText(/does not assume a 401\(k\) loan/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Work optional")).toBeInTheDocument();
  });

  it("captures a generic dated goal without product-specific fields", () => {
    const onAdd = vi.fn();
    render(<GoalEditor goals={[]} impacts={[]} busy={false} onAdd={onAdd} onUpdate={vi.fn()} onDelete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add goal" }));
    fireEvent.change(screen.getByLabelText("Goal name"), { target: { value: "Ten-day splurge" } });
    fireEvent.change(screen.getByLabelText("Target date"), { target: { value: "2028-09-01" } });
    fireEvent.change(screen.getByLabelText("Target amount"), { target: { value: "15000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to plan" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ name: "Ten-day splurge", target_amount: "15000", priority: "required" }));
  });

  it("keeps the fanatical routes as inspectable arithmetic", () => {
    const sprint = weeklySprint(5000, 1000000, 52, 0.9);
    expect(sprint.first_week_profit).toBeCloseTo(45);
    expect(sprint.assumed_annualized_pct).toBeCloseTo(59.35, 2);
    expect(sprint.required_weekly_pct).toBeGreaterThan(10);

    const exit = exitMath(1000000, 20, 30, 5);
    expect(exit.companyExit).toBeCloseTo(7142857.14, 1);
    expect(exit.annualRevenue).toBeCloseTo(1428571.43, 1);

    const loan = loanMath(547426, 0, 0, 8.5, 5);
    expect(loan.newLoan).toBe(50000);
    expect(loan.payment).toBeGreaterThan(1000);
    expect(loan.payment).toBeLessThan(1100);
  });
});
