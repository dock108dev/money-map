"""Independent single-writer ownership for the desktop data root."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import IO


class WriterLockConflict(RuntimeError):
    """Another process owns the selected desktop data root."""


class WriterLock:
    """An advisory process lock whose file contains no secret material."""

    def __init__(self, data_root: Path) -> None:
        self.path = data_root / ".money-map-writer.lock"
        self._handle: IO[str] | None = None
        self.recovered_stale_file = False

    def acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("Desktop writer ownership is already held")
        existed = self.path.exists()
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise WriterLockConflict("The desktop data root is already in use") from error
        except BaseException:
            handle.close()
            raise
        self.recovered_stale_file = existed and os.fstat(handle.fileno()).st_size > 0
        handle.seek(0)
        handle.truncate()
        json.dump(
            {"contract": "money-map-desktop-writer-v1", "pid": os.getpid()},
            handle,
            separators=(",", ":"),
        )
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        cleanup_failed = False
        try:
            held = os.fstat(handle.fileno())
            current = self.path.stat()
            if (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino):
                self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            cleanup_failed = True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        if cleanup_failed:
            raise RuntimeError("Desktop writer lock cleanup failed")

    def __enter__(self) -> WriterLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
