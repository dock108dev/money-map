#!/usr/bin/env python3
"""Sanitize native build paths and run PyInstaller with exact team signing."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__
from PyInstaller.depend import bindepend

PRIVATE_BUILD_PATH = re.compile(rb"(?<!:)/(?:Users|private/(?:tmp|var))/[A-Za-z0-9_.@+,:=\-/]+")
MACHO_MAGICS = {
    bytes.fromhex("cffaedfe"),
    bytes.fromhex("cafebabe"),
    bytes.fromhex("cafebabf"),
}


def sanitize_bytes(content: bytes) -> tuple[bytes, int]:
    count = 0

    def replacement(match: re.Match[bytes]) -> bytes:
        nonlocal count
        count += 1
        original = match.group(0)
        prefix = b"/build/input"
        return prefix + (b"_" * (len(original) - len(prefix)))

    return PRIVATE_BUILD_PATH.sub(replacement, content), count


def sanitize_file(path: Path, identity: str) -> bool:
    content = path.read_bytes()
    sanitized, count = sanitize_bytes(content)
    if not count:
        return False
    path.write_bytes(sanitized)
    if content[:4] in MACHO_MAGICS:
        subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                identity,
                "--timestamp=none",
                str(path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True


def normalize_wheel_record(path: Path) -> None:
    lines = path.read_text().splitlines()
    retained = [line for line in lines if not line.startswith("../../../bin/")]
    path.write_text("\n".join(retained) + "\n")


def main() -> None:
    identity = os.environ.get("APPLE_SIGNING_IDENTITY")
    if not identity or "Apple Development" not in identity:
        raise SystemExit("exact Apple Development identity is required")
    source = Path.cwd()
    environment = source / ".venv"
    if not environment.is_dir():
        raise SystemExit("frozen build environment is missing")
    for path in sorted(environment.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix != ".pth":
            is_macho = path.read_bytes()[:4] in MACHO_MAGICS
            is_sbom = "sboms" in path.parts
            if is_macho:
                sanitize_file(path, "-")
            elif is_sbom:
                sanitize_file(path, identity)
            if path.name == "RECORD" and path.parent.name.endswith(".dist-info"):
                normalize_wheel_record(path)

    original_library = Path(bindepend.get_python_library_path())
    copied_library = source / "build-support" / original_library.name
    copied_library.parent.mkdir(mode=0o700)
    shutil.copy2(original_library, copied_library)
    sanitize_file(copied_library, identity)
    bindepend.get_python_library_path = lambda: str(copied_library)  # type: ignore[assignment]

    sysconfig_name = "_sysconfigdata__darwin_darwin"
    sysconfig_spec = importlib.util.find_spec(sysconfig_name)
    if sysconfig_spec is None or sysconfig_spec.origin is None:
        raise SystemExit("Python sysconfig build input is missing")
    sysconfig_copy = copied_library.parent / f"{sysconfig_name}.py"
    shutil.copy2(sysconfig_spec.origin, sysconfig_copy)
    sanitize_file(sysconfig_copy, identity)

    arguments = [
        "--paths",
        str(copied_library.parent),
        *sys.argv[1:],
        "--codesign-identity",
        identity,
    ]
    PyInstaller.__main__.run(arguments)


if __name__ == "__main__":
    main()
