import { request } from "../api";
import type { GoalProgramView } from "../v2-contracts";
import type {
  RetirementProfileEditRequest,
  RetirementProfileView,
  RetirementProjectionRequest,
  RetirementProjectionResult,
} from "../v2-contracts";
import type { LifeStartingPoint } from "../life-lab/life-lab-types";

export interface PlanningSnapshot {
  id: number;
  name: string;
  snapshot_context: string;
  context_label: string;
  legacy: boolean;
  target_age: number;
  path_key: string;
  status: string;
  summary: Record<string, unknown>;
  input_snapshot: Record<string, unknown>;
  warnings: string[];
  engine_version: string;
  assumption_version: string;
  benchmark_version: string;
  source_fingerprint: string;
  stale: boolean;
  created_at: string;
  periods: Array<Record<string, unknown>>;
}

export function loadRetirementProfile() {
  return request<RetirementProfileView | null>("/api/v2/retirement/profile");
}

export function saveRetirementProfile(payload: RetirementProfileEditRequest) {
  return request<RetirementProfileView>("/api/v2/retirement/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function loadRetirementStartingPoint() {
  return request<LifeStartingPoint & { evidence_classification: Record<string, string>; read_only: true }>(
    "/api/v2/retirement/starting-point",
  );
}

export function loadRetirementOperationalGoals() {
  return request<GoalProgramView[]>("/api/v2/retirement/operational-goals");
}

export function projectRetirement(payload: RetirementProjectionRequest) {
  return request<RetirementProjectionResult>("/api/v2/retirement/project", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadRetirementSnapshots() {
  return request<PlanningSnapshot[]>("/api/v2/retirement/snapshots");
}

export function openRetirementSnapshot(id: number) {
  return request<PlanningSnapshot>(`/api/v2/retirement/snapshots/${id}`);
}

export function saveRetirementSnapshot(name: string, run: RetirementProjectionResult) {
  return request<PlanningSnapshot>("/api/v2/retirement/snapshots", {
    method: "POST",
    body: JSON.stringify({ name, run }),
  });
}
