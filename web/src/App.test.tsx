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

const observedAccounts = {
  ...accounts,
  accounts: [{
    id: 1, institution: "Synthetic Bank", name: "Checking ••0001", type: "checking",
    category: "cash", current_balance: "100.00", balance_as_of: "2026-07-29",
    starting_balance: "100.00", starting_balance_as_of: "2026-07-01", change: "0.00",
    inflows: "0.00", outflows: "0.00", contributions: "0.00", withdrawals: "0.00",
    investment_result: "0.00", performance_status: "tracking", cost_basis: null,
    unrealized_gain: null, balance_point_count: 1, transaction_count: 0, holding_count: 0,
    holdings: [], source: "synthetic", last_synced_at: null, status: "current",
  }],
};

const reviewIssue = {
  id: 1,
  entity_type: "synthetic",
  entity_id: "fixture-1",
  rule: "synthetic_review",
  status: "open",
  residual: "1.00",
  details: { next_steps: ["Review synthetic evidence."] },
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
  options: { issues?: unknown[]; failedConnections?: number; accountData?: unknown; overviewData?: unknown } = {},
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
    if (url === "/api/accounts") return json(options.accountData ?? accounts);
    if (url.startsWith("/api/overview")) return json(options.overviewData ?? overview);
    if (url === "/api/wealth") return json(wealth);
    if (url === "/api/exceptions") return json(options.issues ?? []);
    if (url.startsWith("/api/timeline") || url === "/api/scenarios" || url === "/api/imports") return json([]);
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

function installReadyDesktop() {
  Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
    configurable: true,
    value: {
      mode: true,
      reload: vi.fn(), print: vi.fn(),
      runtimeStatus: vi.fn(async () => ({ state: "ready" as const, generation: 1 })),
      restart: vi.fn(), about: vi.fn(), selectImport: vi.fn(), revealBackup: vi.fn(),
      setOperationsEnabled: vi.fn(),
    },
  });
}

function withReadyDataHome(base: ReturnType<typeof workingFetch>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/desktop/data-home/status") {
      return json({ phase: "already_migrated", ready: true, schema_revision: "0009_goal_persistence" });
    }
    return base(input, init);
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.__MONEY_MAP_DESKTOP__;
  window.location.hash = "";
});

