import { useEffect, useMemo, useState } from "react";

import type {
  LifeGoal,
  LifeProjection,
  LifeStartingPoint,
  PathResult,
} from "./life-lab-types";

function currency(value: number, digits = 0) {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  });
}

function percent(value: number) {
  if (!Number.isFinite(value)) return "∞";
  return `${value.toLocaleString("en-US", { maximumFractionDigits: value < 1 ? 3 : 1 })}%`;
}

function readableDate(value: string) {
  return new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function weeksBetween(start: string, end: string) {
  const startDate = new Date(`${start.slice(0, 10)}T12:00:00`).getTime();
  const endDate = new Date(`${end.slice(0, 10)}T12:00:00`).getTime();
  if (!Number.isFinite(startDate) || !Number.isFinite(endDate)) return 1;
  return Math.max(1, Math.ceil((endDate - startDate) / (7 * 24 * 60 * 60 * 1000)));
}

function monthsBetween(start: string, end: string) {
  const from = new Date(`${start.slice(0, 10)}T12:00:00`);
  const to = new Date(`${end.slice(0, 10)}T12:00:00`);
  const months = (to.getFullYear() - from.getFullYear()) * 12 + to.getMonth() - from.getMonth();
  return Number.isFinite(months) ? Math.max(1, months) : 1;
}

export function weeklySprint(seed: number, target: number, weeks: number, weeklyPct: number) {
  const safeSeed = Math.max(0, seed);
  const safeTarget = Math.max(0, target);
  const safeWeeks = Math.max(1, weeks);
  const rate = Math.max(-99.99, weeklyPct) / 100;
  const projected = safeSeed * (1 + rate) ** safeWeeks;
  const requiredRate = safeTarget <= safeSeed
    ? 0
    : safeSeed === 0
      ? Number.POSITIVE_INFINITY
      : (safeTarget / safeSeed) ** (1 / safeWeeks) - 1;
  return {
    projected,
    required_weekly_pct: requiredRate * 100,
    assumed_annualized_pct: ((1 + rate) ** 52 - 1) * 100,
    first_week_profit: safeSeed * rate,
    gap: safeTarget - projected,
  };
}

export function exitMath(
  afterTaxTarget: number,
  ownershipPct: number,
  taxPct: number,
  revenueMultiple: number,
) {
  const retained = Math.max(0.001, ownershipPct / 100);
  const afterTaxRate = Math.max(0.001, 1 - taxPct / 100);
  const personalGross = Math.max(0, afterTaxTarget) / afterTaxRate;
  const companyExit = personalGross / retained;
  const annualRevenue = companyExit / Math.max(0.1, revenueMultiple);
  return { personalGross, companyExit, annualRevenue, monthlyRevenue: annualRevenue / 12 };
}

export function loanMath(
  eligibleVestedBalance: number,
  currentOutstanding: number,
  highestPriorBalance: number,
  annualRatePct: number,
  years: number,
) {
  const current = Math.max(0, currentOutstanding);
  const reduction = Math.max(0, highestPriorBalance - current);
  const federalDollarCap = Math.max(0, 50000 - reduction);
  const vestedCap = Math.max(0, eligibleVestedBalance) * 0.5;
  const totalPermitted = Math.min(federalDollarCap, vestedCap);
  const newLoan = Math.max(0, totalPermitted - current);
  const months = Math.max(1, Math.round(Math.max(0.25, years) * 12));
  const monthlyRate = Math.max(0, annualRatePct) / 1200;
  const payment = monthlyRate === 0
    ? newLoan / months
    : newLoan * (monthlyRate * (1 + monthlyRate) ** months) / ((1 + monthlyRate) ** months - 1);
  const roughForegoneGrowth = newLoan * ((1.04 ** Math.max(0.25, years)) - 1);
  return { newLoan, payment, roughForegoneGrowth, totalPermitted };
}

function NumberField({
  label,
  value,
  onChange,
  suffix,
  min = 0,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  suffix?: string;
  min?: number;
}) {
  return (
    <label>
      <span>{label}</span>
      <span className="drive-input-wrap">
        <input type="number" min={min} step="0.01" value={value} onChange={(event) => onChange(Number(event.target.value))} />
        {suffix && <i>{suffix}</i>}
      </span>
    </label>
  );
}

export function DriveCalculator({
  projection,
  path,
  goals,
  startingPoint,
}: {
  projection: LifeProjection;
  path: PathResult;
  goals: LifeGoal[];
  startingPoint: LifeStartingPoint;
}) {
  const [missionKey, setMissionKey] = useState("freedom");
  const [deadline, setDeadline] = useState(path.make_it_happen.retirement_deadline.slice(0, 10));
  const [seed, setSeed] = useState(5000);
  const [weeklyPct, setWeeklyPct] = useState(0.9);
  const [takeHomePct, setTakeHomePct] = useState(60);
  const [ownershipPct, setOwnershipPct] = useState(20);
  const [exitTaxPct, setExitTaxPct] = useState(30);
  const [revenueMultiple, setRevenueMultiple] = useState(6);
  const [eligibleBalance, setEligibleBalance] = useState(Number(startingPoint.pretax_retirement));
  const [loanRatePct, setLoanRatePct] = useState(8.5);
  const [loanYears, setLoanYears] = useState(5);
  const [currentLoan, setCurrentLoan] = useState(0);
  const [highestPriorLoan, setHighestPriorLoan] = useState(0);

  const selectedGoal = goals.find((goal) => missionKey === `goal-${goal.id}`) ?? null;
  const planTarget = selectedGoal
    ? Math.max(0, Number(selectedGoal.target_amount) - Number(selectedGoal.reserved_amount))
    : Number(path.make_it_happen.retirement_capital_needed ?? 0);
  const [targetAmount, setTargetAmount] = useState(planTarget);
  const defaultDeadline = selectedGoal?.target_date ?? path.make_it_happen.retirement_deadline.slice(0, 10);
  useEffect(() => setDeadline(defaultDeadline), [defaultDeadline]);
  useEffect(() => setTargetAmount(planTarget), [planTarget]);
  useEffect(() => {
    if (missionKey !== "freedom" && !selectedGoal) setMissionKey("freedom");
  }, [missionKey, selectedGoal]);

  const targetIsSolvable = selectedGoal !== null || path.make_it_happen.retirement_capital_needed !== null;
  const missionLabel = selectedGoal?.name ?? `Age ${path.target_age} work-optional capital`;
  const targetCustomized = Math.abs(targetAmount - planTarget) >= 0.5;
  const deadlineCustomized = deadline !== defaultDeadline;
  const preRetirementShortfall = path.make_it_happen.pre_retirement_shortfall_month;
  const weeks = weeksBetween(projection.as_of, deadline);
  const months = monthsBetween(projection.as_of, deadline);
  const sprint = useMemo(
    () => weeklySprint(seed, targetAmount, weeks, weeklyPct),
    [seed, targetAmount, weeks, weeklyPct],
  );
  const exit = useMemo(
    () => exitMath(targetAmount, ownershipPct, exitTaxPct, revenueMultiple),
    [targetAmount, ownershipPct, exitTaxPct, revenueMultiple],
  );
  const loan = useMemo(
    () => loanMath(eligibleBalance, currentLoan, highestPriorLoan, loanRatePct, loanYears),
    [eligibleBalance, currentLoan, highestPriorLoan, loanRatePct, loanYears],
  );
  const afterTaxMonthly = targetAmount / months;
  const grossAnnual = afterTaxMonthly * 12 / Math.max(0.01, takeHomePct / 100);
  const loanCoverage = targetAmount > 0 ? Math.min(100, loan.newLoan / targetAmount * 100) : 100;

  return (
    <section className="panel drive-panel">
      <header className="drive-heading">
        <div>
          <span className="eyebrow">Here’s what you’ve gotta do</span>
          <h2>{targetAmount === 0 && targetIsSolvable
            ? "This path is already funded."
            : targetIsSolvable ? `Build ${currency(targetAmount)} by ${readableDate(deadline)}.` : "No finite retirement target solves this path."}</h2>
          <p>{targetAmount === 0 && targetIsSolvable
            ? `${missionLabel} works under the selected assumptions. Add a dated goal if you want a bigger mission.`
            : targetIsSolvable && (targetCustomized || deadlineCustomized)
            ? `Custom math mode. The plan-calculated target is ${currency(planTarget)} by ${readableDate(defaultDeadline)}. Every route below now uses your edited number and date.`
            : targetIsSolvable
            ? `${missionLabel} needs that much additional, after-tax accessible capital at the selected work-optional date. Change any input and the math follows.`
            : "The retirement solver could not find a finite answer under these assumptions."}</p>
        </div>
        <div className="drive-mission-controls">
          <label>
            Mission
            <select value={missionKey} onChange={(event) => setMissionKey(event.target.value)}>
              <option value="freedom">Age {path.target_age} work optional · {path.path_label}</option>
              {goals.filter((goal) => goal.enabled).map((goal) => <option key={goal.id} value={`goal-${goal.id}`}>{goal.name}</option>)}
            </select>
          </label>
          <label>
            Build / exit deadline
            <input
              type="date"
              min={projection.as_of}
              value={deadline}
              onInput={(event) => setDeadline(event.currentTarget.value)}
              onChange={(event) => setDeadline(event.target.value)}
            />
          </label>
          <label>
            Capital target
            <input type="number" min="0" step="1000" value={targetAmount} onChange={(event) => setTargetAmount(Math.max(0, Number(event.target.value)))} />
          </label>
        </div>
      </header>

      {!selectedGoal && preRetirementShortfall && (
        <aside className="drive-prerequisite">
          <strong>Separate runway problem · {readableDate(preRetirementShortfall)}</strong>
          <span>Your current cash flow breaks before age {path.target_age}. That does not shorten the retirement math above. Solve it separately; the full-path recurring-income fix is {currency(Number(path.make_it_happen.additional_monthly_after_tax_income ?? 0))}/month after tax.</span>
        </aside>
      )}

      <div className="drive-routes">
        <article className="drive-route cash-route">
          <span className="route-number">01 · Earn it linearly</span>
          <h3>Bank {currency(afterTaxMonthly)}/month after tax.</h3>
          <p>Split the mission target evenly across {months} months. At a {percent(takeHomePct)} take-home rate, that is roughly <strong>{currency(grossAnnual)}/year of new gross income</strong>. Salary, consulting, sales, business cash flow—the formula does not care.</p>
          <div className="drive-fields one-field">
            <NumberField label="Take-home share" value={takeHomePct} onChange={setTakeHomePct} suffix="%" min={1} />
          </div>
        </article>

        <article className="drive-route compound-route">
          <span className="route-number">02 · Compound sprint</span>
          <h3>Turn {currency(seed)} into {currency(targetAmount)} in {weeks} weeks.</h3>
          <p>That demands <strong>{percent(sprint.required_weekly_pct)} every week</strong>. At your chosen {percent(weeklyPct)}/week, the seed reaches <strong>{currency(sprint.projected)}</strong>—{sprint.gap > 0 ? `${currency(sprint.gap)} short` : `${currency(Math.abs(sprint.gap))} over`}.</p>
          <div className="drive-fields">
            <NumberField label="Starting stake" value={seed} onChange={setSeed} suffix="$" />
            <NumberField label="Weekly compound" value={weeklyPct} onChange={setWeeklyPct} suffix="%" min={-99} />
          </div>
          <small>{percent(weeklyPct)}/week compounds to {percent(sprint.assumed_annualized_pct)}/year. Week one alone requires {currency(sprint.first_week_profit, 2)} of profit. Arithmetic, not a claim that the return is repeatable.</small>
        </article>

        <article className="drive-route exit-route">
          <span className="route-number">03 · Build it and sell it</span>
          <h3>Create a {currency(exit.companyExit)} company exit.</h3>
          <p>Build and sell by <strong>{readableDate(deadline)}</strong>. Keep {percent(ownershipPct)}, lose {percent(exitTaxPct)} of your proceeds to the tax haircut, and you net the mission capital. At {revenueMultiple.toFixed(1)}× revenue, that points to <strong>{currency(exit.annualRevenue)} ARR</strong> or {currency(exit.monthlyRevenue)}/month.</p>
          <div className="drive-fields three-fields">
            <NumberField label="Ownership at exit" value={ownershipPct} onChange={setOwnershipPct} suffix="%" min={0.1} />
            <NumberField label="Tax haircut" value={exitTaxPct} onChange={setExitTaxPct} suffix="%" />
            <NumberField label="Exit multiple" value={revenueMultiple} onChange={setRevenueMultiple} suffix="×" min={0.1} />
          </div>
          <small>The evidence gate is outside this formula: real customers, repeatable demand, credible financing, and an ownership table. This proves the required outcome size—not that investors or an exit will appear.</small>
        </article>

        <article className="drive-route loan-route">
          <span className="route-number">04 · 401(k) fuel, if the plan allows it</span>
          <h3>Federal-rule ceiling: {currency(loan.newLoan)} new cash.</h3>
          <p>At {percent(loanRatePct)} for {loanYears} years, repay about <strong>{currency(loan.payment)}/month</strong>. It closes only {percent(loanCoverage)} of this mission and carries roughly {currency(loan.roughForegoneGrowth)} of foregone 4% growth on the borrowed balance.</p>
          <div className="drive-fields three-fields">
            <NumberField label="Eligible vested balance" value={eligibleBalance} onChange={setEligibleBalance} suffix="$" />
            <NumberField label="Loan interest" value={loanRatePct} onChange={setLoanRatePct} suffix="%" />
            <NumberField label="Term" value={loanYears} onChange={setLoanYears} suffix="yr" min={0.25} />
            <NumberField label="Owed now" value={currentLoan} onChange={setCurrentLoan} suffix="$" />
            <NumberField label="Highest balance, prior 12 mo" value={highestPriorLoan} onChange={setHighestPriorLoan} suffix="$" />
          </div>
          <small>Money Map’s retirement total is not proof that the plan permits a loan or that every dollar is eligible and vested. General-purpose loans are normally limited to five years; leaving the employer can trigger a plan offset or taxable distribution. <a href="https://www.irs.gov/retirement-plans/retirement-plans-faqs-regarding-loans" target="_blank" rel="noreferrer">Current IRS boundary</a>.</small>
        </article>
      </div>
    </section>
  );
}
