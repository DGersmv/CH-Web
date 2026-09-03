from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import ollama

from budget import BUDGET
from config import (
    ARCHIVE_ROOT,
    CHAT_BACKEND,
    CHAT_MODEL_LABELS,
    DEFAULT_CHAT_MODEL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OPENROUTER_API_KEY,
    OPENROUTER_CHAT_MODEL,
    ROOT,
    TOOL_ROUNDS,
    WRITE_TOOLS,
    chat_backend_for,
)
from domain import GLOSSARY_FOR_MODEL, is_layout_query
from openrouter_chat import (
    OpenRouterChatError,
    complete as or_complete,
    tool_call_args,
    tool_call_id,
    tool_call_name,
)
from plugins.base import Plugin, ToolSpec

SYSTEM = f"""Ты умник архива PDF. Только поиск и анализ файлов, не CRM.
{ARCHIVE_ROOT} — только чтение. {ROOT} — полный доступ (не .env).
Не правь сделки. Если просят файл в чат — attach_file.
Не выдумывай пути. Если нужно заглянуть на диск — вызови инструмент.
Если инструмент вернул список — данные есть, перечисли. Не пиши «нет таких данных», пока список не пустой.

Подсказки, не запреты:
- list_dir / search_name / read_text
- write_text / make_dir / delete_file — только папка умника ({ROOT})
- search_pdf / get_pdf_info — PDF
- search_layout / look_at_drawing — комнаты и м² из таблиц
- attach_file — положить найденный файл в чат

{GLOSSARY_FOR_MODEL}"""

SYSTEM_CRM = f"""Ты умник CRM. Сейчас правим сделки и файлы D:\\CH-CRM, не архив.
Права — как у человека в чате (crm_whoami). Admin может удалять сделки через crm_delete_deal.
Не пиши «готов работать с архивом» и не говори, что нет эндпоинта на удаление, если can_delete true.
Не выдумывай пути и суммы. Если нужно заглянуть на диск или в сделку — вызови инструмент.

{GLOSSARY_FOR_MODEL}"""

ATTACH_LINE_RE = re.compile(r"^ATTACH_FILE:\s*.+$", re.M)
PATH_RE = re.compile(r"[A-Za-z]:\\[^\s|\"<>]+")
GENERIC_PARTS = frozenset(
    {
        "d",
        "c",
        "pdf",
        "scan",
        "scans",
        "архив",
        "рабочая",
        "общая",
        "общая_рабочая",
        "планировки",
        "загрузки",
        "документы",
        "проекты",
        "дома",
        "модулей",
        "модуля",
        "users",
        "desktop",
        "downloads",
    }
)
HISTORY_TURNS = 10

ANSWER_MARK = "### Ответ"
THINK_MARK = "### Ход работы"


