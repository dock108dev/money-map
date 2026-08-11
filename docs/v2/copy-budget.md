# Money Map v2 visible-copy budget

Status: Slice 6 product contract
Applies to: ordinary, collapsed screen states

Money Map should answer the current question before it explains the evidence. Each primary surface follows one order: page name, current result, next action, controls that change the result, then evidence or history behind a disclosure.

## Ordinary-state rules

- Use one page headline.
- Use at most one short purpose sentence.
- Use one verdict sentence and one next-step sentence.
- Keep metric labels to five words or fewer where practical.
- Keep status messages to approximately 18 words or fewer.
- Do not explain one concept twice in the same ordinary view.
- Keep full assumptions, formulas, provenance, historical context, and caveats available in evidence or details.
- Keep critical warnings visible and concise. Critical warnings are exempt from the prose budget.

## Practical limits

| Surface | Maximum ordinary prose words |
| --- | ---: |
| Goals first viewport | 55 |
| Retirement result before chart | 65 |
| Lab seed chooser | 65 |
| Lab active-result summary | 70 |
| Cash Flow first viewport | 45 |
| Wealth hero and first result | 50 |
| Utility page heading | 20 |

The count excludes user-provided names, numeric values, form labels, control labels, metric labels, and expanded evidence. The frontend marks budgeted surfaces with `data-copy-budget` and the ordinary prose within them with `data-prose`; semantic tests count only those prose nodes. This keeps tests tied to meaning instead of the whole rendered document or a particular pixel layout.

## Evidence and exceptions

Concise screen copy never removes exact evidence. Assumptions, formulas, fingerprints, warnings, provenance, older observations, and stored snapshots remain reachable through named disclosures and are expanded or represented in print. Failed or partial refresh, stale sources, missing evidence, floor breaches, negative cash flow, expired pace, completed goals, Retirement failures, unavailable performance, promotion conflicts, and legacy labels remain textual in the ordinary or collapsed state where they matter.
