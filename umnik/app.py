from __future__ import annotations

# Gradio-сайт на :7860 больше не запускаем: поиск в CRM /archive/, чат умника в карточке.
# Оставлен на случай отладки индекса. Ежедневный запуск — mcp_server.py --http (:7861).

import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import gradio as gr
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent, as_text, chat_cost_usd, chat_model_label, strip_thinking
from claude_desktop import (
    install_claude_desktop,
    mcp_http_url,
    open_claude_desktop,
    open_firewall_mcp,
    write_claude_mcp_config,
)
from budget import BUDGET
from config import (
    ARCHIVE_ROOT,
    CHAT_MODEL_LABELS,
    CHAT_MODELS,
    DATA_DIR,
    DEFAULT_CHAT_MODEL,
    GRADIO_HOST,
    GRADIO_PORT,
    LAN_READONLY,
    MCP_HOST,
    MCP_PORT,
    WEB_USERS,
)
from net import firewall_report, is_loopback, is_private, primary_ip, urls as net_urls
from plugins.registry import load_plugins
from watcher import Watcher

plugins = load_plugins()
agent = Agent(plugins)
watcher = Watcher(plugins)


def _history_to_messages(history: list) -> list[dict[str, str]]:
    messages = []
    for item in history or []:
        if isinstance(item, dict) and item.get("role") in ("user", "assistant"):
            content = as_text(item.get("content"))
            if item.get("role") == "assistant":
                content = strip_thinking(content)
            if content:
                messages.append({"role": item["role"], "content": content})
    return messages


AUDIT_LOG = DATA_DIR / "chat_audit.log"
CHAT_OUTBOX = DATA_DIR / "chat_outbox"
_ATTACH_RE = re.compile(r"^ATTACH_FILE:\s*(.+)\s*$", re.M)


def _visible_chat_text(text: str) -> str:
    shown = _ATTACH_RE.sub("", text or "").strip()
    return shown or (text or "")


def outbox_links(path: Path) -> list[str]:
    from urllib.parse import quote

    encoded = quote(path.name, safe="")
    return net_urls(GRADIO_PORT, f"/outbox/{encoded}")


def _share_note(files: list[Path]) -> str:
    lines = [
        "Скачать с любого компьютера сети (не путь на диске сервера):",
    ]
    for path in files:
        urls = outbox_links(path)
        lan = [u for u in urls if "127.0.0.1" not in u]
        for url in lan or urls:
            lines.append(url)
    return "\n".join(lines)


def _chat_content_with_files(text: str):
    """Текст ответа + вложения из строк ATTACH_FILE: путь."""
    shown = _visible_chat_text(text)
    files: list[Path] = []
    for match in _ATTACH_RE.finditer(text or ""):
        raw = match.group(1).strip().strip('"')
        path = Path(raw)
        if path.is_file() and path not in files:
            files.append(path)
    if not files:
        return shown
    note = _share_note(files)
    body = f"{shown}\n\n{note}".strip() if shown else note
    blocks: list = [body]
    for path in files:
        mime, _ = mimetypes.guess_type(path.name)
        block = {
            "path": str(path),
            "orig_name": path.name,
            "meta": {"_type": "gradio.FileData"},
        }
        if mime:
            block["mime_type"] = mime
        blocks.append(block)
    return blocks


def outbox_file(name: str) -> Path | None:
    folder = CHAT_OUTBOX.resolve()
    dest = (folder / Path(name).name).resolve()
    try:
        if dest.is_file() and dest.is_relative_to(folder):
            return dest
    except (OSError, ValueError):
        return None
    return None


def register_outbox_route(app) -> None:
    """Раздать chat_outbox по HTTP, чтобы PDF открывался с других ПК в LAN."""

    @app.get("/outbox/{name}")
    async def serve_outbox(name: str, request: Request):
        host = request.client.host if request.client else ""
        if not is_private(host):
            return PlainTextResponse("Только локальная сеть", status_code=403)
        dest = outbox_file(name)
        if dest is None:
            return PlainTextResponse("Нет файла", status_code=404)
        mime, _ = mimetypes.guess_type(dest.name)
        return FileResponse(
            dest,
            media_type=mime or "application/octet-stream",
            filename=dest.name,
            content_disposition_type="inline",
        )
        host = request.client.host if request.client else ""
        if not is_private(host):
            return PlainTextResponse("Только локальная сеть", status_code=403)
        dest = outbox_file(name)
        if dest is None:
            return PlainTextResponse("Нет файла", status_code=404)
        mime, _ = mimetypes.guess_type(dest.name)
        return FileResponse(
            dest,
            media_type=mime or "application/octet-stream",
            filename=dest.name,
            content_disposition_type="inline",
        )


