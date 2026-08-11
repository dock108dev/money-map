import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { goalProgram } from "../goals/fixtures";
import {
  labResult,
  labSeed,
  legacySnapshot,
  promotionApplied,
  promotionPreview,
  retirementProfile,
  retirementSnapshot,
} from "../retirement/test-fixtures";
import { exitMath, loanMath, weeklySprint } from "./DriveCalculator";
import LifeLabView from "./LifeLabView";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function labFetch(options: { confirmStatus?: number; previewStatus?: number } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v2/lab/snapshots" && init?.method === "POST") return json({ ...legacySnapshot, id: 12, legacy: false, snapshot_context: "lab_blank" });
    if (url === "/api/v2/lab/snapshots") return json([legacySnapshot]);
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
  await screen.findByRole("heading", { name: "Dated mission" });
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

    expect(await screen.findByRole("heading", { name: "How should this isolated experiment begin?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start blank/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start from current goal/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Start from retirement result/ })).toBeDisabled();
    expect(screen.getByText("Legacy combined plan · v1.2.1 inputs")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/lab/experiments")).toBe(false);

    fireEvent.change(screen.getByLabelText("Retirement result seed"), { target: { value: "11" } });
    expect(screen.getByRole("button", { name: /Start from retirement result/ })).toBeEnabled();
  });

  it.each([
    ["blank", "Blank experiment", "No Goal or Retirement money was copied."],
    ["current goal", goalProgram.name, "Later source edits do not alter this experiment."],
    ["retirement result", retirementSnapshot.name, "Later source edits do not alter this experiment."],
  ] as const)("starts a %s seed as an isolated draft", async (kind, source, copyText) => {
    vi.stubGlobal("fetch", labFetch());
    render(<LifeLabView />);
    await start(kind);
    expect(screen.getByRole("heading", { name: source })).toBeInTheDocument();
    expect(screen.getByText(copyText)).toBeInTheDocument();
    expect(screen.getByText(/goal_mutation=false · retirement_mutation=false/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Edit the durable profile" })).not.toBeInTheDocument();
  });

  it("keeps draft edits local, exposes the four arithmetic routes, and saves only an experiment", async () => {
    const fetch = labFetch();
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);
    await start("blank");

    fireEvent.change(screen.getByLabelText("Isolated mission capital"), { target: { value: "2000000.00" } });
    expect(screen.getByText(/draft changed locally/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recalculate changed draft" }));
    await waitFor(() => expect(screen.queryByText(/draft changed locally/)).not.toBeInTheDocument());
    expect(screen.getByText(/01 · Earn it linearly/)).toBeInTheDocument();
    expect(screen.getByText(/02 · Compound sprint/)).toBeInTheDocument();
    expect(screen.getByText(/03 · Build it and sell it/)).toBeInTheDocument();
    expect(screen.getByText(/04 · 401\(k\) fuel/)).toBeInTheDocument();
    expect(screen.getByText(/Arithmetic only; this is not approval, eligibility, advice, or a borrowing action/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Experiment snapshot name"), { target: { value: "Extreme path" } });
    fireEvent.click(screen.getByRole("button", { name: "Save experiment" }));
    await screen.findByText("Reproducible experiment snapshot saved. Goals and Retirement were unchanged.");
    expect(fetch.mock.calls.some(([input, init]) => String(input).includes("/goals/") && init?.method === "PUT")).toBe(false);
    expect(fetch.mock.calls.some(([input, init]) => String(input) === "/api/v2/retirement/profile" && init?.method === "PUT")).toBe(false);
  });

  it("renders an exact zero-write diff and requires a keyboard-contained confirmation", async () => {
    const fetch = labFetch();
    vi.stubGlobal("fetch", fetch);
    render(<LifeLabView />);
    await start("current goal");
    fireEvent.change(screen.getByLabelText("Promotion exact value"), { target: { value: "15000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate zero-write preview" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("goal_programs.target_amount")).toBeInTheDocument();
    expect(within(table).getByText("$14,000")).toBeInTheDocument();
    expect(within(table).getByText("$15,000")).toBeInTheDocument();
    expect(screen.getByText(/Preview only · applied=false/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("/confirm"))).toBe(false);

    const trigger = screen.getByRole("button", { name: "Review confirmation" });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Confirm this exact promotion?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(within(dialog).getByRole("button", { name: "Confirm promotion" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm promotion" }));
    expect(await screen.findByText(/Applied to goals. Observation: created./)).toBeInTheDocument();
  });

  it("preserves the changed experiment when stale or unsupported confirmation is rejected", async () => {
    vi.stubGlobal("fetch", labFetch({ confirmStatus: 409 }));
    render(<LifeLabView />);
    await start("current goal");
    const mission = screen.getByLabelText("Isolated mission capital");
    fireEvent.change(mission, { target: { value: "1750000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate zero-write preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review confirmation" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm promotion" }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("target changed after preview");
    expect(screen.getByLabelText("Isolated mission capital")).toHaveValue(1750000);
  });
});

describe("Life Lab arithmetic helpers", () => {
  it("keeps the four extreme-path formulas inspectable", () => {
    const sprint = weeklySprint(5000, 1000000, 52, 0.9);
    expect(sprint.assumed_annualized_pct).toBeCloseTo(59.35, 2);
    expect(exitMath(1000000, 20, 30, 5).companyExit).toBeCloseTo(7142857.14, 1);
    expect(loanMath(547426, 0, 0, 8.5, 5).newLoan).toBe(50000);
  });
});
