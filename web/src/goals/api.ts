import { request } from "../api";
import type {
  GoalCandidateList,
  GoalCheckInState,
  GoalCheckInTimelinePage,
  GoalComparisonState,
  GoalEditRequest,
  GoalMilestoneState,
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

async function goalRequest<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await request<T>(path, init);
  } catch (reason) {
    if (reason instanceof GoalApiError) throw reason;
    throw reason;
  }
}

async function goalWrite<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new GoalApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function loadPrimaryGoal(): Promise<PrimaryGoalState> {
  return goalRequest("/api/v2/goals/primary");
}

export function loadGoalCandidates(): Promise<GoalCandidateList> {
  return goalRequest("/api/v2/goals/candidates");
}

export function loadGoalPosition(): Promise<GoalPositionState> {
  return goalRequest("/api/v2/goals/position");
}

export function loadLatestGoalCheckIn(): Promise<GoalCheckInState> {
  return goalRequest("/api/v2/goals/check-ins/latest");
}

export function loadGoalCheckIns(cursor?: string): Promise<GoalCheckInTimelinePage> {
  const query = new URLSearchParams({ limit: "5" });
  if (cursor) query.set("cursor", cursor);
  return goalRequest(`/api/v2/goals/check-ins?${query}`);
}

export function loadGoalComparison(): Promise<GoalComparisonState> {
  return goalRequest("/api/v2/goals/comparison");
}

export function loadGoalMilestone(): Promise<GoalMilestoneState> {
  return goalRequest("/api/v2/goals/milestone");
}

export function loadGoalProvenance(): Promise<GoalProvenanceState> {
  return goalRequest("/api/v2/goals/provenance");
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
