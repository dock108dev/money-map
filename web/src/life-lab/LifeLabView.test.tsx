import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { goalProgram } from "../goals/fixtures";
import { COPY_BUDGETS, proseWordCount } from "../copy-budget";
import { retiredDuplicateCopy } from "../test-fixtures/slice6-state-matrix";
import {
  labResult,
  labSeed,
  legacySnapshot,
  lifeProjection,
  promotionApplied,
  promotionPreview,
  retirementProfile,
  retirementPath,
  retirementSnapshot,
} from "../retirement/test-fixtures";
import { DriveCalculator, exitMath, loanMath, weeklySprint, wholeMonthIntervals } from "./DriveCalculator";
import type { LifeGoal } from "./life-lab-types";
import { availableMissionOptions, initialMissionKey } from "./mission-selection";
import LifeLabView from "./LifeLabView";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function labFetch(options: { confirmStatus?: number; previewStatus?: number; snapshots?: Array<typeof legacySnapshot> } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v2/lab/snapshots" && init?.method === "POST") return json({ ...legacySnapshot, id: 12, legacy: false, snapshot_context: "lab_blank" });
    if (url === "/api/v2/lab/snapshots") return json(options.snapshots ?? [legacySnapshot]);
    if (url === "/api/v2/retirement/snapshots") return json([retirementSnapshot]);
    if (url === "/api/v2/goals/primary") return json({ state: "primary", goal: goalProgram });
    if (url === "/api/v2/retirement/profile") return json(retirementProfile);
    if (url === "/api/v2/lab/experiments") {
      const body = JSON.parse(String(init?.body)) as { seed_kind: "blank" | "current_goal" | "retirement_result" };
      return json(labSeed(body.seed_kind));
    }
    if (url === "/api/v2/lab/experiments/project") {
      const body = JSON.parse(String(init?.body)) as { experiment_id: string; draft: Record<string, unknown> };
      const kind = body.experiment_id.replace("lab-", "") as "blank" | "current_goal" | "retirement_result";
      const seed = { ...labSeed(kind), draft: body.draft };
      return json({ ...labResult(seed), draft: body.draft });
    }
    if (url === "/api/v2/lab/promotions/preview") {
      if (options.previewStatus) return json({ detail: "Unsupported Lab output remains Lab-only" }, options.previewStatus);
      return json(promotionPreview);
    }
    if (url === "/api/v2/lab/promotions/confirm") {
      if (options.confirmStatus) return json({ detail: "The target changed after preview" }, options.confirmStatus);
      return json(promotionApplied);
    }
    return new Response("Not found", { status: 404 });
  });
}

