#!/usr/bin/env python3
"""Reject broken local Markdown links in current repository documentation."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REMOTE_SCHEMES = {"http", "https", "mailto"}


def markdown_files(root: Path = ROOT) -> tuple[Path, ...]:
    files = [root / "README.md", *(root / "docs").rglob("*.md")]
    return tuple(sorted(path for path in files if path.is_file()))


def local_link_target(document: Path, raw_link: str) -> Path | None:
    value = raw_link.strip()
    if value.startswith("<") and ">" in value:
        value = value[1 : value.index(">")]
    else:
        value = value.split(maxsplit=1)[0]
    parsed = urlsplit(value)
    if parsed.scheme.lower() in REMOTE_SCHEMES or parsed.netloc or not parsed.path:
        return None
    return (document.parent / unquote(parsed.path)).resolve()


def broken_links(root: Path = ROOT) -> tuple[str, ...]:
    failures: list[str] = []
    for document in markdown_files(root):
        for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for match in LINK.finditer(line):
                target = local_link_target(document, match.group(1))
                if target is not None and not target.exists():
                    relative_document = document.relative_to(root)
                    failures.append(
                        f"{relative_document}:{line_number}: missing local link target "
                        f"{match.group(1)!r}"
                    )
    return tuple(failures)


def main() -> None:
    failures = broken_links()
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Documentation link check passed: {len(markdown_files())} Markdown files")


if __name__ == "__main__":
    main()
