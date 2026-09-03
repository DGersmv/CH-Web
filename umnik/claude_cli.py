"""Claude по подписке Pro, через CLI Claude Code. Без API-ключей.

CLI логинится один раз логином и паролем (`claude login`) и дальше работает
на подписке владельца сервера. Все пользователи локальной сети спрашивают
через него же — ключи и токены с их компьютеров не нужны.

Архив CLI видит через наш MCP: он сам поднимает mcp_server.py по stdio.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

from config import (
    ARCHIVE_ROOT,
    CLAUDE_CLI_MODEL,
    CLAUDE_MAX_PARALLEL,
    CLAUDE_TIMEOUT_SEC,
    CRM_ROOT,
    CRM_TOOLS,
    DATA_DIR,
    OPENROUTER_PROXY,
    ROOT,
)
from domain import GLOSSARY_FOR_MODEL

MCP_NAME = "arhiv"
MCP_CONFIG = DATA_DIR / "claude_cli_mcp.json"
_ATTACH_LINE_RE = re.compile(r"^ATTACH_FILE:\s*.+$", re.M)

READ_TOOLS = (
    "search_layout",
    "search_pdf",
    "get_pdf_info",
    "look_at_drawing",
    "list_dir",
    "search_name",
    "read_text",
    "list_project",
    "read_project",
    "attach_file",
)
WRITE_TOOLS = ("write_text", "make_dir", "delete_file")
# Встроенные инструменты Claude Code по --add-dir. Без них -p не правит D:\CH-CRM.
DEV_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "LS",
    "NotebookEdit",
)

SYSTEM_ARCHIVE = f"""Ты умник архива PDF. Сейчас НЕ CRM: только поиск и анализ файлов.
{ARCHIVE_ROOT} — только чтение. {ROOT} — рабочая папка Scan_Pdf.
Не правь сделки, не ходи в D:\\CH-CRM, не вызывай crm_*.
Если просят «дай файл / скинь PDF / положи в чат» — вызови attach_file с полным путём.
Не выдумывай пути: смотри диск инструментами mcp__{MCP_NAME}__*.
Если инструмент вернул список — данные есть, перечисли с площадями и полным путём.

{GLOSSARY_FOR_MODEL}"""

SYSTEM_CRM = f"""Ты умник-разработчик внутри CRM CH-Web. Можно и нужно менять код в {CRM_ROOT}.
Это Django-проект: templates, deals, core, accounts. Не трогай .env и секреты.
Права на запись в {CRM_ROOT} уже выданы. Не проси нажать Allow и не останавливайся из‑за «permissions».
Правь сразу: Edit/Write или mcp__{MCP_NAME}__write_text / make_dir. Если Edit вернул отказ — сразу write_text тем же содержимым.
После правок напиши, какие файлы изменил и что обновить в браузере (шаблон — Ctrl+F5; Python — docker compose restart app).
Сделки и цифры: crm_whoami, crm_search_deals, crm_get_deal, crm_update_deal, crm_update_config, crm_update_cost, crm_delete_deal.
Права как у человека в чате. Admin может crm_delete_deal.
Архив {ARCHIVE_ROOT} — планировки/PDF, не основная тема. Не представляйся помощником по архиву.
После инструментов всегда напиши, что сделал. Не оставляй ответ пустым.