describe("application states", () => {
  it("restores the durable fresh-setup state before requesting financial APIs", async () => {
    Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
      configurable: true,
      value: {
        mode: true,
        reload: vi.fn(),
        print: vi.fn(),
        runtimeStatus: vi.fn(async () => ({ state: "ready" as const, generation: 1 })),
        restart: vi.fn(),
        about: vi.fn(),
        selectImport: vi.fn(),
        revealBackup: vi.fn(),
      },
    });
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/desktop/data-home/status") {
        return json({ phase: "fresh_setup_available", ready: false });
      }
      return new Response("Not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Set up Money Map" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Start fresh" })).toBeEnabled();
    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/desktop/data-home/status",
    ]);
  });

  it("restores durable recovery actions after a desktop reload", async () => {
    Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
      configurable: true,
      value: {
        mode: true,
        reload: vi.fn(),
        print: vi.fn(),
        runtimeStatus: vi.fn(async () => ({ state: "ready" as const, generation: 3 })),
        restart: vi.fn(),
        about: vi.fn(),
        selectImport: vi.fn(),
        revealBackup: vi.fn(),
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => json({
      phase: "recoverable_failure",
      ready: false,
      recoverable: true,
      resume_available: true,
      rollback_available: true,
    })));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "The operation paused safely." })).toBeVisible();
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Roll back" })).toBeEnabled();
  });

  it("blocks stale controls after desktop service failure and restores the current route after one deliberate restart", async () => {
    window.location.hash = "#view=goals";
    let ready = false;
    const runtimeStatus = vi.fn(async () =>
      ready ? { state: "ready" as const, generation: 2 } : { state: "failed" as const, generation: 1 },
    );
    const restart = vi.fn(async () => {
      ready = true;
      return { state: "ready" as const, generation: 2 };
    });
    Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
      configurable: true,
      value: { mode: true, reload: vi.fn(), print: vi.fn(), runtimeStatus, restart, about: vi.fn() },
    });
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Money Map paused safely." })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Restart local service" }));
    expect(await screen.findByRole("heading", { name: "Goals" })).toBeInTheDocument();
    expect(restart).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#view=goals");
  });

  it("shows bounded desktop restart progress without issuing API requests", async () => {
    let finishRestart: ((value: { state: "failed"; generation: number }) => void) | undefined;
    Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
      configurable: true,
      value: {
        mode: true,
        reload: vi.fn(),
        print: vi.fn(),
        runtimeStatus: vi.fn(async () => ({ state: "failed" as const, generation: 1 })),
        restart: vi.fn(() => new Promise((resolve) => { finishRestart = resolve; })),
        about: vi.fn(),
      },
    });
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Restart local service" }));
    expect(await screen.findByText("Restarting safely…")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    finishRestart?.({ state: "failed", generation: 2 });
  });

  it("shows a loading state while local endpoints are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<App />);
    const heading = screen.getByRole("heading", { level: 1, name: "Loading accounts…" });
    const loading = heading.closest("main");
    expect(heading).toBeVisible();
    expect(loading).toHaveClass("loading-state");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByRole("heading", { name: "Cash Flow" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("withholds completed evidence until every initial dashboard read settles", async () => {
    const settledFetch = workingFetch();
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        held.then(() => settledFetch(input, init))),
    );
    render(<App />);
    expect(screen.getByRole("heading", { name: "Loading accounts…" })).toBeVisible();
    expect(screen.queryByText("$25,600.00")).not.toBeInTheDocument();
    release?.();
    expect(await screen.findByRole("heading", { name: "Cash Flow" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Loading accounts…" })).not.toBeInTheDocument();
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
    expect(screen.getByText(/Use Add account to begin/)).toBeVisible();
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
    const callsBeforeGoals = fetch.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Goals" }));
    expect(await screen.findByRole("heading", { name: "Quiet place by the water" })).toBeInTheDocument();
    expect(
      fetch.mock.calls
        .slice(callsBeforeGoals)
        .filter(([, init]) => ![undefined, "GET"].includes(init?.method)),
    ).toEqual([]);
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
  });

  it("keeps the exact visible navigation order and exposes the conditional Review count", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 2, { issues: [{ id: 1 }, { id: 2 }] }));
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(Array.from(navigation.querySelectorAll("button")).map((button) => button.getAttribute("aria-label")?.replace(/, \d+ issues$/u, ""))).toEqual([
      "Cash Flow", "Goals", "Activity", "Overview", "Accounts", "Income", "Wealth", "Retirement", "Lab", "Add account", "Review",
    ]);
    expect(within(screen.getByRole("group", { name: "Everyday" })).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual(["Cash Flow", "Goals", "Activity"]);
    expect(within(screen.getByRole("group", { name: "Details" })).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual(["Overview", "Accounts", "Income", "Wealth"]);
    expect(within(screen.getByRole("group", { name: "Planning" })).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual(["Retirement", "Lab"]);
    expect(within(screen.getByRole("group", { name: "Data" })).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual(["Add account", "Review, 2 issues"]);
    expect(screen.getByRole("button", { name: "Review, 2 issues" })).toHaveTextContent("Review2");
  });

  it("reveals an active mobile item and keeps every grouped route reachable", async () => {
    const reveal = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: reveal });
    vi.stubGlobal("fetch", workingFetch(false, 2, { issues: [{ id: 1 }] }));
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const expectedRoutes = ["Cash Flow", "Goals", "Activity", "Overview", "Accounts", "Income", "Wealth", "Retirement", "Lab", "Add account", "Review, 1 issues"];
    for (const name of expectedRoutes) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    await waitFor(() => expect(reveal).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Accounts" })).toHaveAttribute("aria-current", "page");
  });

  it("preserves the plaid setup hash route", async () => {
    window.location.hash = "#plaid-live-setup";
    vi.stubGlobal("fetch", workingFetch(false, 2));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Add account" })).toBeInTheDocument();
    expect(screen.getByText("Manual import stays first-class.")).toBeVisible();
  });

  it("preserves sealed Add account copy and zero side effects across installed deep-route reload", async () => {
    installReadyDesktop();
    window.location.hash = "#view=connections";
    const base = workingFetch(false, 0);
    const fetch = withReadyDataHome(base);
    vi.stubGlobal("fetch", fetch);
    const first = render(<App />);
    const heading = await screen.findByRole("heading", { name: "Add account" });
    expect(heading).toHaveAccessibleDescription("Manual import stays first-class.");
    expect(screen.getByText("Manual import stays first-class.")).toBeVisible();
    expect(window.location.hash).toBe("#view=connections");
    first.unmount();

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Add account" })).toHaveAccessibleDescription(
      "Manual import stays first-class.",
    );
    expect(window.location.hash).toBe("#view=connections");
    const applicationCalls = base.mock.calls.map(([input, init]) => ({ url: String(input), method: init?.method ?? "GET" }));
    expect(applicationCalls.filter(({ url }) => url === "/api/plaid/status")).toHaveLength(2);
    expect(applicationCalls.filter(({ url }) => url === "/api/imports")).toHaveLength(2);
    expect(applicationCalls.every(({ method }) => method === "GET")).toBe(true);
    expect(applicationCalls.some(({ url }) => /plaid\/(link-token|sync|sync-all)/u.test(url))).toBe(false);
  });

  it("opens Overview lazily and renders its accepted heading", async () => {
    const fetch = workingFetch(false, 2, { accountData: observedAccounts });
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/overview"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/overview"))).toHaveLength(1);
  });

  it("validates installed Overview deep routes and safely rejects unknown hashes", async () => {
    installReadyDesktop();
    window.location.hash = "#view=overview";
    const base = workingFetch(false, 2, { accountData: observedAccounts });
    vi.stubGlobal("fetch", withReadyDataHome(base));
    const first = render(<App />);
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#view=overview");
    first.unmount();

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(base.mock.calls.filter(([input]) => String(input).startsWith("/api/overview")).every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    cleanup();
    window.location.hash = "#view=not-a-route";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Cash Flow" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cash Flow" })).toHaveAttribute("aria-current", "page");
  });

  it("seals empty Overview as unavailable and routes its next action through Add account", async () => {
    vi.stubGlobal("fetch", workingFetch(false, 0, { accountData: { ...accounts, as_of: null } }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Overview" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use Add account" }));
    expect(await screen.findByRole("heading", { name: "Add account" })).toBeInTheDocument();
  });

  it("shows accessible bounded Overview loading and a sanitized recoverable failure", async () => {
    let resolveOverview: ((value: Response) => void) | undefined;
    const base = workingFetch(false, 2, { accountData: observedAccounts });
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).startsWith("/api/overview")) {
        return new Promise<Response>((resolve) => { resolveOverview = resolve; });
      }
      return base(input, init);
    });
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Overview" }));
    expect(await screen.findByRole("status", { name: "Loading Overview" })).toBeInTheDocument();
    resolveOverview?.(new Response(JSON.stringify({ detail: "/private/secret should not render" }), { status: 503, headers: { "Content-Type": "application/json" } }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Overview unavailable");
    expect(screen.queryByText(/private\/secret/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("keeps Overview periods inclusive, read-only, route-retaining, and independent of Cash Flow", async () => {
    const periodOverview = {
      ...overview,
      period_presets: { current_year: { start: "2026-01-01", end: "2026-12-31" } },
    };
    const fetch = workingFetch(false, 2, { accountData: observedAccounts, overviewData: periodOverview });
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    const cashFlowCalls = fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/v2/cash-flow")).length;
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    await screen.findByRole("heading", { name: "Overview" });
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input) === "/api/overview?start_date=2026-01-01&end_date=2026-12-31")).toBe(true));
    expect(fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/v2/cash-flow"))).toHaveLength(cashFlowCalls);
    expect(fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/overview")).every(([, init]) => !init?.method || init.method === "GET")).toBe(true);

    fireEvent.click(screen.getByText("Custom range"));
    fireEvent.change(screen.getByLabelText("Custom range start"), { target: { value: "2026-08-12" } });
    fireEvent.change(screen.getByLabelText("Custom range end"), { target: { value: "2026-08-11" } });
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("suppresses stale Overview period responses", async () => {
    const periodOverview = {
      ...overview,
      period_presets: {
        current_year: { start: "2026-01-01", end: "2026-12-31" },
        previous_year: { start: "2025-01-01", end: "2025-12-31" },
      },
    };
    let resolveCurrent: ((value: Response) => void) | undefined;
    const base = workingFetch(false, 2, { accountData: observedAccounts, overviewData: periodOverview });
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/overview") && url.includes("start_date=2026-01-01")) return new Promise<Response>((resolve) => { resolveCurrent = resolve; });
      return base(input, init);
    });
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Overview" }));
    await screen.findByRole("heading", { name: "Overview" });
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    fireEvent.click(screen.getByRole("button", { name: "Accounts" }));
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    resolveCurrent?.(json({ ...periodOverview, period: { start: "2026-01-01", end: "2026-12-31" } }));
    await Promise.resolve();
    expect(screen.getByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("routes every Overview support action and keeps Review distinct", async () => {
    const fetch = workingFetch(false, 2, { accountData: observedAccounts, issues: [reviewIssue] });
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    for (const [button, heading] of [["Accounts", "Accounts"], ["Activity", "Activity"], ["Income", "Income"], ["Wealth", "Wealth"]] as const) {
      fireEvent.click(await screen.findByRole("button", { name: "Overview" }));
      await screen.findByRole("heading", { name: "Overview" });
      const details = screen.getByRole("region", { name: "Money detail views" });
      fireEvent.click(within(details).getByRole("button", { name: new RegExp(`^${button}`) }));
      await screen.findByRole("heading", { name: heading });
    }
    fireEvent.click(screen.getByRole("button", { name: "Review, 1 issues" }));
    expect(await screen.findByRole("heading", { name: "Review" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
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

  it("keeps local evidence usable offline and requires a deliberate update retry", async () => {
    const fetch = workingFetch(false, 2);
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    window.dispatchEvent(new Event("offline"));
    expect(await screen.findByText("Offline · local data available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update data" })).toBeEnabled();
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/sync-all")).toHaveLength(0);
    window.dispatchEvent(new Event("online"));
    expect(await screen.findByText(/Updated/)).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/plaid/sync-all")).toHaveLength(0);
  });

  it("dispatches native menus through the same routes and report/diagnostics operations", async () => {
    const reportAction = vi.fn();
    const diagnosticsPreview = vi.fn(async () => ({
      contract: "money-map-sanitized-diagnostics-v1",
      product_version: "2.1.0",
      database_checks: { integrity: "pass", foreign_keys: "pass" },
    }));
    const setOperationsEnabled = vi.fn();
    Object.defineProperty(window, "__MONEY_MAP_DESKTOP__", {
      configurable: true,
      value: {
        mode: true,
        reload: vi.fn(),
        print: vi.fn(),
        runtimeStatus: vi.fn(async () => ({ state: "ready" as const, generation: 1 })),
        restart: vi.fn(),
        about: vi.fn(),
        selectImport: vi.fn(),
        revealBackup: vi.fn(),
        reportAction,
        diagnosticsPreview,
        exportDiagnostics: vi.fn(async () => false),
        setOperationsEnabled,
      },
    });
    const base = workingFetch(false, 2, { accountData: observedAccounts, issues: [reviewIssue] });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/desktop/data-home/status") {
        return json({ phase: "already_migrated", ready: true, schema_revision: "0009_goal_persistence" });
      }
      if (url === "/api/reports/trailing-12") {
        return json({ report_id: "trailing-12-month", filename: "trailing-12-month-money-map.html" });
      }
      return base(input, init);
    }));

    render(<App />);
    await screen.findByRole("heading", { name: "Cash Flow" });
    window.dispatchEvent(new CustomEvent("money-map-menu", { detail: "view-wealth" }));
    expect(await screen.findByRole("heading", { name: "Wealth" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#view=wealth");

    window.dispatchEvent(new CustomEvent("money-map-menu", { detail: "view-overview" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#view=overview");
    window.dispatchEvent(new CustomEvent("money-map-menu", { detail: "view-review" }));
    expect(await screen.findByRole("heading", { name: "Review" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#view=review");

    window.dispatchEvent(new CustomEvent("money-map-menu", { detail: "generate-report" }));
    expect(await screen.findByText("Report ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Report" }));
    expect(reportAction).toHaveBeenCalledWith("trailing-12-month", "open");

    window.dispatchEvent(new CustomEvent("money-map-menu", { detail: "export-diagnostics" }));
    expect(await screen.findByRole("dialog", { name: "Sanitized diagnostics" })).toBeInTheDocument();
    expect(diagnosticsPreview).toHaveBeenCalledOnce();
    expect(screen.getByText(/Financial records, paths, credentials, ports, and filenames are excluded\./)).toBeInTheDocument();
    expect(setOperationsEnabled).toHaveBeenCalledWith(true);
  });
});
