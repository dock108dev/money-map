from __future__ import annotations

import argparse
import socket
import time
from concurrent.futures import ThreadPoolExecutor


def request(port: int, payload: bytes) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.settimeout(3)
        client.sendall(payload)
        response = client.recv(256)
    first = response.split(b"\r\n", 1)[0].split()
    if len(first) < 2 or not first[1].isdigit():
        raise RuntimeError("Ambiguous HTTP response")
    return int(first[1])


def probe(port: int, name: str, request_lines: bytes) -> tuple[str, int]:
    status = request(port, request_lines)
    if status < 400:
        raise RuntimeError(f"Unauthorized probe succeeded: {name}")
    return name, status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    port = args.port
    host = f"127.0.0.1:{port}".encode()
    base = b"GET /api/desktop/health HTTP/1.1\r\nHost: " + host + b"\r\n"
    probes = {
        "sessionless": base + b"\r\n",
        "wrong-session": base + b"X-Money-Map-Session: " + b"f" * 64 + b"\r\n\r\n",
        "stale-session": base + b"X-Money-Map-Session: " + b"e" * 64 + b"\r\n\r\n",
        "duplicate-session": base + b"X-Money-Map-Session: a\r\nX-Money-Map-Session: b\r\n\r\n",
        "wrong-host": b"GET /api/desktop/health HTTP/1.1\r\nHost: localhost\r\n\r\n",
        "hostile-origin": base + b"Origin: https://attacker.invalid\r\n\r\n",
        "null-origin": base + b"Origin: null\r\n\r\n",
        "traversal": b"GET /api/../secrets HTTP/1.1\r\nHost: " + host + b"\r\n\r\n",
        "double-encoding": b"GET /api/%252e%252e/secrets HTTP/1.1\r\nHost: " + host + b"\r\n\r\n",
        "unsupported-method": b"TRACE /api/desktop/health HTTP/1.1\r\nHost: " + host + b"\r\n\r\n",
        "oversized-body": b"POST /api/imports/scan HTTP/1.1\r\nHost: "
        + host
        + b"\r\nContent-Length: 1048577\r\n\r\n",
        "wrong-content-type": b"POST /api/imports/scan HTTP/1.1\r\nHost: "
        + host
        + b"\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\n{}",
        "smuggling-cl-te": b"POST /api/imports/scan HTTP/1.1\r\nHost: "
        + host
        + b"\r\nContent-Length: 4\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        "duplicate-host": b"GET /api/desktop/health HTTP/1.1\r\nHost: "
        + host
        + b"\r\nHost: "
        + host
        + b"\r\n\r\n",
    }
    results = [probe(port, name, payload) for name, payload in probes.items()]
    with ThreadPoolExecutor(max_workers=32) as executor:
        flood = list(executor.map(lambda _: request(port, base + b"\r\n"), range(64)))
    if any(status < 400 for status in flood):
        raise RuntimeError("Unauthorized flood succeeded")
    slow_clients = [socket.create_connection(("127.0.0.1", port), timeout=2) for _ in range(16)]
    try:
        for client in slow_clients:
            client.sendall(b"GET /api/desktop/health HTTP/1.1\r\n")
        time.sleep(0.5)
    finally:
        for client in slow_clients:
            client.close()
    if request(port, base + b"\r\n") < 400:
        raise RuntimeError("Service failed closed after slow-client campaign")
    print(
        f"Loopback attack campaign passed ({len(results)} cases + {len(flood)} flood "
        f"requests + {len(slow_clients)} slow clients)"
    )


if __name__ == "__main__":
    main()
