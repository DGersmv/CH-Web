from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from config import ARCHIVE_ROOT, CRM_ROOT, DATA_DIR, ROOT, SKIP_DIR_NAMES, SKIP_DIR_PREFIXES, crm_mode
from plugins.base import SearchHit, SyncStats, ToolSpec

SKIP_PARTS = {".venv", ".git", "__pycache__", "node_modules", ".cursor"}
SKIP_FILES = {".env"}
BLOCK_PARTS = {".venv", ".git", "node_modules"}
SKIP_DIR_LOWER = {n.lower() for n in SKIP_DIR_NAMES} | {p.lower() for p in SKIP_PARTS}
TEXT_SUFFIX = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".log",
    ".py",
    ".bat",
    ".ps1",
    ".toml",
    ".ini",
    ".cfg",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".yml",
    ".yaml",
    ".svg",
    ".dxf",
    ".csv",
}
MAX_READ = 16000
MAX_LIST = 150
MAX_SEARCH = 80
MAX_WALK = 40000


def roots() -> tuple[Path, ...]:
    items = [ARCHIVE_ROOT.resolve(), ROOT.resolve()]
    if crm_mode():
        items.append(CRM_ROOT.resolve())
    return tuple(items)


def deny_outside(path: str) -> str:
    if crm_mode():
        return (
            f"{ARCHIVE_ROOT} — чтение. {ROOT} — Scan_Pdf. {CRM_ROOT} — полный доступ к CRM. "
            f"Не .env. Путь отклонён: {path}"
        )
    return (
        f"{ARCHIVE_ROOT} — только чтение. {ROOT} — полный доступ, кроме .env. "
        f"Путь отклонён: {path}"
    )


def allowed_path(path: str) -> Path | None:
    raw = (path or "").strip().strip('"')
    if not raw:
        return None
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            for root in roots():
                cand = (root / p).resolve()
                if _inside(cand) and cand.exists():
                    return cand
            p = (ARCHIVE_ROOT / p).resolve()
        else:
            p = p.resolve()
        if not _inside(p):
            return None
        if p.name in SKIP_FILES:
            return None
        if any(part.lower() in BLOCK_PARTS for part in p.parts):
            return None
        return p
    except (OSError, RuntimeError, ValueError):
        return None


def _inside(p: Path) -> bool:
    try:
        return any(p == root or p.is_relative_to(root) for root in roots())
    except (OSError, ValueError):
        return False


def _skip_secret(name: str) -> bool:
    return name in SKIP_FILES or name.lower() in {".venv", ".git", "node_modules", "__pycache__", ".cursor"}


def _skip_walk_dir(name: str) -> bool:
    if _skip_secret(name):
        return True
    low = name.lower()
    if low in SKIP_DIR_LOWER or "unrealengine" in low:
        return True
    return any(low.startswith(p) for p in SKIP_DIR_PREFIXES)


def _list_children(folder: Path) -> list[str]:
    lines: list[str] = []
    try:
        children = sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as exc:
        return [f"(не прочитать: {exc})"]
    n = 0
    extra = 0
    for child in children:
        if _skip_secret(child.name):
            continue
        n += 1
        if len(lines) >= MAX_LIST:
            extra += 1
            continue
        mark = "/" if child.is_dir() else ""
        lines.append(f"{child.name}{mark}")
    if extra:
        lines.append(f"… ещё {extra}")
    if not lines:
        lines.append("(пусто или всё скрыто)")
    return lines


def list_dir(path: str = "") -> str:
    raw = (path or "").strip()
    if not raw:
        blocks = [
            "Доступные корни:" if crm_mode() else f"Доступ только на чтение к двум папкам: {ARCHIVE_ROOT} и {ROOT}.",
            "",
        ]
        if crm_mode():
            blocks[0] = (
                f"Режим CRM. Корни: {CRM_ROOT} (правка проектов), "
                f"{ARCHIVE_ROOT} (чтение), {ROOT} (Scan_Pdf)."
            )
        for root in roots():
            blocks.append(f"=== {root} ===")
            blocks.extend(_list_children(root))
            blocks.append("")
        return "\n".join(blocks).rstrip()
    p = allowed_path(raw)
    if p is None:
        return deny_outside(raw)
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        return f"Нет папки: {p}"
    return f"{p}\n" + "\n".join(_list_children(p))


