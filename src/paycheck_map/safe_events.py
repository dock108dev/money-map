"""Bounded, private, allowlisted desktop lifecycle event log."""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

EVENT_CONTRACT = "money-map-safe-events-v1"
ALLOWED_CODES = frozenset(
    {
        "MM-DESKTOP-START",
        "MM-DESKTOP-READY",
        "MM-DESKTOP-STOP",
        "MM-DESKTOP-FAIL",
        "MM-DATA-INTEGRITY-FAIL",
        "MM-IMPORT-REJECTED",
        "MM-GOAL-CURRENTNESS-FAIL",
        "MM-GOAL-CHECKIN-FAIL",
        "MM-OPERATION-COMMIT-FAIL",
        "MM-REQUEST-FAIL",
        "MM-DATA-OPERATION-FAIL",
        "MM-SYNC-FAIL",
        "MM-FORECAST-UNAVAILABLE",
        "MM-PROVENANCE-INVALID",
    }
)
MAX_LOG_BYTES = 256 * 1024
MAX_LOG_FILES = 3
_LOG_LOCK = RLock()
_LOGGER = logging.getLogger("paycheck_map.failures")


class SafeEventLog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "desktop-events.jsonl"

    def emit(self, code: str, classification: str) -> None:
        if code not in ALLOWED_CODES or classification not in {
            "lifecycle",
            "data_integrity",
            "import",
            "goal_observation",
        }:
            raise ValueError("Unsafe event classification")
        self._append(
            {
                "contract": EVENT_CONTRACT,
                "code": code,
                "classification": classification,
                "at": datetime.now(UTC).isoformat(),
            }
        )

    def _append(self, value: dict[str, Any]) -> None:
        # Threaded API requests share rotation and append as one bounded operation.
        with _LOG_LOCK:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.root.is_symlink() or not self.root.is_dir():
                raise RuntimeError("The safe log location was rejected")
            self.root.chmod(0o700)
            self._rotate()
            payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise RuntimeError("The safe log file was rejected")
                os.fchmod(descriptor, 0o600)
                remaining = memoryview(payload.encode("ascii") + b"\n")
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("The safe event could not be written")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _rotate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < MAX_LOG_BYTES:
            return
        for index in range(MAX_LOG_FILES - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            destination = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                if destination.exists():
                    destination.unlink()
                os.replace(source, destination)
        os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))


def record_failure(code: str, classification: str, error: BaseException | None = None) -> None:
    """Keep code locations, never exception text, locals, SQL, request data or private paths."""
    from .config import settings

    frames: list[str] = []
    traceback = error.__traceback__ if error is not None else None
    package_root = Path(__file__).parent
    while traceback is not None:
        filename = Path(traceback.tb_frame.f_code.co_filename)
        # PyInstaller may retain package-relative compilation filenames.
        if filename.parent in {package_root, Path("paycheck_map")} and filename.suffix == ".py":
            frames.append(f"{filename.name}:{traceback.tb_lineno}")
        traceback = traceback.tb_next
    frames = frames[-16:]
    # The allowlist is checked even when no durable desktop log is configured.
    if code not in ALLOWED_CODES or classification not in {
        "lifecycle",
        "data_integrity",
        "import",
        "goal_observation",
    }:
        raise ValueError("Unsafe event classification")
    level = (
        logging.WARNING
        if code in {"MM-FORECAST-UNAVAILABLE", "MM-IMPORT-REJECTED"}
        else logging.ERROR
    )
    _LOGGER.log(level, "%s %s frames=%s", code, classification, ",".join(frames))
    if settings.desktop_log_root is None:
        return
    try:
        log = SafeEventLog(settings.desktop_log_root)
        log.emit(code, classification)
        log.path = log.root / "failure-events.jsonl"
        log._append(
            {
                "contract": "money-map-safe-failures-v1",
                "code": code,
                "classification": classification,
                "at": datetime.now(UTC).isoformat(),
                "frames": frames,
            }
        )
    except (OSError, RuntimeError):
        # Telemetry cannot undo a commit or mask its original failure.
        _LOGGER.error("MM-TELEMETRY-UNAVAILABLE")
