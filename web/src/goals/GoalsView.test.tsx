import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  GoalCandidateList,
  GoalComparisonState,
  GoalMilestoneState,
  GoalObservationResult,
  GoalPositionState,
  PrimaryGoalState,
} from "../v2-contracts";
import { COPY_BUDGETS, proseWordCount } from "../copy-budget";
import GoalsView, { milestoneSentence, verdictSentence } from "./GoalsView";
import {
  candidateProgram,
  candidatesState,
  checkIn,
  comparisonState,
  goalHash,
  goalPosition,
  goalProgram,
  historyPage,
  latestState,
  milestoneState,
  noCandidatesState,
  noComparisonState,
  noPrimaryState,
  olderHistoryPage,
  positionState,
  primaryState,
  provenanceState,
  unavailableComparisonState,
  unchangedObservation,
} from "./fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

interface FetchOptions {
  primary?: PrimaryGoalState;
  position?: GoalPositionState;
  comparison?: GoalComparisonState;
  milestone?: GoalMilestoneState;
  candidates?: GoalCandidateList;
  failures?: Record<string, { status: number; detail: string }>;
  patchStatus?: number;
  putStatus?: number;
  backfill?: GoalObservationResult;
  history?: typeof historyPage;
}

function goalsFetch(options: FetchOptions = {}) {
  let historyCalls = 0;
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const failure = options.failures?.[url];
    if (failure) return json({ detail: failure.detail }, failure.status);
    if (url === "/api/v2/goals/primary" && init?.method === "PUT") {
      return options.putStatus ? json({ detail: "Candidate changed" }, options.putStatus) : json(candidateProgram);
    }
    if (url.startsWith("/api/v2/goals/goal_") && init?.method === "PATCH") {
      return options.patchStatus ? json({ detail: "Goal changed" }, options.patchStatus) : json(goalProgram);
    }
    if (url === "/api/v2/goals/check-ins/backfill" && init?.method === "POST") {
      return json(options.backfill ?? unchangedObservation);
    }
    if (url === "/api/v2/goals/primary") return json(options.primary ?? primaryState);
    if (url === "/api/v2/goals/position") return json(options.position ?? positionState);
    if (url === "/api/v2/goals/check-ins/latest") return json(latestState);
    if (url === "/api/v2/goals/comparison") return json(options.comparison ?? comparisonState("250.00"));
    if (url === "/api/v2/goals/milestone") return json(options.milestone ?? milestoneState());
    if (url === "/api/v2/goals/candidates") return json(options.candidates ?? noCandidatesState);
    if (url.startsWith("/api/v2/goals/check-ins?")) {
      historyCalls += 1;
      return json(historyCalls === 1 ? (options.history ?? historyPage) : olderHistoryPage);
    }
    if (url === "/api/v2/goals/provenance") return json(provenanceState);
    return json({ detail: "Not found" }, 404);
  });
}

async function renderOrdinary(options: FetchOptions = {}) {
  const fetch = goalsFetch(options);
  vi.stubGlobal("fetch", fetch);
  render(<GoalsView reloadVersion={0} />);
  await screen.findByRole("heading", { name: goalProgram.name });
  return fetch;
}

function writeCalls(fetch: ReturnType<typeof goalsFetch>) {
  return fetch.mock.calls.filter(([, init]) => ![undefined, "GET"].includes(init?.method));
}

