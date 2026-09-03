from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
# MCP — только диск. Claude Pro (Desktop/Cursor) платит подпиской, не OpenRouter.
os.environ["MCP_NO_OPENROUTER"] = "1"
os.environ.pop("OPENROUTER_API_KEY", None)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ARCHIVE_ROOT, CRM_ROOT, ROOT as PROJECT_ROOT, crm_mode
from domain import GLOSSARY_FOR_MODEL
from mcp.server.mcpserver import MCPServer
from mcp_guard import guard_crm, guard_write
from plugins.pdf_archive.plugin import PdfArchivePlugin
from plugins.readonly_fs import (
    allowed_path,
    attach_file as fs_attach_file,
    copy_to_crm as fs_copy_to_crm,
    deny_outside,
    delete_file as fs_delete_file,
    list_dir as fs_list_dir,
    make_dir as fs_make_dir,
    read_text as fs_read_text,
    search_name as fs_search_name,
    write_text as fs_write_text,
)

if crm_mode():
    INSTRUCTIONS = f"""Режим CRM. Сейчас правим проекты, не архив.
- {CRM_ROOT} — полный доступ (не .env)
- {ARCHIVE_ROOT} — только чтение, брать планировки и PDF
- {PROJECT_ROOT} — папка умника (индекс, логи), если нужно положить копию
Сделки: crm_whoami, crm_search_deals, crm_get_deal, crm_update_deal, crm_update_config, crm_update_cost, crm_delete_deal
Файлы: list_dir, read_text, write_text, copy_to_crm
PDF: search_pdf / search_layout / look_at_drawing / attach_file
Не представляйся помощником по архиву.

{GLOSSARY_FOR_MODEL}"""
else:
    INSTRUCTIONS = f"""Две папки:
- {ARCHIVE_ROOT} — только чтение (чертежи, PDF, планировки)
- {PROJECT_ROOT} — полный доступ: читать, писать, создавать, удалять файлы. Не .env.
Тема — поиск и анализ PDF. CRM не трогать.
Чем пользоваться:
- list_dir / search_name / read_text
- write_text / make_dir / delete_file — только {PROJECT_ROOT}
- search_pdf / get_pdf_info / search_layout / look_at_drawing
- attach_file — положить найденный файл в чат, чтобы человек скачал

Если инструмент вернул список — данные есть, перечисли. Не пиши «нет таких данных», пока список не пустой.

{GLOSSARY_FOR_MODEL}"""

mcp = MCPServer(
    name="arhiv",
    title="Умник CRM / архив",
    instructions=INSTRUCTIONS,
)

_plugin: PdfArchivePlugin | None = None


def plugin() -> PdfArchivePlugin:
    global _plugin
    if _plugin is None:
        _plugin = PdfArchivePlugin()
    return _plugin


def mcp_command_block() -> dict:
    from claude_desktop import desktop_mcp_block

    return desktop_mcp_block()


def merge_mcp_json(path: Path) -> Path:
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
    data["mcpServers"]["obshaya-rabochaya"] = mcp_command_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def install_configs() -> int:
    from claude_desktop import mcp_http_url, write_claude_mcp_config, write_client_config

    dest = write_claude_mcp_config()
    client = write_client_config()
    print(f"Claude Desktop на сервере: {dest}")
    print(f"Файл для сотрудников: {client}")
    print(f"HTTP MCP: {mcp_http_url()}")
    print("Инструкция для сети — SETUP_LAN.md")
    return 0


@mcp.tool(
    description=(
        "Комнаты, площади, спальни, сауна, проёмы из таблиц. "
        "Любой вопрос про состав дома — можно сюда."
    ),
    structured_output=False,
)
def search_layout(query: str) -> str:
    return plugin()._tool_layout(query)


@mcp.tool(
    description=(
        "Найти PDF по имени файла, объекта, папке, году, 1МД/2МД или любой другой подписи."
    ),
    structured_output=False,
)
def search_pdf(query: str, scope: str = "") -> str:
    return plugin()._tool_search(query, scope)


@mcp.tool(
    description="Карточка одного PDF по полному пути из поиска: страницы, вид, штамп, сниппет.",
    structured_output=False,
)
def get_pdf_info(path: str) -> str:
    p = allowed_path(path)
    if p is None:
        return deny_outside(path)
    return plugin()._tool_info(str(p))


