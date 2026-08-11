import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExactDecimalString } from "../v2-contracts";
import {
  parseExactMoneyCents,
  validateGoalGapPreviewResponse,
  type GoalGapPreviewAvailable,
  type GoalGapPreviewRequest,
  type GoalGapPreviewResponse,
} from "../v21-contracts";
import GoalGapCard from "./GoalGapCard";
import {
  candidateFixture,
  goalGapFixture,
  unavailableMoney,
} from "./goal-gap-test-fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function exact(cents: bigint): ExactDecimalString {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  return `${negative ? "-" : ""}${absolute / 100n}.${(absolute % 100n).toString().padStart(2, "0")}` as ExactDecimalString;
}

function divideHalfUp(numerator: bigint, denominator: bigint): bigint {
  return (numerator * 2n + denominator) / (denominator * 2n);
}

function scenarioFixture(request: GoalGapPreviewRequest): GoalGapPreviewAvailable {
  const value = structuredClone(goalGapFixture());
  const target = parseExactMoneyCents("1872168.96");
  const existing = parseExactMoneyCents("0.00");
  const additional = parseExactMoneyCents(request.additional_reservation);
  const spending = parseExactMoneyCents(request.monthly_spending_reduction);
  const income = parseExactMoneyCents(request.monthly_after_tax_income);
  const total = existing + additional;
  const remaining = target > total ? target - total : 0n;
  const targetDate = request.target_date ?? "2030-08-10";
  const pace =
    remaining === 0n
      ? 0n
      : targetDate === "2035-11-18"
        ? parseExactMoneyCents("16824.34")
        : divideHalfUp(remaining, 48n);
  const takeHome = parseExactMoneyCents("4200.00") + income;
  const outflow = parseExactMoneyCents("9802.98") - spending;
  const margin = takeHome - outflow;
  const gap = margin < 0n ? -margin : 0n;
  const combined = pace > margin ? pace - margin : 0n;
  value.preview_target_date = targetDate;
  value.additional_draft_reservation.amount = request.additional_reservation;
  value.preview_total_reservation.amount = exact(total);
  value.preview_remaining_target.amount = exact(remaining);
  value.exact_funding_months =
    targetDate === "2035-11-18" ? "111.277419354839" : "48.000000000000";
  value.preview_required_goal_pace.amount = exact(pace);
  value.draft_spending_reduction.amount = request.monthly_spending_reduction;
  value.draft_after_tax_income.amount = request.monthly_after_tax_income;
  value.adjusted_recurring_take_home.amount = exact(takeHome);
  value.adjusted_recurring_outflow.amount = exact(outflow);
  value.adjusted_monthly_margin.amount = exact(margin);
  value.adjusted_stabilization_gap.amount = exact(gap);
  value.remaining_combined_monthly_improvement.amount = exact(combined);
  if (
    targetDate !== "2030-08-10" ||
    additional !== 0n ||
    spending !== 0n ||
    income !== 0n
  ) {
    value.gross_income_context = {
      state: "unavailable",
      reason: "Synthetic changed-result gross context omitted",
    };
  }
  return validateGoalGapPreviewResponse(value) as GoalGapPreviewAvailable;
}

function fetchForDialog() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v2/cash-flow/recurring-outflow-candidates") {
      return json(candidateFixture());
    }
    if (url === "/api/v2/goals/gap-preview" && init?.method === "POST") {
      const payload = JSON.parse(String(init.body)) as GoalGapPreviewRequest;
      return json(scenarioFixture(payload));
    }
    return json({ detail: "Not found" }, 404);
  });
}

const onOpenGoals = vi.fn();

