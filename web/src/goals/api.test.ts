import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backfillGoalCheckIn,
  editGoal,
  GoalApiError,
  loadGoalCandidates,
  loadGoalCheckIns,
  loadGoalComparison,
  loadGoalMilestone,
  loadGoalPosition,
  loadGoalProvenance,
  loadLatestGoalCheckIn,
  loadPrimaryGoal,
  selectPrimaryGoal,
} from "./api";
import {
  candidatesState,
  comparisonState,
  editToken,
  goalProgram,
  historyPage,
  latestState,
  milestoneState,
  positionState,
  primaryState,
  provenanceState,
  unchangedObservation,
} from "./fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Goals API", () => {
  it("uses every accepted read endpoint without invoking a check-in creation operation", async () => {
    const responses: Record<string, unknown> = {
      "/api/v2/goals/primary": primaryState,
      "/api/v2/goals/candidates": candidatesState,
      "/api/v2/goals/position": positionState,
      "/api/v2/goals/check-ins/latest": latestState,
      "/api/v2/goals/check-ins?limit=5": historyPage,
      "/api/v2/goals/comparison": comparisonState("250.00"),
      "/api/v2/goals/milestone": milestoneState(),
      "/api/v2/goals/provenance": provenanceState,
    };
    const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => json(responses[String(input)]));
    vi.stubGlobal("fetch", fetch);

    await Promise.all([
      loadPrimaryGoal(),
      loadGoalCandidates(),
      loadGoalPosition(),
      loadLatestGoalCheckIn(),
      loadGoalCheckIns(),
      loadGoalComparison(),
      loadGoalMilestone(),
      loadGoalProvenance(),
    ]);

    const calls = fetch.mock.calls.map(([input, init]) => ({ path: String(input), method: init?.method }));
    expect(calls.map((call) => call.path)).toEqual(expect.arrayContaining(Object.keys(responses)));
    expect(calls.every((call) => call.method === undefined || call.method === "GET")).toBe(true);
    expect(calls.some((call) => /ensure|create|backfill/i.test(call.path))).toBe(false);
  });

  it("uses one explicit typed command for load backfill", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      json(unchangedObservation),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(backfillGoalCheckIn()).resolves.toEqual(unchangedObservation);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v2/goals/check-ins/backfill",
      expect.objectContaining({ method: "POST" }),
    );
    const call = fetch.mock.calls[0];
    expect(call?.[1]?.body).toBeUndefined();
    expect(String(call?.[0])).not.toMatch(/[?&](opened|timestamp|telemetry|observed_on)=/i);
  });

  it("preserves exact decimal strings and accepted stale-write tokens", async () => {
    const fetch = vi.fn(async () => json(goalProgram));
    vi.stubGlobal("fetch", fetch);
    await editGoal(goalProgram.goal_program_id, {
      expected_edit_token: editToken,
      target_amount: "14000.00",
      protected_cash_floor: "3000.00",
      reserved_for_goal: "2000.00",
    });
    await selectPrimaryGoal({
      goal_program_id: goalProgram.goal_program_id,
      expected_edit_token: editToken,
    });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `/api/v2/goals/${goalProgram.goal_program_id}`,
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          expected_edit_token: editToken,
          target_amount: "14000.00",
          protected_cash_floor: "3000.00",
          reserved_for_goal: "2000.00",
        }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v2/goals/primary",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          goal_program_id: goalProgram.goal_program_id,
          expected_edit_token: editToken,
        }),
      }),
    );
  });

  it("retains HTTP status for stale-write review", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Goal changed" }, 409)));
    await expect(
      editGoal(goalProgram.goal_program_id, {
        expected_edit_token: editToken,
        name: "Preserved draft",
      }),
    ).rejects.toMatchObject({ status: 409, message: "Goal changed" });
  });

  it("encodes cursor pagination and keeps each page bounded", async () => {
    const fetch = vi.fn(async () => json(historyPage));
    vi.stubGlobal("fetch", fetch);
    await loadGoalCheckIns("cursor with spaces");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v2/goals/check-ins?limit=5&cursor=cursor+with+spaces",
      expect.any(Object),
    );
  });
});
