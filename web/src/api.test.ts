import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CashFlowApiError,
  CashFlowUnavailableError,
  CashFlowValidationError,
  loadCashFlow,
  loadOverviewRoute,
  loadRecurringOutflowCandidates,
  previewGoalGap,
} from "./api";
import { candidateFixture, goalGapFixture } from "./cash-flow/goal-gap-test-fixtures";
import { cashFlowFixture } from "./cash-flow/test-fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => vi.unstubAllGlobals());

describe("Cash Flow API", () => {
  it("loads Overview period evidence with exact inclusive read-only requests", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/overview")) return json({ period: { start: "2026-04-03", end: "2026-04-19" } });
      if (url === "/api/accounts") return json({ as_of: "2026-04-19", accounts: [{}] });
      if (url.startsWith("/api/timeline")) return json([]);
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetch);
    await loadOverviewRoute({ startDate: "2026-04-03", endDate: "2026-04-19" });
    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/overview?start_date=2026-04-03&end_date=2026-04-19",
      "/api/accounts",
      "/api/timeline?start_date=2026-04-03&end_date=2026-04-19",
    ]);
    expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("does not invent timeline evidence for an empty Overview", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input) === "/api/accounts"
      ? json({ as_of: null, accounts: [] })
      : json({ period: { start: "2026-04-03", end: "2026-04-19" } }));
    vi.stubGlobal("fetch", fetch);
    const result = await loadOverviewRoute();
    expect(result.timeline).toEqual([]);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/timeline"))).toBe(false);
  });

  it.each([
    ["all_imported_history", "/api/v2/cash-flow?period_kind=all_imported_history"],
    ["trailing_12_months", "/api/v2/cash-flow?period_kind=trailing_12_months"],
    ["year_to_date", "/api/v2/cash-flow?period_kind=year_to_date"],
    [
      "custom_range",
      "/api/v2/cash-flow?period_kind=custom_range&start_date=2026-04-03&end_date=2026-04-19",
    ],
  ] as const)("loads and validates %s", async (periodKind, expectedUrl) => {
    const fetch = vi.fn(async () => json(cashFlowFixture()));
    vi.stubGlobal("fetch", fetch);
    const result = await loadCashFlow({
      periodKind,
      ...(periodKind === "custom_range"
        ? { startDate: "2026-04-03", endDate: "2026-04-19" }
        : {}),
    });
    expect(fetch).toHaveBeenCalledWith(expectedUrl);
    expect(result.totals.money_in.amount).toBe("7213.00");
    expect(result.totals.net_cash_flow.amount).toBe("-805.00");
  });

  it("safely parses object-shaped 409 unavailable detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: { state: "unavailable", reason: "No imported cash activity" } }, 409)),
    );
    await expect(loadCashFlow({ periodKind: "all_imported_history" })).rejects.toMatchObject({
      name: "CashFlowUnavailableError",
      status: 409,
      reason: "No imported cash activity",
      message: "No imported cash activity",
    } satisfies Partial<CashFlowUnavailableError>);
  });

  it("uses a safe unavailable fallback for malformed 409 detail", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: { state: "unavailable" } }, 409)));
    await expect(loadCashFlow({ periodKind: "all_imported_history" })).rejects.toThrow(
      "Cash Flow is unavailable.",
    );
  });

  it("keeps string and FastAPI-array 422 validation errors distinct", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Custom dates are invalid" }, 422))
      .mockResolvedValueOnce(json({ detail: [{ msg: "Input should be a valid period" }] }, 422));
    vi.stubGlobal("fetch", fetch);
    await expect(loadCashFlow({ periodKind: "custom_range" })).rejects.toMatchObject({
      name: "CashFlowValidationError",
      status: 422,
      message: "Custom dates are invalid",
    } satisfies Partial<CashFlowValidationError>);
    await expect(loadCashFlow({ periodKind: "year_to_date" })).rejects.toThrow(
      "Input should be a valid period",
    );
  });

  it("represents general HTTP and invalid-contract failures separately", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Service offline" }, 503))
      .mockResolvedValueOnce(json({ totals: { money_in: 12.34 } }));
    vi.stubGlobal("fetch", fetch);
    await expect(loadCashFlow({ periodKind: "all_imported_history" })).rejects.toMatchObject({
      name: "CashFlowApiError",
      status: 503,
    } satisfies Partial<CashFlowApiError>);
    await expect(loadCashFlow({ periodKind: "all_imported_history" })).rejects.toMatchObject({
      name: "CashFlowApiError",
      status: 0,
    } satisfies Partial<CashFlowApiError>);
  });

  it("posts and validates an exact read-only goal-gap preview", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      json(goalGapFixture()),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await previewGoalGap({
      target_date: null,
      additional_reservation: "0.00",
      monthly_spending_reduction: "0.00",
      monthly_after_tax_income: "0.00",
    });
    expect(result.state).toBe("available");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v2/goals/gap-preview",
      expect.objectContaining({ method: "POST" }),
    );
    const init = fetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      target_date: null,
      additional_reservation: "0.00",
      monthly_spending_reduction: "0.00",
      monthly_after_tax_income: "0.00",
    });
  });

  it("loads and validates recurring-outflow candidates", async () => {
    const fetch = vi.fn(async () => json(candidateFixture()));
    vi.stubGlobal("fetch", fetch);
    const result = await loadRecurringOutflowCandidates();
    expect(result.candidates[0].confidence).toBe("high");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v2/cash-flow/recurring-outflow-candidates",
    );
  });

  it("keeps goal-gap HTTP and invalid-contract errors explicit", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Draft exceeds supported outflow" }, 422))
      .mockResolvedValueOnce(json({ state: "available" }));
    vi.stubGlobal("fetch", fetch);
    const payload = {
      target_date: null,
      additional_reservation: "0.00" as const,
      monthly_spending_reduction: "0.00" as const,
      monthly_after_tax_income: "0.00" as const,
    };
    await expect(previewGoalGap(payload)).rejects.toMatchObject({
      status: 422,
      message: "Draft exceeds supported outflow",
    });
    await expect(previewGoalGap(payload)).rejects.toMatchObject({ status: 0 });
  });
});
