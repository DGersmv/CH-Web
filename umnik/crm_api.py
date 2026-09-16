"""Простой JSON для CRM: планировки и чат admin без протокола MCP."""
from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


LAYOUT_LIMIT = 5
LAYOUT_LIMIT_MAX = 40
ROOM_LIMIT = 20

CRM_CHAT_PROMPT = """Ты умник-разработчик CRM CH-Web и помощник по сделкам.
Код проекта — папка CRM (родитель umnik/). Писать в файлы уже можно — не проси Allow.
Вопросы про вкладки, меню «Состояние проекта», формы, раздел «Проектирование»,
чек-лист разделов (объединить ОВ/ВК, добавить Навесы/Террасы) — сразу открывай
файлы в D:\\CH-CRM и меняй код. Шаблон разделов: deals/services/design.py.
Если Edit отказал — вызови mcp__arhiv__write_text. Сделки и цифры — инструменты crm_*.
Файл из чата в раздел сделки — crm_attach_design_file (deal_id, slug, attachment_id или source_path, title).
«Добавь в согласования …» (материал, цвет, RAL, решение клиента) — crm_update_approval
(deal_id, slug, append_note). Фасад и отделка — slug finishing.
Не пиши и не правь deals/migrations ради PDF или пункта чек-листа на одной сделке.
Шаблон для всех сделок — DEFAULT_DESIGN_SECTIONS, потом docker compose restart app.
«Найди / поищи / какие есть проекты, хозблоки, планировки, PDF» — это архив:
вызови ask_local_qwen с формулировкой человека (локальный Qwen 14B, сам ходит
в search_layout / search_pdf / search_archive_project). Не отвечай «ничего не нашлось»,
пока не вызвал Qwen. Параллельно можно crm_search_deals.
Правки кода и сделок — сам, без Qwen.
После правок кода скажи, что обновить в браузере.
Не пиши «готов работать с архивом». После инструментов всегда напиши, что сделал."""

CRM_HELLO = (
    "Связь есть. Это умник CRM: сделки, расчёты, поиск проектов в архиве. "
    "Права как у вас в CRM. Чем помочь?"
)


def is_crm_ping(message: str) -> bool:
    text = " ".join((message or "").lower().replace("ё", "е").split()).strip(" .!?")
    return text in {"проверка связи", "привет", "ping", "тест связи"}


_CODE_START = re.compile(r"(?<!\d)\d+\s*МД\b", re.I)
_STATUS_TAIL = re.compile(
    r"\s+(?:New|Production|Lost|Delivered|Contract|Qualified|Prepayment|"
    r"Installation|Sent quote)\s*$",
    re.I,
)


def extract_deal_codes(text: str) -> list[str]:
    """Коды вроде «9МД Тест Ручное Создание» из фразы или вставки таблицы CRM."""
    codes: list[str] = []
    raw = (text or "").replace("\u00a0", " ")
    for chunk in re.split(r"(?<!\d)(?=\d+\s*МД\b)", raw, flags=re.I):
        match = re.match(r"(\d+\s*МД\b.*)", chunk, flags=re.I | re.S)
        if not match:
            continue
        piece = match.group(1).split("\t", 1)[0]
        piece = re.split(r"\s+[—–-]\s+\d+\b", piece, maxsplit=1)[0]
        piece = re.split(r"\s+\d{1,2}\.\d{2}\.\d{4}", piece, maxsplit=1)[0]
        piece = _STATUS_TAIL.sub("", piece).strip(" \t\r\n.—–-")
        piece = " ".join(piece.split())
        if _CODE_START.match(piece) and 3 < len(piece) < 200 and piece not in codes:
            codes.append(piece)
    return codes


def extract_deal_ids(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"(?:сделк\w*|id|#)\s*(\d{1,6})\b", text or "", re.I):
        num = match.group(1)
        if num not in found:
            found.append(num)
    return found


def _payload_json(raw: str) -> dict:
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad_payload", "detail": (raw or "")[:400]}
    return data if isinstance(data, dict) else {"ok": False, "error": "bad_payload"}


