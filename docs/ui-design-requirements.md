# Money Map UI design requirements

## Start with the task

Each screen should make its purpose, current result or state, and next useful action easy to find. The default is one compact heading, useful content, and a clear action. Add descriptions, panels, and statuses only when they help a decision.

- Use familiar words and sentence case. “Save goal” is clearer than “Plan action”. Explain blocked actions in terms of what the player or user can do next.
- Keep useful labels, units, dates and status distinctions. “Monthly contribution” is clearer than “Amount”.
- Remove repeated titles, filler, decorative category labels, and explanations of obvious controls. Keep teaching, narrative, and consequential explanations that serve the product.
- Show the result or working area early. Prefer compact rows for comparisons and related facts together. Keep controls close to their result. Do not force every value into its own card.
- Put advanced setup, full history, technical identifiers, and lengthy explanations behind named secondary controls. Keep current blockers, meaningful uncertainty, freshness, costs, and destructive consequences visible where they matter.
- Preserve stop, cancel, recovery, and confirmation behavior. Do not replace scrolling with extra steps, nested scrolling, or a maze of tabs and dialogs.

## Appearance and accessibility

Retain the cool, light glass direction: system typography, slate text, blue actions, restrained translucency and depth. Use `web/src/styles/glass.css` for the implemented theme.

Default body text is 16px on the web; primary controls are at least 44px high. Use compact spacing, not tiny type or cramped targets. Compact headers replace giant hero sections. Avoid widespread uppercase, widely spaced labels, and pills for ordinary information.

Blue indicates action or selection. Success, caution, and errors have meaningful text as well as color. Preserve negative, zero, unknown, stale, and unavailable states. Essential information must not depend on an unexplained icon, clipped text, color, or hover alone.

Use native semantics, clear labels, visible focus, logical keyboard order, and dialogs that return focus. Maintain readable contrast: at least 4.5:1 for ordinary text and 3:1 for meaningful control boundaries and large text. Check composited colors on translucent surfaces. Respect reduced motion and transparency; supply an opaque fallback.

## Before calling a screen improved

Compare representative before/after states at the same viewport and with the same data. Inspect desktop and narrow sizes the product supports; use real supported window sizes for games. Check increased text scale, long content, keyboard access, disclosures, and empty/error/disabled states relevant to the change.

Confirm the important result and action are easier to find without losing meaning or adding routine task steps. Word counts and pixel measurements support the review; they do not establish usability by themselves.

Keep design guidance consistent with the implementation. Preserve data contracts, calculations, permissions, persistence and game rules.
