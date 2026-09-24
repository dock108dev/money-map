# Glass UI adoption verification

September 21, 2026 · source implementation and engineering review only.

Frontend production build passed; 18 frontend test files / 230 tests passed. Browser review uses existing synthetic test fixtures with every API request intercepted. Cash Flow was inspected at 1440px and 390px. No private financial database, account, or installed application was accessed.

## Retained review

The shared review gallery (`review.html` in `/Users/michaelfuscoletti/Desktop/ui-templates` on the owner’s Mac; not included in this repository) contains screenshots and browser check results. Browser specimens are local fixtures or isolated startup states. Web review checked representative 1440px/390px layouts, page exceptions, and page-level horizontal overflow; it is not an exhaustive audit of every state, contrast pair, screen reader, browser, installed build, or physical phone.

Template gallery search, form submit feedback, dialog opening, and Escape dismissal were exercised. Shared styles include keyboard focus, reduced-motion, and reduced-transparency handling. Native Godot is a basic translucent fallback, not a true blur material. Native games retain their desktop layout and illustrated artwork.

See [design and future template use](ui-design.md). No owner acceptance or release qualification is inferred. Rebuild/relaunch the appropriate source application to see the change; installed or frozen copies remain their original versions.

## Clarity pass — September 23, 2026

The September 21 screenshots above are historical. This pass captured the active React app before and after editing, with identical synthetic fixtures and 1440×900 / 390×900 viewports. All API requests were intercepted; no backend, owner database, provider, Keychain or installed app was used. Fixtures came from current frontend tests and the housing engine's synthetic test case. Existing documentation edits and frozen builds were preserved.

Review captures and measurement logs are local-only artifacts under `docs/review/clarity/`, intentionally excluded from Git. They are not included in a fresh checkout or CI; the filenames below identify the original local review evidence.

| Matched screen | Before → after observation | Local screenshot filenames |
| --- | --- | --- |
| Housing, desktop | Calculate starts at y=1584 → 329; results at y=1697 → 438. Key warnings and funding remain visible; full comparisons use one disclosure. | `before-housing-1440.png`, `after-housing-1440.png` |
| Housing, narrow | Calculate y=2824 → 420; results y=3012 → 609. Page overflow removed; expanded tables have keyboard-accessible horizontal scrolling. | `before-housing-390.png`, `after-housing-390.png` |
| Cash Flow, narrow | Metrics y=309 → 302. Labels increase from 9–11px to 14px; page becomes taller (1131 → 1270px) to preserve readability. | `before-cash-flow-390.png`, `after-cash-flow-390.png` |
| Life Lab, narrow | Page height 1045 → 981px. “Seed” becomes “starting point”; the copy explains that experiments leave the original plan unchanged. | `before-lab-390.png`, `after-lab-390.png` |

Cash Flow, Housing, Accounts, Goals, Retirement and Lab had no page overflow at either normal viewport and no browser exceptions. Housing empty/saved/error/busy/dirty states, discard, disabled setup explanations, Cash Flow error/retry/custom-date validation, keyboard disclosure activation and visible focus were exercised. Print events open the new disclosure and restore it afterward. Local logs: `states.json` (state checks), `before.json` and `after.json` (measurements).

Desktop at 200% CSS scale had no page overflow; this is a layout stress check, not native browser zoom or VoiceOver qualification. At 390px with 200% CSS scale, all six screens overflow: the existing 320px minimum body width exceeds the effective viewport. No claim of full accessibility conformance, every screen/state, installed runtime, owner acceptance or release qualification.

At the time of this local review, with local artifacts present, the complete source gate passed: 580 Python tests, one existing opt-in restored-copy drill skipped, 230 frontend tests, production build, TypeScript, Ruff, mypy (116 files), documentation links and private-data checks. Final presentation adjustments were followed by another frontend build/test run and matched browser checks. Native checks were not run because native code and packaging were unchanged.

Separate follow-ups, not implemented:
- Housing saved baselines stay dated after new imports (confirmed in source and tracker). A refresh comparison changes behavior/data rules; next action is the tracker's B1 implementation packet.
- Minimum-width/large-scale behavior needs a focused accessibility pass across the shared shell and all forms, rather than removing the minimum blindly. Reproduce browser-native zoom before choosing a supported reflow target.