def caller(request) -> tuple[str, str, bool]:
    """Кто спрашивает: (имя, ip, только-чтение)."""
    host = ""
    name = ""
    if request is not None:
        client = getattr(request, "client", None)
        host = getattr(client, "host", "") or ""
        name = getattr(request, "username", "") or ""
    local = is_loopback(host)
    if not name:
        name = "сервер" if local else (host or "гость")
    readonly = LAN_READONLY and not local
    return name, host or "127.0.0.1", readonly


def _audit(name: str, host: str, model: str, message: str) -> None:
    line = "\t".join(
        [
            time.strftime("%Y-%m-%d %H:%M:%S"),
            name,
            host,
            model,
            " ".join(message.split())[:300],
        ]
    )
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def chat_fn(message: str, history: list, model: str, request: gr.Request = None):
    message = as_text(message).strip()
    name, host, readonly = caller(request)
    if not message:
        yield history, _status(name)
        return
    _audit(name, host, model, message)
    BUDGET.hit(name, CHAT_MODEL_LABELS.get(model, model))
    history = list(history or [])
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": "### Ход работы\n- читаю вопрос"})
    status = _status(name)
    yield history, status
    try:
        n = 0
        for text in agent.ask_stream(
            message,
            history=_history_to_messages(history[:-2]),
            model=model,
            readonly=readonly,
            user=name,
        ):
            history[-1] = {"role": "assistant", "content": _visible_chat_text(text)}
            n += 1
            if n == 1 or "вызываю" in text or n % 12 == 0:
                status = _status(name)
            yield history, status
        history[-1] = {
            "role": "assistant",
            "content": _chat_content_with_files(text if n else ""),
        }
        yield history, status
    except Exception as exc:
        history[-1] = {
            "role": "assistant",
            "content": (
                f"Не удалось обратиться к модели {chat_model_label()}.\n"
                f"{exc}\n\nПроверь OpenRouter в .env или локальную Ollama: ollama pull qwen2.5:14b"
            ),
        }
        yield history, _status(name)


def refresh_now(request: gr.Request = None):
    name, _host, readonly = caller(request)
    if readonly:
        return _status(name) + "\nПереиндексацию запускает только сам сервер."
    watcher.kick()
    return _status(name)


def _status(user: str | None = None) -> str:
    extra = ""
    try:
        st = plugins[0].status()
        extra = (
            f"\nзрение/OCR: {st.get('vision_files', 0)} файлов"
            f"\nпланировки OpenRouter: {st.get('layout_sheets', 0)} листов"
            f", ${st.get('layout_usd', 0)}"
            f"\nчат: {chat_model_label()}"
        )
    except Exception:
        pass
    return watcher.status_text() + extra


def lan_urls(port: int | None = None) -> list[str]:
    return net_urls(GRADIO_PORT if port is None else port)


MCP_PID_FILE = DATA_DIR / "mcp_http.pid"
_mcp_proc: subprocess.Popen | None = None


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    return True


