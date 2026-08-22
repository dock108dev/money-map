"""Frozen, argument-free Apple Silicon desktop sidecar entrypoint."""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn


def _synthetic_root() -> Path:
    raw = os.environ.get("PAYCHECK_MAP_LOCAL_DIR")
    if not raw:
        raise RuntimeError("Disposable desktop data root is required")
    root = Path(raw).resolve()
    if not root.name.startswith("money-map-slice0-"):
        raise RuntimeError("Slice 0 refuses a non-disposable data root")
    return root


def main() -> None:
    root = _synthetic_root()
    if os.environ.get("PAYCHECK_MAP_DESKTOP_MODE") != "true":
        raise RuntimeError("Desktop mode is required")
    if not os.environ.get("PAYCHECK_MAP_DESKTOP_SESSION"):
        raise RuntimeError("Desktop session is required")
    root.mkdir(parents=True, exist_ok=False)
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
    main()
