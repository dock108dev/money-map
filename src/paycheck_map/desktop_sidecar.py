"""Frozen, argument-free Apple Silicon desktop sidecar entrypoint."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from paycheck_map.data_home import DataHomePaths
from paycheck_map.desktop_lock import WriterLock


def _synthetic_root() -> Path:
    raw = os.environ.get("PAYCHECK_MAP_LOCAL_DIR")
    if not raw:
        raise RuntimeError("Disposable desktop data root is required")
    root = Path(raw).resolve()
    if os.environ.get("PAYCHECK_MAP_DESKTOP_DATA_MODE") != "disposable-synthetic":
        raise RuntimeError("Disposable synthetic desktop mode is required")
    if root.name != "money-map-synthetic-data" or not root.parent.name.startswith(
        "money-map-runtime-"
    ):
        raise RuntimeError("Desktop runtime refuses a non-disposable data root")
    if root.is_symlink() or ".local" in root.parts:
        raise RuntimeError("Desktop runtime refuses an unsafe data root")
    return root


def _desktop_root() -> Path:
    mode = os.environ.get("PAYCHECK_MAP_DESKTOP_DATA_MODE")
    if mode == "disposable-synthetic":
        return _synthetic_root()
    if mode in {"production-v1", "acceptance-synthetic-v1"}:
        paths = DataHomePaths.from_trusted_environment()
        return paths.application
    raise RuntimeError("Desktop data mode is required")


def main() -> None:
    root = _desktop_root()
    if os.environ.get("PAYCHECK_MAP_DESKTOP_MODE") != "true":
        raise RuntimeError("Desktop mode is required")
    if not os.environ.get("PAYCHECK_MAP_DESKTOP_SESSION"):
        raise RuntimeError("Desktop session is required")
    delay_ms = min(
        max(int(os.environ.get("PAYCHECK_MAP_DESKTOP_STARTUP_DELAY_MS", "0")), 0), 30_000
    )
    if delay_ms:
        time.sleep(delay_ms / 1000)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    with WriterLock(root):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        print(f"MONEY_MAP_READY {port}", flush=True)
        config = uvicorn.Config(
            "paycheck_map.desktop_app:desktop_app",
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        def await_shutdown() -> None:
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    server.should_exit = True
                    return

        threading.Thread(target=await_shutdown, name="desktop-shutdown", daemon=True).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("MONEY_MAP_FAILED", flush=True)
        raise SystemExit(1) from None
