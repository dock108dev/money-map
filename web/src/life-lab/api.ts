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