def _port_open(port: int) -> bool:
    import socket

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _tracked_pid() -> int | None:
    global _mcp_proc
    if _mcp_proc is not None and _mcp_proc.poll() is None:
        return _mcp_proc.pid
    if MCP_PID_FILE.is_file():
        try:
            pid = int(MCP_PID_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            return None
        if _pid_running(pid):
            return pid
    return None


def mcp_status_text() -> str:
    try:
        urls = "\n".join(f"{u}/mcp" for u in lan_urls(MCP_PORT))
        pid = _tracked_pid()
        listening = _port_open(MCP_PORT)
    except Exception:
        return "MCP: статус не прочитался. Нажми Запуск."
    if pid and listening:
        return f"MCP запущен (pid {pid})\n{urls}"
    if listening:
        return f"Порт {MCP_PORT} уже занят, MCP скорее всего работает.\n{urls}"
    if pid:
        return f"Процесс {pid} есть, порт {MCP_PORT} ещё не слушает — подожди секунду."
    return (
        "MCP остановлен. Запуск поднимает HTTP-сервер, ставит Claude Desktop "
        "если его нет, и открывает его окно чата."
    )


def _write_cursor_mcp(http: bool) -> None:
    path = Path.home() / ".cursor" / "mcp.json"
    data: dict = {"mcpServers": {}}
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                data = loaded
        data.setdefault("mcpServers", {})
        if not isinstance(data["mcpServers"], dict):
            data["mcpServers"] = {}
    if http:
        block: dict = {"url": f"http://127.0.0.1:{MCP_PORT}/mcp"}
    else:
        block = {
            "command": str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "args": [str(ROOT / "mcp_server.py")],
            "cwd": str(ROOT),
            "env": {"PYTHONUTF8": "1", "MCP_NO_OPENROUTER": "1"},
        }
    data["mcpServers"]["obshaya-rabochaya"] = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_mcp_running() -> str:
    global _mcp_proc
    if _port_open(MCP_PORT):
        return mcp_status_text()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "mcp_http.log"
    logf = open(log_path, "ab", buffering=0)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["MCP_NO_OPENROUTER"] = "1"
    env.pop("OPENROUTER_API_KEY", None)
    _mcp_proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "mcp_server.py"),
            "--http",
            "--host",
            MCP_HOST,
            "--port",
            str(MCP_PORT),
        ],
        cwd=str(ROOT),
        stdout=logf,
        stderr=logf,
        env=env,
        creationflags=flags,
    )
    MCP_PID_FILE.write_text(str(_mcp_proc.pid), encoding="utf-8")
    deadline = time.time() + 12
    while time.time() < deadline:
        if _mcp_proc.poll() is not None:
            return f"MCP не стартовал (код {_mcp_proc.returncode}). Смотри {log_path}"
        if _port_open(MCP_PORT):
            break
        time.sleep(0.3)
    return mcp_status_text()


def _server_only(request) -> str | None:
    _name, _host, readonly = caller(request)
    if readonly:
        return (
            "Эта кнопка открывает окна на экране сервера — по сети она выключена. "
            "Пользуйся вкладкой «Чат» или подключи свой Claude Desktop по MCP "
            "(вкладка «Сеть»)."
        )
    return None


def start_mcp(request: gr.Request = None):
    blocked = _server_only(request)
    if blocked:
        return blocked
    text = _ensure_mcp_running()
    if text.startswith("MCP не стартовал"):
        return text
    lines = [text]
    try:
        cfg = write_claude_mcp_config()
        lines.append(f"Конфиг Claude Desktop: {cfg}")
        lines.append(f"Диалог через {mcp_http_url()}")
    except Exception as exc:
        lines.append(f"Конфиг Claude Desktop не записался: {exc}")
    lines.append(install_claude_desktop())
    lines.append(open_firewall_mcp())
    lines.append(open_claude_desktop())
    lines.append(
        "Чат — окно Claude Desktop (подписка Pro). Cursor не запускаю. OpenRouter нет. "
        f"{ARCHIVE_ROOT} только чтение, D:\\Scan_Pdf полный доступ."
    )
    return "\n".join(lines)


def open_claude_here(request: gr.Request = None) -> str:
    blocked = _server_only(request)
    return blocked or open_claude_desktop()


def stop_mcp(request: gr.Request = None):
    global _mcp_proc
    blocked = _server_only(request)
    if blocked:
        return blocked
    pid = _tracked_pid()
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )
            else:
                os.kill(pid, 9)
        except OSError:
            pass
    _mcp_proc = None
    if MCP_PID_FILE.is_file():
        MCP_PID_FILE.unlink(missing_ok=True)
    time.sleep(0.4)
    return mcp_status_text()


def claude_status(request: gr.Request = None) -> str:
    """Инструкцию про вход видит только сам сервер: сотруднику она бесполезна."""
    import claude_cli

    _name, _host, readonly = caller(request)
    ok, _note = claude_cli.available()
    if ok:
        return "Claude по подписке готов."
    if readonly:
        return claude_cli.HINT_USER
    return claude_cli.status()


def claude_recheck(request: gr.Request = None) -> str:
    """Кнопка на сервере: перепроверить сразу после `claude login`."""
    import claude_cli

    _name, _host, readonly = caller(request)
    if not readonly:
        claude_cli.invalidate()
    return claude_status(request)


def new_dialog(request: gr.Request = None):
    """Забыть сессию Claude: следующий вопрос начнёт разговор с нуля."""
    import claude_cli

    name, _host, _ro = caller(request)
    claude_cli.forget_session(name)
    return [], "Диалог начат заново."


