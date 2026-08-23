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
runtime_data=$(mktemp -d /private/tmp/money-map-runtime-data.XXXXXX)
trap 'rm -rf "$runtime_data"' EXIT
ditto --norsrc alembic "$runtime_data/alembic"
ditto --norsrc config "$runtime_data/config"
find "$runtime_data" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$runtime_data" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
pnpm --dir web build
uv run pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name money-map-sidecar \
  --paths src \
  --collect-submodules paycheck_map \
  --collect-all keyring.backends \
  --add-data "$runtime_data/alembic:paycheck_map/_alembic" \
  --add-data "$runtime_data/config:paycheck_map/config" \
  src/paycheck_map/desktop_sidecar.py
mkdir -p desktop/src-tauri/binaries
cp dist/money-map-sidecar "desktop/src-tauri/binaries/money-map-sidecar-$target_triple"
web/node_modules/.bin/tauri build --config desktop/src-tauri/tauri.conf.json --bundles app