def try_direct_crm_action(message: str, caps=None, deal_id=None) -> dict | None:
    """Удаление сделок без Claude: модель часто не вызывает MCP в -p."""
    text = message or ""
    if re.search(r"не\s+удал", text, re.I):
        return None
    if not re.search(r"удал", text, re.I):
        return None
    if not re.search(r"сделк|\d+\s*МД\b|#\s*\d+|id\s*\d+", text, re.I):
        return None
    if re.search(r"удал\w*\s+вс[её]", text, re.I) and not extract_deal_codes(text):
        return {
            "ok": True,
            "answer": (
                "Все сделки сразу не удаляю. Назови коды, "
                "например: 9МД Тест Ручное Создание."
            ),
            "changed": False,
        }
    codes = extract_deal_codes(text)
    ids = [] if codes else extract_deal_ids(text)
    if (
        not codes
        and not ids
        and deal_id not in (None, "")
        and re.search(r"эту сделк", text, re.I)
    ):
        ids = [str(deal_id)]
    if not codes and not ids:
        return {
            "ok": True,
            "answer": "Назови код сделки, например: удали сделку 9МД Тест Ручное Создание.",
            "changed": False,
        }
    allowed = None
    if isinstance(caps, dict) and "can_delete" in caps:
        allowed = bool(caps.get("can_delete"))
    import crm_bridge

    if allowed is None:
        me = _payload_json(crm_bridge.whoami())
        allowed = bool(me.get("can_delete"))
    if not allowed:
        return {
            "ok": True,
            "answer": "Удалять сделки может только admin.",
            "changed": False,
        }
    lines: list[str] = []
    deleted = 0
    targets: list[tuple[str, str]] = [("code", c) for c in codes] + [("id", i) for i in ids]
    for kind, value in targets:
        if kind == "code":
            found = _payload_json(crm_bridge.get_deal(project_code=value))
            deal = found.get("deal") if found.get("ok") else None
            if not isinstance(deal, dict):
                search = _payload_json(crm_bridge.search_deals(value, limit=8))
                items = search.get("deals") if isinstance(search.get("deals"), list) else []
                exact = [row for row in items if (row or {}).get("project_code") == value]
                deal = exact[0] if exact else (items[0] if len(items) == 1 else None)
            if not isinstance(deal, dict):
                lines.append(f"Не нашёл «{value}».")
                continue
            pk = deal.get("id")
            label = deal.get("project_code") or value
        else:
            pk = value
            label = f"#{value}"
        result = _payload_json(crm_bridge.delete_deal(str(pk)))
        if result.get("ok"):
            gone = result.get("deleted") if isinstance(result.get("deleted"), dict) else {}
            code = gone.get("project_code") or label
            lines.append(f"Удалил #{gone.get('id') or pk} «{code}».")
            deleted += 1
        else:
            lines.append(
                f"«{label}»: {result.get('detail') or result.get('error') or 'не удалилось'}."
            )
    answer = "\n".join(lines) if lines else "Не нашёл сделок для удаления."
    return {"ok": True, "answer": answer, "changed": bool(deleted)}


APPROVAL_WRITE_RE = re.compile(
    r"(добав|запиш|внеси|зафиксир)\w*\s+в\s+согласован",
    re.I,
)
APPROVAL_CODE_RE = re.compile(
    r"шаблон|для всех сделок|DEFAULT_APPROVAL|в код|новый пункт",
    re.I,
)
APPROVAL_SLUG_HINTS = (
    ("finishing", ("фасад", "отделк", "материал", "планкен", "ral", "краск", "цвет", "окрас")),
    ("layout", ("планиров",)),
    ("cost_quote", ("стоимост", "смета", "кп")),
    ("bathrooms", ("сануз", "сантех", "плитк")),
    ("electrical", ("электрик", "розеток", "щит")),
    ("additional_options", ("навес", "террас", "доп")),
    ("site", ("участ", "подъезд", "площадк")),
    ("foundation_geology", ("фундамент", "геологи")),
    ("timeline", ("срок", "график")),
    ("contract_data", ("договор", "паспорт", "реквизит")),
)


def guess_approval_slug(message: str) -> str:
    text = (message or "").lower().replace("ё", "е")
    hits = [slug for slug, hints in APPROVAL_SLUG_HINTS if any(hint in text for hint in hints)]
    if "фасад" in text and "finishing" in hits:
        return "finishing"
    return hits[0] if len(hits) == 1 else ""


def extract_approval_note(message: str) -> str:
    text = re.sub(
        r"(?i)^(пожалуйста,?\s*)?(добав|запиш|внеси|зафиксир)\w*\s+в\s+согласован\w*[.:]?\s*",
        "",
        (message or "").strip(),
    )
    return re.sub(r"\s+", " ", text).strip(" .")


