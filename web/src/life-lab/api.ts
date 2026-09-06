import { request } from "../api";
import type {
  LifeLabExperimentCreateRequest,
  LifeLabExperimentProjectRequest,
  LifeLabExperimentResult,
  LifeLabExperimentSeed,
  LifeLabPromotionApplied,
  LifeLabPromotionConfirmationRequest,
  LifeLabPromotionPreview,
  LifeLabPromotionPreviewRequest,
} from "../v2-contracts";
import type { PlanningSnapshot } from "../retirement/api";

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