async function start(kind: "blank" | "current goal" | "retirement result") {
  if (kind === "retirement result") {
    fireEvent.change(await screen.findByLabelText("Retirement result seed"), { target: { value: "11" } });
  }
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`Start from ${kind}|Start ${kind}`, "i") }));
  await screen.findByRole("button", { name: "Edit experiment" });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("isolated Life Lab", () => {
  it("requires an explicit blank, current-goal, or Retirement-result seed and preserves legacy evidence", async () => {
    const fetch = labFetch();
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);

    expect(await screen.findByRole("heading", { name: "Start an experiment" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start blank/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start from current goal/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start from retirement result/ })).toBeDisabled();
    fireEvent.click(screen.getByText("Experiment and legacy evidence"));
    expect(screen.getByText(/Legacy combined plan · v1.2.1 inputs/)).toBeInTheDocument();
    expect(screen.getByText("Legacy combined scenario")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/lab/experiments")).toBe(false);
    const budget = document.querySelector('[data-copy-budget="lab-seed-chooser"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["lab-seed-chooser"]);

    fireEvent.change(screen.getByLabelText("Retirement result seed"), { target: { value: "11" } });
    expect(screen.getByRole("button", { name: /Start from retirement result/ })).toBeEnabled();
  });

  it.each([
    ["blank", "Blank experiment", "No Goal or Retirement money was copied."],
    ["current goal", goalProgram.name, "The source was copied once; later edits do not alter this experiment."],
    ["retirement result", retirementSnapshot.name, "The source was copied once; later edits do not alter this experiment."],
  ] as const)("starts a %s seed as an isolated draft", async (kind, source, copyText) => {
    vi.stubGlobal("fetch", labFetch());
    render(<LifeLabView />);
    await start(kind);
    expect(screen.getByRole("heading", { name: source })).toBeInTheDocument();
    expect(screen.getByText("Isolated experiment")).toBeInTheDocument();
    if (kind === "current goal") {
      expect(screen.getByText("Life Lab route convention · 51 whole-month intervals")).toBeInTheDocument();
    }
    fireEvent.click(screen.getByText("Source evidence"));
    expect(screen.getByText(copyText)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("goal_mutation=false");
    expect(document.body).not.toHaveTextContent("retirement_mutation=false");
    expect(document.body).not.toHaveTextContent("applied=false");
    const budget = document.querySelector('[data-copy-budget="lab-active-summary"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["lab-active-summary"]);
    for (const phrase of retiredDuplicateCopy) expect(document.body).not.toHaveTextContent(phrase);
    expect(screen.queryByRole("heading", { name: "Edit Retirement assumptions" })).not.toBeInTheDocument();
  });

  it("keeps draft edits local, exposes the four arithmetic routes, and saves only an experiment", async () => {
    const fetch = labFetch();
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);
    await start("blank");

    fireEvent.click(screen.getByRole("button", { name: "Edit experiment" }));
    const missionDialog = screen.getByRole("dialog", { name: "Edit experiment" });
    fireEvent.change(within(missionDialog).getByLabelText("Mission capital"), { target: { value: "2000000.00" } });
    fireEvent.click(within(missionDialog).getByRole("button", { name: "Save experiment" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit experiment" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("Route formulas and time convention"));
    fireEvent.change(screen.getByLabelText("Mission"), { target: { value: "freedom" } });
    expect(await screen.findByText(/01 · Earn it linearly/)).toBeInTheDocument();
    expect(screen.getByText(/02 · Compound sprint/)).toBeInTheDocument();
    expect(screen.getByText(/03 · Build it and sell it/)).toBeInTheDocument();
    expect(screen.getByText(/04 · 401\(k\) fuel/)).toBeInTheDocument();
    expect(screen.getByText(/Arithmetic only; this is not approval, eligibility, advice, or a borrowing action/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save experiment" }));
    fireEvent.change(screen.getByLabelText("Snapshot name"), { target: { value: "Extreme path" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Save experiment" })).getByRole("button", { name: "Save experiment" }));
    await screen.findByText("Experiment snapshot saved.");
    expect(fetch.mock.calls.some(([input, init]) => String(input).includes("/goals/") && init?.method === "PUT")).toBe(false);
    expect(fetch.mock.calls.some(([input, init]) => String(input) === "/api/v2/retirement/profile" && init?.method === "PUT")).toBe(false);
  });

  it("renders an exact zero-write diff and requires a keyboard-contained confirmation", async () => {
    const fetch = labFetch();
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);
    await start("current goal");
    fireEvent.click(screen.getByRole("button", { name: "Promote a value" }));
    fireEvent.change(screen.getByLabelText("Promotion exact value"), { target: { value: "15000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview change" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("goal_programs.target_amount")).toBeInTheDocument();
    expect(within(table).getByText("$14,000")).toBeInTheDocument();
    expect(within(table).getByText("$15,000")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("applied=false");
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("/confirm"))).toBe(false);

    const dialog = screen.getByRole("dialog", { name: "Promote a value" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const trigger = screen.getByRole("button", { name: "Promote a value" });
    expect(trigger).toHaveFocus();

    fireEvent.click(trigger);
    fireEvent.change(screen.getByLabelText("Promotion exact value"), { target: { value: "15000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview change" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm promotion" }));
    expect(await screen.findByText("Promotion confirmed for Goals.")).toBeInTheDocument();
    expect(screen.getByText(/Promotion confirmed. Observation: created./)).toBeInTheDocument();
  });

  it("preserves the changed experiment when stale or unsupported confirmation is rejected", async () => {
    vi.stubGlobal("fetch", labFetch({ confirmStatus: 409 }));
    render(<LifeLabView />);
    await start("current goal");
    fireEvent.click(screen.getByRole("button", { name: "Edit experiment" }));
    fireEvent.change(screen.getByLabelText("Mission capital"), { target: { value: "1750000.00" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Edit experiment" })).getByRole("button", { name: "Save experiment" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit experiment" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Promote a value" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview change" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm promotion" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("target changed after preview");
    expect(screen.getByRole("heading", { name: /\$1,750,000 by/ })).toBeInTheDocument();
  });

  it("shows three recent Lab snapshots, searches older evidence, and keeps the legacy label textual", async () => {
    const snapshots = Array.from({ length: 5 }, (_, index) => ({
      ...legacySnapshot,
      id: index + 30,
      legacy: index === 4,
      name: index === 4 ? "Older combined evidence" : `Experiment ${index + 1}`,
      created_at: `2026-08-${String(index + 1).padStart(2, "0")}T12:00:00Z`,
    }));
    vi.stubGlobal("fetch", labFetch({ snapshots }));
    render(<LifeLabView />);
    await screen.findByRole("heading", { name: "Start an experiment" });
    fireEvent.click(screen.getByText("Experiment and legacy evidence"));
    expect(document.querySelectorAll(".scenario-list > button")).toHaveLength(3);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search saved Lab evidence" }), { target: { value: "Older combined" } });
    expect(screen.getByText("Legacy combined scenario")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search saved Lab evidence" }), { target: { value: "missing" } });
    expect(screen.getByText("No saved Lab evidence matches this search.")).toBeInTheDocument();
  });

  it("prints dated Lab evidence while source details stay collapsed on screen", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", labFetch());
    render(<LifeLabView />);
    await start("blank");
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("Life Lab evidence · 2026-08-10");
    expect(screen.getByText("Source evidence").closest("details")).not.toHaveAttribute("open");
    expect(Array.from(document.querySelectorAll(".lab-source-evidence code")).some((node) => node.textContent === "e".repeat(64))).toBe(true);
  });
});

describe("Life Lab arithmetic helpers", () => {
  it("keeps the four extreme-path formulas inspectable", () => {
    const sprint = weeklySprint(5000, 1000000, 52, 0.9);
    expect(sprint.assumed_annualized_pct).toBeCloseTo(59.35, 2);
    expect(exitMath(1000000, 20, 30, 5).companyExit).toBeCloseTo(7142857.14, 1);
    expect(loanMath(547426, 0, 0, 8.5, 5).newLoan).toBe(50000);
  });

  it("uses the exact independent whole-month interval convention", () => {
    expect(wholeMonthIntervals("2026-08-10", "2030-11-18")).toBe(51);
  });
});

function missionGoal(overrides: Partial<LifeGoal> = {}): LifeGoal {
  return {
    id: 1,
    profile_id: 0,
    name: "Unfinished current mission",
    target_date: "2030-11-18",
    target_amount: "1000000.00",
    reserved_amount: "0.00",
    annual_cost: "0.00",
    priority: "required",
    enabled: true,
    notes: "Synthetic mission",
    created_at: "2026-08-10T12:00:00Z",
    updated_at: "2026-08-10T12:00:00Z",
    provenance: "user_entered",
    ...overrides,
  };
}

describe("Life Lab mission-selection policy", () => {
  it("prefers the seeded unfinished current Goal without relying on source order", () => {
    const funded = missionGoal({ id: 2, name: "Funded first", target_amount: "500.00", reserved_amount: "500.00" });
    const current = missionGoal({ id: 3, name: "Seeded current Goal" });
    const unrelated = missionGoal({ id: 4, name: "Unrelated projection goal" });
    const options = availableMissionOptions([funded, unrelated, current], retirementPath());
    expect(initialMissionKey({ seedKind: "current_goal", seededGoalLabel: "Seeded current Goal", options })).toBe("goal-3");
  });

  it("auto-selects only one valid unfinished current-goal mission and rejects funded, disabled, invalid, blank, and Retirement defaults", () => {
    const unfinished = missionGoal();
    const funded = missionGoal({ id: 2, target_amount: "500.00", reserved_amount: "500.00" });
    const disabled = missionGoal({ id: 3, enabled: false });
    const invalid = missionGoal({ id: 4, target_amount: "not-money" });
    const options = availableMissionOptions([funded, disabled, invalid, unfinished], retirementPath());
    expect(options.map((option) => option.key)).toEqual(["freedom", "goal-2", "goal-1"]);
    expect(initialMissionKey({ seedKind: "current_goal", seededGoalLabel: null, options })).toBe("goal-1");
    expect(initialMissionKey({ seedKind: "blank", seededGoalLabel: null, options })).toBe("");
    expect(initialMissionKey({ seedKind: "retirement_result", seededGoalLabel: null, options })).toBe("");
    const fundedOnly = availableMissionOptions([funded], retirementPath());
    expect(initialMissionKey({ seedKind: "current_goal", seededGoalLabel: "Funded first", options: fundedOnly })).toBe("");
  });
});

describe("Life Lab mission route states", () => {
  const baseProps = {
    projection: lifeProjection,
    path: retirementPath(),
    startingPoint: lifeProjection.starting_point,
    seededGoalLabel: null,
  };

  it("requires explicit selection for blank seeds, hides $0 routes, and renders all formulas only for positive capital", async () => {
    const funded = missionGoal({ id: 2, name: "Already funded", target_amount: "500.00", reserved_amount: "500.00" });
    const positive = missionGoal({ id: 3, name: "Positive mission" });
    render(<DriveCalculator {...baseProps} goals={[funded, positive]} seedKind="blank" selectionContext="experiment-a" />);
    expect(screen.getByRole("heading", { name: "Choose a mission" })).toBeInTheDocument();
    expect(screen.queryByText(/01 · Earn it linearly/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Mission"), { target: { value: "goal-2" } });
    expect(await screen.findByRole("heading", { name: "This mission is funded." })).toBeInTheDocument();
    expect(screen.getByText(/No \$0 route cards are shown/)).toBeInTheDocument();
    expect(screen.queryByText(/01 · Earn it linearly/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Mission"), { target: { value: "goal-3" } });
    expect(await screen.findByText(/01 · Earn it linearly/)).toBeInTheDocument();
    expect(screen.getByText(/02 · Compound sprint/)).toBeInTheDocument();
    expect(screen.getByText(/03 · Build it and sell it/)).toBeInTheDocument();
    expect(screen.getByText(/04 · 401\(k\) fuel/)).toBeInTheDocument();
  });

  it("labels the accepted 51-whole-month comparison and keeps the full convention in named evidence", () => {
    const current = missionGoal({ name: "Seeded current Goal" });
    render(<DriveCalculator {...baseProps} goals={[current]} seedKind="current_goal" seededGoalLabel="Seeded current Goal" selectionContext="current-goal-a" />);
    expect(screen.getByText(/51 whole-month intervals/)).toHaveTextContent("Aug 10, 2026 to Nov 18, 2030");
    const evidence = screen.getByText("Life Lab whole-month convention").closest("details");
    expect(evidence).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Life Lab whole-month convention"));
    expect(screen.getByText(/independent experimental route convention/)).toHaveTextContent("not the operational Goal's inclusive actual-calendar fractional-month pace");
  });

  it("resets an explicit mission when the experiment, path, projection, or available mission context changes", async () => {
    const goals = [missionGoal()];
    const view = render(<DriveCalculator {...baseProps} goals={goals} seedKind="blank" selectionContext="experiment-a" />);
    fireEvent.change(screen.getByLabelText("Mission"), { target: { value: "goal-1" } });
    expect(await screen.findByText(/01 · Earn it linearly/)).toBeInTheDocument();
    view.rerender(<DriveCalculator {...baseProps} path={retirementPath("rough")} goals={goals} seedKind="blank" selectionContext="experiment-b" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Choose a mission" })).toBeInTheDocument());
    expect(screen.queryByText(/01 · Earn it linearly/)).not.toBeInTheDocument();
  });
});