def try_direct_approval_action(message: str, deal_id=None) -> dict | None:
    """Запись в чек-лист согласований без Claude: модель часто пишет код вместо crm_update_approval."""
    text = message or ""
    if deal_id in (None, ""):
        return None
    if APPROVAL_CODE_RE.search(text):
        return None
    if not APPROVAL_WRITE_RE.search(text):
        return None
    slug = guess_approval_slug(text)
    note = extract_approval_note(text)
    if not slug or not note:
        return None
    approved = bool(
        re.search(r"уже\s+согласован|поставь\s+согласован|утвердил|клиент\s+соглас", text, re.I)
    )
    status = "approved" if approved else "waiting_client"
    import crm_bridge

    result = _payload_json(
        crm_bridge.update_approval(str(deal_id), slug, status=status, append_note=note)
    )
    if not result.get("ok"):
        return {
            "ok": True,
            "answer": result.get("error") or result.get("detail") or "Не записал в согласования.",
            "changed": False,
        }
    approval = result.get("approval") if isinstance(result.get("approval"), dict) else {}
    title = approval.get("title") or slug
    status_label = approval.get("status_label") or status
    return {
        "ok": True,
        "answer": f"Записал в согласования «{title}»: {note}. Статус: {status_label}.",
        "changed": True,
    }


def compact_layout(row: dict) -> dict:
    rooms = []
    for room in (row.get("rooms") or [])[:ROOM_LIMIT]:
        rooms.append(
            {
                "name": room.get("name") or "",
                "area_m2": room.get("area_m2"),
            }
        )
    path = row.get("path") or ""
    return {
        "path": path,
        "name": Path(path).stem if path else "",
        "object": row.get("object") or "",
        "version": row.get("version") or "",
        "page": row.get("page"),
        "sheet_type": row.get("sheet_type") or "",
        "title": row.get("title") or "",
        "area_total": row.get("area_total"),
        "area_living": row.get("area_living"),
        "room_counts": row.get("room_counts") or {},
        "rooms": rooms,
    }


def lookup_archive(query: str, *, limit: int = LAYOUT_LIMIT) -> dict:
    q = (query or "").strip()
    if not q:
        return {"ok": True, "query": "", "layouts": []}
    from mcp_server import plugin
    from archive_search import file_as_layout, search_project

    rows = plugin().catalog.search_layout(q, limit=limit)
    layouts = [compact_layout(row) for row in rows]
    if layouts:
        return {"ok": True, "query": q, "layouts": layouts}
    found = search_project(q)
    extra = [file_as_layout(path) for path in (found.get("pdfs") or [])[:limit]]
    return {"ok": True, "query": q, "layouts": extra}


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "umnik-crm"})


async def lookup(request: Request) -> JSONResponse:
    query = (request.query_params.get("query") or "").strip()
    try:
        raw_limit = (request.query_params.get("limit") or "").strip()
        limit = int(raw_limit) if raw_limit else LAYOUT_LIMIT
    except ValueError:
        limit = LAYOUT_LIMIT
    limit = max(1, min(limit, LAYOUT_LIMIT_MAX))
    try:
        payload = lookup_archive(query, limit=limit)
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "query": query, "layouts": [], "error": type(exc).__name__},
            status_code=503,
        )
    return JSONResponse(payload)


_agent = None


def _crm_agent():
    global _agent
    if _agent is None:
        from agent import Agent
        from plugins.registry import load_plugins

        _agent = Agent(load_plugins())
    return _agent


def _with_history(message: str, history: list) -> str:
    lines = []
    for item in (history or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content[:2000]}")
    if not lines:
        return message
    return "Диалог:\n" + "\n".join(lines) + "\n\nНовый вопрос:\n" + message


def format_chat_attachments(attachments) -> str:
    """Текст для extra_prompt: id, имя, shared_path вложений этого сообщения."""
    if not isinstance(attachments, list) or not attachments:
        return ""
    lines = ["Вложения этого сообщения:"]
    for att in attachments:
        if not isinstance(att, dict):
            continue
        aid = att.get("id", "")
        name = att.get("name") or att.get("original_name") or ""
        shared = att.get("shared_path") or att.get("path") or ""
        lines.append(f"- id={aid} name={name} shared_path={shared}")
    if len(lines) == 1:
        return ""
    lines.append(
        "Этот файл клади в раздел сделки инструментом crm_attach_design_file "
        "(deal_id, slug, attachment_id или source_path, title). Не пиши data-миграцию Django."
    )
    return "\n".join(lines)


