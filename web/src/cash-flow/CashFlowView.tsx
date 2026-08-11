import { useCallback, useEffect, useRef, useState } from "react";

import {
  CashFlowApiError,
  CashFlowUnavailableError,
  CashFlowValidationError,
  loadCashFlow,
  previewGoalGap,
  type CashFlowRequest,
} from "../api";
import {
  parseExactMoneyCents,
  type CashFlowPeriodResult,
  type GoalGapPreviewResponse,
  type MonthlyCashFlowPoint,
} from "../v21-contracts";
import GoalGapCard from "./GoalGapCard";
import "./cash-flow.css";

type PeriodChoice = "all" | "trailing" | "year" | "prior" | "custom";

interface PeriodSelection {
  choice: PeriodChoice;
  request: CashFlowRequest;
}

interface ActivityPeriod {
  startDate: string;
  endDate: string;
}

interface CashFlowViewProps {
  netWorth: string | null;
  reloadVersion: number;
  onShowActivity: (period: ActivityPeriod) => void;
  onShowAccounts: () => void;
  onShowIncome: () => void;
  onShowWealth: () => void;
  onShowGoals: () => void;
}

type RecurringPattern =
  | { state: "available"; kind: "gap" | "margin"; cents: bigint }
  | { state: "unavailable"; reason: string };

const ALL_SELECTION: PeriodSelection = {
  choice: "all",
  request: { periodKind: "all_imported_history" },
};

const PERIODS: Array<{ choice: PeriodChoice; label: string }> = [
  { choice: "all", label: "All" },
  { choice: "trailing", label: "Last 12 months" },
  { choice: "year", label: "Year to date" },
  { choice: "prior", label: "Prior year" },
  { choice: "custom", label: "Custom range" },
];

function groupDigits(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/gu, ",");
}

function formatCents(cents: bigint, signed = false): string {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const dollars = groupDigits((absolute / 100n).toString());
  const remainder = (absolute % 100n).toString().padStart(2, "0");
  const sign = negative ? "−" : signed && cents > 0n ? "+" : "";
  return `${sign}$${dollars}.${remainder}`;
}

function formatExactMoney(value: string, signed = false): string {
  return formatCents(parseExactMoneyCents(value), signed);
}

