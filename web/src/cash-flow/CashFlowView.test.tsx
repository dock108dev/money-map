import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { COPY_BUDGETS, proseWordCount } from "../copy-budget";
import type { ExactDecimalString } from "../v2-contracts";
import {
  validateCashFlowPeriodResult,
  validateGoalGapPreviewResponse,
  type CashFlowPeriodResult,
  type GoalGapPreviewResponse,
} from "../v21-contracts";
import CashFlowView from "./CashFlowView";
import { goalGapFixture, unavailableMoney } from "./goal-gap-test-fixtures";
import { cashFlowFixture, longZeroCashFlow } from "./test-fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const callbacks = {
  onShowActivity: vi.fn(),
  onShowAccounts: vi.fn(),
  onShowIncome: vi.fn(),
  onShowWealth: vi.fn(),
  onShowGoals: vi.fn(),
};

function cashFlowWith(
  mutate: (value: CashFlowPeriodResult) => void,
  base = cashFlowFixture(),
): CashFlowPeriodResult {
  const value = structuredClone(base);
  mutate(value);
  return validateCashFlowPeriodResult(value);
}

function positiveGoalGap(): GoalGapPreviewResponse {
  const value = structuredClone(goalGapFixture());
  value.baseline_current_recurring_facts.observed_recurring_monthly_outflow.amount = "3900.00";
  value.baseline_current_recurring_facts.current_monthly_margin.amount = "300.00";
  value.baseline_current_recurring_facts.stabilization_gap.amount = "0.00";
  value.baseline_current_recurring_facts.margin_state = "positive";
  value.baseline_combined_monthly_improvement.amount = "38703.52";
  value.adjusted_recurring_outflow.amount = "3900.00";
  value.adjusted_monthly_margin.amount = "300.00";
  value.adjusted_stabilization_gap.amount = "0.00";
  value.remaining_combined_monthly_improvement.amount = "38703.52";
  return validateGoalGapPreviewResponse(value);
}

function goalWithGap(amount: ExactDecimalString): GoalGapPreviewResponse {
  const value = structuredClone(goalGapFixture());
  value.baseline_current_recurring_facts.effective_recurring_take_home.amount = "3200.00";
  value.baseline_current_recurring_facts.observed_recurring_monthly_outflow.amount = "3700.00";
  value.baseline_current_recurring_facts.current_monthly_margin.amount = `-${amount}` as ExactDecimalString;
  value.baseline_current_recurring_facts.stabilization_gap.amount = amount;
  value.baseline_combined_monthly_improvement.amount = "39503.52";
  value.adjusted_recurring_take_home.amount = "3200.00";
  value.adjusted_recurring_outflow.amount = "3700.00";
  value.adjusted_monthly_margin.amount = `-${amount}` as ExactDecimalString;
  value.adjusted_stabilization_gap.amount = amount;
  value.remaining_combined_monthly_improvement.amount = "39503.52";
  return validateGoalGapPreviewResponse(value);
}

function workingFetch(
  cashFlow: CashFlowPeriodResult = cashFlowFixture(),
  goal: GoalGapPreviewResponse | Response = positiveGoalGap(),
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith("/api/v2/cash-flow?")) return json(cashFlow);
    if (url === "/api/v2/goals/gap-preview" && init?.method === "POST") {
      return goal instanceof Response ? goal : json(goal);
    }
    return json({ detail: "Not found" }, 404);
  });
}

