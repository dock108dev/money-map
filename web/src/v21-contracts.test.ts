import { describe, expect, it } from "vitest";

import matrix from "../../examples/synthetic/money-map-v2.1-contracts.json";
import {
  candidateFixture,
  goalGapFixture,
} from "./cash-flow/goal-gap-test-fixtures";
import {
  isV21ContractVector,
  parseExactMoneyCents,
  validateCashFlowPeriodResult,
  validateGoalGapPreviewResponse,
  validateRecurringOutflowCandidateList,
  validateV21ContractVector,
} from "./v21-contracts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mergePatch(base: unknown, patch: unknown): unknown {
  if (isRecord(base) && isRecord(patch)) {
    const result: Record<string, unknown> = structuredClone(base);
    Object.entries(patch).forEach(([key, value]) => {
      result[key] = key in result ? mergePatch(result[key], value) : structuredClone(value);
    });
    return result;
  }
  return structuredClone(patch);
}

function materialize(caseValue: (typeof matrix.valid_cases)[number]): unknown {
  const payload = mergePatch(matrix.base_vector, caseValue.patch);
  if (!isRecord(payload)) throw new Error("Materialized vector must be an object");
  payload.vector_id = caseValue.vector_id;
  payload.covers = caseValue.covers;
  return payload;
}

function materializeInvalid(caseValue: (typeof matrix.invalid_cases)[number]): unknown {
  const payload = mergePatch(matrix.base_vector, caseValue.patch);
  if (!isRecord(payload)) throw new Error("Materialized vector must be an object");
  payload.vector_id = caseValue.case_id;
  payload.covers = caseValue.covers;
  return payload;
}

describe("Money Map v2.1 frontend contracts", () => {
  it("validates every executable vector and the complete state matrix", () => {
    const vectors = matrix.valid_cases.map((caseValue) =>
      validateV21ContractVector(materialize(caseValue)),
    );
    const covered = new Set(vectors.flatMap((vector) => vector.covers));
    matrix.invalid_cases.forEach((caseValue) => {
      caseValue.covers.forEach((tag) => covered.add(tag));
    });

    expect(covered).toEqual(new Set(matrix.required_states));
    expect(vectors.every((vector) => isV21ContractVector(vector))).toBe(true);
    expect(new Set(vectors.map((vector) => vector.cash_flow.period.kind))).toEqual(
      new Set(["all_imported_history", "trailing_12_months", "year_to_date", "custom_range"]),
    );
  });

  it("rejects malformed cents and monthly/summary drift", () => {
    matrix.invalid_cases.forEach((caseValue) => {
      expect(() => validateV21ContractVector(materializeInvalid(caseValue))).toThrow(
        caseValue.expected_error,
      );
    });
    ["1.0", "01.00", "$1.00", "NaN", "Infinity", "1.001", 1, 1.0].forEach((value) => {
      expect(() => parseExactMoneyCents(value)).toThrow("exact two-place decimal");
    });
  });

  it("exports the standalone Cash Flow result validator used by the API client", () => {
    const vector = validateV21ContractVector(materialize(matrix.valid_cases[0]));
    expect(validateCashFlowPeriodResult(structuredClone(vector.cash_flow))).toEqual(
      vector.cash_flow,
    );
  });

  it("keeps historical net, recurring margin, stabilization, and goal pace distinct", () => {
    const vector = validateV21ContractVector(materialize(matrix.valid_cases[0]));

    expect(vector.cash_flow.totals.net_cash_flow.amount).toBe("-805.00");
    expect(vector.recurring.current_monthly_margin.amount).toBe("-5602.98");
    expect(vector.recurring.stabilization_gap.amount).toBe("5602.98");
    expect(vector.goal.required_goal_pace.amount).toBe("39003.52");
    expect(vector.combined_monthly_improvement.amount).toBe("44606.50");
  });

  it("keeps excluded transfers auditable without counting them as cash flow", () => {
    const vector = validateV21ContractVector(materialize(matrix.valid_cases[1]));

    expect(vector.cash_flow.totals.money_in.amount).toBe("0.00");
    expect(vector.cash_flow.totals.money_out.amount).toBe("0.00");
    expect(vector.cash_flow.transfers_excluded.matched_owned_account_amount.amount).toBe(
      "10000.00",
    );
    expect(vector.cash_flow.transfers_excluded.internal_transfer_amount.amount).toBe("2000.00");
  });

  it("propagates unavailable recurring evidence only to dependent results", () => {
    const vector = validateV21ContractVector(materialize(matrix.valid_cases[2]));

    expect(vector.cash_flow.totals.net_cash_flow.amount).toBe("0.00");
    expect(vector.goal.required_goal_pace.amount).toBe("1000.00");
    expect(vector.recurring.current_monthly_margin.evidence).toBe("unavailable");
    expect(vector.combined_monthly_improvement.evidence).toBe("unavailable");
  });

  it("validates exact goal-gap preview arithmetic and gross evidence", () => {
    const result = validateGoalGapPreviewResponse(goalGapFixture());
    expect(result.state).toBe("available");
    if (result.state !== "available") throw new Error("Expected available preview");
    expect(result.baseline_combined_monthly_improvement.amount).toBe("44606.50");
    expect(result.exact_funding_months).toBe("48.000000000000");
    expect(result.gross_income_context.state).toBe("available");
  });

  it("rejects preview arithmetic drift while preserving unavailable states", () => {
    const drift = structuredClone(goalGapFixture());
    drift.remaining_combined_monthly_improvement.amount = "44606.49";
    expect(() => validateGoalGapPreviewResponse(drift)).toThrow("does not reconcile");
    expect(
      validateGoalGapPreviewResponse({
        state: "no_primary",
        observed_on: "2026-08-11",
        reason: "A primary goal has not been selected",
        warnings: [],
        calculation_version: "goal-arithmetic-v1",
        contract_version: "money-map-v2.1-contract-v1",
      }).state,
    ).toBe("no_primary");
  });

  it("validates high-confidence recurring candidates and cadence conversion", () => {
    const result = validateRecurringOutflowCandidateList(candidateFixture());
    expect(result.state).toBe("available");
    expect(result.candidates[0].typical_monthly_amount.amount).toBe("10.00");
    const drift = structuredClone(candidateFixture());
    drift.candidates[0].typical_monthly_amount.amount = "10.01";
    expect(() => validateRecurringOutflowCandidateList(drift)).toThrow(
      "does not match cadence",
    );
  });
});
