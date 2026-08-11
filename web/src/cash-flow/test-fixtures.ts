import matrix from "../../../examples/synthetic/money-map-v2.1-contracts.json";
import { validateCashFlowPeriodResult, type CashFlowPeriodResult } from "../v21-contracts";

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

export function cashFlowFixture(
  vectorId:
    | "current_relationship"
    | "trailing_transfer_heavy_zero_margin"
    | "ytd_no_activity_missing_payroll"
    | "custom_positive_period" = "current_relationship",
): CashFlowPeriodResult {
  const selected = matrix.valid_cases.find((item) => item.vector_id === vectorId);
  if (!selected) throw new Error(`Unknown fixture ${vectorId}`);
  const vector = mergePatch(matrix.base_vector, selected.patch);
  if (!isRecord(vector)) throw new Error("Fixture vector is invalid");
  return validateCashFlowPeriodResult(vector.cash_flow);
}

export function longZeroCashFlow(monthCount = 48): CashFlowPeriodResult {
  const template = cashFlowFixture("ytd_no_activity_missing_payroll");
  const start = new Date(Date.UTC(2022, 8, 1));
  const points = Array.from({ length: monthCount }, (_, index) => {
    const current = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + index, 1));
    const month = current.toISOString().slice(0, 7);
    const last = new Date(
      Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + 1, 0),
    ).getUTCDate();
    return {
      ...structuredClone(template.monthly_points[0]),
      month,
      start_date: `${month}-01`,
      end_date: `${month}-${String(last).padStart(2, "0")}`,
      partial: false,
    };
  });
  const end = points.at(-1)!.end_date;
  return validateCashFlowPeriodResult({
    ...structuredClone(template),
    period: {
      kind: "all_imported_history",
      start_date: points[0].start_date,
      end_date: end,
      as_of_date: end,
    },
    coverage: {
      ...template.coverage,
      coverage_start: points[0].start_date,
      coverage_end: end,
      opening_month: "full",
      closing_month: "full",
    },
    monthly_points: points,
  });
}
