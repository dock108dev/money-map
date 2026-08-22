#!/bin/zsh
set -euo pipefail

repo_root=${0:A:h:h}
target_triple=$(rustc --print host-tuple)
if [[ "$target_triple" != "aarch64-apple-darwin" ]]; then
  print -u2 "The Money Map owner runtime supports only aarch64-apple-darwin"
  exit 1
fi

cd "$repo_root"
export MONEY_MAP_BUILD_COMMIT=${MONEY_MAP_BUILD_COMMIT:-$(git rev-parse HEAD)}
export MONEY_MAP_BUILD_ID=${MONEY_MAP_BUILD_ID:-"slice1-$MONEY_MAP_BUILD_COMMIT"}
pnpm --dir web build
uv run pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name money-map-sidecar \
  --paths src \
  --collect-submodules paycheck_map \
  --collect-all keyring.backends \
  --add-data "alembic:paycheck_map/_alembic" \
  --add-data "config:paycheck_map/config" \
  src/paycheck_map/desktop_sidecar.py
mkdir -p desktop/src-tauri/binaries
cp dist/money-map-sidecar "desktop/src-tauri/binaries/money-map-sidecar-$target_triple"
web/node_modules/.bin/tauri build --config desktop/src-tauri/tauri.conf.json --bundles app
