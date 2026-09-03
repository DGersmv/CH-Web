"""Сеть: адрес сервера в LAN, ссылки для клиентов, правила брандмауэра.

IP больше нигде не захардкожен — DHCP может выдать другой, всё считается на лету.
"""
from __future__ import annotations

import ipaddress
import socket
import subprocess

LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


def lan_ips() -> list[str]:
    """IPv4 машины без loopback. Первым — тот, через который реально уходит трафик."""
    found: list[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # никуда не отправляет пакет, только просит маршрут у ядра
        sock.connect(("8.8.8.8", 80))
        found.append(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.")]


def primary_ip() -> str:
    """Адрес, который надо давать людям в локальной сети."""
    ips = lan_ips()
    for ip in ips:
        try:
            if ipaddress.ip_address(ip).is_private:
                return ip
        except ValueError:
            continue
    return ips[0] if ips else "127.0.0.1"


def urls(port: int, path: str = "") -> list[str]:
    tail = path if path.startswith("/") or not path else f"/{path}"
    out = [f"http://127.0.0.1:{port}{tail}"]
    for ip in lan_ips():
        out.append(f"http://{ip}:{port}{tail}")
    return out


def is_loopback(host: str | None) -> bool:
    """Клиент сидит за этим же компьютером?"""
    raw = (host or "").strip().lower()
    if raw in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return False


def is_private(host: str | None) -> bool:
    """Клиент из локальной сети, а не из интернета."""
    raw = (host or "").strip().lower()
    if is_loopback(raw):
        return True
    try:
        return ipaddress.ip_address(raw).is_private
    except ValueError:
        return False


def open_firewall(port: int, name: str) -> str:
    """Разрешить входящие TCP на порт. Без прав администратора просто не сработает."""
    # netsh печатает в кодировке консоли (cp866), не в UTF-8 — читаем байтами,
    # нам всё равно нужен только код возврата.
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True,
            timeout=15,
        )
        proc = subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={name}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={port}",
                "profile=private,domain",
            ],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"порт {port}: правило не записалось ({exc}). Запусти от администратора."
    if proc.returncode != 0:
        return f"порт {port}: netsh отказал. Нужны права администратора."
    return f"порт {port} открыт для локальной сети ({name})."


def firewall_report(ports: dict[int, str]) -> str:
    return "\n".join(open_firewall(port, name) for port, name in ports.items())


if __name__ == "__main__":
    print("LAN IP:", primary_ip())
    for u in urls(7860):
        print(" ", u)
