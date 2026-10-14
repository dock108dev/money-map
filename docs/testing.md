# Focused local checks

Updated October 7, 2026. Scope: personal use and a handful of users. [Working approach](personal-use.md).

Use the smallest relevant check for the changed behavior. Financial arithmetic, transfers, duplicate imports, account participation and saved-plan persistence deserve meaningful regression coverage. Pure documentation or low-impact presentation edits do not need a whole build/native campaign.

## Focused checks

From the repository root after [local setup](development.md):

```sh
uv run pytest tests/test_api.py
uv run ruff check src
pnpm --dir web test
uv run python scripts/check_docs.py
```

Select the actual affected test files. Tests use disposable synthetic data; never aim them at `.local` financial state or the installed app's Application Support directory. Rebuild web assets only when needed to run updated frontend code.

## Existing broader tools

`paycheck-map verify`, the Rust checks and hosted CI remain available for substantial shared changes or reproduced faults. They are not mandatory before every handoff or owner-use attempt. Use native checks only for actual native-shell changes. Distribution builds, signing/DMG inventories, installed acceptance matrices, sleep/wake/offline campaigns and platform compatibility jobs are deferred unless a concrete personal-use problem needs one.

Check the affected ordinary flow and save/reopen after a change. Back up before data/schema updates. Keep real imports and credentials private. Existing CI/workflows are unchanged by this documentation pass.