function availableAmount(value: { amount: string | null }, label: string): string {
  if (value.amount === null) throw new Error(`${label} is unavailable`);
  return value.amount;
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function monthLabel(point: MonthlyCashFlowPoint): string {
  const label = new Intl.DateTimeFormat("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${point.month}-01T00:00:00Z`));
  return point.partial ? `${label} (partial)` : label;
}

function freshnessTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function netContext(value: string): "positive" | "negative" | "even" {
  const cents = parseExactMoneyCents(value);
  return cents > 0n ? "positive" : cents < 0n ? "negative" : "even";
}

function recurringPattern(state: GoalGapPreviewResponse): RecurringPattern {
  if (state.state !== "available") {
    return { state: "unavailable", reason: "No primary goal supplies recurring evidence." };
  }
  const recurring = state.baseline_current_recurring_facts;
  const margin = recurring.current_monthly_margin;
  if (margin.amount === null) {
    return {
      state: "unavailable",
      reason: margin.unavailable_reason ?? "The recurring cash-flow pattern is unavailable.",
    };
  }
  const marginCents = parseExactMoneyCents(margin.amount);
  return marginCents < 0n
    ? { state: "available", kind: "gap", cents: -marginCents }
    : { state: "available", kind: "margin", cents: marginCents };
}

function requestError(reason: unknown): string {
  if (reason instanceof CashFlowUnavailableError) return `Cash Flow unavailable: ${reason.reason}`;
  if (reason instanceof CashFlowValidationError) return `Period not available: ${reason.message}`;
  if (reason instanceof CashFlowApiError) return `${reason.message} Try again.`;
  return reason instanceof Error ? `${reason.message} Try again.` : "Cash Flow could not load. Try again.";
}

function selectionFor(choice: Exclude<PeriodChoice, "prior" | "custom">): PeriodSelection {
  return {
    choice,
    request: {
      periodKind:
        choice === "all"
          ? "all_imported_history"
          : choice === "trailing"
            ? "trailing_12_months"
            : "year_to_date",
    },
  };
}

function priorYearSelection(asOfDate: string): PeriodSelection {
  const year = Number(asOfDate.slice(0, 4)) - 1;
  return {
    choice: "prior",
    request: {
      periodKind: "custom_range",
      startDate: `${year}-01-01`,
      endDate: `${year}-12-31`,
    },
  };
}

function CashFlowChart({ result }: { result: CashFlowPeriodResult }) {
  const points = result.monthly_points;
  const values = points.flatMap((point) => [
    parseExactMoneyCents(availableAmount(point.amounts.money_in, "money in")),
    parseExactMoneyCents(availableAmount(point.amounts.money_out, "money out")),
  ]);
  const maxCents = values.reduce((maximum, value) => (value > maximum ? value : maximum), 0n);
  const chartLeft = 42;
  const chartRight = 984;
  const chartTop = 12;
  const baseline = 184;
  const chartHeight = baseline - chartTop;
  const groupWidth = (chartRight - chartLeft) / points.length;
  const barWidth = Math.max(2, Math.min(13, groupWidth * 0.28));
  const labelEvery = Math.max(1, Math.ceil(points.length / 12));
  const finalLabelClearance = Math.max(1, Math.ceil(34 / groupWidth));
  const heightFor = (cents: bigint) => {
    if (maxCents === 0n || cents === 0n) return 0;
    const ratio = Number((cents * 10_000n) / maxCents) / 10_000;
    return Math.max(1, ratio * chartHeight);
  };
  const totalIn = availableAmount(result.totals.money_in, "money in");
  const totalOut = availableAmount(result.totals.money_out, "money out");
  const net = availableAmount(result.totals.net_cash_flow, "net cash flow");
  const description = `${dateLabel(result.period.start_date)} through ${dateLabel(result.period.end_date)}. Money in ${formatExactMoney(totalIn)}, money out ${formatExactMoney(totalOut)}, ${netContext(net)} net ${formatExactMoney(net, true)}.`;

  return (
    <section className="cash-flow-chart-panel" aria-labelledby="cash-flow-chart-heading">
      <div className="cash-flow-chart-heading">
        <h2 id="cash-flow-chart-heading">Monthly money in and out</h2>
        <div className="cash-flow-legend" aria-label="Chart legend">
          <span><i className="legend-in" aria-hidden="true" />Money in</span>
          <span><i className="legend-out" aria-hidden="true" />Money out</span>
        </div>
      </div>
      <svg
        className="cash-flow-chart"
        viewBox="0 0 1000 220"
        role="img"
        aria-labelledby="cash-flow-chart-title cash-flow-chart-description"
        preserveAspectRatio="none"
      >
        <title id="cash-flow-chart-title">Monthly money in compared with money out</title>
        <desc id="cash-flow-chart-description">{description} Exact monthly values follow in the Cash Flow evidence table.</desc>
        <defs>
          <pattern id="cash-flow-out-pattern" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" fill="#d9b18e" />
            <line x1="0" y1="0" x2="0" y2="7" stroke="#604a37" strokeWidth="2" />
          </pattern>
        </defs>
        <line className="cash-flow-zero-line" x1={chartLeft} x2={chartRight} y1={baseline} y2={baseline} />
        {points.map((point, index) => {
          const moneyIn = parseExactMoneyCents(availableAmount(point.amounts.money_in, "money in"));
          const moneyOut = parseExactMoneyCents(availableAmount(point.amounts.money_out, "money out"));
          const inHeight = heightFor(moneyIn);
          const outHeight = heightFor(moneyOut);
          const center = chartLeft + groupWidth * index + groupWidth / 2;
          const showLabel =
            index === points.length - 1 ||
            (index % labelEvery === 0 && index < points.length - 1 - finalLabelClearance);
          return (
            <g key={`${point.month}-${point.start_date}`} data-month={point.month}>
              <title>{`${monthLabel(point)}: money in ${formatCents(moneyIn)}, money out ${formatCents(moneyOut)}`}</title>
              <rect className="cash-flow-bar-in" x={center - barWidth - 1} y={baseline - inHeight} width={barWidth} height={inHeight} />
              <rect className="cash-flow-bar-out" x={center + 1} y={baseline - outHeight} width={barWidth} height={outHeight} />
              {showLabel && (
                <text className="cash-flow-axis-label" x={center} y={207} textAnchor="middle">
                  {point.month.slice(5, 7)}/{point.month.slice(2, 4)}{point.partial ? "*" : ""}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <p className="cash-flow-chart-summary sr-only">{description}</p>
    </section>
  );
}

export default function CashFlowView({
  netWorth,
  reloadVersion,
  onShowActivity,
  onShowAccounts,
  onShowIncome,
  onShowWealth,
  onShowGoals,
}: CashFlowViewProps) {
  const [result, setResult] = useState<CashFlowPeriodResult | null>(null);
  const [activeSelection, setActiveSelection] = useState<PeriodSelection>(ALL_SELECTION);
  const activeSelectionRef = useRef<PeriodSelection>(ALL_SELECTION);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastAttempt, setLastAttempt] = useState<PeriodSelection>(ALL_SELECTION);
  const [customOpen, setCustomOpen] = useState(false);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [liveMessage, setLiveMessage] = useState("");
  const [pattern, setPattern] = useState<RecurringPattern>({
    state: "unavailable",
    reason: "Recurring evidence is loading.",
  });
  const [goalGap, setGoalGap] = useState<GoalGapPreviewResponse | null>(null);
  const [goalGapError, setGoalGapError] = useState("");
  const requestSequence = useRef(0);

  const requestPeriod = useCallback(async (selection: PeriodSelection) => {
    const sequence = ++requestSequence.current;
    setLastAttempt(selection);
    setLoading(true);
    setError("");
    try {
      const next = await loadCashFlow(selection.request);
      if (sequence !== requestSequence.current) return;
      setResult(next);
      setActiveSelection(selection);
      activeSelectionRef.current = selection;
      setCustomStart((current) => current || next.period.start_date);
      setCustomEnd((current) => current || next.period.end_date);
      setLiveMessage(`Cash Flow updated for ${dateLabel(next.period.start_date)} through ${dateLabel(next.period.end_date)}.`);
    } catch (reason) {
      if (sequence !== requestSequence.current) return;
      setError(requestError(reason));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void requestPeriod(activeSelectionRef.current);
  }, [reloadVersion, requestPeriod]);

  useEffect(() => {
    let current = true;
    setGoalGapError("");
    void previewGoalGap({
      target_date: null,
      additional_reservation: "0.00",
      monthly_spending_reduction: "0.00",
      monthly_after_tax_income: "0.00",
    })
      .then((state) => {
        if (current) {
          setGoalGap(state);
          setPattern(recurringPattern(state));
        }
      })
      .catch((reason: unknown) => {
        if (!current) return;
        const message = reason instanceof Error ? reason.message : "Goal impact could not load.";
        setGoalGapError(message);
        setPattern({
          state: "unavailable",
          reason: message,
        });
      });
    return () => {
      current = false;
    };
  }, [reloadVersion]);

  const choosePreset = (choice: PeriodChoice) => {
    if (choice === "custom") {
      setCustomOpen(true);
      return;
    }
    if (choice === "prior") {
      if (result) void requestPeriod(priorYearSelection(result.period.as_of_date));
      return;
    }
    void requestPeriod(selectionFor(choice));
  };

  const applyCustom = () => {
    const asOf = result?.period.as_of_date;
    if (!customStart || !customEnd) {
      setError("Choose both inclusive custom dates.");
      return;
    }
    if (customStart > customEnd) {
      setError("Custom start must be on or before custom end.");
      return;
    }
    if (asOf && customEnd > asOf) {
      setError(`Custom end must be on or before ${dateLabel(asOf)}.`);
      return;
    }
    void requestPeriod({
      choice: "custom",
      request: { periodKind: "custom_range", startDate: customStart, endDate: customEnd },
    });
  };

  const totalIn = result ? availableAmount(result.totals.money_in, "money in") : null;
  const totalOut = result ? availableAmount(result.totals.money_out, "money out") : null;
  const totalNet = result ? availableAmount(result.totals.net_cash_flow, "net cash flow") : null;

  return (
    <div className="cash-flow-view" data-responsive-surface="cash-flow">
      <section className="cash-flow-first-viewport" data-copy-budget="cash-flow-first-viewport">
        <header className="cash-flow-title">
          <div>
            <span className="eyebrow">Selected cash activity</span>
            <h1 data-prose>Cash Flow</h1>
            {result && (
              <p className="cash-flow-coverage">
                <strong>{activeSelection.choice === "all" ? "All imported history" : PERIODS.find((period) => period.choice === activeSelection.choice)?.label}</strong>
                <span>{dateLabel(result.period.start_date)} through {dateLabel(result.period.end_date)} · inclusive</span>
              </p>
            )}
          </div>
          <div className="cash-flow-title-actions">
            {loading && <span className="cash-flow-busy" role="status">Updating Cash Flow…</span>}
            <button type="button" className="cash-flow-print" onClick={() => window.print()}>
              Print evidence
            </button>
          </div>
        </header>

        <div className="cash-flow-periods" role="group" aria-label="Cash Flow period">
          {PERIODS.map((period) => (
            <button
              type="button"
              key={period.choice}
              className={activeSelection.choice === period.choice ? "active" : ""}
              aria-pressed={activeSelection.choice === period.choice}
              disabled={loading && result === null || period.choice === "prior" && result === null}
              onClick={() => choosePreset(period.choice)}
            >
              {period.label}
            </button>
          ))}
        </div>

        {customOpen && (
          <div className="cash-flow-custom" aria-label="Custom Cash Flow range">
            <label>From<input type="date" value={customStart} max={customEnd || result?.period.as_of_date} onChange={(event) => setCustomStart(event.currentTarget.value)} onInput={(event) => setCustomStart(event.currentTarget.value)} /></label>
            <label>Through<input type="date" value={customEnd} min={customStart || undefined} max={result?.period.as_of_date} onChange={(event) => setCustomEnd(event.currentTarget.value)} onInput={(event) => setCustomEnd(event.currentTarget.value)} /></label>
            <button type="button" onClick={applyCustom}>Apply range</button>
            <button type="button" className="cash-flow-custom-close" onClick={() => setCustomOpen(false)} aria-label="Close custom range">×</button>
          </div>
        )}

        {error && (
          <div className="cash-flow-error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => void requestPeriod(lastAttempt)}>Retry</button>
          </div>
        )}

        {result && totalIn && totalOut && totalNet ? (
          <>
            <div className="cash-flow-metrics" aria-live="off">
              <article><span>Money in</span><strong>{formatExactMoney(totalIn)}</strong></article>
              <article><span>Money out</span><strong>{formatExactMoney(totalOut)}</strong></article>
              <article className={`cash-flow-net net-${netContext(totalNet)}`}>
                <span>Net</span>
                <strong>{formatExactMoney(totalNet, true)}</strong>
                <small>{netContext(totalNet)} net cash flow</small>
              </article>
            </div>
            {netWorth && <p className="cash-flow-net-worth">Net worth <strong>{formatExactMoney(netWorth)}</strong></p>}
            <CashFlowChart result={result} />
            <div className="cash-flow-current-answer">
              <strong>
                {pattern.state === "available"
                  ? `Current monthly ${pattern.kind}: ${formatCents(pattern.cents)}`
                  : "Current monthly pattern unavailable"}
              </strong>
              <span className={`freshness freshness-${result.freshness.state}`}>
                Evidence {result.freshness.state} as of {freshnessTime(result.freshness.observed_at)} · {result.coverage.completeness} coverage
              </span>
            </div>
            <GoalGapCard result={goalGap} error={goalGapError} onOpenGoals={onShowGoals} />
          </>
        ) : !loading ? (
          <div className="cash-flow-empty" role="status">No Cash Flow result is available. Use Retry after activity evidence is imported.</div>
        ) : null}
        <span className="sr-only" aria-live="polite" aria-atomic="true">{liveMessage}</span>
      </section>

      {result && (
        <>
          <section className="cash-flow-destinations" aria-label="Cash Flow supporting destinations">
            <button type="button" onClick={() => onShowActivity({ startDate: result.period.start_date, endDate: result.period.end_date })}><strong>Activity</strong><span>Transactions for this period</span></button>
            <button type="button" onClick={onShowAccounts}><strong>Accounts</strong><span>Balances and sources</span></button>
            <button type="button" onClick={onShowIncome}><strong>Income</strong><span>Payroll evidence</span></button>
            <button type="button" onClick={onShowWealth}><strong>Wealth</strong><span>Net worth and performance</span></button>
          </section>

          <p className="print-only print-evidence-header" aria-hidden="true">
            Cash Flow evidence · {result.period.start_date} through {result.period.end_date} · observed {result.freshness.observed_at}
          </p>
          <details className="cash-flow-evidence" data-print-evidence="cash-flow">
            <summary>Cash Flow evidence</summary>
            <div className="cash-flow-evidence-body">
              <dl className="cash-flow-evidence-grid">
                <div><dt>Selected boundaries</dt><dd>{result.period.start_date} through {result.period.end_date}, inclusive</dd></div>
                <div><dt>Transaction count</dt><dd>{result.coverage.transaction_count}</dd></div>
                <div><dt>External inflows</dt><dd>{formatExactMoney(availableAmount(result.totals.external_cash_inflows, "external inflows"))}</dd></div>
                <div><dt>Interest</dt><dd>{formatExactMoney(availableAmount(result.totals.interest_received, "interest"))}</dd></div>
                <div><dt>External outflows</dt><dd>{formatExactMoney(availableAmount(result.totals.external_cash_outflows, "external outflows"))}</dd></div>
                <div><dt>Fees</dt><dd>{formatExactMoney(availableAmount(result.totals.fees_paid, "fees"))}</dd></div>
                <div><dt>Matched owned transfers</dt><dd>{formatExactMoney(availableAmount(result.transfers_excluded.matched_owned_account_amount, "matched transfers"))} · {result.transfers_excluded.matched_owned_account_count} transactions</dd></div>
                <div><dt>Internal transfers</dt><dd>{formatExactMoney(availableAmount(result.transfers_excluded.internal_transfer_amount, "internal transfers"))} · {result.transfers_excluded.internal_transfer_count} transactions</dd></div>
                <div><dt>Coverage</dt><dd>{result.coverage.completeness} · {result.coverage.coverage_start} through {result.coverage.coverage_end}</dd></div>
                <div><dt>Incomplete reasons</dt><dd>{result.coverage.incomplete_reasons.length ? result.coverage.incomplete_reasons.join("; ") : "None"}</dd></div>
                <div><dt>Freshness time</dt><dd>{result.freshness.observed_at}</dd></div>
                <div><dt>Stale sources</dt><dd>{result.freshness.stale_sources.length ? result.freshness.stale_sources.join("; ") : "None"}</dd></div>
                <div><dt>Warnings</dt><dd>{[...result.freshness.warnings, ...result.warnings].length ? [...result.freshness.warnings, ...result.warnings].join("; ") : "None"}</dd></div>
                {pattern.state === "unavailable" && <div><dt>Recurring pattern</dt><dd>{pattern.reason}</dd></div>}
              </dl>
              <div className="cash-flow-table-wrap">
                <table aria-label="Exact monthly Cash Flow values">
                  <caption>Exact month-by-month evidence</caption>
                  <thead><tr><th>Month</th><th>Coverage</th><th>Transactions</th><th>Money in</th><th>Money out</th><th>Net</th></tr></thead>
                  <tbody>
                    {result.monthly_points.map((point) => (
                      <tr key={`${point.month}-${point.start_date}`}>
                        <th scope="row">{monthLabel(point)}</th>
                        <td>{point.start_date} through {point.end_date}</td>
                        <td>{point.transaction_count}</td>
                        <td>{formatExactMoney(availableAmount(point.amounts.money_in, "money in"))}</td>
                        <td>{formatExactMoney(availableAmount(point.amounts.money_out, "money out"))}</td>
                        <td>{formatExactMoney(availableAmount(point.amounts.net_cash_flow, "net cash flow"), true)} · {netContext(availableAmount(point.amounts.net_cash_flow, "net cash flow"))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
