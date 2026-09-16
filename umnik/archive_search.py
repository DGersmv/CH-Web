"""Поиск проектов в архиве D:\\Общая_Рабочая — тот же умник, что ищет PDF.

Чат CRM запускает его вторым агентом: сделки смотрит CRM, папки и чертежи — архив.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from domain import layout_object_tokens, _norm

SKIP_NAME = {".db", ".bak", "thumbs.db", "plot.log", "audit report.txt"}
SKIP_SUFFIX = {".bak", ".db", ".tmp", ".log"}
PLAN_STEMS = (
    "планиров",
    "размерн",
    "эскиз",
    "итог",
    "в1",
    "в2",
    "в3",
    "мд",
)
PATH_NOISE = frozenset(
    {
        "общая",
        "рабочая",
        "работы",
        "загрузки",
        "документы",
        "планировки",
        "telegram",
        "desktop",
        "юра",
        "валя",
    }
)
CRM_ONLY_RE = re.compile(
    r"удал|измени\s+статус|поставь\s+статус|наценк|смет[аеуы]|конфигуратор|"
    r"правь(?:\s+код)?|вкладк|django|шаблон|меню\s+состояние|"
    r"сделай|сделаем|объедин|добав(?:им|ить|ьте)|раздел|"
    r"проектирован|чек.?лист|для\s+каждого",
    re.I,
)
FOLLOW_RE = re.compile(
    r"ещ[её]\s+раз|посмотр|что\s+тут|что\s+здесь|в\s+этой\s+папк|из\s+этой|"
    r"финальн|итогов|нужен|нужна|скинь|открой|внутри|лежит",
    re.I,
)
WANT_PLAN_RE = re.compile(r"финальн|итог|планиров|размерн|план\b|эскиз", re.I)
WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\n\"<>|*?]+")

_pdf_plugin = None


def _plugin():
    global _pdf_plugin
    if _pdf_plugin is None:
        from mcp_server import plugin as load_plugin

        _pdf_plugin = load_plugin()
    return _pdf_plugin


def _want_plan(message: str) -> bool:
    return bool(WANT_PLAN_RE.search(message or ""))


def extract_existing_path(text: str):
    """Самый длинный существующий путь из фразы (хвост «посмотри…» отрезается)."""
    from plugins.readonly_fs import allowed_path

    found = None
    for match in WIN_PATH_RE.finditer(text or ""):
        raw = match.group(0).rstrip(" .,;\"'")
        while raw:
            p = allowed_path(raw)
            if p is None:
                try:
                    p = Path(raw)
                except (OSError, ValueError):
                    p = None
            if p is not None and p.exists():
                found = p
                break
            name = Path(raw).name
            if " " not in name:
                break
            parent = Path(raw).parent
            shorter = " ".join(name.split()[:-1])
            raw = str(parent / shorter) if shorter else str(parent)
    return found


def focus_from_history(history) -> Path | None:
    for item in reversed(list(history or [])):
        if not isinstance(item, dict):
            continue
        path = extract_existing_path(str(item.get("content") or ""))
        if path is not None:
            return path
    return None


def archive_query(message: str) -> str:
    path = extract_existing_path(message)
    text = message or ""
    if path is not None:
        text = text.replace(str(path), " ").replace(str(path).replace("\\", "/"), " ")
    tokens = [t for t in layout_object_tokens(text) if t not in PATH_NOISE]
    return " ".join(tokens).strip()


def is_project_search_query(message: str, *, deal_id=None, history=None) -> bool:
    """Только открыть уже известную папку. «Поищи хозблоки» — не сюда, а в Claude/Qwen."""
    text = (message or "").strip()
    if not text:
        return False
    if CRM_ONLY_RE.search(text):
        return False
    if extract_existing_path(text) is not None:
        return True
    if FOLLOW_RE.search(text) and focus_from_history(history) is not None:
        return True
    return False


def _skip_file(path: str) -> bool:
    name = Path(path).name.lower()
    if name in SKIP_NAME:
        return True
    return Path(path).suffix.lower() in SKIP_SUFFIX


def _parse_name_hits(blob: str) -> tuple[list[str], list[str]]:
    folders: list[str] = []
    files: list[str] = []
    for raw in (blob or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("Ничего") or line.startswith("Укажи") or line.startswith("…"):
            continue
        if line.endswith("\\") or line.endswith("/"):
            folders.append(line.rstrip("\\/"))
            continue
        p = Path(line)
        if not p.suffix:
            folders.append(line)
        elif _skip_file(line):
            continue
        else:
            files.append(line)
    return folders, files


def _pdf_paths_from_search(blob: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"путь:\s*(.+)$", blob or "", re.M):
        path = match.group(1).strip()
        key = path.lower()
        if path and key not in seen:
            seen.add(key)
            paths.append(path)
    return paths


def _score_pdf(path: str, *, want_plan: bool = False) -> int:
    blob = _norm(path)
    score = 0
    for stem in PLAN_STEMS:
        if stem in blob:
            score += 10
    if blob.endswith(".pdf"):
        score += 3
    if "планиров" in blob:
        score += 25
    if "итог" in blob:
        score += 22
    if re.search(r"\d+мд", blob.replace(" ", "")):
        score += 15
    if want_plan and ("финальн" in blob or "итог" in blob or "размерн" in blob):
        score += 20
    if "кд " in blob or "\\кд\\" in blob or "/кд/" in blob:
        score -= 8
    if "вишнев" in blob:
        score -= 40
    return score


def _object_folders(folders: list[str], files: list[str], query: str) -> list[str]:
    tokens = [t for t in _norm(query).split() if len(t) >= 3 and t not in PATH_NOISE]
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    candidates = list(folders)
    for path in files:
        parent = str(Path(path).parent)
        if parent not in candidates:
            candidates.append(parent)
    for folder in candidates:
        key = folder.lower()
        if key in seen:
            continue
        seen.add(key)
        name = _norm(Path(folder).name)
        blob = _norm(folder)
        if not tokens:
            continue
        hit_name = all(t in name for t in tokens)
        hit_all = all(t in blob for t in tokens)
        if not hit_name and not hit_all:
            continue
        score = 80 if hit_name else 25
        ranked.append((score, -len(folder), folder))
    ranked.sort(reverse=True)
    return [item[2] for item in ranked[:4]]


def _pick_pdfs(files: list[str], limit: int = 5, *, want_plan: bool = False) -> list[str]:
    pdfs = [p for p in files if p.lower().endswith(".pdf")]
    pdfs.sort(key=lambda p: _score_pdf(p, want_plan=want_plan), reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for path in pdfs:
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
        if len(out) >= limit:
            break
    return out


def _pdfs_under(folder: Path, limit: int = 40) -> list[str]:
    hits: list[str] = []
    try:
        for child in folder.rglob("*"):
            if not child.is_file() or _skip_file(str(child)):
                continue
            if child.suffix.lower() == ".pdf":
                hits.append(str(child))
            if len(hits) >= 80:
                break
    except OSError:
        return []
    return hits[:limit] if limit else hits


def inspect_folder(folder: Path, *, message: str = "") -> dict:
    from plugins.readonly_fs import allowed_path, list_dir

    p = allowed_path(str(folder)) or folder
    if p.is_file():
        p = p.parent
    listing = list_dir(str(p))
    pdfs_all = _pdfs_under(p)
    want = _want_plan(message)
    pdfs = _pick_pdfs(pdfs_all, limit=6, want_plan=want)
    if want:
        pdfs = [x for x in pdfs if _score_pdf(x, want_plan=True) >= 20] or pdfs[:3]
    label = "Финальный / итоговый план в папке" if want else f"Содержимое папки {p.name}"
    lines = [f"{label}:", str(p), ""]
    lines.append(listing)
    if pdfs:
        lines.append("")
        lines.append("Главные PDF:")
        for path in pdfs:
            lines.append(f"- {path}")
    attach = [x for x in pdfs[:3] if x.lower().endswith(".pdf")]
    return {
        "ok": True,
        "query": str(p),
        "folders": [str(p)],
        "files": pdfs_all,
        "pdfs": pdfs,
        "layouts_text": "",
        "pdf_text": "",
        "text": "\n".join(lines).strip(),
        "attach": attach,
        "inspect": True,
    }


def _name_search(query: str) -> str:
    from plugins.readonly_fs import search_name

    tokens = [t for t in layout_object_tokens(query) if t not in PATH_NOISE]
    joined = " ".join(tokens).strip() or query.strip()
    variants = []
    if joined:
        variants.append(joined)
    if len(tokens) >= 2:
        variants.append(tokens[0] + " " + tokens[-1])
    blob = ""
    for item in variants:
        blob = search_name(item)
        if blob and not blob.startswith("Ничего") and not blob.startswith("Укажи"):
            return blob
    if len(tokens) == 1 and len(tokens[0]) >= 5:
        return search_name(tokens[0])
    return blob or ""


def search_project(query: str, *, history=None) -> dict:
    """Инструменты архивного умника: папка по пути, имя объекта, PDF."""
    empty = {
        "ok": True,
        "query": "",
        "folders": [],
        "files": [],
        "pdfs": [],
        "layouts_text": "",
        "pdf_text": "",
        "text": "",
        "attach": [],
    }
    path = extract_existing_path(query) or (
        focus_from_history(history) if FOLLOW_RE.search(query or "") else None
    )
    if path is not None:
        return inspect_folder(path, message=query)

    q = archive_query(query) or (query or "").strip()
    empty["query"] = q
    if not q:
        empty["text"] = "Назови объект или дай путь к папке."
        return empty

    name_blob = _name_search(q)
    folders, files = _parse_name_hits(name_blob)

    pdf_plugin = _plugin()
    pdf_text = pdf_plugin._tool_search(q)
    layout_text = pdf_plugin._tool_layout(q)
    for item in _pdf_paths_from_search(pdf_text):
        if item not in files:
            files.append(item)

    object_dirs = _object_folders(folders, files, q)
    scoped = []
    if object_dirs:
        root = Path(object_dirs[0])
        scoped = [f for f in files if _norm(f).startswith(_norm(str(root)))]
    pdfs = _pick_pdfs(scoped or files, want_plan=_want_plan(query))
    has_layout_facts = bool(layout_text) and "нет фактов" not in layout_text[:80].lower()
    if not object_dirs and not pdfs and not has_layout_facts:
        empty["pdf_text"] = pdf_text
        empty["layouts_text"] = layout_text
        empty["text"] = f"В архиве ничего не нашлось по «{q}»."
        return empty

    title = Path(object_dirs[0]).name if object_dirs else q
    lines = [f"В архиве проект «{title}»:"]
    if object_dirs:
        lines.append("")
        lines.append("Папка:")
        lines.append(f"- {object_dirs[0]}")
        for extra in object_dirs[1:]:
            lines.append(f"- {extra}")
    if pdfs:
        lines.append("")
        lines.append("Основные PDF:")
        for item in pdfs:
            lines.append(f"- {item}")
    if has_layout_facts:
        lines.append("")
        lines.append(layout_text[:3500])
    extra_files = [p for p in (scoped or files) if p not in pdfs and not _skip_file(p)]
    if extra_files:
        lines.append("")
        lines.append(f"В папке ещё {len(extra_files)} файлов.")

    attach = [p for p in pdfs[:3] if p.lower().endswith(".pdf")]
    return {
        "ok": True,
        "query": q,
        "folders": object_dirs,
        "files": files,
        "pdfs": pdfs,
        "layouts_text": layout_text,
        "pdf_text": pdf_text,
        "text": "\n".join(lines).strip(),
        "attach": attach,
    }


def _format_deals(payload: dict) -> str:
    deals = payload.get("deals") if isinstance(payload, dict) else None
    if not isinstance(deals, list) or not deals:
        return ""
    lines = ["В CRM нашлись сделки:"]
    for row in deals[:8]:
        if not isinstance(row, dict):
            continue
        code = row.get("project_code") or ""
        pk = row.get("id")
        status = row.get("status") or ""
        site = row.get("code_site_name") or ""
        client = row.get("code_client_name") or ""
        bits = [f"#{pk}" if pk else "", f"«{code}»" if code else "", status, client, site]
        lines.append("- " + " ".join(b for b in bits if b))
    return "\n".join(lines)


def run_archive_agent(message: str, *, actor: str = "crm", history=None) -> dict:
    found = search_project(message, history=history)
    return {
        "ok": True,
        "answer": found.get("text") or "В архиве ничего не нашлось.",
        "attachments": list(found.get("attach") or []),
        "changed": False,
        "query": found.get("query") or "",
        "inspect": bool(found.get("inspect")),
    }


def answer_project_search(message: str, *, actor: str = "admin", history=None) -> dict:
    """CRM-сделки + архивный умник. Для чата CH-CRM."""
    archive = run_archive_agent(message, actor=actor, history=history)
    parts: list[str] = []
    if not archive.get("inspect"):
        q = archive_query(message) or (message or "").strip()
        try:
            import crm_bridge

            raw = crm_bridge.search_deals(q, limit=8)
            deals_payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not isinstance(deals_payload, dict):
                deals_payload = {}
            deals_text = _format_deals(deals_payload)
            if deals_text:
                parts.append(deals_text)
        except Exception:
            pass
    parts.append(archive.get("answer") or "")
    answer = "\n\n".join(p for p in parts if p).strip()
    attachments = list(archive.get("attachments") or [])
    if attachments:
        answer = answer + "\n\n" + "\n".join(f"ATTACH_FILE: {path}" for path in attachments)
    return {
        "ok": True,
        "answer": answer,
        "changed": False,
        "attachments": attachments,
    }


def file_as_layout(path: str) -> dict:
    p = Path(path)
    return {
        "path": path,
        "name": p.stem,
        "object": p.parent.name,
        "version": "",
        "page": None,
        "sheet_type": "",
        "title": p.name,
        "area_total": None,
        "area_living": None,
        "room_counts": {},
        "rooms": [],
    }