function backfillCalls(fetch: ReturnType<typeof goalsFetch>) {
  return fetch.mock.calls.filter(
    ([input, init]) =>
      init?.method === "POST" && String(input) === "/api/v2/goals/check-ins/backfill",
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Goals first answer", () => {
  it("shows a semantic loading state while goal reads are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<GoalsView reloadVersion={0} />);
    expect(screen.getByRole("heading", { name: "Goals" })).toBeInTheDocument();
    expect(screen.getByText("Loading the current goal…")).toBeInTheDocument();
  });

  it("keeps a primary-endpoint failure recoverable within Goals", async () => {
    const fetch = goalsFetch({
      failures: { "/api/v2/goals/primary": { status: 500, detail: "Goal storage is unavailable" } },
    });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} />);
    expect(await screen.findByRole("heading", { name: "Goals could not load." })).toBeInTheDocument();
    expect(screen.getByText("Goal storage is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders the complete concise primary result and keeps capacity distinct from reservation", async () => {
    const fetch = await renderOrdinary();
    expect(screen.getByRole("heading", { level: 1, name: "Goals" })).toBeInTheDocument();
    expect(screen.getByText("$14,000.00 by Aug 10, 2027")).toBeInTheDocument();
    expect(screen.getByLabelText("Explicitly reserved: $2,000.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Above protected floor: $4,500.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Required monthly pace: $1,000.00")).toBeInTheDocument();
    expect(screen.getByText("Accessible capital increased by $250.00 since Jul 10.")).toBeInTheDocument();
    expect(screen.getByText("Since last financial change")).toBeInTheDocument();
    expect(screen.getByText("Fund this goal at $1,000.00 per month.")).toBeInTheDocument();
    expect(screen.getByText("Observed Aug 10, 2026")).toBeInTheDocument();
    expect(screen.queryByText(/saved for/i)).not.toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/goals/provenance")).toBe(false);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/v2/goals/check-ins?"))).toBe(false);
    const budget = document.querySelector('[data-copy-budget="goals-first-viewport"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["goals-first-viewport"]);
  });

  it.each([
    ["positive", comparisonState("1234.56"), "Accessible capital increased by $1,234.56 since Jul 10."],
    ["negative", comparisonState("-345.67"), "Accessible capital decreased by $345.67 since Jul 10."],
    ["zero", comparisonState("0.00"), "Observed accessible capital is unchanged since Jul 10."],
    ["no previous", noComparisonState, "No saved comparison exists yet."],
    ["unavailable", unavailableComparisonState, "Comparison unavailable: Source fingerprints do not support a comparison."],
  ])("writes an honest %s verdict", (_label, state, expected) => {
    expect(verdictSentence(state)).toBe(expected);
  });

  it.each([
    ["floor breach", milestoneState("restore_floor", "850.25"), "Restore the protected cash floor by $850.25."],
    ["recurring gap", milestoneState("close_recurring_gap", "325.40"), "Close the $325.40 monthly recurring gap."],
    ["fund goal", milestoneState("fund_goal", "1000.00"), "Fund this goal at $1,000.00 per month."],
    ["completed", milestoneState("goal_complete", "0.00"), "This goal is fully reserved."],
    ["unavailable", milestoneState("data_unavailable", "0.00", "The goal date has expired"), "Milestone unavailable: The goal date has expired."],
  ])("writes the one binding %s milestone", (_label, state, expected) => {
    expect(milestoneSentence(state)).toBe(expected);
  });

  it("keeps an expired goal honest and never substitutes zero for missing evidence", async () => {
    const expiredPosition: GoalPositionState = {
      state: "available",
      source_fingerprint: goalHash,
      position: { ...goalPosition, pace_status: "expired", required_funding_pace: { ...goalPosition.required_funding_pace, amount: null, evidence: "unavailable", source_refs: [], derivation: null, unavailable_reason: "Target date has passed" } },
    };
    await renderOrdinary({
      position: expiredPosition,
      milestone: milestoneState("data_unavailable", "0.00", "Target date has passed"),
    });
    expect(screen.getByLabelText("Required monthly pace: Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Milestone unavailable: Target date has passed.")).toBeInTheDocument();
  });

  it("retains a valid primary when position sources are partially unavailable", async () => {
    const partial: GoalPositionState = {
      state: "available",
      source_fingerprint: goalHash,
      position: {
        ...goalPosition,
        accessible_investments: { amount: null, evidence: "unavailable", source_refs: [], derivation: null, unavailable_reason: "Latest investment balance coverage is incomplete" },
        available_above_floor: { amount: null, evidence: "unavailable", source_refs: [], derivation: null, unavailable_reason: "Accessible evidence is incomplete" },
      },
    };
    await renderOrdinary({ position: partial });
    expect(screen.getByRole("heading", { name: goalProgram.name })).toBeInTheDocument();
    expect(screen.getByLabelText("Above protected floor: Unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Position and formulas"));
    expect(screen.getByText("Sellable investments").parentElement).toHaveTextContent("Unavailable");
  });

  it("isolates a comparison detail failure from the valid position", async () => {
    await renderOrdinary({
      failures: { "/api/v2/goals/comparison": { status: 503, detail: "Comparison evidence is offline" } },
    });
    expect(screen.getByLabelText("Above protected floor: $4,500.00")).toBeInTheDocument();
    expect(screen.getAllByText("Comparison unavailable: Comparison evidence is offline.")).not.toHaveLength(0);
  });

  it("uses only the expected GET endpoints on ordinary mount", async () => {
    const fetch = await renderOrdinary();
    expect(writeCalls(fetch)).toEqual([]);
    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/v2/goals/primary",
      "/api/v2/goals/position",
      "/api/v2/goals/check-ins/latest",
      "/api/v2/goals/comparison",
      "/api/v2/goals/milestone",
    ]);
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
  });

  it("keeps reload, remount, and duplicate Strict Mode effects read-only", async () => {
    const fetch = goalsFetch();
    vi.stubGlobal("fetch", fetch);
    const view = render(<GoalsView reloadVersion={0} />);
    await screen.findByRole("heading", { name: goalProgram.name });
    view.rerender(<GoalsView reloadVersion={1} />);
    await waitFor(() => {
      expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/goals/primary"))
        .toHaveLength(2);
    });
    view.unmount();
    render(
      <StrictMode>
        <GoalsView reloadVersion={0} />
      </StrictMode>,
    );
    await screen.findByRole("heading", { name: goalProgram.name });
    expect(writeCalls(fetch)).toEqual([]);
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
  });
});

