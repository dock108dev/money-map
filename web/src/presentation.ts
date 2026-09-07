/** Display names only: API values and exported records keep their original identifiers. */
const labels: Record<string, string> = {
  already_migrated: "Ready to use", activation_complete: "Ready to use", fresh_setup_available: "Setup needed",
  restore_complete: "Restore complete", backup_verified: "Backup checked", recoverable_failure: "Needs attention",
  ready: "Ready", starting: "Starting", restarting: "Restarting", stopped: "Stopped", failed: "Needs attention",
  pass: "Passed", passed: "Passed", fail: "Failed", unavailable: "Not available", unknown: "Not known",
  active: "Active", complete: "Complete", pending: "Pending", needs_attention: "Needs attention",
  reconciled: "Balances match", unreconciled: "Balances need review", resolved: "Resolved", open: "Needs review",
  works: "Plan is funded", works_essentials_only: "Essential spending is funded", shortfall: "Funding shortfall",
  insufficient_accessible_bridge: "Not enough money available before retirement withdrawals",
  external_inflow: "Money received", external_outflow: "Money spent", internal_transfer: "Transfer between your accounts",
  investment_contribution: "Investment deposit", employer_contribution: "Employer contribution",
  accessible_now: "Money available now", reserved_for_goal: "Set aside for this goal",
  protected_cash_floor: "Minimum cash to keep", goal_target: "Goal amount", target_amount: "Goal amount",
  recurring_margin: "Monthly money left over", monthly_recurring_margin: "Monthly money left over",
  required_monthly_pace: "Monthly amount needed", funding_gap: "Amount still needed",
  retirement_essential_monthly_spend: "Essential monthly spending", retirement_flexible_monthly_spend: "Flexible monthly spending",
  current_goal: "Current goal", retirement_result: "Retirement result", early_crash: "Early market downturn",
  middle: "Middle path", rough: "Difficult market path", balance: "Account balance", user_entered: "Entered by you",
  observed: "From your records", assumed: "Assumption", unverified: "Not checked", stale: "Needs an update",
  incomplete: "Some data is missing", current: "Up to date", partial: "Some accounts or dates are missing",
  manual: "Entered manually", plaid: "Connected account", statement: "Statement", payroll: "Paycheck",
  credit_card: "Credit card", brokerage: "Investment account", depository: "Bank account",
  balance_reconciliation: "Balance difference", account_balance_reconciliation: "Account balance difference",
  missing_source_evidence: "More records are needed", needs_source_evidence: "More records are needed",
};

export function displayLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "Not available";
  return labels[value] ?? value.replaceAll("_", " ").replace(/\b\w/u, (letter) => letter.toUpperCase());
}

export function dataFormat(value: unknown): string {
  if (typeof value !== "string" || value === "unavailable") return "Not available";
  const revision = /^0*(\d+)_[a-z_]+$/.exec(value);
  if (revision) return `Format version ${revision[1]}`;
  return displayMessage(value).replace(/current \d+/gi, "current");
}

export function displayMessage(value: string): string {
  return value
    .replace(/source fingerprints?/gi, "source records")
    .replace(/source provenance/gi, "source details")
    .replace(/schema/gi, "data format")
    .replace(/cutover/gi, "data switch")
    .replace(/rehearsal/gi, "test copy")
    .replace(/database/gi, "saved data")
    .replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (code) => displayLabel(code))
    .replace(/^\p{Ll}/u, (letter) => letter.toUpperCase());
}
