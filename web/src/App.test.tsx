import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { cashFlowFixture } from "./cash-flow/test-fixtures";
import {
  comparisonState,
  latestState,
  milestoneState,
  noCandidatesState,
  positionState,
  primaryState,
  unchangedObservation,
} from "./goals/fixtures";
import { goalProgram } from "./goals/fixtures";
import {
  labResult,
  labSeed,
  legacySnapshot,
  retirementProfile,
  retirementRun,
  retirementSnapshot,
  retirementStartingPoint,
} from "./retirement/test-fixtures";

const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });

const overview = {
  period: { start: "2025-07-01", end: "2026-06-30" },
  period_presets: {},
  coverage: { paychecks_in_period: 26, all_imported_paychecks: 8, months_present: [], destination_detail_complete: 3, is_complete: true },
  totals: { gross_compensation: "100.00", taxes: "20.00", net_payments: "70.00" },
  percent_of_gross: {},
  latest_payroll_baseline: null,
  recurring_paycheck: null,
  annual_snapshots: [],
  allocation: {
    sections: {},
    destinations: [],
    reconciliation: {
      accounted_from_gross: "100.00",
      residual: "0.00",
      status: "reconciled",
    },
  },
  cashflow: { coverage: { start: null, end: null, transactions: 0 }, external_inflows: "0.00", external_outflows: "0.00", transfer_in: "0.00", transfer_out: "0.00", interest: "0.00", fees: "0.00", net_external: "0.00", matched_transfer_transactions: 0 },
  investments: { coverage: { start: null, end: null, transactions: 0 }, employee_contributions: "0.00", employer_contributions: "0.00", stock_plan_contributions: "0.00", employee_fidelity_contributions: "0.00", total_payroll_fidelity_contributions: "0.00", other_contributions: "0.00", withdrawals: "0.00", investment_result: "0.00", bridge_count: 0 },
  warnings: [],
};

const accounts = {
  as_of: "2026-07-29",
  activity_period: { start: null, end: null },
  totals: { net_worth: "100.00", assets: "100.00", debts: "0.00", cash: "100.00", investments: "0.00", money_in: "0.00", money_out: "0.00", net_cash_flow: "0.00" },
  accounts: [],
  activity: [],
};

const wealth = {
  as_of: "2026-08-03",
  accessible: { total: "33014.92", cash: "6761.75", sellable_investments: "26253.17", accounts: [] },
  excluded: { total: "459830.08", message: "Tracked separately." },
  fidelity: {
    current_value: "486083.25",
    accounts: [],
    history: [],
    recent_observation: null,
    performance_periods: [],
    funding: { period_start: "2025-08-03", period_end: "2026-08-03", you_contributed: "25560.66", employer_contributed: "8385.91", total_payroll_funding: "33946.57" },
  },
  paycheck: { spendable_cash: "3765.83", accessible_stock_funding: "730.77", accessible_value_before_spending: "4496.60", locked_account_funding: "748.07", total_paycheck_value: "5244.67" },
};

function plaid(refreshDue: boolean, connectionCount = 1) {
  return {
    configuration: {
      sandbox: { configured: false, client_id_hint: null },
      production: { configured: true, client_id_hint: "••••live" },
    },
    connections: Array.from({ length: connectionCount }, (_, index) => ({
      id: index + 1,
      environment: "production",
      target: index === 0 ? "sofi" : "fidelity",
      institution_name: index === 0 ? "Bank" : "Investment provider",
      status: "active",
      products: [],
      consent_expires_at: null,
      last_synced_at: "2026-07-29T20:00:00Z",
      last_error: null,
      account_count: index === 0 ? 3 : 7,
      history_start: null,
      history_end: null,
      latest_sync: null,
    })),
    refresh: {
      last_successful_refresh: "2026-07-29T20:00:00Z",
      local_refresh_date: "2026-07-31",
      refresh_needed: refreshDue,
      automatic_refresh_due: refreshDue,
      refresh_in_progress: false,
      active_connections: connectionCount,
      connections_current: refreshDue ? 0 : connectionCount,
      connections_needing_attention: false,
      auto_refresh_enabled: true,
      last_auto_refresh_attempt_date: null,
    },
    security: { credentials: "macOS Keychain", bank_passwords_stored: false, money_movement_enabled: false, data_transit: "Plaid" },
  };
}

