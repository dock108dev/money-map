import { request } from "../api";
import type {
  IncomeBenchmarks,
  LifeGoal,
  LifeGoalInput,
  LifePlanProfile,
  LifePlanProfileInput,
  LifeProjection,
  LifeStartingPoint,
  SavedLifeScenario,
} from "./life-lab-types";
import type {
  LifeLabExperimentCreateRequest,
  LifeLabExperimentProjectRequest,
  LifeLabExperimentResult,
  LifeLabExperimentSeed,
  LifeLabPromotionApplied,
  LifeLabPromotionConfirmationRequest,
  LifeLabPromotionPreview,
  LifeLabPromotionPreviewRequest,
  RetirementProfileView,
} from "../v2-contracts";
import type { PlanningSnapshot } from "../retirement/api";

export function loadLifeProfile() {
  return request<LifePlanProfile | null>("/api/life-plan/profile");
}

export function saveLifeProfile(payload: LifePlanProfileInput) {
  return request<LifePlanProfile>("/api/life-plan/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function loadLifeStartingPoint() {
  return request<LifeStartingPoint>("/api/life-plan/starting-point");
}

export function loadIncomeBenchmarks(state?: string) {
  const query = state ? `?state=${encodeURIComponent(state)}` : "";
  return request<IncomeBenchmarks>(`/api/life-plan/benchmarks${query}`);
}

export function loadLifeGoals() {
  return request<LifeGoal[]>("/api/life-plan/goals");
}

export function addLifeGoal(payload: LifeGoalInput) {
  return request<LifeGoal>("/api/life-plan/goals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveLifeGoal(id: number, payload: LifeGoalInput) {
  return request<LifeGoal>(`/api/life-plan/goals/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteLifeGoal(id: number) {
  return request<{ deleted: boolean }>(`/api/life-plan/goals/${id}`, { method: "DELETE" });
}

export function projectLifePlan(targetAges?: number[]) {
  return request<LifeProjection>("/api/life-plan/project", {
    method: "POST",
    body: JSON.stringify({ target_ages: targetAges }),
  });
}

export function loadLifeScenarios() {
  return request<SavedLifeScenario[]>("/api/life-plan/scenarios");
}

export function saveLifeScenario(payload: { name: string; target_age: number; path_key: string }) {
  return request<SavedLifeScenario>("/api/life-plan/scenarios", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createLabExperiment(payload: LifeLabExperimentCreateRequest) {
  return request<LifeLabExperimentSeed>("/api/v2/lab/experiments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function projectLabExperiment(payload: LifeLabExperimentProjectRequest) {
  return request<LifeLabExperimentResult>("/api/v2/lab/experiments/project", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadLabSnapshots() {
  return request<PlanningSnapshot[]>("/api/v2/lab/snapshots");
}

export function openLabSnapshot(id: number) {
  return request<PlanningSnapshot>(`/api/v2/lab/snapshots/${id}`);
}

export function saveLabSnapshot(name: string, result: LifeLabExperimentResult) {
  return request<PlanningSnapshot>("/api/v2/lab/snapshots", {
    method: "POST",
    body: JSON.stringify({ name, result }),
  });
}

export function previewLabPromotion(payload: LifeLabPromotionPreviewRequest) {
  return request<LifeLabPromotionPreview>("/api/v2/lab/promotions/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function confirmLabPromotion(payload: LifeLabPromotionConfirmationRequest) {
  return request<LifeLabPromotionApplied>("/api/v2/lab/promotions/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadPrimaryPromotionGoal() {
  return request<{ state: "primary" | "no_primary"; goal: { goal_program_id: string; name: string } | null }>(
    "/api/v2/goals/primary",
  );
}

export function loadRetirementPromotionProfile() {
  return request<RetirementProfileView | null>("/api/v2/retirement/profile");
}