def read_text(path: str = "") -> str:
    p = allowed_path(path)
    if p is None:
        return deny_outside(path)
    if p.is_dir():
        return list_dir(str(p))
    if not p.is_file():
        return f"Файл не найден: {p}"
    suf = p.suffix.lower()
    if suf == ".pdf":
        return f"Это PDF. Для карточки вызови get_pdf_info с путём:\n{p}"
    if suf not in TEXT_SUFFIX:
        return f"Бинарный файл не читаю ({suf or 'без расширения'}). Путь: {p}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Не прочиталось: {exc}"
    if len(text) > MAX_READ:
        text = text[:MAX_READ] + "\n…"
    return f"{p}\n{text}"


def search_name(query: str, under: str = "") -> str:
    q = (query or "").strip().lower().replace("ё", "е")
    if not q:
        return "Укажи фрагмент имени или пути."
    start: list[Path]
    if (under or "").strip():
        p = allowed_path(under)
        if p is None:
            return deny_outside(under)
        start = [p if p.is_dir() else p.parent]
    else:
        start = list(roots())
    hits: list[str] = []
    walked = 0
    for root in start:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            dirnames[:] = [d for d in dirnames if not _skip_walk_dir(d)]
            walked += 1 + len(filenames)
            if walked > MAX_WALK or len(hits) >= MAX_SEARCH:
                break
            blob_dir = dirpath.lower().replace("ё", "е")
            if q in blob_dir:
                rel = dirpath
                if rel not in hits:
                    hits.append(rel + "\\")
            for name in filenames:
                if name in SKIP_FILES:
                    continue
                full = os.path.join(dirpath, name)
                blob = full.lower().replace("ё", "е")
                if q in blob:
                    hits.append(full)
            if len(hits) >= MAX_SEARCH:
                break
        if len(hits) >= MAX_SEARCH:
            break
    if not hits:
        return f"Ничего не нашлось по «{query}» в {', '.join(str(s) for s in start)}."
    extra = ""
    if len(hits) >= MAX_SEARCH:
        extra = f"\n… обрезка по {MAX_SEARCH}"
    return "\n".join(hits[:MAX_SEARCH]) + extra


MAX_WRITE = 400_000


def _in_project(p: Path) -> bool:
    project = ROOT.resolve()
    try:
        return p == project or p.is_relative_to(project)
    except (OSError, ValueError):
        return False


def _in_crm(p: Path) -> bool:
    try:
        crm = CRM_ROOT.resolve()
        return p == crm or p.is_relative_to(crm)
    except (OSError, ValueError):
        return False


def writable_path(path: str) -> Path | None:
    raw = (path or "").strip().strip('"')
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (CRM_ROOT if crm_mode() else ROOT) / p
    try:
        p = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    in_ok = _in_project(p) or (crm_mode() and _in_crm(p))
    if not in_ok:
        return None
    if p.name in SKIP_FILES:
        return None
    if any(part.lower() in BLOCK_PARTS for part in p.parts):
        return None
    return p


def write_text(path: str = "", content: str = "") -> str:
    p = writable_path(path)
    if p is None:
        where = f"{ROOT} или {CRM_ROOT}" if crm_mode() else str(ROOT)
        return f"Писать можно только в {where} (не .env, не архив). Путь отклонён: {path}"
    text = content or ""
    if len(text) > MAX_WRITE:
        return f"Слишком большой текст (>{MAX_WRITE} символов)."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return f"Записал {p} ({len(text)} символов)."


def make_dir(path: str = "") -> str:
    p = writable_path(path)
    if p is None:
        where = f"{ROOT} или {CRM_ROOT}" if crm_mode() else str(ROOT)
        return f"Папки можно создавать только в {where}. Путь отклонён: {path}"
    p.mkdir(parents=True, exist_ok=True)
    return f"Папка: {p}"


def delete_file(path: str = "") -> str:
    p = writable_path(path)
    if p is None or not p.is_file():
        where = f"{ROOT} или {CRM_ROOT}" if crm_mode() else str(ROOT)
        return f"Удалять файлы можно только в {where}. Путь отклонён: {path}"
    p.unlink()
    return f"Удалил {p}"


MAX_SHARE_BYTES = 80 * 1024 * 1024


def attach_file(path: str = "") -> str:
    """Скопировать файл из архива в outbox, чтобы веб-чат отдал его вложением."""
    p = allowed_path(path)
    if p is None or not p.is_file():
        return deny_outside(path) if allowed_path(path) is None else f"Нет файла: {path}"
    try:
        size = p.stat().st_size
    except OSError as exc:
        return f"Не прочитать файл: {exc}"
    if size > MAX_SHARE_BYTES:
        return f"Файл слишком большой для чата ({size} байт). Путь: {p}"
    dest_dir = DATA_DIR / "chat_outbox"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / p.name
    if dest.exists():
        dest = dest_dir / f"{p.stem}_{int(time.time())}{p.suffix}"
    shutil.copy2(p, dest)
    return (
        f"Файл добавлен в чат.\n"
        f"ATTACH_FILE: {dest}\n"
        f"имя: {p.name}\n"
        f"откуда: {p}"
    )