function workingFetch(
  refreshDue = false,
  connectionCount = 1,
  options: { issues?: unknown[]; failedConnections?: number } = {},
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/plaid/sync-all") {
      return json({
        status: options.failedConnections ? "partial" : "complete",
        started_at: "2026-07-31T15:00:00Z",
        finished_at: "2026-07-31T15:00:01Z",
        requested: connectionCount,
        succeeded: Math.max(connectionCount - (options.failedConnections ?? 0), 0),
        failed: options.failedConnections ?? 0,
        connections: connectionCount
          ? [{ connection_id: 1, institution: "Bank", status: options.failedConnections ? "failed" : "complete", accounts: options.failedConnections ? 0 : 10, transactions: 0, holdings: 0, balance_snapshot_date: "2026-07-31", started_at: "2026-07-31T15:00:00Z", finished_at: "2026-07-31T15:00:01Z", last_synced_at: options.failedConnections ? null : "2026-07-31T15:00:01Z", error_code: options.failedConnections ? "provider_unavailable" : null, message: options.failedConnections ? "Try again." : null }]
          : [],
        freshness: plaid(false, connectionCount).refresh,
        goal_observation: { ...unchangedObservation, trigger: "post_refresh" },
        automatic: init?.body,
      });
    }
    if (url.startsWith("/api/v2/cash-flow?")) return json(cashFlowFixture());
    if (url === "/api/accounts") return json(accounts);
    if (url === "/api/wealth") return json(wealth);
    if (url === "/api/exceptions") return json(options.issues ?? []);
    if (url === "/api/timeline" || url === "/api/scenarios" || url === "/api/imports") return json([]);
    if (url === "/api/plaid/status") return json(plaid(refreshDue, connectionCount));
    if (url === "/api/payroll") return json({ period: { start: "2025-01-01", end: "2026-07-29" }, count: 0, statement_count: 0, calculated_count: 0, totals: {}, rows: [] });
    if (url === "/api/v2/goals/primary") return json(primaryState);
    if (url === "/api/v2/goals/check-ins/backfill") return json(unchangedObservation);
    if (url === "/api/v2/goals/position") return json(positionState);
    if (url === "/api/v2/goals/check-ins/latest") return json(latestState);
    if (url === "/api/v2/goals/comparison") return json(comparisonState("250.00"));
    if (url === "/api/v2/goals/milestone") return json(milestoneState());
    if (url === "/api/v2/goals/candidates") return json(noCandidatesState);
    if (url === "/api/v2/retirement/profile") return json(retirementProfile);
    if (url === "/api/v2/retirement/starting-point") return json(retirementStartingPoint);
    if (url === "/api/v2/retirement/operational-goals") return json([goalProgram]);
    if (url === "/api/v2/retirement/project") return json(retirementRun());
    if (url === "/api/v2/retirement/snapshots") return json([retirementSnapshot]);
    if (url === "/api/v2/lab/snapshots") return json([legacySnapshot]);
    if (url === "/api/v2/lab/experiments") return json(labSeed("blank"));
    if (url === "/api/v2/lab/experiments/project") return json(labResult(labSeed("blank")));
    if (url === "/api/life-plan/profile") return json(null);
    if (url === "/api/life-plan/goals" || url === "/api/life-plan/scenarios") return json([]);
    if (url === "/api/life-plan/starting-point") return json({
      as_of: "2026-08-03", cash: "6761.75", accessible_investments: "26253.17", pretax_retirement: "459830.08", hsa: "0.00", restricted_assets: "0.00", debt: "0.00", accessible_total: "33014.92", tracked_total: "492845.00", observed_monthly_outflow: "5500.00", outflow_months: [], payroll: null, accounts: [], warnings: [],
    });
    return new Response("Not found", { status: 404 });
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("application states", () => {
  it("shows a loading state while local endpoints are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<App />);
    expect(screen.getByText("Loading accounts…")).toBeInTheDocument();
  });

  it("shows a recoverable error when local endpoints fail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Database unavailable" }), { status: 500 })),
    );
    render(<App />);
    await waitFor(() => expect(screen.getByText("Money Map could not load.")).toBeInTheDocument());
    expect(screen.getByText("Database unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("updates every account from the top bar", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const button = await screen.findByRole("button", { name: "Update data" });
    fireEvent.click(button);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/plaid/sync-all",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ automatic: false }) }),
      ),
    );
    expect(await screen.findByText("10 accounts updated")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetch.mock.calls.filter(([input]) => String(input).includes("/api/v2/cash-flow?period_kind=all_imported_history")).length).toBeGreaterThan(1);
    });
  });

  it("runs the daily automatic update only once after loading stale data", async () => {
    const fetch = workingFetch(true);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await waitFor(() => {
      const calls = fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/sync-all");
      expect(calls).toHaveLength(1);
      expect(calls[0]?.[1]?.body).toBe(JSON.stringify({ automatic: true }));
    });
  });

  it("does not run an automatic update when every connection is current", async () => {
    const fetch = workingFetch(false, 2);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("button", { name: "Update data" });
    await waitFor(() =>
      expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/status")).not.toHaveLength(0),
    );
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/sync-all")).toHaveLength(0);
  });

  it("opens Add account instead of syncing when no active connection exists", async () => {
    const fetch = workingFetch(false, 0);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Update data" }));
    expect(await screen.findByRole("heading", { name: "Add account" })).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/sync-all")).toHaveLength(0);
  });

  it("keeps a failed partial update visible as live text", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 1, { failedConnections: 1 }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Update data" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 account connection needs attention");
    expect(alert).toHaveTextContent("no new goal observation saved");
  });

  it("opens the accessible wealth and Fidelity performance screen", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Wealth" }));
    expect(await screen.findByRole("heading", { name: "Wealth" })).toBeInTheDocument();
    expect(screen.getByText("$33,014.92")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirement" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lab" })).toBeInTheDocument();
  });

  it("makes Cash Flow the default and first navigation item while Goals stays reachable", async () => {
    const fetch = workingFetch(false, 2);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Cash Flow" })).toBeInTheDocument();
    const navigation = screen.getByRole("navigation");
    const buttons = Array.from(navigation.querySelectorAll("button"));
    expect(buttons[0]).toHaveTextContent("Cash Flow");
    expect(screen.getByRole("button", { name: "Cash Flow" })).toHaveAttribute("aria-current", "page");
    expect(navigation).toHaveAttribute("aria-label", "Primary navigation");
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/life-plan"))).toBe(false);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/overview"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Goals" }));
    expect(await screen.findByRole("heading", { name: "Quiet place by the water" })).toBeInTheDocument();
  });

  it("keeps the exact visible navigation order and exposes the conditional Review count", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2, { issues: [{ id: 1 }, { id: 2 }] }));
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(Array.from(navigation.querySelectorAll("button")).map((button) => button.getAttribute("aria-label")?.replace(/, \d+ issues$/u, ""))).toEqual([
      "Cash Flow", "Goals", "Accounts", "Income", "Activity", "Wealth", "Retirement", "Lab", "Add account", "Review",
    ]);
    expect(screen.getByRole("button", { name: "Review, 2 issues" })).toHaveTextContent("Review2");
  });

  it("preserves the plaid setup hash route", async () => {
    window.location.hash = "#plaid-live-setup";
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Add account" })).toBeInTheDocument();
  });

  it("opens closed evidence for print and restores its screen state afterward", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const evidence = (await screen.findByText("Cash Flow evidence")).closest("details")!;
    expect(evidence).not.toHaveAttribute("open");
    window.dispatchEvent(new Event("beforeprint"));
    expect(evidence).toHaveAttribute("open");
    window.dispatchEvent(new Event("afterprint"));
    expect(evidence).not.toHaveAttribute("open");
  });

  it("loads Retirement and Lab as distinct lazy routes without cross-surface rendering", async () => {
    const fetch = workingFetch(false, 2);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const retirement = await screen.findByRole("button", { name: "Retirement" });
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/v2/retirement"))).toBe(false);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/v2/lab"))).toBe(false);
    fireEvent.click(retirement);
    expect(await screen.findByRole("heading", { name: "Retirement" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Life Lab" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/retirement/project")).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/v2/lab"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Lab" }));
    expect(await screen.findByRole("heading", { name: "Life Lab" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Retirement" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start blank/ })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/lab/snapshots")).toBe(true);
  });

  it("carries a Cash Flow period into Activity while direct navigation stays all-history", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Transactions for this period/ }));
    expect(await screen.findByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByText("Jun 15–Aug 11 · inclusive")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cash Flow" }));
    await screen.findByRole("heading", { name: "Cash Flow" });
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    fireEvent.click(within(navigation).getByRole("button", { name: "Activity" }));
    expect(await screen.findByText("Imported activity")).toBeInTheDocument();
  });

  it("keeps Accounts, Income, Activity, Wealth, Goals, Retirement, and Lab routes reachable", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    for (const route of ["Accounts", "Income", "Activity", "Wealth", "Goals"] as const) {
      fireEvent.click(screen.getByRole("button", { name: route }));
      await screen.findByRole("heading", { name: route === "Goals" ? "Quiet place by the water" : route });
    }
    fireEvent.click(screen.getByRole("button", { name: "Retirement" }));
    await screen.findByRole("heading", { name: "Retirement" });
    fireEvent.click(screen.getByRole("button", { name: "Lab" }));
    await screen.findByRole("heading", { name: "Life Lab" });
  });
});
