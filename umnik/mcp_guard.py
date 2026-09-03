"""Охрана MCP-порта: кто пришёл, с паролем ли, и можно ли ему писать.

Без этого любой человек в локальной сети мог вызвать delete_file в D:\\Scan_Pdf.
"""
from __future__ import annotations

import os
import time
from contextvars import ContextVar
from pathlib import Path

from config import CRM_TOOLS, DATA_DIR, LAN_READONLY, MCP_TOKEN, WRITE_TOOLS
from net import is_loopback, is_private

CLIENT: ContextVar[str] = ContextVar("mcp_client", default="127.0.0.1")
ACCESS_LOG = DATA_DIR / "mcp_access.log"


def client_host() -> str:
    return CLIENT.get()


def readonly_now() -> bool:
    """Удалённый клиент пишет, только если LAN_READONLY явно выключен.

    MCP_FORCE_READONLY ставит веб-чат, когда сервер запускает MCP для
    сетевого пользователя: там подключение локальное, а человек — нет.
    """
    if os.environ.get("MCP_FORCE_READONLY"):
        return True
    return LAN_READONLY and not is_loopback(CLIENT.get())


def guard_write(tool: str) -> str | None:
    """Текст отказа для пишущего инструмента, либо None."""
    if tool in WRITE_TOOLS and readonly_now():
        return (
            f"{tool} недоступен: подключение из сети ({CLIENT.get()}) работает "
            "только на чтение. Запись в D:\\Scan_Pdf — с самого сервера."
        )
    return None


def guard_crm(tool: str) -> str | None:
    if tool not in CRM_TOOLS:
        return None
    if os.environ.get("MCP_CRM_MODE", "").strip().lower() not in {"1", "true", "yes"}:
        return f"{tool} только из чата CRM, не из архива Scan_Pdf."
    if readonly_now():
        return (
            f"{tool} недоступен из сети. Сделки CRM меняет только admin "
            "через чат в CRM."
        )
    return None


def log(host: str, note: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with ACCESS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{host}\t{note}\n")
    except OSError:
        pass


class GuardMiddleware:
    """ASGI-обёртка: пускает только локальную сеть и только с верным токеном."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client") or ("", 0)
        host = client[0] or ""
        if not is_private(host):
            log(host, "отказ: адрес не из локальной сети")
            await _deny(send, 403, "Только локальная сеть")
            return
        if MCP_TOKEN and not is_loopback(host):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            sent = headers.get("authorization", "")
            expected = f"Bearer {MCP_TOKEN}"
            # сравнение постоянного времени тут излишне: сеть своя, токен общий
            if sent != expected:
                log(host, "отказ: неверный или пустой токен")
                await _deny(send, 401, "Нужен заголовок Authorization: Bearer <MCP_TOKEN>")
                return
        token = CLIENT.set(host or "127.0.0.1")
        try:
            await self.app(scope, receive, send)
        finally:
            CLIENT.reset(token)


async def _deny(send, status: int, text: str) -> None:
    body = text.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