function renderView(reloadVersion = 0) {
  return render(
    <CashFlowView
      netWorth="24680.13"
      reloadVersion={reloadVersion}
      {...callbacks}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Cash Flow default surface", () => {
  it("uses all imported history by default and renders exact negative primary metrics", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    expect(await screen.findByRole("heading", { level: 1, name: "Cash Flow" })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/cash-flow?period_kind=all_imported_history")).toBe(true);
    expect(screen.getByText("$7,213.00")).toBeInTheDocument();
    expect(screen.getByText("$8,018.00")).toBeInTheDocument();
    expect(screen.getAllByText("−$805.00").length).toBeGreaterThan(0);
    expect(screen.getByText("negative net cash flow")).toBeInTheDocument();
  });

  it("renders positive net with a textual positive state", async () => {
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture("custom_positive_period")));
    renderView();
    expect(await screen.findByText("positive net cash flow")).toBeInTheDocument();
    expect(screen.getAllByText(/^\+\$/u).length).toBeGreaterThan(0);
  });

  it("renders zero net as even without relying on color", async () => {
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture("trailing_transfer_heavy_zero_margin")));
    renderView();
    expect(await screen.findByText("even net cash flow")).toBeInTheDocument();
    expect(screen.getAllByText("$0.00").length).toBeGreaterThan(0);
  });

  it("puts every monthly point in the chart and exact table", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    await screen.findByRole("img", { name: /Monthly money in compared with money out/ });
    expect(document.querySelectorAll("[data-month]")).toHaveLength(3);
    const table = document.querySelector<HTMLTableElement>('table[aria-label="Exact monthly Cash Flow values"]')!;
    expect(table.tBodies[0].rows).toHaveLength(3);
    expect(table).toHaveTextContent("$3,005.00");
    expect(table).toHaveTextContent("$3,510.00");
  });

  it("labels partial months and exposes a concise accessible chart summary", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    const chart = await screen.findByRole("img", { name: /Monthly money in compared with money out/ });
    expect(chart).toHaveTextContent("Jun 2026 (partial)");
    expect(document.querySelector('table[aria-label="Exact monthly Cash Flow values"]')).toHaveTextContent("Aug 2026 (partial)");
    expect(document.getElementById("cash-flow-chart-description")).toHaveTextContent("negative net");
  });

  it("supports a zero-activity month on a zero baseline", async () => {
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture("ytd_no_activity_missing_payroll")));
    renderView();
    await screen.findByText("even net cash flow");
    const point = document.querySelector("[data-month]")!;
    expect(point).toHaveTextContent("money in $0.00, money out $0.00");
    expect(document.querySelector(".cash-flow-zero-line")).toBeInTheDocument();
  });

  it("renders a long all-history range inside one responsive SVG without page-width markup", async () => {
    vi.stubGlobal("fetch", workingFetch(longZeroCashFlow()));
    renderView();
    await screen.findByRole("img", { name: /Monthly money in compared with money out/ });
    expect(document.querySelectorAll("[data-month]")).toHaveLength(48);
    expect(document.querySelector(".cash-flow-chart")?.getAttribute("viewBox")).toBe("0 0 1000 220");
    expect(document.querySelector(".cash-flow-table-wrap")).toBeInTheDocument();
  });

  it("maps Last 12 months and Year to date to accepted period names", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Last 12 months" }));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).includes("period_kind=trailing_12_months"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Year to date" }));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).includes("period_kind=year_to_date"))).toBe(true));
  });

  it("maps Prior year to the previous as-of calendar year", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Prior year" }));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/cash-flow?period_kind=custom_range&start_date=2025-01-01&end_date=2025-12-31")).toBe(true));
  });

  it("sends a valid inclusive custom range and marks Custom range active", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Custom range" }));
    fireEvent.input(screen.getByLabelText("From"), { target: { value: "2026-07-02" } });
    fireEvent.input(screen.getByLabelText("Through"), { target: { value: "2026-07-19" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply range" }));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/cash-flow?period_kind=custom_range&start_date=2026-07-02&end_date=2026-07-19")).toBe(true));
    expect(screen.getByRole("button", { name: "Custom range" })).toHaveAttribute("aria-pressed", "true");
  });

  it("blocks a reversed custom range locally", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    const initialCashCalls = fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/v2/cash-flow?")).length;
    fireEvent.click(screen.getByRole("button", { name: "Custom range" }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-08" } });
    fireEvent.change(screen.getByLabelText("Through"), { target: { value: "2026-08-07" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply range" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Custom start must be on or before custom end");
    expect(fetch.mock.calls.filter(([input]) => String(input).startsWith("/api/v2/cash-flow?")).length).toBe(initialCashCalls);
  });

  it("blocks a custom end beyond the API as-of date", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Custom range" }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Through"), { target: { value: "2026-08-12" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply range" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("on or before Aug 11, 2026");
  });

  it("shows a 409 unavailable state with a recoverable Retry", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).startsWith("/api/v2/cash-flow?") ? json({ detail: { state: "unavailable", reason: "No imported bank coverage" } }, 409) : json(positiveGoalGap())));
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Cash Flow unavailable: No imported bank coverage");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("keeps prior data visible after a 422 period error", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("trailing_12_months")) return json({ detail: "Unsupported period evidence" }, 422);
      if (url.startsWith("/api/v2/cash-flow?")) return json(cashFlowFixture());
      return json(positiveGoalGap());
    });
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Last 12 months" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Period not available");
    expect(screen.getByText("$7,213.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a retryable general failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).startsWith("/api/v2/cash-flow?") ? json({ detail: "Temporary service problem" }, 503) : json(positiveGoalGap())));
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary service problem Try again");
  });

  it("prevents a slower stale request from replacing a newer period", async () => {
    let cashCalls = 0;
    let resolveTrailing: ((response: Response) => void) | undefined;
    const trailing = new Promise<Response>((resolve) => { resolveTrailing = resolve; });
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v2/goals/gap-preview") return json(positiveGoalGap());
      if (url.includes("trailing_12_months")) return trailing;
      if (url.includes("year_to_date")) return json(cashFlowFixture("ytd_no_activity_missing_payroll"));
      cashCalls += 1;
      return json(cashFlowFixture());
    });
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    expect(cashCalls).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Last 12 months" }));
    fireEvent.click(screen.getByRole("button", { name: "Year to date" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Year to date" })).toHaveAttribute("aria-pressed", "true"));
    await act(async () => { resolveTrailing?.(json(cashFlowFixture("trailing_transfer_heavy_zero_margin"))); });
    expect(screen.getByRole("button", { name: "Year to date" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the current monthly gap from existing goal-position evidence", async () => {
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture(), goalWithGap("500.00")));
    renderView();
    expect(await screen.findByText("Current monthly gap: $500.00")).toBeInTheDocument();
  });

  it("uses exact cents subtraction for a positive current monthly margin", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    expect(await screen.findByText("Current monthly margin: $300.00")).toBeInTheDocument();
  });

  it("keeps the recurring pattern unavailable when dependent evidence is missing", async () => {
    const unavailable = structuredClone(goalGapFixture());
    const reason = "Recurring outflow coverage is incomplete";
    unavailable.baseline_current_recurring_facts.observed_recurring_monthly_outflow = unavailableMoney(reason);
    unavailable.baseline_current_recurring_facts.current_monthly_margin = unavailableMoney(reason);
    unavailable.baseline_current_recurring_facts.stabilization_gap = unavailableMoney(reason);
    unavailable.baseline_current_recurring_facts.margin_state = "unavailable";
    unavailable.baseline_combined_monthly_improvement = unavailableMoney(reason);
    unavailable.adjusted_recurring_outflow = unavailableMoney(reason);
    unavailable.adjusted_monthly_margin = unavailableMoney(reason);
    unavailable.adjusted_stabilization_gap = unavailableMoney(reason);
    unavailable.remaining_combined_monthly_improvement = unavailableMoney(reason);
    unavailable.gross_income_context = { state: "unavailable", reason };
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture(), unavailable));
    renderView();
    expect(await screen.findByText("Current monthly pattern unavailable")).toBeInTheDocument();
    expect(document.querySelector(".cash-flow-evidence")).toHaveTextContent("Recurring outflow coverage is incomplete");
  });

  it("remains usable when goal position fails", async () => {
    vi.stubGlobal("fetch", workingFetch(cashFlowFixture(), json({ detail: "Goal evidence offline" }, 500)));
    renderView();
    expect(await screen.findByText("$7,213.00")).toBeInTheDocument();
    expect(screen.getByText("Current monthly pattern unavailable")).toBeInTheDocument();
  });

  it("preserves and reloads the selected period after Update data changes reloadVersion", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    const view = renderView();
    await screen.findByText("negative net cash flow");
    fireEvent.click(screen.getByRole("button", { name: "Last 12 months" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Last 12 months" })).toHaveAttribute("aria-pressed", "true"));
    view.rerender(<CashFlowView netWorth="24680.13" reloadVersion={1} {...callbacks} />);
    await waitFor(() => expect(fetch.mock.calls.filter(([input]) => String(input).includes("period_kind=trailing_12_months"))).toHaveLength(2));
  });

  it("hands the exact selected dates to Activity", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Activity/ }));
    expect(callbacks.onShowActivity).toHaveBeenCalledWith({ startDate: "2026-06-15", endDate: "2026-08-11" });
  });

  it("keeps exact totals, exclusions, coverage, freshness, warnings, and rows in one disclosure", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    const evidence = await screen.findByText("Cash Flow evidence");
    const details = evidence.closest("details")!;
    expect(details).toHaveTextContent("2026-06-15 through 2026-08-11, inclusive");
    expect(details).toHaveTextContent("$7,200.00");
    expect(details).toHaveTextContent("$13.00");
    expect(details).toHaveTextContent("Matched owned transfers");
    expect(details.querySelectorAll("table")).toHaveLength(1);
  });

  it("renders current, stale, and incomplete evidence textually", async () => {
    const current = workingFetch();
    vi.stubGlobal("fetch", current);
    const view = renderView();
    expect(await screen.findByText(/Evidence current as of/)).toHaveTextContent("complete coverage");
    view.unmount();
    const stale = cashFlowWith((value) => {
      value.freshness.state = "stale";
      value.freshness.stale_sources = ["Synthetic checking feed"];
    });
    vi.stubGlobal("fetch", workingFetch(stale));
    const staleView = renderView();
    expect(await screen.findByText(/Evidence stale as of/)).toBeInTheDocument();
    staleView.unmount();
    const incomplete = cashFlowWith((value) => {
      value.coverage.completeness = "incomplete";
      value.coverage.incomplete_reasons = ["Synthetic opening boundary is incomplete"];
      value.freshness.state = "incomplete";
    });
    vi.stubGlobal("fetch", workingFetch(incomplete));
    renderView();
    expect(await screen.findByText(/incomplete coverage/)).toBeInTheDocument();
    expect(document.querySelector(".cash-flow-evidence")).toHaveTextContent("Synthetic opening boundary is incomplete");
  });

  it("enforces the 45-word semantic copy budget", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    await screen.findByText("negative net cash flow");
    const budget = document.querySelector('[data-copy-budget="cash-flow-first-viewport"]')!;
    expect(proseWordCount(budget)).toBeLessThanOrEqual(COPY_BUDGETS["cash-flow-first-viewport"]);
  });

  it("provides keyboard-reachable semantic controls, chart name, status, and one h1", async () => {
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    await screen.findByText("negative net cash flow");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const periods = screen.getByRole("group", { name: "Cash Flow period" });
    expect(within(periods).getAllByRole("button")).toHaveLength(5);
    expect(within(periods).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /Monthly money in compared with money out/ })).toBeInTheDocument();
  });

  it("marks complete print evidence and responsive hooks", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", workingFetch());
    renderView();
    await screen.findByText("negative net cash flow");
    expect(document.querySelector('[data-responsive-surface="cash-flow"]')).toBeInTheDocument();
    expect(document.querySelector('[data-print-evidence="cash-flow"]')).toBeInTheDocument();
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("2026-06-15 through 2026-08-11");
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    expect(print).toHaveBeenCalledOnce();
  });

  it("does not request Retirement, Lab, goal writes, or check-ins", async () => {
    const fetch = workingFetch();
    vi.stubGlobal("fetch", fetch);
    renderView();
    await screen.findByText("negative net cash flow");
    const urls = fetch.mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => url.includes("retirement") || url.includes("/lab/"))).toBe(false);
    expect(urls.some((url) => url.includes("check-in"))).toBe(false);
    expect(urls.some((url) => url.includes("/goals/") && !url.endsWith("gap-preview"))).toBe(false);
    expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== "GET").every(([input, init]) =>
      String(input) === "/api/v2/goals/gap-preview" && init?.method === "POST",
    )).toBe(true);
  });
});