def _tool_to_ollama(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _short_args(arguments: Any) -> str:
    if isinstance(arguments, str):
        text = arguments
    else:
        try:
            text = json.dumps(arguments, ensure_ascii=False)
        except TypeError:
            text = str(arguments)
    text = " ".join(text.split())
    return text[:180] + ("…" if len(text) > 180 else "")


def _short_result(result: str) -> str:
    text = " ".join((result or "").split())
    return text[:420] + ("…" if len(text) > 420 else "")


def as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return content.decode("utf-8", "replace")
    if isinstance(content, list):
        parts = [as_text(block) for block in content]
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        if content.get("type") == "file" or (
            "path" in content and "text" not in content and "content" not in content
        ):
            file = content.get("file") if isinstance(content.get("file"), dict) else content
            name = (file or {}).get("orig_name") or Path((file or {}).get("path") or "").name
            return f"[файл {name}]" if name else ""
        if "text" in content:
            return as_text(content.get("text"))
        if "content" in content:
            return as_text(content.get("content"))
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    return str(content)


def merge_attach_lines(answer: str, *blobs: str) -> str:
    extra: list[str] = []
    seen = set(ATTACH_LINE_RE.findall(answer or ""))
    for blob in blobs:
        for line in ATTACH_LINE_RE.findall(blob or ""):
            if line not in seen:
                seen.add(line)
                extra.append(line)
    if not extra:
        return answer
    return ((answer or "").rstrip() + "\n" + "\n".join(extra)).strip()


def strip_thinking(content: Any) -> str:
    text = as_text(content)
    if not text:
        return ""
    if ANSWER_MARK in text:
        return text.split(ANSWER_MARK, 1)[1].strip()
    if text.startswith("Ищу") or text.startswith(THINK_MARK):
        return ""
    return text


def format_trace(steps: list[str], answer: str | None = None) -> str:
    body = "\n".join(f"- {s}" for s in steps) if steps else "- думаю…"
    text = f"{THINK_MARK}\n{body}"
    if answer is not None:
        text += f"\n\n{ANSWER_MARK}\n{answer}"
    return text


def _tokens_from_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for path in paths:
        for part in re.split(r"[\\/._\-]+", path):
            t = part.lower().replace("ё", "е").strip()
            if t.endswith("pdf"):
                t = t[:-3].strip()
            if len(t) < 3 or t.isdigit() or t in GENERIC_PARTS or t in seen:
                continue
            seen.add(t)
            tokens.append(t)
    return tokens[:8]


def dialog_focus(history: list[dict[str, str]] | None) -> str:
    paths: list[str] = []
    for item in reversed(history or []):
        if item.get("role") != "assistant":
            continue
        found = PATH_RE.findall(as_text(item.get("content")))
        if found:
            paths = found[:8]
            break
    if not paths:
        return ""
    names = ", ".join(_tokens_from_paths(paths)[:5])
    return f"{names}; {paths[0]}" if names else paths[0]


def _clip(content: str, limit: int = 1600) -> str:
    text = " ".join((content or "").split())
    if len(text) <= limit:
        return content
    return content[:limit].rstrip() + "\n…"


CURRENT_MODEL = DEFAULT_CHAT_MODEL


def chat_model_label() -> str:
    mid = CURRENT_MODEL or DEFAULT_CHAT_MODEL
    return CHAT_MODEL_LABELS.get(mid, mid)


def _use_openrouter(model_id: str | None = None) -> bool:
    mid = model_id or CURRENT_MODEL
    if chat_backend_for(mid) == "ollama":
        return False
    return bool((OPENROUTER_API_KEY or "").strip())


def chat_cost_usd() -> float:
    return BUDGET.spent()


class Agent:
    def __init__(self, plugins: list[Plugin]):
        self.plugins = plugins
        self._by_name: dict[str, ToolSpec] = {}
        for plugin in plugins:
            for tool in plugin.tools():
                self._by_name[tool.name] = tool

    def ollama_tools(self, readonly: bool = False, crm: bool = False) -> list[dict[str, Any]]:
        from config import CRM_TOOLS

        return [
            _tool_to_ollama(t)
            for name, t in self._by_name.items()
            if not (readonly and name in WRITE_TOOLS)
            and (crm or name not in CRM_TOOLS)
        ]

    def dispatch(self, name: str, arguments: Any, readonly: bool = False) -> str:
        spec = self._by_name.get(name)
        if spec is None:
            return f"Неизвестный инструмент: {name}"
        if readonly and name in WRITE_TOOLS:
            return (
                f"{name} недоступен по сети: клиенты из локальной сети работают "
                "только на чтение. Запись — за самим сервером."
            )
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                arguments = {"query": arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            return spec.handler(**arguments)
        except TypeError:
            return spec.handler(arguments.get("query") or arguments.get("path") or "")
        except Exception as exc:
            return f"Ошибка {name}: {exc}"

    def ask_stream(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        model: str | None = None,
        readonly: bool = False,
        user: str = "local",
        extra_prompt: str = "",
        crm: bool = False,
    ) -> Iterator[str]:
        global CURRENT_MODEL
        model_id = (model or CURRENT_MODEL or DEFAULT_CHAT_MODEL).strip()
        CURRENT_MODEL = model_id
        steps = ["читаю вопрос"]
        yield format_trace(steps)
        if chat_backend_for(model_id) == "claude_cli":
            import claude_cli

            ok, note = claude_cli.available()
            if ok:
                try:
                    yield from self._ask_claude(
                        user_message, steps, readonly, user, extra_prompt=extra_prompt, crm=crm
                    )
                    return
                except claude_cli.ClaudeCliError as exc:
                    claude_cli.invalidate()
                    ok, note = False, str(exc)
            if not readonly:
                # За сервером сидит владелец подписки — ему есть что нажать.
                yield format_trace(steps, claude_cli.HINT_SERVER.format(note=note))
                return
            # Сотруднику из сети вход не нужен и недоступен: молча идём к локальному ИИ.
            steps.append("Claude на сервере не подключён — отвечает локальный ИИ")
            yield format_trace(steps)
            model_id = OLLAMA_MODEL
            CURRENT_MODEL = model_id

        system = SYSTEM_CRM if crm else SYSTEM
        if extra_prompt.strip():
            system = system + "\n\n" + extra_prompt.strip()
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        recent = list(history or [])[-HISTORY_TURNS:]
        for item in recent:
            role = item.get("role")
            content = strip_thinking(item.get("content"))
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": _clip(content)})
        focus = dialog_focus(recent)
        follow = bool(
            re.search(
                r"\b(там|этом|этой|ещё|еще|него|неё|внутри|этот проект)\b",
                (user_message or "").lower().replace("ё", "е"),
            )
        )
        if not follow and is_layout_query(user_message):
            focus = ""
        question = user_message
        if focus:
            steps.append(f"помню прошлый проект: {focus.split(';')[0].strip()}")
            yield format_trace(steps)
            question = (
                f"{user_message}\n\n"
                f"[Прошлый шаг: {focus}. Если вопрос про тот же проект или «там/ещё/внутри» — "
                f"ищи только в нём (добавь имя в query или scope). "
                f"Если назвали другой объект — игнорируй этот контекст.]"
            )
        if is_layout_query(user_message) and "search_layout" in self._by_name:
            steps.append("сразу таблицы планировок и м²")
            yield format_trace(steps)
            layout_text = self.dispatch("search_layout", {"query": user_message})
            if len(layout_text) > 24000:
                layout_text = layout_text[:24000].rstrip() + "\n…"
            question = (
                f"{question}\n\n"
                "[Ниже уже результат search_layout из таблиц комнат и площадей. "
                "Если список не пустой — данные есть: перечисли с м² и путём. "
                "Запрещено писать «нет таких данных». Не вызывай search_pdf.]\n\n"
                f"{layout_text}"
            )
        messages.append({"role": "user", "content": question})

        tools = self.ollama_tools(readonly=readonly, crm=crm)
        label = CHAT_MODEL_LABELS.get(model_id, model_id)
        steps.append(f"модель: {label}" + (" · только чтение" if readonly else ""))
        yield format_trace(steps)
        if _use_openrouter(model_id):
            yield from self._ask_openrouter(
                messages, tools, steps, model=model_id, readonly=readonly, user=user
            )
            return
        yield from self._ask_ollama(messages, tools, steps, readonly=readonly)

    def _ask_claude(
        self,
        user_message: str,
        steps: list[str],
        readonly: bool,
        user: str,
        extra_prompt: str = "",
        crm: bool = False,
    ) -> Iterator[str]:
        """Claude по подписке. Историю держит сам CLI — он помнит сессию."""
        import claude_cli

        steps.append("Claude CRM" if crm else "Claude по подписке")
        yield format_trace(steps)
        for kind, payload in claude_cli.ask_stream(
            user_message,
            user=user,
            readonly=readonly,
            extra_prompt=extra_prompt,
            crm=crm,
        ):
            if kind == "tool":
                steps.append(f"вызываю **{payload}**")
                yield format_trace(steps)
            elif kind == "text":
                yield format_trace(steps, payload)
            elif kind == "done":
                yield format_trace(steps + ["готово"], payload)

    def _ask_openrouter(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        steps: list[str],
        model: str | None = None,
        readonly: bool = False,
        user: str = "local",
    ) -> Iterator[str]:
        attached: list[str] = []
        for _ in range(TOOL_ROUNDS):
            steps.append("модель выбирает, чем искать")
            yield format_trace(steps)
            try:
                out = or_complete(messages, tools=tools, model=model)
            except OpenRouterChatError as exc:
                steps.append(f"OpenRouter ошибка, локальная модель: {exc}")
                yield format_trace(steps)
                yield from self._ask_ollama(messages, tools, steps, readonly=readonly)
                return
            BUDGET.add(user, out.get("cost") or 0)
            content = (out.get("content") or "").strip()
            reasoning = (out.get("reasoning") or "").strip()
            if reasoning:
                steps.append("думает: " + " ".join(reasoning.split())[:180])
                yield format_trace(steps)
            tool_calls = out.get("tool_calls") or []
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
            if not tool_calls:
                answer = content or "Пустой ответ модели."
                yield format_trace(steps + ["готово"], merge_attach_lines(answer, *attached))
                return
            for i, call in enumerate(tool_calls):
                name = tool_call_name(call)
                raw_args = tool_call_args(call)
                cid = tool_call_id(call, i)
                steps.append(f"вызываю **{name}**: `{_short_args(raw_args)}`")
                yield format_trace(steps)
                result = self.dispatch(name, raw_args, readonly=readonly)
                attached.append(result)
                steps.append(f"получил: {_short_result(result)}")
                yield format_trace(steps)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "name": name,
                        "content": result,
                    }
                )

        steps.append("собираю итоговый ответ")
        yield format_trace(steps)
        try:
            out = or_complete(messages, tools=None, model=model)
        except OpenRouterChatError as exc:
            yield format_trace(steps, f"Не удалось собрать ответ: {exc}")
            return
        BUDGET.add(user, out.get("cost") or 0)
        answer = (out.get("content") or "").strip() or "Пустой ответ модели."
        yield format_trace(steps, merge_attach_lines(answer, *attached))

    def _ask_ollama(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        steps: list[str],
        readonly: bool = False,
    ) -> Iterator[str]:
        attached: list[str] = []
        for _ in range(TOOL_ROUNDS):
            steps.append("модель выбирает, чем искать")
            yield format_trace(steps)
            content = ""
            tool_calls: list[Any] = []
            stream = ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=tools,
                options={"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.2},
                stream=True,
            )
            for chunk in stream:
                msg = chunk.get("message") or {}
                piece = as_text(msg.get("content"))
                if piece:
                    content += piece
                    yield format_trace(steps + ["пишу черновик"], content)
                extra = msg.get("tool_calls") or []
                if extra:
                    if isinstance(extra, list):
                        tool_calls.extend(extra)
                    else:
                        tool_calls.append(extra)
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
            if not tool_calls:
                answer = content.strip() or "Пустой ответ модели."
                yield format_trace(steps + ["готово"], merge_attach_lines(answer, *attached))
                return
            for call in tool_calls:
                fn = call.get("function") or call
                name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "")
                raw_args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", {})
                steps.append(f"вызываю **{name}**: `{_short_args(raw_args)}`")
                yield format_trace(steps)
                result = self.dispatch(name, raw_args, readonly=readonly)
                attached.append(result)
                steps.append(f"получил: {_short_result(result)}")
                yield format_trace(steps)
                messages.append({"role": "tool", "tool_name": name, "content": result})

        steps.append("собираю итоговый ответ")
        yield format_trace(steps)
        stream = ollama.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            options={"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.2},
            stream=True,
        )
        answer = ""
        for chunk in stream:
            piece = as_text((chunk.get("message") or {}).get("content"))
            if not piece:
                continue
            answer += piece
            yield format_trace(steps, answer)
        yield format_trace(
            steps, merge_attach_lines((answer or "").strip() or "Пустой ответ модели.", *attached)
        )

    def ask(self, user_message: str, history: list[dict[str, str]] | None = None) -> str:
        text = ""
        for text in self.ask_stream(user_message, history=history):
            pass
        return strip_thinking(text) or text
