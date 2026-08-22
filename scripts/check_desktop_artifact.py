from __future__ import annotations

import argparse
from pathlib import Path

FORBIDDEN_NAMES = (".sqlite", ".sqlite3", ".db", ".local", "statement", "backup")
FORBIDDEN_BYTES = (b"Desktop/savings/.local/", b".map\x00sourceMappingURL")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    if app.suffix != ".app" or not app.is_dir():
        raise SystemExit("Expected an extracted .app bundle")
    files = [path for path in app.rglob("*") if path.is_file()]
    bad_names = [
        path.relative_to(app)
        for path in files
        if any(term in path.name.lower() for term in FORBIDDEN_NAMES)
    ]
    if bad_names:
        raise SystemExit(f"Forbidden private-data filenames: {bad_names}")
    project_root = Path(__file__).resolve().parents[1]
    forbidden_bytes = (*FORBIDDEN_BYTES, str(project_root).encode("utf-8"))
    for path in files:
        content = path.read_bytes()
        if any(marker in content for marker in forbidden_bytes):
            raise SystemExit(f"Forbidden private-data marker in {path.relative_to(app)}")
    required = {
        "Contents/MacOS/money-map-desktop",
        "Contents/MacOS/money-map-sidecar",
        "Contents/Info.plist",
    }
    present = {str(path.relative_to(app)) for path in files}
    missing = sorted(required - present)
    if missing:
        raise SystemExit(f"Missing runtime resources: {missing}")
    print(f"Desktop artifact privacy and resource scan passed ({len(files)} files)")


if __name__ == "__main__":
    main()
