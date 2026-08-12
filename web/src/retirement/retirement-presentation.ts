import type { PathResult } from "../life-lab/life-lab-types";
import type { RetirementProjectionResult } from "../v2-contracts";
import type { PlanningSnapshot } from "./api";

export type RetirementOutcomeKind =
  | "funded"
  | "essentials_only"
  | "pre_retirement_gap"
  | "accessible_bridge_gap"
  | "required_spending_gap"
  | "lifetime_exhaustion"
  | "unavailable";

export interface RetirementOutcomePresentation {
  kind: RetirementOutcomeKind;
  title: string;
  detail: string;
  next: string;
  tone: "works" | "essentials" | "bridge" | "shortfall" | "unavailable";
  firstUnsupportedMonth: string | null;
  endSpendableAssets: string | null;
  requiredMoneyRunwayMonths: number | null;
}

interface RetirementOutcomeEvidence {
  rawStatus: unknown;
  bridgeVerdict: unknown;
  preRetirementShortfallMonth: unknown;
  firstShortfallMonth: unknown;
  endSpendableAssets: unknown;
  requiredMoneyRunwayMonths: unknown;
}

const outcomeStatuses = new Set([
  "works",
  "works_essentials_only",
  "shortfall",
  "insufficient_accessible_bridge",
]);

function nullableDate(value: unknown) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}/u.test(value) ? value.slice(0, 10) : null;
}

function nullableMoney(value: unknown) {
  if (typeof value !== "string" || !/^-?\d+(?:\.\d+)?$/u.test(value)) return null;
  return Number.isFinite(Number(value)) ? value : null;
}

function nullableRunway(value: unknown) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function unavailable(): RetirementOutcomePresentation {
  return {
    kind: "unavailable",
    title: "Outcome unavailable",
    detail: "This result does not contain enough stored evidence to classify the plan honestly.",
    next: "Run the projection again or inspect the stored evidence.",
    tone: "unavailable",
    firstUnsupportedMonth: null,
    endSpendableAssets: null,
    requiredMoneyRunwayMonths: null,
  };
}

export function classifyRetirementEvidence(evidence: RetirementOutcomeEvidence): RetirementOutcomePresentation {
  const rawStatus = typeof evidence.rawStatus === "string" && outcomeStatuses.has(evidence.rawStatus)
    ? evidence.rawStatus
    : null;
  const bridgeVerdict = typeof evidence.bridgeVerdict === "string" && outcomeStatuses.has(evidence.bridgeVerdict)
    ? evidence.bridgeVerdict
    : null;
  const endSpendableAssets = nullableMoney(evidence.endSpendableAssets);
  if (!rawStatus || !bridgeVerdict || endSpendableAssets === null) return unavailable();

  const preRetirementShortfallMonth = nullableDate(evidence.preRetirementShortfallMonth);
  const firstShortfallMonth = nullableDate(evidence.firstShortfallMonth);
  const firstUnsupportedMonth = preRetirementShortfallMonth ?? firstShortfallMonth;
  const requiredMoneyRunwayMonths = nullableRunway(evidence.requiredMoneyRunwayMonths);
  const common = { firstUnsupportedMonth, endSpendableAssets, requiredMoneyRunwayMonths };

  if (rawStatus === "works" && bridgeVerdict === "works") {
    return {
      ...common,
      kind: "funded",
      title: "Funded through the plan",
      detail: "Essential and flexible retirement spending stays funded through the plan end.",
      next: "Save this run if you want a durable checkpoint.",
      tone: "works",
    };
  }
  if (rawStatus === "works_essentials_only" || bridgeVerdict === "works_essentials_only") {
    return {
      ...common,
      kind: "essentials_only",
      title: "Essential spending holds",
      detail: "Required spending stays funded, but flexible retirement spending fails.",
      next: "Compare another age, path, or assumption.",
      tone: "essentials",
    };
  }
  if (preRetirementShortfallMonth) {
    return {
      ...common,
      kind: "pre_retirement_gap",
      title: "Accessible cash-flow gap before work stops",
      detail: "Accessible money fails before the selected work-optional date; later assets do not repair that earlier unsupported month.",
      next: "Address the earlier cash-flow gap or compare a later work-optional date.",
      tone: "bridge",
    };
  }
  if (bridgeVerdict === "insufficient_accessible_bridge") {
    return {
      ...common,
      kind: "accessible_bridge_gap",
      title: "Accessible bridge gap after work stops",
      detail: "Accessible money fails after work stops but before retirement assets can carry the plan.",
      next: "Compare another work-optional age, path, or accessible-capital assumption.",
      tone: "bridge",
    };
  }
  if (rawStatus === "shortfall" || bridgeVerdict === "shortfall") {
    if (Number(endSpendableAssets) > 0) {
      return {
        ...common,
        kind: "required_spending_gap",
        title: "Required-spending gap with assets retained",
        detail: "Required spending fails earlier even though spendable assets remain at plan end.",
        next: "Inspect the first unsupported month before changing an assumption.",
        tone: "shortfall",
      };
    }
    return {
      ...common,
      kind: "lifetime_exhaustion",
      title: "Lifetime asset exhaustion",
      detail: "Required spending fails and spendable assets are exhausted by the plan end.",
      next: "Compare another age, path, or required-spending assumption.",
      tone: "shortfall",
    };
  }
  return unavailable();
}

export function classifyRetirementRun(run: RetirementProjectionResult): RetirementOutcomePresentation {
  const selected = run.selected_result as Partial<PathResult>;
  return classifyRetirementEvidence({
    rawStatus: selected.status,
    bridgeVerdict: run.bridge_verdict,
    preRetirementShortfallMonth: selected.make_it_happen?.pre_retirement_shortfall_month,
    firstShortfallMonth: selected.first_shortfall_month,
    endSpendableAssets: run.end_spendable_assets,
    requiredMoneyRunwayMonths: run.required_money_runway_months,
  });
}

export function classifyRetirementSnapshot(snapshot: PlanningSnapshot): RetirementOutcomePresentation {
  const summary = snapshot.summary;
  const makeItHappen = typeof summary.make_it_happen === "object" && summary.make_it_happen !== null
    ? summary.make_it_happen as Record<string, unknown>
    : {};
  const endAssets = typeof summary.end_assets === "object" && summary.end_assets !== null
    ? summary.end_assets as Record<string, unknown>
    : {};
  const lastPeriod = snapshot.periods.at(-1) ?? {};
  const firstShortfall = summary.first_shortfall_month;
  const workStop = nullableDate(summary.work_stop_month);
  const shortfall = nullableDate(firstShortfall);
  const derivedRunway = workStop && shortfall
    ? Math.max(0, (Number(shortfall.slice(0, 4)) - Number(workStop.slice(0, 4))) * 12 + Number(shortfall.slice(5, 7)) - Number(workStop.slice(5, 7)))
    : null;
  return classifyRetirementEvidence({
    rawStatus: snapshot.status,
    bridgeVerdict: snapshot.status,
    preRetirementShortfallMonth: makeItHappen.pre_retirement_shortfall_month,
    firstShortfallMonth: firstShortfall,
    endSpendableAssets: endAssets.total_spendable ?? lastPeriod.total_spendable,
    requiredMoneyRunwayMonths: derivedRunway,
  });
}
