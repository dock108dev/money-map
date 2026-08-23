# Money Map v3 desktop product experience

Status: Slice 3 implementation contract for the signed Apple Silicon application.

## Ordinary loop and navigation

Cash Flow is the initial and durable return route. The native View menu and the in-app grouped
navigation use the same route controller, update the same `#view=` state, and preserve the current
safe route across reload and runtime recovery. Command-1 through Command-9 navigate the principal
views; Review uses Command-Shift-9. Overview is the first supporting route in Details and is also
available as an unmodified native View-menu action. It remains distinct from conditional Review and
loads its read-only period evidence only when opened.

The installed app exposes account update, connection management, optional read-only Plaid setup,
private-inbox import, existing-data import, verified backup/restore, report generation and preview,
printing, safe reload, service restart, About, and sanitized diagnostics without a terminal or
browser. Connected-provider work remains explicit and local evidence remains usable offline.

## Native menus and shortcuts

- Money Map: About, Restart Local Service, Services, Hide, Hide Others, Show All, and Quit.
- File: Import Private Inbox (Command-I), Import Existing Money Map Data (Command-Shift-I), Create
  Verified Backup (Command-Shift-B), Restore from Backup, Generate Report (Command-Shift-R), Export
  Diagnostics, Print (Command-P), and Close Window (Command-W).
- View: every top-level route, Reload (Command-R), Actual Size (Command-0), Zoom In, and Zoom Out.
- Window: Minimize, Zoom, and Bring All to Front.

Menu operations dispatch into the same React operation handlers as visible controls. Backend
confirmation remains authoritative. Unsafe mutation operations are disabled while setup, data-home
work, account work, or runtime recovery is active.

## Window and runtime lifecycle

Closing the last window hides it and deliberately keeps the one local runtime alive. Dock reopen,
application reopen, and a second Finder launch show and focus that same window. Hide/show and
minimize/restore do not reload the route or application state. Quit is the only ordinary action
that exits; it stops the sidecar, removes the listener and session, and releases the writer lock.

System resume performs an authenticated health revalidation. A dead runtime returns to the safe
failed state with stale mutation controls removed and one deliberate restart. There is no automatic
restart loop. Each successful retry creates exactly one new runtime generation and preserves the
prior safe route.

## State, focus, and accessibility language

Progress, confirmed completion, caution, unavailable evidence, recoverable interruption, and safe
failure use consistent status or alert semantics. Existing local evidence remains visible after a
connected update fails. Offline state says local data is available and network restoration never
starts a retry by itself.

Focused operations move focus to the first meaningful control, contain Tab only while modal,
support Escape when cancellation is safe, keep recoverable input, and restore invoking focus.
Background polling updates visual state without repeated live-region announcements. The app honors
reduced motion, provides visible focus, uses 44-pixel controls at constrained sizes, supports native
zoom through 200%, and removes transient controls from print.

## Reports, printing, and diagnostics

The report API returns the opaque identity `trailing-12-month`, never a path. The native shell asks
the backend to re-approve that identity, accepts only the fixed filename inside the approved report
root, rejects symlinks and traversal, and opens a macOS Quick Look preview or Finder reveal. Report
creation is atomic, local, and mode `0600`.

Before printing, closed evidence sections open temporarily; after printing, their on-screen state
is restored. Navigation, dialogs, progress, and transient confirmations are excluded. Cash Flow,
Goals, Retirement, Life Lab, and the trailing-period report are the required print surfaces.

Diagnostics are built from a strict native/backend allowlist and exported through a native Save
panel as mode `0600`. The preview names included categories before any write. Cancel writes nothing.
Allowed categories are version/schema/build/source/architecture/macOS, data-mode and data-home phase,
runtime state and generation, verified-backup count/status, integrity and foreign-key results,
network classification, and artifact identity. Financial values, identifiers, descriptions,
credentials, sessions, ports, paths, filenames, hashes, exceptions, bodies, and environment dumps
are forbidden.
