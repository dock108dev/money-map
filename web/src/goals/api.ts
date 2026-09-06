import { ApiRequestError, request } from "../api";
import type {
  GoalCandidateList,
  GoalCheckInState,
  GoalCheckInTimelinePage,
  GoalComparisonState,
  GoalEditRequest,
  GoalMilestoneState,
  GoalObservationResult,
  GoalPositionState,
  GoalProgramView,
  GoalProvenanceState,
  PrimaryGoalSelectionRequest,
  PrimaryGoalState,
} from "../v2-contracts";

export class GoalApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "GoalApiError";
    this.status = status;
  }
}

async function goalWrite<T>(path: string, init: RequestInit): Promise<T> {
  try {
    return await request<T>(path, init);
  } catch (reason) {
    if (reason instanceof ApiRequestError) throw new GoalApiError(reason.status, reason.message);
    throw reason;
  }
}

export function loadPrimaryGoal(): Promise<PrimaryGoalState> {
  return request("/api/v2/goals/primary");
}

export function loadGoalCandidates(): Promise<GoalCandidateList> {
  return request("/api/v2/goals/candidates");
}

export function loadGoalPosition(): Promise<GoalPositionState> {
  return request("/api/v2/goals/position");
}

export function loadLatestGoalCheckIn(): Promise<GoalCheckInState> {
  return request("/api/v2/goals/check-ins/latest");
}

export function backfillGoalCheckIn(): Promise<GoalObservationResult> {
  return goalWrite("/api/v2/goals/check-ins/backfill", { method: "POST" });
}

export function loadGoalCheckIns(cursor?: string): Promise<GoalCheckInTimelinePage> {
  const query = new URLSearchParams({ limit: "5" });
  if (cursor) query.set("cursor", cursor);
  return request(`/api/v2/goals/check-ins?${query}`);
}

export function loadGoalComparison(): Promise<GoalComparisonState> {
  return request("/api/v2/goals/comparison");
}

export function loadGoalMilestone(): Promise<GoalMilestoneState> {
  return request("/api/v2/goals/milestone");
}

export function loadGoalProvenance(): Promise<GoalProvenanceState> {
  return request("/api/v2/goals/provenance");
}

export function editGoal(
  goalProgramId: string,
  payload: GoalEditRequest,
): Promise<GoalProgramView> {
  return goalWrite(`/api/v2/goals/${encodeURIComponent(goalProgramId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function selectPrimaryGoal(
  payload: PrimaryGoalSelectionRequest,
): Promise<GoalProgramView> {
  return goalWrite("/api/v2/goals/primary", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