def run_crm_chat(payload: dict) -> dict:
    import crm_bridge
    from agent import strip_thinking

    message = str((payload or {}).get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "empty", "answer": "Пустой вопрос."}
    if is_crm_ping(message):
        return {"ok": True, "answer": CRM_HELLO, "changed": False}
    actor = str((payload or {}).get("actor") or "").strip()
    if not actor:
        return {
            "ok": False,
            "error": "no_actor",
            "answer": "Не вижу, кто пишет в чат. Войдите в CRM под своим логином.",
        }
    deal_id = (payload or {}).get("deal_id")
    deal_code = str((payload or {}).get("deal_code") or "").strip()
    history = (payload or {}).get("history") or []
    extra = CRM_CHAT_PROMPT
    caps = (payload or {}).get("capabilities")
    if isinstance(caps, dict) and caps:
        extra += "\nПрава пользователя: " + json.dumps(caps, ensure_ascii=False)
        if caps.get("can_delete"):
            extra += "\nЭто admin: можно crm_delete_deal. Не пиши, что удалить нельзя."
        else:
            extra += "\nУдалять сделки нельзя: can_delete=false."
    if deal_id not in (None, ""):
        extra += f"\nСейчас открыта сделка id={deal_id}"
        if deal_code:
            extra += f" «{deal_code}»"
        extra += ". Если вопрос про цифры или поля этой сделки — crm_get_deal. Решение в согласования — crm_update_approval. Если про интерфейс и код — правь D:\\CH-CRM."
    extra += "\n" + format_chat_attachments((payload or {}).get("attachments"))
    extra = extra.strip()
    token = crm_bridge.ACTOR.set(actor)
    last = ""
    changed = False
    try:
        direct = try_direct_crm_action(message, caps, deal_id=deal_id)
        if direct is not None:
            return direct
        direct = try_direct_approval_action(message, deal_id=deal_id)
        if direct is not None:
            return direct
        from archive_search import answer_project_search, is_project_search_query

        if is_project_search_query(message, deal_id=deal_id, history=history):
            return answer_project_search(message, actor=actor, history=history)
        for chunk in _crm_agent().ask_stream(
            _with_history(message, history),
            history=history if isinstance(history, list) else [],
            readonly=False,
            user=f"crm-v5:{actor}",
            extra_prompt=extra,
            crm=True,
        ):
            last = chunk
            if "crm_update_" in (chunk or "") or "crm_delete_" in (chunk or "") or "crm_attach_" in (chunk or ""):
                changed = True
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "answer": f"Умник споткнулся: {exc}"}
    finally:
        crm_bridge.ACTOR.reset(token)
    answer = strip_thinking(last).strip()
    if not answer or answer == "Пустой ответ.":
        answer = (
            "Не получил ответ модели. Напиши ещё раз коротко, "
            "например: удали сделку 9МД Тест Ручное Создание."
        )
    return {"ok": True, "answer": answer, "changed": changed}


async def chat(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    import anyio

    result = await anyio.to_thread.run_sync(run_crm_chat, payload)
    status = 200 if result.get("ok") else 503
    return JSONResponse(result, status_code=status)


def attach_crm_routes(app) -> None:
    app.router.routes.insert(0, Route("/crm/health", health, methods=["GET"]))
    app.router.routes.insert(0, Route("/crm/lookup", lookup, methods=["GET"]))
    app.router.routes.insert(0, Route("/crm/chat", chat, methods=["POST"]))


if __name__ == "__main__":
    sample = compact_layout(
        {
            "path": r"D:\Общая_Рабочая\Иванов\план.pdf",
            "object": "Иванов",
            "version": "В1",
            "page": 1,
            "sheet_type": "планировка",
            "title": "1 этаж",
            "area_total": 142.5,
            "area_living": 118.0,
            "room_counts": {"спальня": 3, "сауна": 1},
            "rooms": [{"name": "спальня", "area_m2": 14.2}],
        }
    )
    print(json.dumps(sample, ensure_ascii=False))