function renderCard(result: GoalGapPreviewResponse = goalGapFixture()) {
  return render(<GoalGapCard result={result} error="" onOpenGoals={onOpenGoals} />);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("compact goal gap card", () => {
  it("uses one combined headline with the negative-margin equation", () => {
    renderCard();
    expect(screen.getByText("Improve monthly cash flow by $44,606.50 to match the current goal pace.")).toBeInTheDocument();
    expect(screen.getByText("$5,602.98 to stabilize + $39,003.52 goal pace = $44,606.50 combined")).toBeInTheDocument();
    expect(document.querySelectorAll(".goal-gap-card")).toHaveLength(1);
  });

  it("shows how a positive margin offsets pace", () => {
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
    renderCard(validateGoalGapPreviewResponse(value));
    expect(screen.getByText(/Current margin \$300.00 already offsets/)).toBeInTheDocument();
  });

  it("shows completed and expired goals without a meaningless requirement", () => {
    const completed = structuredClone(goalGapFixture());
    completed.baseline_goal_pace_reference.reserved_for_goal.amount = "1872168.96";
    completed.baseline_goal_pace_reference.remaining_target.amount = "0.00";
    completed.baseline_goal_pace_reference.goal_state = "completed";
    completed.baseline_goal_pace_reference.required_goal_pace.amount = "0.00";
    completed.baseline_combined_monthly_improvement.amount = "5602.98";
    const view = renderCard(completed);
    expect(screen.getByText("Goal funding is complete.")).toBeInTheDocument();
    expect(screen.queryByText(/goal pace =/)).not.toBeInTheDocument();
    view.unmount();

    const expired = structuredClone(goalGapFixture());
    expired.baseline_goal_pace_reference.target_date = "2026-08-10";
    expired.baseline_goal_pace_reference.funding_months = "0.000000000000";
    expired.baseline_goal_pace_reference.goal_state = "expired_unfinished";
    expired.baseline_goal_pace_reference.required_goal_pace = unavailableMoney("Target date expired");
    expired.baseline_combined_monthly_improvement = unavailableMoney("Target date expired");
    renderCard(expired);
    expect(screen.getByText("This unfinished goal needs a new target date.")).toBeInTheDocument();
  });

  it("keeps floor breach and dependent-only unavailable states visible", () => {
    const floor = structuredClone(goalGapFixture());
    floor.baseline_goal_pace_reference.accessible_cash.amount = "2000.00";
    floor.baseline_goal_pace_reference.goal_state = "cash_floor_breach";
    const view = renderCard(floor);
    expect(screen.getByText("Protected cash floor is currently breached.")).toBeInTheDocument();
    view.unmount();

    const missingRecurring = structuredClone(goalGapFixture());
    missingRecurring.baseline_current_recurring_facts.effective_recurring_take_home = unavailableMoney("Missing payroll");
    missingRecurring.baseline_current_recurring_facts.current_monthly_margin = unavailableMoney("Missing payroll");
    missingRecurring.baseline_current_recurring_facts.stabilization_gap = unavailableMoney("Missing payroll");
    missingRecurring.baseline_current_recurring_facts.margin_state = "unavailable";
    missingRecurring.baseline_combined_monthly_improvement = unavailableMoney("Missing payroll");
    renderCard(missingRecurring);
    expect(screen.getByText(/\$39,003.52 goal pace · combined improvement needs recurring evidence/)).toBeInTheDocument();
  });

  it("shows stabilization when pace is unavailable and a quiet Goals link with no primary", () => {
    const missingPace = structuredClone(goalGapFixture());
    missingPace.baseline_goal_pace_reference.target_date = "2026-08-10";
    missingPace.baseline_goal_pace_reference.funding_months = "0.000000000000";
    missingPace.baseline_goal_pace_reference.goal_state = "expired_unfinished";
    missingPace.baseline_goal_pace_reference.required_goal_pace = unavailableMoney("Target date expired");
    missingPace.baseline_combined_monthly_improvement = unavailableMoney("Target date expired");
    const view = renderCard(missingPace);
    expect(screen.getByText(/\$5,602.98 to stabilize · target-date math unavailable/)).toBeInTheDocument();
    view.unmount();

    renderCard({
      state: "no_primary",
      observed_on: "2026-08-11",
      reason: "A primary goal has not been selected",
      warnings: [],
      calculation_version: "goal-arithmetic-v1",
      contract_version: "money-map-v2.1-contract-v1",
    });
    fireEvent.click(screen.getByRole("button", { name: "Open Goals" }));
    expect(onOpenGoals).toHaveBeenCalledOnce();
  });

  it("marks current baseline evidence for print while keeping actions separate", () => {
    renderCard();
    expect(document.querySelector('[data-print-goal-gap="current"]')).toHaveTextContent("$44,606.50");
    expect(document.querySelector(".goal-gap-actions")).toBeInTheDocument();
  });
});

describe("draft-only goal option dialog", () => {
  it("traps initial focus, states every boundary, returns focus, and has no Save action", async () => {
    vi.stubGlobal("fetch", fetchForDialog());
    renderCard();
    const explore = screen.getByRole("button", { name: "Explore options" });
    explore.focus();
    fireEvent.click(explore);
    const dialog = screen.getByRole("dialog", { name: "Explore goal options" });
    expect(dialog).toHaveTextContent("Draft only");
    expect(dialog).toHaveTextContent("Nothing here changes Goals");
    expect(dialog).toHaveTextContent("No money is reserved or moved");
    await waitFor(() => expect(screen.getByLabelText("Target date")).toHaveFocus());
    expect(within(dialog).queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(explore).toHaveFocus());
  });

  it("uses the exact 2035 date and exposes the calendar time basis", async () => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare same month/day in 2035" }));
    expect(screen.getByLabelText("Target date")).toHaveValue("2035-08-10");
    fireEvent.change(screen.getByLabelText("Target date"), { target: { value: "2035-11-18" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    await screen.findByText(/111\.277419354839 months/);
    fireEvent.click(screen.getByText("Time-basis evidence"));
    expect(screen.getByText(/inclusive actual-calendar fractional months/)).toHaveTextContent("2035-11-18");
  });

  it.each([
    ["Additional one-time goal reservation", "100000.00", "additional_reservation", "100000.00"],
    ["Generic monthly spending reduction", "100.00", "monthly_spending_reduction", "100.00"],
    ["Monthly after-tax income increase", "200.00", "monthly_after_tax_income", "200.00"],
  ] as const)("sends and shows the effect of %s only", async (label, entered, field, expected) => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.change(screen.getByLabelText(label), { target: { value: entered } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    await waitFor(() => expect(fetch.mock.calls.filter(([input]) => String(input).endsWith("gap-preview"))).toHaveLength(1));
    const call = fetch.mock.calls.find(([input]) => String(input).endsWith("gap-preview"));
    const payload = JSON.parse(String(call?.[1]?.body)) as Record<string, string>;
    expect(payload[field]).toBe(expected);
    expect(screen.getByRole("heading", { name: "Remaining monthly improvement" })).toBeInTheDocument();
  });

  it("combines generic and explicit candidate reductions exactly once after owner entry", async () => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.click(screen.getByText("Repeated outflow candidates"));
    const candidateInput = await screen.findByLabelText(/Proposed monthly reduction/);
    fireEvent.change(candidateInput, { target: { value: "5.00" } });
    fireEvent.change(screen.getByLabelText("Generic monthly spending reduction"), { target: { value: "2.00" } });
    fireEvent.change(screen.getByLabelText("Monthly after-tax income increase"), { target: { value: "3.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    await waitFor(() => expect(fetch.mock.calls.filter(([input]) => String(input).endsWith("gap-preview"))).toHaveLength(1));
    const call = fetch.mock.calls.find(([input]) => String(input).endsWith("gap-preview"));
    const payload = JSON.parse(String(call?.[1]?.body)) as GoalGapPreviewRequest;
    expect(payload.monthly_spending_reduction).toBe("7.00");
    expect(payload.monthly_after_tax_income).toBe("3.00");
  });

  it("candidate disclosure alone changes nothing and labels evidence without recommending it", async () => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.click(screen.getByText("Repeated outflow candidates"));
    expect(await screen.findByText("Invented Media Plan")).toBeInTheDocument();
    expect(screen.getByText(/Evidence only—not savings recommendations/)).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input).endsWith("gap-preview"))).toHaveLength(0);
  });

  it("enforces the candidate cap before any preview request", async () => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.click(screen.getByText("Repeated outflow candidates"));
    fireEvent.change(await screen.findByLabelText(/Proposed monthly reduction/), { target: { value: "10.01" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot exceed $10.00");
    expect(fetch.mock.calls.filter(([input]) => String(input).endsWith("gap-preview"))).toHaveLength(0);
  });

  it("resets all component-memory controls and the prior result", async () => {
    vi.stubGlobal("fetch", fetchForDialog());
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.change(screen.getByLabelText("Additional one-time goal reservation"), { target: { value: "100.00" } });
    fireEvent.change(screen.getByLabelText("Monthly after-tax income increase"), { target: { value: "200.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset to current" }));
    expect(screen.getByLabelText("Additional one-time goal reservation")).toHaveValue("0.00");
    expect(screen.getByLabelText("Monthly after-tax income increase")).toHaveValue("0.00");
    expect(screen.getByText("$44,606.50")).toBeInTheDocument();
  });

  it("shows available and unavailable gross context without a tax-return claim", async () => {
    vi.stubGlobal("fetch", fetchForDialog());
    const view = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    expect(screen.getByText(/\$69,033.92\/month/)).toBeInTheDocument();
    expect(screen.getByText(/Not a tax-return estimate/)).toBeInTheDocument();
    view.unmount();

    const unavailable = structuredClone(goalGapFixture());
    unavailable.gross_income_context = { state: "unavailable", reason: "No supported paycheck" };
    renderCard(unavailable);
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    expect(screen.getByText("No supported paycheck")).toBeInTheDocument();
  });

  it("retains the prior result on a failed recalculation", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("recurring-outflow-candidates")) return json(candidateFixture());
      return json({ detail: "Preview temporarily unavailable" }, 503);
    });
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("$44,606.50")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Recalculate" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Preview temporarily unavailable");
    expect(within(dialog).getByText("$44,606.50")).toBeInTheDocument();
  });

  it("sequence-guards a stale preview after reset and a newer recalculation", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    let previewCalls = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("recurring-outflow-candidates")) return json(candidateFixture());
      const payload = JSON.parse(String(init?.body)) as GoalGapPreviewRequest;
      previewCalls += 1;
      if (previewCalls === 1) return first;
      return json(scenarioFixture(payload));
    });
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.change(screen.getByLabelText("Monthly after-tax income increase"), { target: { value: "100.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to current" }));
    fireEvent.change(screen.getByLabelText("Monthly after-tax income increase"), { target: { value: "200.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    await screen.findByText("$44,406.50");
    resolveFirst?.(json(scenarioFixture({
      target_date: "2030-08-10",
      additional_reservation: "0.00",
      monthly_spending_reduction: "0.00",
      monthly_after_tax_income: "100.00",
    })));
    await waitFor(() => expect(screen.getByText("$44,406.50")).toBeInTheDocument());
    expect(screen.queryByText("$44,506.50")).not.toBeInTheDocument();
  });

  it("opens the real Goals surface without goal edits, check-ins, or Life Lab requests", async () => {
    const fetch = fetchForDialog();
    vi.stubGlobal("fetch", fetch);
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Explore options" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Open Goals" }));
    expect(onOpenGoals).toHaveBeenCalledOnce();
    const urls = fetch.mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => /check-in|life|lab|retirement|goals\/[a-z]/i.test(url))).toBe(false);
  });
});
