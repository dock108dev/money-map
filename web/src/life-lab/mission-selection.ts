import type { LabExperimentSeedKind } from "../v2-contracts";
import type { LifeGoal, PathResult } from "./life-lab-types";

export interface LabMissionOption {
  key: string;
  kind: "work_optional" | "goal";
  label: string;
  targetAmount: number;
  targetDate: string;
  funded: boolean;
  goal: LifeGoal | null;
}

function validAmount(value: string) {
  const amount = Number(value);
  return Number.isFinite(amount) && amount >= 0 ? amount : null;
}

function validDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/u.test(value) && Number.isFinite(new Date(`${value}T12:00:00`).getTime());
}

export function availableMissionOptions(goals: LifeGoal[], path: PathResult): LabMissionOption[] {
  const options: LabMissionOption[] = [];
  const workOptionalTarget = path.make_it_happen.retirement_capital_needed === null
    ? null
    : validAmount(path.make_it_happen.retirement_capital_needed);
  const workOptionalDate = path.make_it_happen.retirement_deadline.slice(0, 10);
  if (workOptionalTarget !== null && validDate(workOptionalDate)) {
    options.push({
      key: "freedom",
      kind: "work_optional",
      label: `Age ${path.target_age} work optional · ${path.path_label}`,
      targetAmount: workOptionalTarget,
      targetDate: workOptionalDate,
      funded: workOptionalTarget === 0,
      goal: null,
    });
  }

  for (const goal of goals) {
    if (!goal.enabled || !validDate(goal.target_date)) continue;
    const target = validAmount(goal.target_amount);
    const reserved = validAmount(goal.reserved_amount);
    if (target === null || reserved === null) continue;
    const remaining = Math.max(0, target - reserved);
    options.push({
      key: `goal-${goal.id}`,
      kind: "goal",
      label: goal.name,
      targetAmount: remaining,
      targetDate: goal.target_date,
      funded: remaining === 0,
      goal,
    });
  }
  return options;
}

export function initialMissionKey({
  seedKind,
  seededGoalLabel,
  options,
}: {
  seedKind: LabExperimentSeedKind;
  seededGoalLabel: string | null;
  options: LabMissionOption[];
}) {
  if (seedKind !== "current_goal") return "";
  const unfinishedGoals = options.filter((option) => option.kind === "goal" && !option.funded && option.targetAmount > 0);
  const seededGoal = unfinishedGoals.find((option) => option.label === seededGoalLabel);
  if (seededGoal) return seededGoal.key;
  return unfinishedGoals.length === 1 ? unfinishedGoals[0].key : "";
}

export function missionSelectionContext({
  experimentId,
  experimentFingerprint,
  seedKind,
  projectionFingerprint,
  path,
  options,
}: {
  experimentId: string;
  experimentFingerprint: string;
  seedKind: LabExperimentSeedKind;
  projectionFingerprint: string;
  path: PathResult;
  options: LabMissionOption[];
}) {
  return [
    experimentId,
    experimentFingerprint,
    seedKind,
    projectionFingerprint,
    path.target_age,
    path.path_key,
    ...options.map((option) => `${option.key}:${option.targetAmount}:${option.targetDate}:${option.funded}`),
  ].join("|");
}
