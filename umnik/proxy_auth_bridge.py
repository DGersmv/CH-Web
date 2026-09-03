"""Локальный прокси без логина → внешний прокси с логином.

Electron/Claude Desktop не умеет Proxy-Authorization из HTTPS_PROXY
и отвечает 407. Chromium ходит сюда на 127.0.0.1 без пароля.
"""
from __future__ import annotations

import base64
import os
import select
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONUTF8", "1")

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("CLAUDE_LOCAL_PROXY_PORT", "17880"))


def _upstream() -> tuple[str, int, str]:
    from config import OPENROUTER_PROXY

    raw = (OPENROUTER_PROXY or "").strip()
    if not raw:
        raise SystemExit("Нет OPENROUTER_PROXY в .env")
    u = urlparse(raw)
    if not u.hostname or not u.port:
        raise SystemExit("OPENROUTER_PROXY без host:port")
    user = u.username or ""
    password = u.password or ""
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return u.hostname, int(u.port), token


UP_HOST, UP_PORT, UP_AUTH = _upstream()


def _relay(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            ready, _, _ = select.select([a, b], [], [], 120)
            if not ready:
                break
            for src in ready:
                dst = b if src is a else a
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)
    except OSError:
        return
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s\n" % (fmt % args))

    def finish(self) -> None:
        if getattr(self, "_tunneled", False):
            return
        super().finish()

    def do_CONNECT(self) -> None:  # noqa: N802
        target = (self.path or "").strip()
        up = socket.create_connection((UP_HOST, UP_PORT), timeout=30)
        req = (
            f"CONNECT {target} HTTP/1.1\r\n"
            f"Host: {target}\r\n"
            f"Proxy-Authorization: Basic {UP_AUTH}\r\n"
            f"Proxy-Connection: Keep-Alive\r\n"
            f"\r\n"
        )
        up.sendall(req.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = up.recv(4096)
            if not chunk:
                break
            buf += chunk
        head = buf.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        if " 200 " not in head:
            self.send_error(502, "upstream CONNECT failed")
            up.close()
            return
        self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        leftover = buf.split(b"\r\n\r\n", 1)[1]
        if leftover:
            self.connection.sendall(leftover)
        self._tunneled = True
        self.close_connection = True
        _relay(self.connection, up)

    def _forward_http(self) -> None:
        body = b""
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
        up = socket.create_connection((UP_HOST, UP_PORT), timeout=30)
        path = self.path
        hdrs = []
        for key, val in self.headers.items():
            low = key.lower()
            if low in {"proxy-connection", "proxy-authorization", "connection"}:
                continue
            hdrs.append(f"{key}: {val}")
        hdrs.append(f"Proxy-Authorization: Basic {UP_AUTH}")
        hdrs.append("Connection: close")
        req = (
            f"{self.command} {path} HTTP/1.1\r\n"
            + "\r\n".join(hdrs)
            + "\r\n\r\n"
        )
        up.sendall(req.encode("latin-1") + body)
        while True:
            chunk = up.recv(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
        up.close()

    def do_GET(self) -> None:  # noqa: N802
        self._forward_http()

    def do_POST(self) -> None:  # noqa: N802
        self._forward_http()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward_http()

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward_http()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward_http()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._forward_http()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward_http()


def main() -> int:
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"local proxy {LISTEN_HOST}:{LISTEN_PORT} -> upstream", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