def net_help() -> str:
    ip = primary_ip()
    web = f"http://{ip}:{GRADIO_PORT}"
    login = (
        "Логин и пароль выдаёт владелец сервера (список в `.env`, ключ `WEB_USERS`)."
        if WEB_USERS
        else "**Пароля сейчас нет** — заполни `WEB_USERS` в `.env`, иначе войдёт любой в сети."
    )
    rights = (
        "Из сети доступно только чтение: поиск, планировки, чтение файлов. "
        "Запись и удаление в `D:\\Scan_Pdf` — только за самим сервером."
        if LAN_READONLY
        else "Из сети доступны и запись, и удаление в `D:\\Scan_Pdf`."
    )
    return (
        "### Как подключиться с другого компьютера\n"
        f"1. Открыть в браузере **{web}** — устанавливать ничего не нужно.\n"
        f"2. {login}\n"
        "3. Спрашивать про архив своими словами: «Васкелово, что за файлы», "
        "«площадь гостиной в 2МД В2».\n\n"
        f"{rights}\n\n"
        f"Если страница не открывается — на сервере не открыт порт {GRADIO_PORT}. "
        "Запусти `start.bat` от администратора один раз, он пропишет правило брандмауэра.\n\n"
        f"Для Claude Desktop и Cursor на своём ПК есть MCP: `http://{ip}:{MCP_PORT}/mcp` — "
        "инструкция в файле `SETUP_LAN.md`."
    )


def spend_report() -> str:
    rows = BUDGET.asks()
    if not rows:
        return "Сегодня ещё никто ничего не спрашивал."
    lines = [f"{key}: {n}" for key, n in rows]
    lines.append("")
    lines.append(
        "Счётчик обнуляется каждые сутки. Claude идёт по одной подписке сервера — "
        "если упрётесь в её лимит, переключитесь на локальный ИИ."
    )
    return "\n".join(lines)


def open_folder(path: str, request: gr.Request = None) -> str:
    _name, _host, readonly = caller(request)
    if readonly:
        return (
            "Проводник открывается на экране сервера, поэтому по сети кнопка "
            "выключена. Скопируй путь и открой у себя."
        )
    path = (path or "").strip().strip('"')
    if not path:
        return "Укажи полный путь к файлу или папке."
    p = Path(path)
    if p.is_file():
        subprocess.run(["explorer", f"/select,{p}"], check=False)
        return f"Открываю: {p}"
    if p.is_dir():
        os.startfile(p)  # noqa: S606
        return f"Открываю папку: {p}"
    parent = p.parent
    if parent.is_dir():
        os.startfile(parent)  # noqa: S606
        return f"Файла нет, открыл папку: {parent}"
    return f"Путь не найден: {path}"