{GLOSSARY_FOR_MODEL}"""

# Подписка одна на всех: больше двух параллельных запросов упрутся в лимит.
_gate = threading.Semaphore(CLAUDE_MAX_PARALLEL)
_sessions: dict[str, str] = {}
_sessions_lock = threading.Lock()


class ClaudeCliError(RuntimeError):
    pass


def find_cli() -> Path | None:
    """Нативный claude.exe, не npm .cmd: cmd.exe режет argv и ломает права на запись."""
    appdata = os.environ.get("APPDATA") or ""
    native = (
        Path(appdata)
        / "npm"
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe"
    )
    if native.is_file():
        return native
    direct = shutil.which("claude")
    if direct:
        path = Path(direct)
        if os.name == "nt" and path.suffix.lower() not in {".exe", ".cmd", ".bat"}:
            for suffix in (".cmd", ".exe"):
                alt = path.with_suffix(suffix)
                if alt.is_file():
                    return alt
        return path
    candidates = [
        Path(appdata) / "npm" / "claude.cmd",
        Path(appdata) / "npm" / "claude",
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
        Path(os.environ.get("ProgramFiles") or "") / "nodejs" / "claude.cmd",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def proxy_env(*, sandbox: bool = False) -> dict[str, str]:
    """Anthropic за прокси. Логин-пароль снимает локальный мост, не сам CLI."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    no_proxy = "localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"
    if (OPENROUTER_PROXY or "").strip():
        from claude_desktop import LOCAL_PROXY_PORT, ensure_local_proxy

        ensure_local_proxy()
        local = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            env[key] = local
    else:
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            env.pop(key, None)
    env["NO_PROXY"] = no_proxy
    env["no_proxy"] = no_proxy
    if sandbox:
        # Без этого Windows-CLI игнорирует --dangerously-skip-permissions и пишет user-rejected.
        env["IS_SANDBOX"] = "1"
    # Ключей быть не должно: работаем на подписке.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)
    return env


