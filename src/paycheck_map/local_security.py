"""Security boundary for the standalone loopback browser application."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_REQUEST_BODY = 1_048_576
_MAX_SECURITY_HEADER = 512
_MAX_ACTIVE_REQUESTS = 32
_BODY_READ_TIMEOUT_SECONDS = 2.0
_REQUEST_SECURITY_HEADERS = frozenset(
    {
        b"host",
        b"origin",
        b"content-type",
        b"content-length",
        b"transfer-encoding",
        b"sec-fetch-site",
    }
)
_RESPONSE_SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (
        b"content-security-policy",
        (
            b"default-src 'none'; script-src 'self' https://cdn.plaid.com; "
            b"style-src 'self' 'unsafe-inline'; img-src 'self' data: https://cdn.plaid.com; "
            b"font-src 'self'; frame-src https://cdn.plaid.com; connect-src 'self' "
            b"https://sandbox.plaid.com https://production.plaid.com; object-src 'none'; "
            b"base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; "
            b"media-src 'none'"
        ),
    ),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-robots-tag", b"noindex, nofollow, noarchive"),
)


def _response(status: int, message: str) -> tuple[dict[str, Any], bytes]:
    body = json.dumps({"detail": message}, separators=(",", ":")).encode("utf-8")
    return (
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                *_RESPONSE_SECURITY_HEADERS,
            ],
        },
        body,
    )


class LocalSecurityMiddleware:
    """Fail closed around the non-desktop loopback HTTP boundary."""

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner
        self._active_requests = 0
        self._request_lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if settings.desktop_mode or scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return

        grouped: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            grouped.setdefault(bytes(key).lower(), []).append(bytes(value))
        if not self._valid_security_headers(grouped):
            await self._reject(send, 400, "The local request headers were rejected.")
            return

        expected_authority = f"{settings.host}:{settings.port}"
        host = grouped[b"host"][0].decode("ascii")
        if host != expected_authority:
            await self._reject(send, 400, "The local service rejected the request host.")
            return

        expected_origin = f"http://{expected_authority}"
        origin_values = grouped.get(b"origin", [])
        origin = origin_values[0].decode("ascii") if origin_values else ""
        if origin and origin != expected_origin:
            await self._reject(send, 403, "The local service rejected the request origin.")
            return
        fetch_site_values = grouped.get(b"sec-fetch-site", [])
        fetch_site = fetch_site_values[0].decode("ascii") if fetch_site_values else ""
        if fetch_site and fetch_site not in {"same-origin", "none"}:
            await self._reject(send, 403, "The local service rejected the request site.")
            return

        method = str(scope.get("method", "")).upper()
        if method not in _ALLOWED_METHODS:
            await self._reject(send, 405, "The local service rejected the request method.")
            return
        if not self._valid_path(str(scope.get("path", "")), bytes(scope.get("raw_path", b""))):
            await self._reject(send, 400, "The local service rejected the request path.")
            return
        if method == "OPTIONS":
            if origin != expected_origin:
                await self._reject(send, 403, "The local service requires its exact origin.")
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [
                        *_RESPONSE_SECURITY_HEADERS,
                        (b"access-control-allow-origin", expected_origin.encode("ascii")),
                        (
                            b"access-control-allow-methods",
                            b"GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS",
                        ),
                        (b"access-control-allow-headers", b"Content-Type"),
                        (b"vary", b"Origin"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        content_type = grouped.get(b"content-type", [b""])[0].split(b";", 1)[0].strip().lower()
        if method in _MUTATION_METHODS and content_type != b"application/json":
            await self._reject(send, 415, "The local request content type was rejected.")
            return

        async with self._request_lock:
            if self._active_requests >= _MAX_ACTIVE_REQUESTS:
                await self._reject(send, 429, "The local service is busy.")
                return
            self._active_requests += 1
        bounded = await self._read_body(receive)
        if bounded is None:
            await self._release_request()
            await self._reject(send, 413, "The local request was too large or incomplete.")
            return
        messages = iter(bounded)

        async def secured_receive() -> Message:
            return next(messages, {"type": "http.disconnect"})

        async def secured_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                replaced = {name for name, _value in _RESPONSE_SECURITY_HEADERS}
                headers = [
                    (bytes(key).lower(), bytes(value))
                    for key, value in message.get("headers", [])
                    if bytes(key).lower() not in replaced
                ]
                headers.extend(_RESPONSE_SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        try:
            await self.inner(scope, secured_receive, secured_send)
        finally:
            await self._release_request()

    @staticmethod
    def _valid_security_headers(grouped: dict[bytes, list[bytes]]) -> bool:
        if len(grouped.get(b"host", [])) != 1:
            return False
        if grouped.get(b"content-length") and grouped.get(b"transfer-encoding"):
            return False
        for key in _REQUEST_SECURITY_HEADERS:
            values = grouped.get(key, [])
            if len(values) > 1:
                return False
            for value in values:
                if (
                    len(value) > _MAX_SECURITY_HEADER
                    or not value.isascii()
                    or any(byte < 0x20 or byte == 0x7F for byte in value)
                ):
                    return False
        return True

    @staticmethod
    def _valid_path(path: str, raw_path: bytes) -> bool:
        if (
            not path.startswith("/")
            or "\\" in path
            or any(ord(character) < 32 for character in path)
            or len(raw_path) > 4_096
        ):
            return False
        if any(segment in {".", ".."} for segment in path.split("/")):
            return False
        lowered = raw_path.lower()
        return not any(
            value in lowered for value in (b"%0a", b"%0d", b"%25", b"%2e", b"%2f", b"%5c")
        )

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
    async def _reject(send: Send, status: int, message: str) -> None:
        start, body = _response(status, message)
        await send(start)
        await send({"type": "http.response.body", "body": body})
