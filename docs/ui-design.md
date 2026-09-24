# Money Map UI design

Updated September 23, 2026. Shared Glass UI Starter 02 clarity adaptation; presentation-only adoption.

## For future contributors

Start with the [local design requirements](ui-design-requirements.md) and the repository’s own styles. These preserve the adopted Glass UI Starter 02 baseline. The original shared Desktop gallery is not present in this workspace and is not required to build or run the app.

Use light cool glass, slate text, blue actions, restrained depth, rounded controls, and system typography as the default. Do not reintroduce the generic beige/green/yellow template. Preserve explicit semantic success, caution, error, unavailable, and unknown states. Readability and the task's layout outrank decoration.

Project assets are checked in locally. Use the local requirements and implementation as the available design reference; adopt future template revisions deliberately.

## This project's adaptation

App shell, sidebar, panels, forms, and planning surfaces use the cool palette and system typography. Existing print styles are preserved. Financial calculations, source meaning, and persistence are unchanged. This source update does not replace or qualify an installed/signed desktop build.

Implementation: web/src/styles/glass.css; styles.css; supporting screen styles.

## Review and status

See [UI adoption verification](ui-verification.md). Source changes and technical/visual checks do not establish owner acceptance, a new release, live-data qualification, or acceptance of an older frozen candidate. Existing project-specific gates remain separate.

## Starter 02 clarity pass — September 23, 2026

Working source now adapts Starter 02's task-first guidance: compact headings, readable Cash Flow and goal labels, plain Life Lab wording, and Housing Move actions/results before its long form. Housing unknowns, assumptions, reserve consequences and funding needs remain visible; detailed comparisons expand on demand. Full-size controls and the glass palette remain. Existing calculation, persistence and release boundaries are unchanged. See the matched synthetic review in [UI verification](ui-verification.md#clarity-pass--september-23-2026).