def write_mcp_config(readonly: bool, crm: bool = False) -> Path:
    """Конфиг MCP для CLI. Архив он поднимает сам, по stdio."""
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    env = {"PYTHONUTF8": "1", "MCP_NO_OPENROUTER": "1"}
    if readonly:
        env["MCP_FORCE_READONLY"] = "1"
    if crm:
        env["MCP_CRM_MODE"] = "1"
    block = {
        "mcpServers": {
            MCP_NAME: {
                "command": str(py if py.is_file() else "python"),
                "args": [str(ROOT / "mcp_server.py")],
                "cwd": str(ROOT),
                "env": env,
            }
        }
    }
    if crm:
        path = DATA_DIR / "claude_cli_mcp_crm.json"
    elif readonly:
        path = DATA_DIR / "claude_cli_mcp_ro.json"
    else:
        path = MCP_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(block, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_crm_settings() -> Path:
    """Разрешить Edit/Write без промпта Allow — иначе -p пишет user-rejected."""
    path = DATA_DIR / "claude_cli_crm_settings.json"
    block = {
        "defaultMode": "bypassPermissions",
        "permissions": {
            "allow": [
                "Read",
                "Write",
                "Edit",
                "MultiEdit",
                "Glob",
                "Grep",
                "LS",
                "NotebookEdit",
                f"mcp__{MCP_NAME}__write_text",
                f"mcp__{MCP_NAME}__make_dir",
                f"mcp__{MCP_NAME}__delete_file",
                f"mcp__{MCP_NAME}__*",
            ]
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(block, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _trust_crm_project() -> None:
    """Claude Code не пишет в папку, пока не принят trust dialog."""
    cfg = Path.home() / ".claude.json"
    if not cfg.is_file():
        return
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return
    roots = {str(CRM_ROOT), str(CRM_ROOT).replace("\\", "/"), str(CRM_ROOT.resolve())}
    changed = False
    for key, block in list(projects.items()):
        if not isinstance(block, dict):
            continue
        if key.replace("\\", "/") not in {item.replace("\\", "/") for item in roots}:
            continue
        if block.get("hasTrustDialogAccepted") is not True:
            block["hasTrustDialogAccepted"] = True
            changed = True
        tools = block.get("allowedTools")
        needed = ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "mcp__arhiv__write_text"]
        if not isinstance(tools, list):
            block["allowedTools"] = needed
            changed = True
        else:
            for name in needed:
                if name not in tools:
                    tools.append(name)
                    changed = True
    if "D:/CH-CRM" in projects and isinstance(projects["D:/CH-CRM"], dict):
        if projects["D:/CH-CRM"].get("hasTrustDialogAccepted") is not True:
            projects["D:/CH-CRM"]["hasTrustDialogAccepted"] = True
            changed = True
    if not changed:
        return
    try:
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def allowed_tool_list(readonly: bool, crm: bool = False) -> list[str]:
    """Имена инструментов отдельными аргументами. Запятая на Windows режет argv."""
    names = list(READ_TOOLS)
    if not readonly:
        names.extend(WRITE_TOOLS)
    if crm:
        names.extend(sorted(CRM_TOOLS))
    prefixes = (MCP_NAME,)
    parts: list[str] = []
    if crm:
        parts.extend(DEV_TOOLS)
    parts.extend(f"mcp__{prefix}__{n}" for prefix in prefixes for n in names)
    return list(dict.fromkeys(parts))


def allowed_tools(readonly: bool, crm: bool = False) -> str:
    return ",".join(allowed_tool_list(readonly, crm=crm))


def build_cli_args(
    cli: Path,
    prompt: str,
    *,
    readonly: bool,
    crm: bool,
    extra_prompt: str = "",
    previous: str | None = None,
) -> tuple[list[str], str]:
    cfg = write_mcp_config(readonly, crm=crm)
    system = SYSTEM_CRM if crm else SYSTEM_ARCHIVE
    if extra_prompt.strip():
        system = system + "\n\n" + extra_prompt.strip()
    args: list[str] = [
        str(cli),
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--strict-mcp-config",
        "--mcp-config",
        str(cfg),
        # append, не --system-prompt: иначе CLI выкидывает инструкцию про MCP
        "--append-system-prompt",
        system,
        "--add-dir",
        str(ARCHIVE_ROOT),
        "--add-dir",
        str(ROOT),
    ]
    workdir = str(ROOT)
    if crm:
        # Без --allowed-tools Write/Edit Claude Code в -p отклоняет запись как user-rejected.
        settings = write_crm_settings()
        workdir = str(CRM_ROOT)
        args += [
            "--add-dir",
            str(CRM_ROOT),
            "--settings",
            str(settings),
            "--allowed-tools",
            *allowed_tool_list(readonly, crm=True),
            "--permission-mode",
            "bypassPermissions",
            "--allow-dangerously-skip-permissions",
            "--dangerously-skip-permissions",
            "--disallowed-tools",
            "Bash",
            "PowerShell",
            "WebFetch",
            "WebSearch",
        ]
    else:
        args += ["--restricted", "--allowed-tools", *allowed_tool_list(readonly, crm=False)]
    if CLAUDE_CLI_MODEL:
        args += ["--model", CLAUDE_CLI_MODEL]
    if previous:
        args += ["--resume", previous]
    return args, workdir


# Проверка входа поднимает процесс CLI — на каждый вопрос это дорого.
STATUS_TTL_SEC = 120
_status_cache: tuple[float, bool, str] | None = None
_status_lock = threading.Lock()

# Текст для владельца сервера: ему есть что нажать.
HINT_SERVER = (
    "Claude по подписке пока не подключён. {note}\n\n"
    "Один раз на этом компьютере выполни в командной строке:\n"
    "    claude login\n"
    "и войди логином и паролем своей учётной записи Anthropic.\n\n"
    "Сотрудникам из сети это делать не нужно и не видно: пока входа нет, "
    "их вопросы уходят к локальному ИИ."
)
# Текст для сотрудника из сети: он всё равно ничего сделать не может.
HINT_USER = (
    "Claude на сервере сейчас недоступен — отвечает локальный ИИ. "
    "Если нужен именно Claude, скажите администратору сервера."
)


def available(force: bool = False) -> tuple[bool, str]:
    """Готов ли Claude. Ответ кэшируется, чтобы не дёргать CLI на каждый вопрос."""
    global _status_cache
    import time

    with _status_lock:
        cached = _status_cache
        if not force and cached is not None and time.time() - cached[0] < STATUS_TTL_SEC:
            return cached[1], cached[2]
    if find_cli() is None:
        result = (
            False,
            "CLI не установлен. Выполни: npm install -g @anthropic-ai/claude-code",
        )
    else:
        result = check_login()
    with _status_lock:
        _status_cache = (time.time(), result[0], result[1])
    return result


def invalidate() -> None:
    """Сбросить кэш: после `claude login` статус меняется сразу."""
    global _status_cache
    with _status_lock:
        _status_cache = None


def status(force: bool = False) -> str:
    """Одна строка для панели: стоит ли CLI и залогинен ли он."""
    cli = find_cli()
    if cli is None:
        return "Claude CLI не установлен. Выполни: npm install -g @anthropic-ai/claude-code"
    ok, note = available(force=force)
    if ok:
        return f"Claude по подписке готов ({cli.name})."
    return f"Вход по подписке не выполнен. {note}"


def check_login(timeout: int = 90) -> tuple[bool, str]:
    """Пробный короткий запрос: проверяет разом подписку и прокси."""
    cli = find_cli()
    if cli is None:
        return False, "CLI не найден."
    try:
        proc = subprocess.run(
            [
                str(cli),
                "-p",
                "ответь одним словом: готов",
                "--output-format",
                "json",
                "--restricted",
                "--strict-mcp-config",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=proxy_env(),
            cwd=str(ROOT),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "CLI не ответил вовремя — проверь прокси."
    except OSError as exc:
        return False, f"CLI не запустился: {exc}"
    raw = (proc.stdout or "").strip()
    text = ""
    try:
        data = json.loads(raw)
        text = str(data.get("result") or "")
        if not data.get("is_error"):
            return True, "вход выполнен"
    except (ValueError, AttributeError):
        text = raw[:200]
    note = " ".join((text or proc.stderr or "").split())[:250]
    if "login" in note.lower():
        return False, "CLI отвечает: вход не выполнен."
    return False, note or "CLI ответил ошибкой."


def _session_for(user: str) -> str | None:
    with _sessions_lock:
        return _sessions.get(user)


def _remember_session(user: str, session_id: str) -> None:
    if not session_id:
        return
    with _sessions_lock:
        _sessions[user] = session_id


def forget_session(user: str) -> None:
    with _sessions_lock:
        _sessions.pop(user, None)


def ask_stream(
    prompt: str,
    user: str = "local",
    readonly: bool = True,
    new_dialog: bool = False,
    extra_prompt: str = "",
    crm: bool = False,
) -> Iterator[tuple[str, str]]:
    """Отдаёт пары (вид, текст): ('tool', имя) | ('text', кусок) | ('done', ответ)."""
    cli = find_cli()
    if cli is None:
        raise ClaudeCliError(
            "Claude CLI не установлен. На сервере выполни:\n"
            "npm install -g @anthropic-ai/claude-code\nзатем: claude login"
        )
    if crm:
        _trust_crm_project()
    # CRM: история уже в тексте вопроса. --resume тащит личность «архивного» умника.
    previous = None if (new_dialog or crm) else _session_for(user)
    args, workdir = build_cli_args(
        cli,
        prompt,
        readonly=readonly,
        crm=crm,
        extra_prompt=extra_prompt,
        previous=previous,
    )

    if not _gate.acquire(timeout=CLAUDE_TIMEOUT_SEC):
        raise ClaudeCliError("Claude сейчас занят другими запросами, попробуй ещё раз.")
    try:
        yield from _run(args, user, cwd=workdir, sandbox=crm)
    finally:
        _gate.release()


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def _humanize_tool_blob(name: str, blob: str) -> str:
    raw = (blob or "").strip()
    short = name.replace(f"mcp__{MCP_NAME}__", "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        deleted = data.get("deleted")
        if data.get("ok") and isinstance(deleted, dict):
            code = deleted.get("project_code") or ""
            pk = deleted.get("id")
            return f"Удалил сделку #{pk} «{code}»." if pk else f"Удалил «{code}»."
        if data.get("ok") is False:
            return data.get("detail") or data.get("error") or raw[:800]
        if data.get("ok") and data.get("changed"):
            keys = data.get("changed") or data.get("changed_keys") or True
            return f"Изменил сделку: {keys}."
        if data.get("ok"):
            return raw[:1500]
    if raw:
        return f"{short}: {raw[:1500]}"
    return f"{short}: без текста."


def _answer_from_tools(notes: list[tuple[str, str]], attempted: list[str] | None = None) -> str:
    if notes:
        return "\n".join(_humanize_tool_blob(name, blob) for name, blob in notes[-6:])
    if attempted:
        names = ", ".join(dict.fromkeys(attempted))
        return f"Вызвал {names}, но без текста результата. Напиши ещё раз коротко, что сделать."
    return (
        "Не получилось вызвать инструменты (файлы D:\\CH-CRM или CRM). "
        "Напиши ещё раз коротко, что сделать."
    )


def _with_attach_lines(answer: str, attached: list[str]) -> str:
    extra = [line for line in attached if line not in (answer or "")]
    if not extra:
        return answer
    return (answer or "").rstrip() + "\n" + "\n".join(extra)


def _public_args(args: list[str]) -> list[str]:
    hide = {"-p", "--append-system-prompt", "--system-prompt"}
    out: list[str] = []
    skip = False
    for item in args:
        if skip:
            out.append("<hidden>")
            skip = False
            continue
        if item in hide:
            out.append(item)
            skip = True
            continue
        out.append(item)
    return out


def _dump_last(
    *,
    args: list[str],
    cwd: str,
    stderr: str,
    events: int,
    tools: list[str],
    answer: str,
    code: int | None,
    result_error: str = "",
) -> None:
    payload = {
        "cwd": cwd,
        "args": _public_args(args),
        "exit": code,
        "events": events,
        "tools": tools,
        "answer_len": len(answer or ""),
        "error": (result_error or "")[:1500],
        "stderr": (stderr or "")[-4000:],
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "claude_cli_last.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _run(
    args: list[str],
    user: str,
    cwd: str | None = None,
    sandbox: bool = False,
) -> Iterator[tuple[str, str]]:
    # CREATE_NO_WINDOW + .cmd на Windows срывает запись: Allow некому нажать, skip-permissions не действует.
    flags = 0 if sandbox or os.name != "nt" else subprocess.CREATE_NO_WINDOW
    workdir = cwd or str(ROOT)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=proxy_env(sandbox=sandbox),
        cwd=workdir,
        creationflags=flags,
    )
    err_chunks: list[str] = []

    def _drain_stderr() -> None:
        try:
            err_chunks.append(proc.stderr.read() or "")
        except OSError:
            pass

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()
    answer = ""
    attached: list[str] = []
    pending_tools: list[str] = []
    attempted: list[str] = []
    tool_notes: list[tuple[str, str]] = []
    events = 0
    result_error = ""
    code: int | None = None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events += 1
            kind = event.get("type")
            if kind == "system" and event.get("session_id"):
                _remember_session(user, event["session_id"])
            elif kind == "assistant":
                for block in (event.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        answer += block["text"]
                        yield "text", answer
                    elif block.get("type") == "tool_use":
                        name = str(block.get("name") or "")
                        short = name.replace(f"mcp__{MCP_NAME}__", "")
                        pending_tools.append(short)
                        attempted.append(short)
                        yield "tool", short
            elif kind == "user":
                for block in (event.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    blob = _tool_result_text(block)
                    attached.extend(_ATTACH_LINE_RE.findall(blob))
                    name = pending_tools.pop(0) if pending_tools else "tool"
                    tool_notes.append((name, blob or "(пусто)"))
            elif kind == "result":
                if event.get("session_id"):
                    _remember_session(user, event["session_id"])
                text = event.get("result")
                if isinstance(text, dict):
                    text = json.dumps(text, ensure_ascii=False)
                if isinstance(text, str) and text.strip():
                    answer = text
                if event.get("is_error"):
                    result_error = str(text or event.get("errors") or "Claude вернул ошибку.")[:1500]
                    raise ClaudeCliError(result_error)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        err_thread.join(timeout=8)
        err = "".join(err_chunks)
        if err.strip():
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                (DATA_DIR / "claude_cli_last.err").write_text(err[-8000:], encoding="utf-8")
            except OSError:
                pass
        try:
            proc.stderr.close()
        except OSError:
            pass
        try:
            code = proc.wait(timeout=15)
        except Exception:
            code = None
        _dump_last(
            args=args,
            cwd=workdir,
            stderr=err,
            events=events,
            tools=attempted,
            answer=answer,
            code=code,
            result_error=result_error,
        )
        if code not in (0, None) and not answer and not tool_notes:
            raise ClaudeCliError(
                f"Claude CLI завершился с кодом {code}. {' '.join(err.split())[:300]}"
            )
    final = (answer or "").strip()
    if not final or final == "Пустой ответ.":
        final = _answer_from_tools(tool_notes, attempted)
    yield "done", _with_attach_lines(final, attached)
