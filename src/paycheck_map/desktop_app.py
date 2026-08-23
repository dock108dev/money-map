"""Authenticated loopback wrapper used only by the native desktop sidecar."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .app import app
from .desktop_bootstrap import active_bootstrap, matches_session

_ALLOWED_ORIGINS = frozenset({"http://tauri.localhost", "tauri://localhost"})
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "OPTIONS"})
_MAX_REQUEST_BODY = 1_048_576
_MAX_SECURITY_HEADER = 512
_MAX_ACTIVE_REQUESTS = 32
_BODY_READ_TIMEOUT_SECONDS = 2.0
_SECURITY_HEADERS = frozenset(
    {b"host", b"origin", b"x-money-map-session", b"content-length", b"transfer-encoding"}
)


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
        self._active_requests = 0
        self._request_lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return
        raw_headers = [
            (bytes(key).lower(), bytes(value)) for key, value in scope.get("headers", [])
        ]
        grouped: dict[bytes, list[bytes]] = {}
        for key, value in raw_headers:
            grouped.setdefault(key, []).append(value)
        if not self._valid_security_headers(grouped):
            await self._reject(send, 400, "The desktop request headers were rejected.")
            return
        host = grouped[b"host"][0].decode("ascii")
        origin_values = grouped.get(b"origin", [])
        origin = origin_values[0].decode("ascii") if origin_values else ""
        method = str(scope.get("method", "")).upper()
        raw_path = bytes(scope.get("raw_path", b""))
        path = str(scope.get("path", ""))
        if host != f"127.0.0.1:{active_bootstrap().port}":
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
        if len(grouped.get(b"x-money-map-session", [])) != 1:
            await self._reject(send, 401, "Desktop session authentication is required.")
            return
        supplied = grouped[b"x-money-map-session"][0].decode("ascii")
        if not supplied or not matches_session(supplied):
            await self._reject(send, 401, "Desktop session authentication is required.")
            return
        content_type = (
            next((value for key, value in raw_headers if key == b"content-type"), b"")
            .split(b";", 1)[0]
            .strip()
            .lower()
        )
        if method in {"POST", "PUT", "DELETE"} and content_type != b"application/json":
            await self._reject(send, 415, "The desktop request content type was rejected.")
            return
        async with self._request_lock:
            if self._active_requests >= _MAX_ACTIVE_REQUESTS:
                await self._reject(send, 429, "The desktop service is busy.")
                return
            self._active_requests += 1
        bounded = await self._read_body(receive)
        if bounded is None:
            await self._release_request()
            await self._reject(send, 413, "The desktop request was too large.")
            return
        messages = iter(bounded)

        async def secured_receive() -> Message:
            return next(messages, {"type": "http.disconnect"})

        if scope.get("path") == "/api/desktop/health":
            if method != "GET":
                await self._release_request()
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
            await self._release_request()
            return

        async def secured_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"cache-control", b"no-store"))
                if origin:
                    response_headers.extend(self._cors(origin))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.inner(scope, secured_receive, secured_send)
        finally:
            await self._release_request()

    @staticmethod
    def _valid_security_headers(grouped: dict[bytes, list[bytes]]) -> bool:
        if len(grouped.get(b"host", [])) != 1:
            return False
        if len(grouped.get(b"x-money-map-session", [])) > 1:
            return False
        if len(grouped.get(b"origin", [])) > 1:
            return False
        if len(grouped.get(b"content-length", [])) > 1:
            return False
        if grouped.get(b"content-length") and grouped.get(b"transfer-encoding"):
            return False
        for key in _SECURITY_HEADERS:
            for value in grouped.get(key, []):
                if (
                    len(value) > _MAX_SECURITY_HEADER
                    or not value.isascii()
                    or any(byte < 0x20 or byte == 0x7F for byte in value)
                ):
                    return False
        return True

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
            try:
                message = await asyncio.wait_for(receive(), timeout=_BODY_READ_TIMEOUT_SECONDS)
            except TimeoutError:
                return None
            messages.append(message)
            if message.get("type") != "http.request":
                return messages
            size += len(message.get("body", b""))
            if size > _MAX_REQUEST_BODY:
                return None
            if not message.get("more_body", False):
                return messages

    async def _release_request(self) -> None:
        async with self._request_lock:
            self._active_requests = max(0, self._active_requests - 1)

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
