#!/usr/bin/env python3
"""Fail when likely private financial input is outside the ignored local-data boundary."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_EXTENSIONS = {".pdf", ".xls", ".xlsx", ".csv", ".tsv", ".ofx", ".qfx"}
ALLOWED_DATA_PREFIXES = ("examples/synthetic/", "tests/fixtures/synthetic/")
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".toml",
    ".json",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".yml",
    ".yaml",
}
SUSPICIOUS_PATTERNS = {
    # Require non-alphanumeric boundaries so digits embedded in a public SHA-256
    # provenance hash are not mistaken for a standalone identifier.
    "nine-digit identifier": re.compile(r"(?<![A-Za-z0-9])\d{9}(?![A-Za-z0-9])"),
    "unmasked account label": re.compile(
        r"(?i)\b(?:account|person|payroll relationship)\s*(?:number|#|no\.?)?\s*[:=-]?\s*\d{6,}"
    ),
}


def candidates() -> list[Path]:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return [ROOT / line for line in result.stdout.splitlines() if line]


def main() -> int:
    failures: list[str] = []
    for path in candidates():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(".local/") or not path.is_file():
            continue
        if path.suffix.lower() in PRIVATE_EXTENSIONS and not relative.startswith(
            ALLOWED_DATA_PREFIXES
        ):
            failures.append(
                f"{relative}: private-data extension outside an approved synthetic path"
            )
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SUSPICIOUS_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{relative}: possible {label}")
    if failures:
        print("Private-data leak check failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("Private-data leak check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
