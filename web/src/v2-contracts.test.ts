import { describe, expect, it } from "vitest";

import {
  isEvidencedMoney,
  isExactDecimalString,
  type EvidencedMoney,
  type LifeLabExperimentSeed,
  type LifeLabPromotionPreview,
  type PrimaryGoalProgram,
  type RetirementRunSelection,
} from "./v2-contracts";

const enteredMoney = (amount: `${number}.${number}${number}`, source: string): EvidencedMoney => ({
  amount,
  evidence: "user_entered",
  source_refs: [source],
  derivation: null,
  unavailable_reason: null,
});

describe("Money Map v2 frontend contracts", () => {
  it("keeps exact money separate from formatted display copy", () => {
    expect(isExactDecimalString("14000.00")).toBe(true);
    expect(isExactDecimalString("$14,000.00")).toBe(false);
    expect(
      isEvidencedMoney({
        amount: "14000.00",
        evidence: "user_entered",
        source_refs: ["goal:target"],
        derivation: null,
        unavailable_reason: null,
      }),
    ).toBe(true);
    expect(
      isEvidencedMoney({
        amount: null,
        evidence: "observed",
        source_refs: [],
        derivation: null,
        unavailable_reason: null,
      }),
    ).toBe(false);
  });

  it("types the exclusive primary-goal policy", () => {
    const program = {
      goal_program_id: "goal_home",
      name: "Synthetic home reserve",
      target_date: "2027-08-09",
      target_amount: enteredMoney("14000.00", "goal:target"),
      protected_cash_floor: enteredMoney("3000.00", "goal:floor"),
      reserved_for_goal: enteredMoney("2000.00", "goal:reserved"),
      primary: true,
      reservation_policy: "exclusive_primary_goal",
      source_life_goal_id: 1,
    } satisfies PrimaryGoalProgram;

    expect(program.primary).toBe(true);
    expect(program.reservation_policy).toBe("exclusive_primary_goal");
  });

  it("keeps retirement selection and Lab editing non-mutating", () => {
    const retirement = {
      run_selection_id: "retirement_baseline",
      include_operational_goal: false,
      included_goal: null,
      goal_default_policy: "excluded",
      operational_goal_mutation: false,
    } satisfies RetirementRunSelection;
    const lab = {
      experiment_id: "lab_blank",
      seed_kind: "blank",
      source_fingerprint: null,
      seeded_money: {},
      edit_scope: "isolated_draft",
      goal_mutation: false,
      retirement_mutation: false,
    } satisfies LifeLabExperimentSeed;
    const preview = {
      experiment_id: "lab_synthetic",
      experiment_fingerprint: "a".repeat(64),
      target_surface: "goals",
      changes: [
        {
          field: "goal_target",
          before: enteredMoney("14000.00", "goal:target"),
          after: enteredMoney("15000.00", "lab:goal_target"),
        },
      ],
      state: "preview_only",
      requires_explicit_confirmation: true,
      applied: false,
    } satisfies LifeLabPromotionPreview;

    expect(retirement.operational_goal_mutation).toBe(false);
    expect(lab.goal_mutation).toBe(false);
    expect(preview.applied).toBe(false);
  });
});
