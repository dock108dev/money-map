export const COPY_BUDGETS = {
  "goals-first-viewport": 55,
  "retirement-before-chart": 65,
  "lab-seed-chooser": 65,
  "lab-active-summary": 70,
  "cash-flow-first-viewport": 45,
  "wealth-hero-result": 50,
  "utility-page-heading": 20,
} as const;

export type CopyBudgetName = keyof typeof COPY_BUDGETS;

export function proseWordCount(root: ParentNode) {
  return Array.from(root.querySelectorAll<HTMLElement>("[data-prose]"))
    .map((element) => element.textContent?.trim() ?? "")
    .join(" ")
    .split(/\s+/u)
    .filter(Boolean).length;
}
