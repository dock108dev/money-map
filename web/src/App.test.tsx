import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

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

function workingFetch(refreshDue = false, connectionCount = 1) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/plaid/sync-all") {
      return json({
        status: "complete",
        started_at: "2026-07-31T15:00:00Z",
        finished_at: "2026-07-31T15:00:01Z",
        requested: connectionCount,
        succeeded: connectionCount,
        failed: 0,
        connections: connectionCount
          ? [{ connection_id: 1, institution: "Bank", status: "complete", accounts: 10, transactions: 0, holdings: 0, balance_snapshot_date: "2026-07-31", started_at: "2026-07-31T15:00:00Z", finished_at: "2026-07-31T15:00:01Z", last_synced_at: "2026-07-31T15:00:01Z", error_code: null, message: null }]
          : [],
        freshness: plaid(false, connectionCount).refresh,
        automatic: init?.body,
      });
    }
    if (url === "/api/overview") return json(overview);
    if (url === "/api/accounts") return json(accounts);
    if (url === "/api/wealth") return json(wealth);
    if (url === "/api/exceptions" || url === "/api/timeline" || url === "/api/scenarios" || url === "/api/imports") return json([]);
    if (url === "/api/plaid/status") return json(plaid(refreshDue, connectionCount));
    if (url === "/api/payroll") return json({ period: { start: "2025-01-01", end: "2026-07-29" }, count: 0, statement_count: 0, calculated_count: 0, totals: {}, rows: [] });
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
    const button = await screen.findByRole("button", { name: "Update data" });
    fireEvent.click(button);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/plaid/sync-all",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ automatic: false }) }),
      ),
    );
    expect(await screen.findByText("10 accounts updated")).toBeInTheDocument();
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

  it("opens the accessible wealth and Fidelity performance screen", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "◇ Wealth" }));
    expect(await screen.findByRole("heading", { name: "Wealth" })).toBeInTheDocument();
    expect(screen.getByText("$33,014.92")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "◎ Plan" })).toBeInTheDocument();
  });

  it("loads Life Lab only after Plan is opened", async () => {
    const fetch = workingFetch(false, 2);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    const plan = await screen.findByRole("button", { name: "◎ Plan" });
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/life-plan"))).toBe(false);
    fireEvent.click(plan);
    expect(await screen.findByRole("heading", { name: "Set up Life Lab" })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/life-plan/starting-point")).toBe(true);
  });
});
