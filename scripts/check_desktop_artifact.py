from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import stat
import subprocess
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAME_PARTS = (
    ".sqlite",
    ".local",
    "statement",
    "backup",
    "report",
    ".map",
)
FORBIDDEN_BYTES = (
    b"Desktop/savings/.local/",
    b"/private/tmp/money-map-",
    b".map\x00sourceMappingURL",
    b"http://127.0.0.1:5173",
    b"localhost:5173",
)
REQUIRED_MIGRATIONS = tuple(f"000{index}_" for index in range(1, 10))
APP_COMMANDS = {
    "allow-desktop-fetch",
    "allow-desktop-reload",
    "allow-desktop-print",
    "allow-desktop-runtime-status",
    "allow-desktop-restart",
    "allow-desktop-about",
    "allow-desktop-select-import",
    "allow-desktop-reveal-backup",
    "allow-desktop-report-action",
    "allow-desktop-diagnostics-preview",
    "allow-desktop-export-diagnostics",
    "allow-desktop-set-operations-enabled",
    "allow-desktop-open-external",
    "allow-desktop-qualification-observe",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_markers(label: str, content: bytes, markers: tuple[bytes, ...]) -> None:
    has_posix_home = re.search(rb"(?<!:)\/Users\/", content) is not None
    if has_posix_home or any(marker and marker in content for marker in markers):
        raise SystemExit(f"Forbidden private or development marker in {label}")


def _scan_pyinstaller(sidecar: Path, markers: tuple[bytes, ...]) -> tuple[int, int, int]:
    archive = CArchiveReader(str(sidecar))
    names = set(archive.toc)
    migration_names = [
        name for name in names if "_alembic/versions/000" in name and name.endswith(".py")
    ]
    for prefix in REQUIRED_MIGRATIONS:
        matches = [name for name in migration_names if f"/versions/{prefix}" in name]
        if len(matches) != 1:
            raise SystemExit(f"Required migration {prefix} is missing or duplicated")
    native_count = 0
    with tempfile.TemporaryDirectory(prefix="money-map-artifact-native.") as temp:
        temp_root = Path(temp)
        for index, name in enumerate(sorted(names)):
            lowered = name.lower()
            if lowered.endswith((".sqlite", ".sqlite3", ".db", ".map")) or ".local" in lowered:
                raise SystemExit(f"Forbidden archived resource: {name}")
            extracted = archive.extract(name)
            if isinstance(extracted, bytes):
                _reject_markers(f"sidecar archive entry {name}", extracted, markers)
                if extracted[:4] == bytes.fromhex("cffaedfe"):
                    native_count += 1
                    native = temp_root / f"native-{index}"
                    native.write_bytes(extracted)
                    architecture = subprocess.run(
                        ["lipo", "-archs", str(native)],
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()
                    if architecture != "arm64":
                        raise SystemExit(f"Embedded code is not thin arm64: {name}")
                    signature = subprocess.run(
                        [
                            "/usr/bin/codesign",
                            "--verify",
                            "--strict",
                            (
                                "-R=anchor apple generic and "
                                'certificate leaf[subject.OU] = "E3G5D247ZN"'
                            ),
                            str(native),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if signature.returncode:
                        raise SystemExit(
                            f"Embedded code lacks the exact Apple team signature: {name}"
                        )
    pyz = archive.open_embedded_archive("PYZ.pyz")
    for name in pyz.toc:
        extracted = pyz.extract(name, raw=True)
        if isinstance(extracted, bytes):
            _reject_markers(f"frozen Python module {name}", extracted, markers)
    required_modules = {
        "paycheck_map.desktop_app",
        "paycheck_map.desktop_bootstrap",
        "paycheck_map.desktop_sidecar",
        "paycheck_map.import_security",
        "paycheck_map.native_secrets",
        "paycheck_map.safe_events",
    }
    missing = sorted(required_modules - set(pyz.toc))
    if missing:
        raise SystemExit(f"Missing frozen security modules: {missing}")
    return len(names), len(pyz.toc), native_count


def _scan_capabilities() -> None:
    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    active = config["app"]["security"].get("capabilities")
    if active != ["main-window", "safe-error-window"]:
        raise SystemExit("Tauri capabilities are not an explicit reviewed list")
    main = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())
    safe = json.loads((ROOT / "desktop/src-tauri/capabilities/safe-error.json").read_text())
    if set(main["permissions"]) != APP_COMMANDS or main.get("windows") != ["main"]:
        raise SystemExit("Main-window command capability differs from the reviewed allowlist")
    if safe.get("windows") != ["safe-error"] or set(safe["permissions"]) != {
        "allow-desktop-runtime-status",
        "allow-desktop-restart",
        "allow-desktop-about",
    }:
        raise SystemExit("Safe-error capability differs from the reviewed allowlist")
    encoded = json.dumps([config["app"]["security"], main, safe], sort_keys=True)
    for forbidden in ("shell:", "fs:", "http:", "opener:", '"*"'):
        if forbidden in encoded:
            raise SystemExit(f"Forbidden capability or wildcard: {forbidden}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--canary", action="append", default=[])
    args = parser.parse_args()
    app = args.app.resolve()
    if app.suffix != ".app" or not app.is_dir():
        raise SystemExit("Expected an extracted .app bundle")
    files = [path for path in app.rglob("*") if path.is_file()]
    for path in app.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (path.is_file() and metadata.st_nlink != 1):
            raise SystemExit(f"Linked artifact entry: {path.relative_to(app)}")
    bad_names = [
        path.relative_to(app)
        for path in files
        if any(term in path.name.lower() for term in FORBIDDEN_NAME_PARTS)
    ]
    if bad_names:
        raise SystemExit(f"Forbidden private-data filenames: {bad_names}")
    markers = (
        *FORBIDDEN_BYTES,
        str(ROOT).encode(),
        str(ROOT.parent).encode(),
        *(value.encode() for value in args.canary),
    )
    for path in files:
        _reject_markers(str(path.relative_to(app)), path.read_bytes(), markers)
    required = {
        "Contents/MacOS/money-map-desktop",
        "Contents/MacOS/money-map-sidecar",
        "Contents/Info.plist",
    }
    present = {str(path.relative_to(app)) for path in files}
    missing = sorted(required - present)
    if missing:
        raise SystemExit(f"Missing runtime resources: {missing}")
    executable_files = {
        str(path.relative_to(app))
        for path in files
        if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    }
    if executable_files != {
        "Contents/MacOS/money-map-desktop",
        "Contents/MacOS/money-map-sidecar",
    }:
        raise SystemExit(f"Unapproved executable files: {sorted(executable_files)}")
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if plist.get("CFBundleIdentifier") != "com.moneymap.desktop":
        raise SystemExit("Unexpected bundle identifier")
    if plist.get("CFBundleShortVersionString") != "2.1.0":
        raise SystemExit("Unexpected bundle version")
    signature = subprocess.run(
        [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            '-R=anchor apple generic and certificate leaf[subject.OU] = "E3G5D247ZN"',
            str(app),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if signature.returncode:
        raise SystemExit("Strict signed owner-beta identity verification failed")
    sidecar = app / "Contents/MacOS/money-map-sidecar"
    header = sidecar.read_bytes()[:8]
    if header != bytes.fromhex("cffaedfe0c000001"):
        raise SystemExit("Sidecar is not a thin Apple Silicon Mach-O")
    archive_entries, frozen_modules, native_files = _scan_pyinstaller(sidecar, markers)
    _scan_capabilities()
    inventory = [
        {
            "path": str(path.relative_to(app)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(files)
    ]
    print(
        "Desktop artifact security scan passed "
        f"({len(files)} files; {archive_entries} archive entries; "
        f"{frozen_modules} frozen modules; {native_files} signed embedded native files)"
    )
    for item in inventory:
        print(f"{item['path']} {item['size']} {item['sha256']}")


if __name__ == "__main__":
    main()