describe("Goal selection and editing", () => {
  it("shows explicit candidate selection without auto-selecting", async () => {
    const fetch = goalsFetch({ primary: noPrimaryState, candidates: candidatesState });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} />);
    expect(await screen.findByRole("heading", { name: "Choose the primary goal" })).toBeInTheDocument();
    expect(screen.getByText("Only one goal can be primary. Nothing is selected automatically.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: candidateProgram.name })).toBeInTheDocument();
    expect(screen.getByText("Reserved").parentElement).toHaveTextContent("$750.00");
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/goals/candidates")).toHaveLength(1);
  });

  it("shows the honest no-primary empty state without a Life Lab redirect", async () => {
    const fetch = goalsFetch({ primary: noPrimaryState, candidates: noCandidatesState });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} />);
    expect(await screen.findByRole("heading", { name: "No goal is ready to select." })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([input]) => String(input).includes("life-plan"))).toBe(false);
    expect(fetch.mock.calls.some(([input]) =>
      String(input) === "/api/v2/goals/check-ins/backfill",
    )).toBe(false);
    expect(screen.queryByText(/Observed source evidence/)).not.toBeInTheDocument();
  });

  it("labels observed financial evidence without inventing a goal", async () => {
    const fetch = goalsFetch({ primary: noPrimaryState, candidates: noCandidatesState });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} hasObservedSourceEvidence />);
    expect(await screen.findByRole("heading", { name: "No goal is ready to select." })).toBeInTheDocument();
    expect(screen.getByText("Observed source evidence · no accepted goal program.")).toBeInTheDocument();
    expect(writeCalls(fetch)).toEqual([]);
  });

  it("selects a candidate with its edit token and reloads the complete goal surface", async () => {
    let selected = false;
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v2/goals/primary" && init?.method === "PUT") {
        selected = true;
        return json({ ...candidateProgram, is_primary: true });
      }
      if (url === "/api/v2/goals/primary") return json(selected ? primaryState : noPrimaryState);
      if (url === "/api/v2/goals/candidates") return json(candidatesState);
      if (url === "/api/v2/goals/position") return json(positionState);
      if (url === "/api/v2/goals/check-ins/latest") return json(latestState);
      if (url === "/api/v2/goals/comparison") return json(comparisonState("250.00"));
      if (url === "/api/v2/goals/milestone") return json(milestoneState());
      if (url === "/api/v2/goals/check-ins/backfill" && init?.method === "POST") {
        return json(unchangedObservation);
      }
      return json({ detail: "Not found" }, 404);
    });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Make primary" }));
    expect(await screen.findByText("Primary goal selected.")).toBeInTheDocument();
    const selection = fetch.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(selection?.[1]?.body).toBe(JSON.stringify({
      goal_program_id: candidateProgram.goal_program_id,
      expected_edit_token: candidateProgram.edit_token,
    }));
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/goals/position").length).toBeGreaterThan(1);
    expect(backfillCalls(fetch as ReturnType<typeof goalsFetch>)).toHaveLength(1);
  });

  it("keeps candidate selection reviewable after a stale conflict", async () => {
    const fetch = goalsFetch({ primary: noPrimaryState, candidates: candidatesState, putStatus: 409 });
    vi.stubGlobal("fetch", fetch);
    render(<GoalsView reloadVersion={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Make primary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This goal changed before selection");
    expect(screen.getByRole("button", { name: "Reload goals" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: candidateProgram.name })).toBeInTheDocument();
    expect(backfillCalls(fetch)).toHaveLength(0);
  });

  it("submits exact edit strings, confirms compactly, and reloads through the explicit backfill command", async () => {
    const fetch = await renderOrdinary();
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    fireEvent.change(screen.getByLabelText("Goal name"), { target: { value: "Revised quiet place" } });
    fireEvent.change(screen.getByLabelText("Reserved amount"), { target: { value: "2400.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByText("Goal updated.")).toBeInTheDocument();
    const patch = fetch.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patch?.[1]?.body).toBe(JSON.stringify({
      expected_edit_token: goalProgram.edit_token,
      name: "Revised quiet place",
      target_date: goalProgram.target_date,
      target_amount: "14000.00",
      protected_cash_floor: "3000.00",
      reserved_for_goal: "2400.00",
    }));
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/goals/position").length).toBeGreaterThan(1);
    expect(backfillCalls(fetch)).toHaveLength(1);
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
  });

  it("shows financial-change success only after an authorized edit creates one observation", async () => {
    const fetch = await renderOrdinary({
      backfill: {
        ...unchangedObservation,
        status: "created",
        message: "A new financial-change observation was saved.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    fireEvent.change(screen.getByLabelText("Reserved amount"), { target: { value: "2400.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByText("Financial change saved.")).toHaveAttribute(
      "data-observation-status",
      "created",
    );
    expect(backfillCalls(fetch)).toHaveLength(1);
  });

  it("keeps a successful edit visible when its explicit observation is not current", async () => {
    const fetch = await renderOrdinary({
      backfill: {
        status: "not_current",
        trigger: "load_backfill",
        check_in: null,
        retryable: true,
        message: "No new goal observation was saved because one or more financial sources are not current. Retry Update data.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    fireEvent.change(screen.getByLabelText("Reserved amount"), { target: { value: "2400.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByText("Goal updated.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No new goal observation was saved");
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
    expect(backfillCalls(fetch)).toHaveLength(1);
  });

  it("does not backfill or show success after a rejected edit", async () => {
    const fetch = await renderOrdinary({ patchStatus: 409 });
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    fireEvent.change(screen.getByLabelText("Goal name"), { target: { value: "Rejected change" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your entries are preserved");
    expect(backfillCalls(fetch)).toHaveLength(0);
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
  });

  it("does not show false success when observation persistence fails after a successful edit", async () => {
    const fetch = await renderOrdinary({
      failures: {
        "/api/v2/goals/check-ins/backfill": {
          status: 503,
          detail: "Observation persistence is unavailable",
        },
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    fireEvent.change(screen.getByLabelText("Reserved amount"), { target: { value: "2400.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByText("Goal updated.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No new goal observation was saved");
    expect(screen.getByRole("alert")).toHaveTextContent("Use Update data to retry");
    expect(screen.queryByText("Financial change saved.")).not.toBeInTheDocument();
    expect(backfillCalls(fetch)).toHaveLength(1);
  });

  it("associates local validation errors and does not submit an invalid reservation", async () => {
    const fetch = await renderOrdinary();
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    const reserved = screen.getByLabelText("Reserved amount");
    fireEvent.change(reserved, { target: { value: "15000.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(screen.getByText("Reserved money cannot exceed the target amount.")).toHaveAttribute("id", "goal-reserved-error");
    expect(reserved).toHaveAttribute("aria-invalid", "true");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
  });

  it("preserves unsaved input and offers reload after a stale edit", async () => {
    await renderOrdinary({ patchStatus: 409 });
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    const name = screen.getByLabelText("Goal name");
    fireEvent.change(name, { target: { value: "Unsaved owner wording" } });
    fireEvent.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your entries are preserved");
    expect(name).toHaveValue("Unsaved owner wording");
    expect(screen.getByRole("button", { name: "Reload current goal" })).toBeInTheDocument();
  });

  it("names the dialog, restores focus, and closes on Escape", async () => {
    await renderOrdinary();
    const edit = screen.getByRole("button", { name: "Edit goal" });
    edit.focus();
    fireEvent.click(edit);
    expect(screen.getByRole("dialog", { name: "Edit goal" })).toBeInTheDocument();
    expect(screen.getByLabelText("Goal name")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(edit).toHaveFocus();
  });
});

describe("Progressive evidence", () => {
  it("loads cursor-bounded history only when opened and appends an older page", async () => {
    const fetch = await renderOrdinary();
    expect(screen.queryByText("Accessible first saved observation")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Financial change timeline"));
    expect(await screen.findByText("Accessible first saved observation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show older evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Load older evidence" }));
    expect(await screen.findByText("Jul 10, 2026")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v2/goals/check-ins?limit=5&cursor=older-cursor",
      expect.any(Object),
    );
    expect(writeCalls(fetch)).toEqual([]);
  });

  it("never renders more than 25 timeline entries", async () => {
    const many = Array.from({ length: 30 }, (_, index) => ({
      ...checkIn,
      check_in_id: `check-in-${index}`,
      effective_observation_date: `2026-07-${String((index % 28) + 1).padStart(2, "0")}`,
    }));
    await renderOrdinary({
      history: { state: "available", check_ins: many, comparisons: [], next_cursor: null },
    });
    fireEvent.click(screen.getByText("Financial change timeline"));
    await screen.findAllByText("Accessible first saved observation");
    expect(document.querySelectorAll(".goal-timeline > li")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Show older evidence" }));
    expect(document.querySelectorAll(".goal-timeline > li")).toHaveLength(25);
  });

  it("keeps provenance closed by default and displays only sanitized source evidence", async () => {
    const fetch = await renderOrdinary();
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/goals/provenance")).toBe(false);
    fireEvent.click(screen.getByText("Source provenance"));
    expect(await screen.findByText(provenanceState.source_fingerprint ?? "")).toBeInTheDocument();
    expect(screen.queryByText(goalProgram.goal_program_id, { exact: false })).not.toBeInTheDocument();
    expect(screen.getByText("accessible cash: $6,000.00")).toBeInTheDocument();
    expect(screen.queryByText("balance:synthetic:1")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(".sqlite3");
    expect(writeCalls(fetch)).toEqual([]);
  });

  it("keeps a provenance failure inside its opened detail", async () => {
    await renderOrdinary({
      failures: { "/api/v2/goals/provenance": { status: 500, detail: "Source evidence is unavailable" } },
    });
    fireEvent.click(screen.getByText("Source provenance"));
    expect(await screen.findByText("Source evidence is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: goalProgram.name })).toBeInTheDocument();
  });

  it("honors the operating system reduced-motion preference", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    await renderOrdinary();
    expect(screen.getByRole("heading", { level: 1, name: "Goals" }).closest(".goals-view"))
      .toHaveAttribute("data-reduced-motion", "true");
  });

  it("uses landmark-compatible headings, accessible metric labels, and named controls", async () => {
    await renderOrdinary();
    expect(screen.getByRole("heading", { level: 1, name: "Goals" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: goalProgram.name })).toBeInTheDocument();
    expect(screen.getByLabelText("Primary goal metrics")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit goal" })).toBeInTheDocument();
    expect(screen.getByText("Binding milestone").parentElement).toHaveTextContent("Fund this goal");
  });

  it("prints dated Goals evidence with bounded history and provenance", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const fetch = await renderOrdinary();
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    await waitFor(() => expect(print).toHaveBeenCalledOnce());
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("Goals evidence · Observed Aug 10, 2026");
    expect(document.querySelector(".goal-primary-card .print-only")).toHaveTextContent(`Source fingerprint: ${goalHash}`);
    expect(fetch.mock.calls.some(([input]) => String(input) === "/api/v2/goals/provenance")).toBe(true);
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/v2/goals/check-ins?"))).toBe(true);
    expect(writeCalls(fetch)).toEqual([]);
  });
});
