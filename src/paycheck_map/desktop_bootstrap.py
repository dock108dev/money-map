"""Process-private bootstrap state for the authenticated desktop transport."""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass

BOOTSTRAP_CONTRACT = "money-map-desktop-bootstrap-v1"
MAX_BOOTSTRAP_BYTES = 8192
SESSION_BYTES = 32


@dataclass(frozen=True)
class DesktopBootstrap:
    session: str
    port: int


_lock = threading.Lock()
_active: DesktopBootstrap | None = None


def install_bootstrap(session: str, port: int) -> None:
    """Install one generation exactly once before the ASGI app is imported."""

    global _active
    if (
        len(session) != SESSION_BYTES * 2
        or not session.isascii()
        or any(character not in "0123456789abcdef" for character in session)
        or not 0 < port <= 65_535
    ):
        raise RuntimeError("Desktop bootstrap material was rejected")
    with _lock:
        if _active is not None:
            raise RuntimeError("Desktop bootstrap material was already installed")
        _active = DesktopBootstrap(session=session, port=port)


def active_bootstrap() -> DesktopBootstrap:
    with _lock:
        if _active is None:
            raise RuntimeError("Desktop bootstrap material is unavailable")
        return _active


def matches_session(supplied: str) -> bool:
    active = active_bootstrap()
    return hmac.compare_digest(supplied, active.session)


def clear_bootstrap() -> None:
    global _active
    with _lock:
        _active = None
