# Money Map UI design

Updated September 21, 2026. Shared Glass UI Starter 01; presentation-only adoption.

## For future contributors

Start with [local design requirements](ui-design-requirements.md), then review the shared UI Templates gallery (`index.html`) and template guide (`README.md`), if available locally. The source folder on the owner's Mac is `/Users/michaelfuscoletti/Desktop/UI Templates`. It contains dashboard, list/table, form/setup, settings, detail, state/dialog, and native Godot starters.

Use light cool glass, slate text, blue actions, restrained depth, rounded controls, and system typography as the default. Do not reintroduce the generic beige/green/yellow template. Preserve explicit semantic success, caution, error, unavailable, and unknown states. Readability and the task's layout outrank decoration.

The shared folder is a design reference, not a runtime dependency. Project assets are checked in locally and can run without the Desktop folder. If you receive this repository alone, this local requirements copy and the implementation describe the baseline. Request the source template folder when you need the full gallery. Template revisions are adopted deliberately, never silently synchronized.

## This project's adaptation

App shell, sidebar, panels, forms, and planning surfaces use the cool palette and system typography. Existing print styles are preserved. Financial calculations, source meaning, and persistence are unchanged. This source update does not replace or qualify an installed/signed desktop build.

Implementation: web/src/styles/glass.css; styles.css; supporting screen styles.

## Review and status

See [UI adoption verification](ui-verification.md). Source changes and technical/visual checks do not establish owner acceptance, a new release, live-data qualification, or acceptance of an older frozen candidate. Existing project-specific gates remain separate.
