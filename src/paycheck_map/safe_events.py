"""Bounded, private, allowlisted desktop lifecycle event log."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

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
    }
)
MAX_LOG_BYTES = 256 * 1024
MAX_LOG_FILES = 3


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
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise RuntimeError("The safe log location was rejected")
        self.root.chmod(0o700)
        self._rotate()
        payload = json.dumps(
            {
                "contract": EVENT_CONTRACT,
                "code": code,
                "classification": classification,
                "at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, payload.encode("ascii") + b"\n")
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