def build() -> gr.Blocks:
    with gr.Blocks(title="Архив PDF") as demo:
        links = " · ".join(f"`{u}`" for u in lan_urls())
        access = (
            "вход по логину и паролю" if WEB_USERS else "**без пароля — войдёт любой в сети**"
        )
        rights = (
            "из сети — только чтение" if LAN_READONLY else "из сети — чтение и запись"
        )
        gr.Markdown(
            f"### Архив PDF — общий доступ по локальной сети\n"
            f"Архив: `{ARCHIVE_ROOT}` (только чтение) · проект: `D:\\Scan_Pdf` ({rights})\n\n"
            f"Открывать с любого компьютера сети: {links} · {access}\n\n"
            f"Можно попросить положить PDF в чат — появится вложение и ссылка "
            f"`http://{primary_ip()}:{GRADIO_PORT}/outbox/...` для всей сети."
        )
        status = gr.Textbox(label="Индекс", value=_status, lines=5, interactive=False)
        with gr.Tabs():
            with gr.Tab("Чат"):
                model_dd = gr.Dropdown(
                    choices=[(label, mid) for mid, label in CHAT_MODELS],
                    value=DEFAULT_CHAT_MODEL,
                    label="Модель",
                )
                chatbot = gr.Chatbot(
                    label="Чат",
                    height=460,
                    placeholder=(
                        "Claude работает по подписке сервера. Спрашивай про архив. "
                        "Можно: «положи этот PDF в чат»."
                    ),
                )
                msg = gr.Textbox(
                    label="Вопрос",
                    placeholder="Найди Васкелово → какая площадь гостиной? → положи PDF в чат",
                )
                with gr.Row():
                    send = gr.Button("Спросить", variant="primary")
                    fresh = gr.Button("Начать заново")
                    upd = gr.Button("Обновить индекс сейчас")
                with gr.Row():
                    path_box = gr.Textbox(label="Путь — открыть в Проводнике", scale=4)
                    open_btn = gr.Button("Открыть", scale=1)
                send.click(chat_fn, [msg, chatbot, model_dd], [chatbot, status]).then(
                    lambda: "", None, msg
                )
                msg.submit(chat_fn, [msg, chatbot, model_dd], [chatbot, status]).then(
                    lambda: "", None, msg
                )
                upd.click(refresh_now, None, status)
                fresh.click(new_dialog, None, [chatbot, status])
                open_btn.click(open_folder, path_box, path_box)
            with gr.Tab("Сеть"):
                gr.Markdown(net_help())
                claude_box = gr.Textbox(
                    label="Claude по подписке",
                    value=claude_status,
                    lines=2,
                    interactive=False,
                )
                net_box = gr.Textbox(
                    label="Кто сколько спрашивал сегодня",
                    value=spend_report,
                    lines=8,
                    interactive=False,
                )
                gr.Button("Проверить").click(claude_recheck, None, claude_box).then(
                    spend_report, None, net_box
                )
            with gr.Tab("MCP Claude"):
                gr.Markdown(
                    "**Кнопки этой вкладки работают только за самим сервером** — "
                    "они открывают окна на его экране.\n\n"
                    "**Запуск** ставит Claude Desktop если его нет, поднимает MCP "
                    f"и открывает **окно Claude Desktop**. "
                    f"Диалог идёт через `{mcp_http_url()}`. "
                    f"`{ARCHIVE_ROOT}` — чтение. `D:\\Scan_Pdf` — полный доступ."
                )
                mcp_box = gr.Textbox(
                    label="Сервер MCP",
                    value=mcp_status_text,
                    lines=4,
                    interactive=False,
                )
                mcp_log = gr.Textbox(
                    label="Диалоговое окно запуска",
                    lines=10,
                    interactive=False,
                    placeholder="Нажми Запуск — здесь будет лог, чат откроется в Claude Desktop.",
                )
                with gr.Row():
                    mcp_start = gr.Button("Запуск", variant="primary")
                    mcp_stop = gr.Button("Стоп")
                    mcp_open = gr.Button("Открыть Claude Desktop")
                mcp_start.click(start_mcp, None, mcp_log)
                mcp_stop.click(stop_mcp, None, mcp_box)
                mcp_open.click(open_claude_here, None, mcp_log)
                if hasattr(gr, "Timer"):
                    mcp_timer = gr.Timer(3)
                    mcp_timer.tick(mcp_status_text, None, mcp_box)
        if hasattr(gr, "Timer"):
            timer = gr.Timer(5)
            timer.tick(_status, None, status)
    return demo


if __name__ == "__main__":
    import threading

    def _names():
        for plugin in plugins:
            if hasattr(plugin, "index_names"):
                plugin.index_names()

    threading.Thread(target=_names, daemon=True, name="pdf-names").start()

    print(
        firewall_report(
            {GRADIO_PORT: f"ScanPdf web {GRADIO_PORT}", MCP_PORT: f"ScanPdf MCP {MCP_PORT}"}
        )
    )
    print("Для сети: " + " · ".join(lan_urls()))
    if not WEB_USERS:
        print(
            "ВНИМАНИЕ: WEB_USERS в .env пуст — веб-чат открыт без пароля "
            "любому в локальной сети."
        )

    # Локальный Qwen-VL на 3060 не гоняем: планировки уже в таблицах OpenRouter.
    watcher.start(run_immediately=False)
    import webbrowser

    import uvicorn

    CHAT_OUTBOX.mkdir(parents=True, exist_ok=True)
    api = FastAPI()
    register_outbox_route(api)
    demo = build()
    demo.queue()
    api = gr.mount_gradio_app(
        api,
        demo,
        path="/",
        allowed_paths=[str(CHAT_OUTBOX.resolve())],
        auth=WEB_USERS or None,
        auth_message="Архив PDF — вход для сотрудников",
        show_error=True,
        server_name=GRADIO_HOST,
        server_port=GRADIO_PORT,
    )
    webbrowser.open(f"http://127.0.0.1:{GRADIO_PORT}")
    uvicorn.run(api, host=GRADIO_HOST, port=GRADIO_PORT, log_level="warning")
