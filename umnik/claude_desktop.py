from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from config import DATA_DIR, MCP_HTTP_URL, MCP_PORT, MCP_TOKEN, OPENROUTER_PROXY, ROOT
from net import lan_ips, open_firewall, primary_ip

INSTALLER_URLS = (
    "https://downloads.claude.ai/releases/win32/x64/ClaudeSetup.exe",
    "https://claude.ai/api/desktop/win32/x64/setup/latest/redirect",
)


def mcp_http_url() -> str:
    preferred = (MCP_HTTP_URL or "").strip()
    if preferred:
        return preferred.rstrip("/")
    return f"http://{primary_ip()}:{MCP_PORT}/mcp"


def claude_config_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Claude" / "claude_desktop_config.json"


def find_claude_exe() -> Path | None:
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    home = Path.home()
    pf = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    candidates = [
        local / "AnthropicClaude" / "claude.exe",
        local / "Programs" / "AnthropicClaude" / "claude.exe",
        local / "Programs" / "Claude" / "Claude.exe",
        local / "Programs" / "claude" / "Claude.exe",
        local / "Claude" / "Claude.exe",
        pf / "Claude" / "Claude.exe",
        home / "AppData" / "Local" / "AnthropicClaude" / "claude.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


LOCAL_PROXY_PORT = 17880
PROXY_PID_FILE = DATA_DIR / "claude_proxy.pid"


def claude_proxy() -> str:
    return (OPENROUTER_PROXY or "").strip()


def _port_open(host: str, port: int) -> bool:
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _no_proxy() -> str:
    """Локальная сеть мимо прокси. Свои адреса подставляем, а не хардкодим."""
    parts = ["localhost", "127.0.0.1", "::1", *lan_ips()]
    parts += ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]
    return ",".join(dict.fromkeys(parts))


def claude_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = _no_proxy()
    env["no_proxy"] = _no_proxy()
    return env


def ensure_local_proxy() -> str:
    if not claude_proxy():
        return "прокси в .env нет"
    if _port_open("127.0.0.1", LOCAL_PROXY_PORT):
        return f"локальный прокси уже слушает 127.0.0.1:{LOCAL_PROXY_PORT}"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(DATA_DIR / "claude_proxy.log", "ab", buffering=0)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "proxy_auth_bridge.py")],
        cwd=str(ROOT),
        stdout=logf,
        stderr=logf,
        creationflags=flags,
    )
    PROXY_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(25):
        if proc.poll() is not None:
            return f"локальный прокси сразу вышел (код {proc.returncode}). Смотри data/claude_proxy.log"
        if _port_open("127.0.0.1", LOCAL_PROXY_PORT):
            return f"локальный прокси pid {proc.pid} на 127.0.0.1:{LOCAL_PROXY_PORT}"
        time.sleep(0.2)
    return "локальный прокси не успел открыть порт"


def desktop_mcp_block() -> dict:
    url = mcp_http_url()
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    return {
        "command": str(py),
        "args": [str(ROOT / "mcp_http_bridge.py"), url],
        "cwd": str(ROOT),
        "env": {
            "PYTHONUTF8": "1",
            "MCP_NO_OPENROUTER": "1",
            "NO_PROXY": _no_proxy(),
            "no_proxy": _no_proxy(),
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
        },
    }


def remote_mcp_block() -> dict:
    """Блок для чужого ПК: нужен только Node.js, копия проекта не нужна.

    mcp-remote переводит stdio Claude Desktop в наш HTTP.
    """
    args = ["-y", "mcp-remote", mcp_http_url(), "--allow-http"]
    if MCP_TOKEN:
        args += ["--header", f"Authorization: Bearer {MCP_TOKEN}"]
    return {"command": "npx", "args": args}


def write_client_config(dest: Path | None = None) -> Path:
    """Файл, который сотрудник копирует себе в claude_desktop_config.json."""
    path = dest or (ROOT / "mcp" / "client_claude_desktop_config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"mcpServers": {"obshaya-rabochaya": remote_mcp_block()}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_claude_mcp_config() -> Path:
    path = claude_config_path()
    data: dict = {}
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                data = loaded
    data.setdefault("mcpServers", {})
    if not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}
    data["mcpServers"]["obshaya-rabochaya"] = desktop_mcp_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    snippet = ROOT / "mcp" / "claude_desktop_config.snippet.json"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        json.dumps({"mcpServers": {"obshaya-rabochaya": desktop_mcp_block()}}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ScanPdf"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def install_claude_desktop() -> str:
    found = find_claude_exe()
    if found:
        return f"Claude Desktop уже есть: {found}"
    notes: list[str] = []
    try:
        proc = subprocess.run(
            [
                "winget",
                "install",
                "-e",
                "--id",
                "Anthropic.Claude",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        notes.append((proc.stdout or "")[-400:] + (proc.stderr or "")[-200:])
        found = find_claude_exe()
        if found:
            return f"Поставил Claude Desktop через winget: {found}"
    except (OSError, subprocess.SubprocessError) as exc:
        notes.append(f"winget: {exc}")
    dest = ROOT / "data" / "ClaudeSetup.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = ""
    for url in INSTALLER_URLS:
        try:
            _download(url, dest)
            if dest.stat().st_size < 1_000_000:
                last_err = f"слишком маленький файл с {url}"
                continue
            subprocess.Popen([str(dest)], close_fds=True)
            time.sleep(4)
            found = find_claude_exe()
            if found:
                return f"Запустил установщик Claude Desktop. Нашлись: {found}"
            return (
                f"Запустил установщик {dest}. Подтверди окно установки и вход в Pro, "
                "затем снова нажми Запуск."
            )
        except Exception as exc:
            last_err = f"{url}: {exc}"
    return "Claude Desktop не поставился. " + " | ".join([*notes, last_err])[:500]


def open_claude_desktop() -> str:
    exe = find_claude_exe()
    if exe is None:
        return "Claude Desktop ещё не найден после установки."
    notes: list[str] = []
    if claude_proxy():
        notes.append(ensure_local_proxy())
    env = claude_launch_env()
    args = [str(exe)]
    if claude_proxy():
        args.append(f"--proxy-server=http://127.0.0.1:{LOCAL_PROXY_PORT}")
        args.append("--proxy-bypass-list=<-loopback>;localhost;127.0.0.1;192.168.200.20")
    subprocess.Popen(args, env=env, close_fds=True)
    if claude_proxy():
        notes.append(
            "Открыл Claude Desktop через локальный прокси с логином "
            f"(127.0.0.1:{LOCAL_PROXY_PORT}). Пароль в процесс Chromium не передаётся."
        )
        return " ".join(notes)
    return f"Открыл Claude Desktop: {exe} (прокси в .env нет)."


def open_firewall_mcp() -> str:
    return open_firewall(MCP_PORT, f"ScanPdf MCP {MCP_PORT}")


def lan_reachable() -> str:
    return primary_ip()