@mcp.tool(
    description=(
        "Комнаты и площади одного PDF из уже готовых таблиц. "
        "Не распознаёт чертеж заново и не ходит в облако. "
        "Если таблиц нет — search_layout по объекту."
    ),
    structured_output=False,
)
def look_at_drawing(path: str) -> str:
    p = allowed_path(path)
    if p is None:
        return deny_outside(path)
    plug = plugin()
    if plug.catalog.search_layout(p.name, limit=3):
        return plug._tool_layout(p.name)
    facts = plug.catalog.vision_for_file(str(p))
    done = [
        {"page": f.get("page"), "summary": f.get("summary")}
        for f in facts
        if (f.get("summary") or "").strip() and not f.get("error")
    ]
    if done:
        return json.dumps(done, ensure_ascii=False, indent=2)
    return (
        "Этого листа ещё нет в таблицах. MCP не вызывает OpenRouter. "
        "Можно search_layout / search_name / list_dir по той же папке."
    )


@mcp.tool(
    description=(
        "Положить файл из архива в веб-чат, чтобы человек скачал. "
        "Путь бери из search_pdf / search_name / list_dir."
    ),
    structured_output=False,
)
def attach_file(path: str) -> str:
    return fs_attach_file(path)


@mcp.tool(
    description=(
                    "Список файлов и папок. Пустой path — оба корня. "
                    f"{ARCHIVE_ROOT} чтение, {PROJECT_ROOT} полный доступ."
    ),
    structured_output=False,
)
def list_dir(path: str = "") -> str:
    return fs_list_dir(path)


@mcp.tool(
    description="Найти файлы и папки по фрагменту имени или пути в двух корнях.",
    structured_output=False,
)
def search_name(query: str, under: str = "") -> str:
    return fs_search_name(query, under)


@mcp.tool(
    description="Прочитать текстовый файл из двух корней. PDF — get_pdf_info. Не .env.",
    structured_output=False,
)
def read_text(path: str) -> str:
    p = allowed_path(path)
    if p is None:
        return deny_outside(path)
    return fs_read_text(str(p))


@mcp.tool(
    description=f"Список в {PROJECT_ROOT}. То же, что list_dir по этой папке.",
    structured_output=False,
)
def list_project(subdir: str = "") -> str:
    return fs_list_dir(str(PROJECT_ROOT / subdir) if subdir else str(PROJECT_ROOT))


@mcp.tool(
    description=f"Прочитать текст из {PROJECT_ROOT}.",
    structured_output=False,
)
def read_project(path: str) -> str:
    return fs_read_text(path)


@mcp.tool(
    description="Кто сейчас в чате CRM и какие у него права (смотреть / менять / удалять сделки).",
    structured_output=False,
)
def crm_whoami() -> str:
    import crm_bridge

    return guard_crm("crm_whoami") or crm_bridge.whoami()


@mcp.tool(
    description="Найти сделки в CRM по коду, фамилии или участку. Вернёт id и статус.",
    structured_output=False,
)
def crm_search_deals(query: str = "") -> str:
    import crm_bridge

    return guard_crm("crm_search_deals") or crm_bridge.search_deals(query)


@mcp.tool(
    description="Карточка сделки CRM: статус, модули, наценка, конфигуратор, суммы. Нужен deal_id или project_code.",
    structured_output=False,
)
def crm_get_deal(deal_id: str = "", project_code: str = "") -> str:
    import crm_bridge

    return guard_crm("crm_get_deal") or crm_bridge.get_deal(deal_id, project_code)


@mcp.tool(
    description=(
        "Изменить сделку CRM. deal_id обязателен. "
        "Можно status (new/qualified/sent_quote/contract/prepayment/production/installation/delivered/lost), "
        "margin_percent, module_count, project_code, assigned_manager, code_client_name, code_site_name."
    ),
    structured_output=False,
)
def crm_update_deal(
    deal_id: str,
    status: str = "",
    margin_percent: str = "",
    module_count: str = "",
    project_code: str = "",
    assigned_manager: str = "",
    code_client_name: str = "",
    code_site_name: str = "",
) -> str:
    import crm_bridge

    return guard_crm("crm_update_deal") or crm_bridge.update_deal(
        deal_id,
        status=status,
        margin_percent=margin_percent,
        module_count=module_count,
        project_code=project_code,
        assigned_manager=assigned_manager,
        code_client_name=code_client_name,
        code_site_name=code_site_name,
    )


