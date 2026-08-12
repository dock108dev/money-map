import { describe, expect, it } from "vitest";

import {
  requiredCriticalEvidence,
  retiredDuplicateCopy,
  slice6StateMatrix,
} from "./test-fixtures/slice6-state-matrix";

describe("Slice 6 state-matrix contract", () => {
  it("commits every required synthetic state without duplicate labels", () => {
    expect(slice6StateMatrix.navigation).toHaveLength(6);
    expect(slice6StateMatrix.goals).toHaveLength(12);
    expect(slice6StateMatrix.retirement).toHaveLength(9);
    expect(slice6StateMatrix.lab).toHaveLength(13);
    expect(slice6StateMatrix.presentation).toHaveLength(7);
    expect(slice6StateMatrix.moneyUtilities).toHaveLength(7);
    for (const states of Object.values(slice6StateMatrix)) {
      expect(new Set(states).size).toBe(states.length);
    }
  });

  it("keeps the complete critical-evidence and retired-copy audit lists explicit", () => {
    expect(requiredCriticalEvidence).toHaveLength(14);
    expect(requiredCriticalEvidence).toContain("Retirement shortfall");
    expect(requiredCriticalEvidence).toContain("legacy combined scenario label");
    expect(retiredDuplicateCopy).toEqual(expect.arrayContaining([
      "goal_mutation=false",
      "retirement_mutation=false",
      "applied=false",
    ]));
  });
});
