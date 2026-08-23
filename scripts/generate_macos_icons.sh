#!/bin/zsh
set -euo pipefail

if [[ $# -ne 2 ]]; then
  print -u2 "usage: generate_macos_icons.sh SOURCE_1024_PNG OUTPUT_ICNS"
  exit 2
fi
source_png=$1
output_icns=$2
[[ -f "$source_png" ]] || { print -u2 "missing icon source"; exit 1; }
dimensions=$(sips -g pixelWidth -g pixelHeight "$source_png" 2>/dev/null)
[[ "$dimensions" == *"pixelWidth: 1024"* && "$dimensions" == *"pixelHeight: 1024"* ]] || {
  print -u2 "icon source must be 1024x1024"
  exit 1
}
icon_root=$(mktemp -d /private/tmp/money-map-icon.XXXXXX)
chmod 700 "$icon_root"
trap 'rm -rf "$icon_root"' EXIT
iconset="$icon_root/MoneyMap.iconset"
mkdir -m 700 "$iconset"
for spec in '16 icon_16x16.png' '32 icon_16x16@2x.png' '32 icon_32x32.png' \
  '64 icon_32x32@2x.png' '128 icon_128x128.png' '256 icon_128x128@2x.png' \
  '256 icon_256x256.png' '512 icon_256x256@2x.png' '512 icon_512x512.png' \
  '1024 icon_512x512@2x.png'; do
  size=${spec%% *}
  name=${spec#* }
  sips -s format png -z "$size" "$size" "$source_png" --out "$iconset/$name" >/dev/null
done
mkdir -p "${output_icns:h}"
iconutil -c icns "$iconset" -o "$output_icns"
[[ -s "$output_icns" ]] || { print -u2 "ICNS generation failed"; exit 1; }