@mcp.tool(
    description=(
        "Поменять поля конфигуратора и пересчитать смету. deal_id обязателен. "
        "fields_json — JSON, например {\"living_area\": 110, \"building_area\": 140, \"bathrooms_count\": 2}."
    ),
    structured_output=False,
)
def crm_update_config(deal_id: str, fields_json: str) -> str:
    import json

    import crm_bridge

    blocked = guard_crm("crm_update_config")
    if blocked:
        return blocked
    try:
        fields = json.loads(fields_json or "{}")
    except json.JSONDecodeError:
        return json.dumps({"ok": False, "error": "fields_json is not JSON"}, ensure_ascii=False)
    if not isinstance(fields, dict):
        return json.dumps({"ok": False, "error": "fields_json must be an object"}, ensure_ascii=False)
    return crm_bridge.update_config(deal_id, **fields)


@mcp.tool(
    description="Вручную поправить итоги сметы сделки: materials_total и work_total в рублях. Наценка применится сама.",
    structured_output=False,
)
def crm_update_cost(deal_id: str, materials_total: str, work_total: str) -> str:
    import crm_bridge

    return guard_crm("crm_update_cost") or crm_bridge.update_cost(
        deal_id, materials_total=materials_total, work_total=work_total
    )


@mcp.tool(
    description=(
        "Удалить сделку CRM целиком. Только если у пользователя can_delete=true (admin). "
        "Нужен deal_id или project_code (например «9МД Тест Ручное Создание»)."
    ),
    structured_output=False,
)
def crm_delete_deal(deal_id: str = "", project_code: str = "") -> str:
    import crm_bridge

    return guard_crm("crm_delete_deal") or crm_bridge.delete_deal(deal_id, project_code)


@mcp.tool(
    description=(
        "Скопировать PDF или другой файл из архива/Scan_Pdf в D:\\CH-CRM. "
        "Только чат CRM. dest — полный путь внутри CH-CRM."
    ),
    structured_output=False,
)
def copy_to_crm(src: str, dest: str) -> str:
    return guard_crm("copy_to_crm") or fs_copy_to_crm(src, dest)


_WRITE_WHERE = f"{PROJECT_ROOT} или {CRM_ROOT}" if crm_mode() else str(PROJECT_ROOT)


@mcp.tool(
    description=f"Записать текстовый файл в {_WRITE_WHERE}. Архив только чтение. Не .env.",
    structured_output=False,
)
def write_text(path: str, content: str = "") -> str:
    return guard_write("write_text") or fs_write_text(path, content)


@mcp.tool(
    description=f"Создать папку в {_WRITE_WHERE}.",
    structured_output=False,
)
def make_dir(path: str) -> str:
    return guard_write("make_dir") or fs_make_dir(path)


@mcp.tool(
    description=f"Удалить файл в {_WRITE_WHERE}. Не архив, не .env.",
    structured_output=False,
)
def delete_file(path: str) -> str:
    return guard_write("delete_file") or fs_delete_file(path)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    args = sys.argv[1:]
    if args and args[0] in {"--install", "install"}:
        raise SystemExit(install_configs())
    if args and args[0] in {"--http", "http"}:
        from config import MCP_HOST, MCP_PORT

        host = MCP_HOST
        port = MCP_PORT
        i = 1
        while i < len(args):
            if args[i] == "--host" and i + 1 < len(args):
                host = args[i + 1]
                i += 2
                continue
            if args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
                continue
            i += 1
        import uvicorn

        from config import MCP_TOKEN
        from crm_api import attach_crm_routes
        from mcp_guard import GuardMiddleware
        from net import urls as lan_urls

        starlette_app = mcp.streamable_http_app(stateless_http=True, host=host)
        attach_crm_routes(starlette_app)
        app = GuardMiddleware(starlette_app)
        for u in lan_urls(port, "/mcp"):
            print(f"MCP: {u}", file=sys.stderr)
        for u in lan_urls(port, "/crm/lookup"):
            print(f"CRM: {u}", file=sys.stderr)
        if not MCP_TOKEN:
            print(
                "ВНИМАНИЕ: MCP_TOKEN в .env пуст — по сети пускаем без пароля.",
                file=sys.stderr,
            )
        try:
            from plugins.registry import load_plugins
            from watcher import Watcher

            Watcher(load_plugins()).start(run_immediately=False)
            print("Индекс архива: фоновое обновление включено.", file=sys.stderr)
        except Exception as exc:
            print(f"Индекс архива не запущен: {exc}", file=sys.stderr)
        uvicorn.run(app, host=host, port=port, log_level="warning")
        raise SystemExit(0)
    mcp.run(transport="stdio")
