"""Fail-closed resource and container limits for private manual imports."""

from __future__ import annotations

import csv
import json
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pdfplumber


@dataclass(frozen=True)
class ImportLimits:
    max_file_bytes: int = 16 * 1024 * 1024
    max_filename_bytes: int = 240
    max_csv_rows: int = 100_000
    max_csv_fields: int = 256
    max_csv_field_bytes: int = 16 * 1024
    max_csv_row_bytes: int = 64 * 1024
    max_xlsx_entries: int = 2_000
    max_xlsx_expanded_bytes: int = 64 * 1024 * 1024
    max_xlsx_expansion_ratio: int = 100
    max_pdf_pages: int = 32
    max_pdf_text_bytes: int = 2 * 1024 * 1024
    max_json_depth: int = 32
    max_json_items: int = 20_000


LIMITS = ImportLimits()
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".json", ".csv", ".xlsx"})
_DANGEROUS_PDF_MARKERS = (
    b"/EmbeddedFile",
    b"/JavaScript",
    b"/JS ",
    b"/OpenAction",
    b"/Launch",
)


class ImportSecurityError(ValueError):
    """A safe rejection that never contains imported content or a raw path."""


def validate_import(path: Path, *, approved_root: Path, limits: ImportLimits = LIMITS) -> None:
    _validate_path(path, approved_root=approved_root, limits=limits)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        _validate_pdf(path, limits)
    elif suffix == ".xlsx":
        _validate_xlsx(path, limits)
    elif suffix == ".csv":
        _validate_csv(path, limits)
    elif suffix == ".json":
        _validate_json(path, limits)
    else:
        raise ImportSecurityError("The import type is not supported.")


def _validate_path(path: Path, *, approved_root: Path, limits: ImportLimits) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ImportSecurityError("The import could not be verified.") from error
    name = path.name
    if (
        len(name.encode("utf-8")) > limits.max_filename_bytes
        or name in {"", ".", ".."}
        or name.startswith("-")
        or unicodedata.normalize("NFKC", name) != name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
        or "/" in name
        or "\\" in name
    ):
        raise ImportSecurityError("The import filename was rejected.")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ImportSecurityError("The import must be one regular private file.")
    if metadata.st_size == 0 or metadata.st_size > limits.max_file_bytes:
        raise ImportSecurityError("The import size was rejected.")
    try:
        resolved = path.resolve(strict=True)
        approved = approved_root.resolve(strict=True)
    except OSError as error:
        raise ImportSecurityError("The import location could not be verified.") from error
    if resolved.parent != approved and approved not in resolved.parents:
        raise ImportSecurityError("The import location was rejected.")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ImportSecurityError("The import type is not supported.")


def _validate_pdf(path: Path, limits: ImportLimits) -> None:
    header = path.read_bytes()[:8]
    if not header.startswith(b"%PDF-"):
        raise ImportSecurityError("The PDF signature was rejected.")
    raw = path.read_bytes()
    if any(marker in raw for marker in _DANGEROUS_PDF_MARKERS):
        raise ImportSecurityError("Active or embedded PDF content is not supported.")
    try:
        with pdfplumber.open(path) as document:
            if not 0 < len(document.pages) <= limits.max_pdf_pages:
                raise ImportSecurityError("The PDF page count was rejected.")
            extracted = 0
            for page in document.pages:
                extracted += len((page.extract_text() or "").encode("utf-8"))
                if extracted > limits.max_pdf_text_bytes:
                    raise ImportSecurityError("The PDF text limit was exceeded.")
    except ImportSecurityError:
        raise
    except Exception as error:
        raise ImportSecurityError("The PDF container could not be verified.") from error


def _validate_xlsx(path: Path, limits: ImportLimits) -> None:
    if path.read_bytes()[:4] != b"PK\x03\x04":
        raise ImportSecurityError("The workbook signature was rejected.")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not 0 < len(entries) <= limits.max_xlsx_entries:
                raise ImportSecurityError("The workbook entry count was rejected.")
            expanded = 0
            for entry in entries:
                name = entry.filename
                pure = PurePosixPath(name)
                if (
                    pure.is_absolute()
                    or ".." in pure.parts
                    or "\\" in name
                    or any(ord(character) < 32 for character in name)
                ):
                    raise ImportSecurityError("The workbook entry path was rejected.")
                lowered = name.lower()
                if "vbaproject" in lowered or lowered.endswith((".exe", ".dll", ".dylib")):
                    raise ImportSecurityError("Executable workbook content is not supported.")
                expanded += entry.file_size
                if expanded > limits.max_xlsx_expanded_bytes:
                    raise ImportSecurityError("The workbook expansion limit was exceeded.")
                if entry.compress_size == 0 and entry.file_size > 0:
                    raise ImportSecurityError("The workbook compression ratio was rejected.")
                if (
                    entry.compress_size
                    and entry.file_size > entry.compress_size * limits.max_xlsx_expansion_ratio
                ):
                    raise ImportSecurityError("The workbook compression ratio was rejected.")
                if lowered.endswith(".rels"):
                    content = archive.read(entry)
                    if b'TargetMode="External"' in content or b"TargetMode='External'" in content:
                        raise ImportSecurityError(
                            "External workbook relationships are not supported."
                        )
                if (
                    lowered.startswith("xl/worksheets/")
                    and lowered.endswith(".xml")
                    and b"<f" in archive.read(entry)
                ):
                    raise ImportSecurityError("Workbook formulas are not supported.")
            if archive.testzip() is not None:
                raise ImportSecurityError("The workbook archive failed verification.")
    except ImportSecurityError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise ImportSecurityError("The workbook container could not be verified.") from error


def _validate_csv(path: Path, limits: ImportLimits) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for row_number, row in enumerate(reader, start=1):
                if row_number > limits.max_csv_rows:
                    raise ImportSecurityError("The CSV row limit was exceeded.")
                if len(row) > limits.max_csv_fields:
                    raise ImportSecurityError("The CSV field count was exceeded.")
                encoded = [field.encode("utf-8") for field in row]
                if any(len(field) > limits.max_csv_field_bytes for field in encoded):
                    raise ImportSecurityError("The CSV field size was exceeded.")
                if sum(len(field) for field in encoded) > limits.max_csv_row_bytes:
                    raise ImportSecurityError("The CSV row size was exceeded.")
                if any(_formula_like(field) for field in row):
                    raise ImportSecurityError("CSV formula-like content is not supported.")
    except ImportSecurityError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise ImportSecurityError("The CSV encoding or structure was rejected.") from error


def _validate_json(path: Path, limits: ImportLimits) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImportSecurityError("The JSON encoding or structure was rejected.") from error
    stack: list[tuple[object, int]] = [(value, 1)]
    items = 0
    while stack:
        current, depth = stack.pop()
        if depth > limits.max_json_depth:
            raise ImportSecurityError("The JSON nesting limit was exceeded.")
        if isinstance(current, dict):
            items += len(current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            items += len(current)
            stack.extend((item, depth + 1) for item in current)
        if items > limits.max_json_items:
            raise ImportSecurityError("The JSON item limit was exceeded.")


def _formula_like(value: str) -> bool:
    stripped = value.lstrip()
    if not stripped:
        return False
    if stripped[0] in {"=", "+", "@"}:
        return True
    if stripped[0] == "-":
        return len(stripped) == 1 or stripped[1] not in "0123456789."
    return False
