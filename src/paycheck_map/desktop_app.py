"""Authenticated loopback wrapper used only by the native desktop sidecar."""

from __future__ import annotations

import hmac
import json
import os
import re
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .app import app

_HOST = re.compile(r"^127\.0\.0\.1:\d{1,5}$")
_ALLOWED_ORIGINS = frozenset({"http://tauri.localhost", "tauri://localhost"})
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "OPTIONS"})
_MAX_REQUEST_BODY = 1_048_576
_SESSION = os.environ.get("PAYCHECK_MAP_DESKTOP_SESSION", "")
if not _SESSION:
    raise RuntimeError("Desktop session configuration is unavailable")


def _response(status: int, message: str) -> tuple[dict[str, Any], bytes]:
    body = json.dumps({"detail": message}, separators=(",", ":")).encode("utf-8")
    return (
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        },
        body,
    )


class DesktopSecurityMiddleware:
    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("ascii", "ignore")
        origin = headers.get(b"origin", b"").decode("ascii", "ignore")
        method = str(scope.get("method", "")).upper()
        raw_path = bytes(scope.get("raw_path", b""))
        path = str(scope.get("path", ""))
        if not self._valid_host(host):
            await self._reject(send, 400, "The desktop service rejected the request host.")
            return
        if origin and origin not in _ALLOWED_ORIGINS:
            await self._reject(send, 403, "The desktop service rejected the request origin.")
            return
        if method not in _ALLOWED_METHODS:
            await self._reject(send, 405, "The desktop service rejected the request method.")
            return
        if not self._valid_path(path, raw_path):
            await self._reject(send, 400, "The desktop service rejected the request path.")
            return
        if method == "OPTIONS":
            if not origin:
                await self._reject(send, 403, "The desktop service requires a trusted origin.")
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": self._cors(origin),
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        supplied = headers.get(b"x-money-map-session", b"").decode("ascii", "ignore")
        if not supplied or not hmac.compare_digest(supplied, _SESSION):
            await self._reject(send, 401, "Desktop session authentication is required.")
            return
        bounded = await self._read_body(receive)
        if bounded is None:
            await self._reject(send, 413, "The desktop request was too large.")
            return
        messages = iter(bounded)

        async def secured_receive() -> Message:
            return next(messages, {"type": "http.disconnect"})

        if scope.get("path") == "/api/desktop/health":
            if method != "GET":
                await self._reject(send, 405, "The desktop health request method was rejected.")
                return
            body = json.dumps(
                {"ready": True, "version": app.version}, separators=(",", ":")
            ).encode("utf-8")
            response_headers = [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(body)).encode("ascii")),
            ]
            if origin:
                response_headers.extend(self._cors(origin))
            await send({"type": "http.response.start", "status": 200, "headers": response_headers})
            await send({"type": "http.response.body", "body": body})
            return

        async def secured_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"cache-control", b"no-store"))
                if origin:
                    response_headers.extend(self._cors(origin))
                message["headers"] = response_headers
            await send(message)

        await self.inner(scope, secured_receive, secured_send)

    @staticmethod
    def _valid_host(host: str) -> bool:
        if not _HOST.fullmatch(host):
            return False
        try:
            return 0 < int(host.rsplit(":", 1)[1]) <= 65_535
        except ValueError:
            return False

    @staticmethod
    def _valid_path(path: str, raw_path: bytes) -> bool:
        if not path.startswith("/api/") or "\\" in path or any(ord(char) < 32 for char in path):
            return False
        if any(segment in {"", ".", ".."} for segment in path.split("/")[2:]):
            return False
        lowered = raw_path.lower()
        if any(value in lowered for value in (b"%0a", b"%0d", b"%2e", b"%2f", b"%5c")):
            return False
        return len(raw_path) <= 4_096

    @staticmethod
    async def _read_body(receive: Receive) -> list[Message] | None:
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") != "http.request":
                return messages
            size += len(message.get("body", b""))
            if size > _MAX_REQUEST_BODY:
                return None
            if not message.get("more_body", False):
                return messages

    @staticmethod
    def _cors(origin: str) -> list[tuple[bytes, bytes]]:
        return [
            (b"access-control-allow-origin", origin.encode("ascii")),
            (b"access-control-allow-methods", b"GET,POST,PUT,DELETE,OPTIONS"),
            (b"access-control-allow-headers", b"Content-Type,X-Money-Map-Session"),
            (b"vary", b"Origin"),
        ]

    @staticmethod
    async def _reject(send: Send, status: int, message: str) -> None:
        start, body = _response(status, message)
        await send(start)
        await send({"type": "http.response.body", "body": body})


desktop_app = DesktopSecurityMiddleware(app)