def copy_to_crm(src: str = "", dest: str = "") -> str:
    """Скопировать файл из архива/Scan_Pdf в D:\\CH-CRM (режим CRM)."""
    if not crm_mode():
        return "copy_to_crm только из чата CRM, не из архива."
    src_p = allowed_path(src)
    if src_p is None or not src_p.is_file():
        return f"Источник не найден или вне корней: {src}"
    dest_p = writable_path(dest)
    if dest_p is None:
        return f"Назначение должно быть в {CRM_ROOT} или {ROOT}. Путь отклонён: {dest}"
    if dest_p.exists() and dest_p.is_dir():
        dest_p = dest_p / src_p.name
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_p, dest_p)
    return f"Скопировал {src_p} → {dest_p}"


class WorkspacePlugin:
    name = "workspace"
    title = "Две папки, только чтение"

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="list_dir",
                description=(
                    "Список файлов и папок. Пустой path — корни "
                    f"{ARCHIVE_ROOT} и {ROOT}. Только чтение."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Папка внутри двух корней, можно пусто",
                        }
                    },
                },
                handler=lambda path="", **_: list_dir(path),
            ),
            ToolSpec(
                name="search_name",
                description="Найти файлы и папки по фрагменту имени или пути в двух корнях.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Фрагмент имени или пути"},
                        "under": {
                            "type": "string",
                            "description": "Сузить к одной папке, можно пусто",
                        },
                    },
                    "required": ["query"],
                },
                handler=lambda query="", under="", **_: search_name(query, under),
            ),
            ToolSpec(
                name="read_text",
                description="Прочитать текстовый файл из двух корней. PDF — get_pdf_info. Не .env.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Полный путь или относительно корня"}
                    },
                    "required": ["path"],
                },
                handler=lambda path="", **_: read_text(path),
            ),
            ToolSpec(
                name="write_text",
                description=(
                    f"Записать текстовый файл в {ROOT}. "
                    f"Архив {ARCHIVE_ROOT} только чтение. Не .env."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь внутри D:\\Scan_Pdf"},
                        "content": {"type": "string", "description": "Текст файла"},
                    },
                    "required": ["path"],
                },
                handler=lambda path="", content="", **_: write_text(path, content),
            ),
            ToolSpec(
                name="make_dir",
                description=f"Создать папку в {ROOT}.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь внутри D:\\Scan_Pdf"}
                    },
                    "required": ["path"],
                },
                handler=lambda path="", **_: make_dir(path),
            ),
            ToolSpec(
                name="delete_file",
                description=f"Удалить файл в {ROOT}. Не архив, не .env.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Файл внутри D:\\Scan_Pdf"}
                    },
                    "required": ["path"],
                },
                handler=lambda path="", **_: delete_file(path),
            ),
            ToolSpec(
                name="attach_file",
                description=(
                    "Положить файл из архива в веб-чат, чтобы человек скачал его. "
                    "Путь из search_pdf / list_dir / search_name."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Полный путь к файлу в Общая_Рабочая или Scan_Pdf"}
                    },
                    "required": ["path"],
                },
                handler=lambda path="", **_: attach_file(path),
            ),
            ToolSpec(
                name="list_project",
                description=f"Список в {ROOT}. То же, что list_dir по этой папке.",
                parameters={
                    "type": "object",
                    "properties": {
                        "subdir": {"type": "string", "description": "Подпапка, можно пусто"}
                    },
                },
                handler=lambda subdir="", **_: list_dir(str(ROOT / subdir) if subdir else str(ROOT)),
            ),
            ToolSpec(
                name="read_project",
                description=f"Прочитать текст из {ROOT}.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь внутри проекта"}
                    },
                    "required": ["path"],
                },
                handler=lambda path="", **_: read_text(path),
            ),
        ]

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        return []

    def sync(self, progress=None) -> SyncStats:
        return SyncStats(message="папки только чтение, без индекса")

    def status(self) -> dict:
        return {"roots": [str(ARCHIVE_ROOT), str(ROOT)], "mode": "archive-ro project-rw"}
