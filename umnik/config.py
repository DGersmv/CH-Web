import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT") or r"D:\Общая_Рабочая")
# local — один процесс как раньше (разработка).
# indexer — офис: читает PDF, публикует индекс в S3, поиск CRM не обслуживает.
# query — облако: тянет индекс, отвечает CRM lookup/chat.
UMNIK_ROLE = (os.environ.get("UMNIK_ROLE") or "local").strip().lower()
INDEX_S3_BUCKET = (os.environ.get("INDEX_S3_BUCKET") or "").strip()
INDEX_S3_PREFIX = (os.environ.get("INDEX_S3_PREFIX") or "umnik-index").strip()
INDEX_S3_ENDPOINT = (os.environ.get("INDEX_S3_ENDPOINT") or os.environ.get("AWS_S3_ENDPOINT_URL") or "").strip()
INDEX_S3_REGION = (os.environ.get("INDEX_S3_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ru-central1").strip()
INDEX_S3_ACCESS_KEY = (
    os.environ.get("INDEX_S3_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID") or ""
).strip()
INDEX_S3_SECRET_KEY = (
    os.environ.get("INDEX_S3_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY") or ""
).strip()
INDEX_SNAPSHOT_DIR = (os.environ.get("INDEX_SNAPSHOT_DIR") or "").strip()


def umnik_role() -> str:
    role = UMNIK_ROLE if UMNIK_ROLE in {"local", "indexer", "query"} else "local"
    return role


def is_indexer() -> bool:
    return umnik_role() == "indexer"


def is_query() -> bool:
    return umnik_role() == "query"


OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_NUM_CTX = 4096
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DEVICE = "cpu"

SYNC_INTERVAL_SEC = 5 * 60
ENABLED_PLUGINS = ["pdf_archive", "workspace"]

# Папки, где PDF почти нет, а файлов миллионы — не обходим
SKIP_DIR_NAMES = {
    "unrealengine",
    "seafile",
    "node_modules",
    ".git",
    "__pycache__",
    "$recycle.bin",
    "system volume information",
}

SKIP_DIR_PREFIXES = (
    "syncthing",
    "adobe.acrobat",
    "ultraiso",
)

MAX_PAGES_EMBED = 40
MAX_CHARS_PAGE = 2500
MIN_CHARS_EMBED = 40
SEARCH_LIMIT = 8
LAYOUT_PROGRAM_LIMIT = 80
TOOL_ROUNDS = 4
GRADIO_PORT = int(os.environ.get("GRADIO_PORT", "7860"))
GRADIO_HOST = (os.environ.get("GRADIO_HOST") or "0.0.0.0").strip()
MCP_PORT = int(os.environ.get("MCP_PORT", "7861"))
MCP_HOST = (os.environ.get("MCP_HOST") or "0.0.0.0").strip()
# Пусто — адрес считается из net.primary_ip(), чтобы смена IP по DHCP ничего не ломала.
MCP_HTTP_URL = (os.environ.get("MCP_HTTP_URL") or "").strip()
# Общий пароль для MCP из сети. Пусто — по сети пускаем без пароля (не советую).
MCP_TOKEN = (os.environ.get("MCP_TOKEN") or "").strip()
OLLAMA_VL_MODEL = "qwen2.5vl:7b"
VISION_DPI = 110
VISION_MAX_SIDE = 1400
VISION_PAGES_PER_FILE = 3
VISION_INTERVAL_SEC = 8
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen2.5-vl-72b-instruct")
OPENROUTER_CHAT_MODEL = os.environ.get(
    "OPENROUTER_CHAT_MODEL", "qwen/qwen3-235b-a22b-2507"
)
OPENROUTER_MAX_USD = float(os.environ.get("OPENROUTER_MAX_USD", "4.0"))
# Потолок на одного человека в сутки. Чат открыт всей сети — без него один
# пользователь выжигает общий баланс.
CHAT_MAX_USD_PER_USER = float(os.environ.get("CHAT_MAX_USD_PER_USER", "1.0"))
OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "4096"))
OPENROUTER_PROXY = (
    os.environ.get("OPENROUTER_PROXY")
    or os.environ.get("HTTPS_PROXY")
    or os.environ.get("HTTP_PROXY")
    or ""
).strip()

# ── Доступ из локальной сети ────────────────────────────────────────────────
# "ivan:пароль,petr:пароль" — вход в веб-чат. Пусто = без пароля, любой в сети войдёт.
WEB_USERS_RAW = (os.environ.get("WEB_USERS") or "").strip()


def _parse_web_users(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item or ":" not in item:
            continue
        name, password = item.split(":", 1)
        name, password = name.strip(), password.strip()
        if name and password:
            pairs.append((name, password))
    return pairs


WEB_USERS = _parse_web_users(WEB_USERS_RAW)
# Клиенты не с этого компьютера не пишут и не удаляют в папке умника.
LAN_READONLY = (os.environ.get("LAN_READONLY") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
WRITE_TOOLS = frozenset(
    {
        "write_text",
        "make_dir",
        "delete_file",
        "restart_crm",
        "crm_update_deal",
        "crm_update_config",
        "crm_update_cost",
        "crm_delete_deal",
        "crm_attach_design_file",
        "crm_update_approval",
    }
)
CODE_WRITE_TOOLS = frozenset(
    {
        "write_text",
        "make_dir",
        "delete_file",
        "restart_crm",
    }
)
CRM_TOOLS = frozenset(
    {
        "crm_whoami",
        "crm_search_deals",
        "crm_get_deal",
        "crm_update_deal",
        "crm_update_config",
        "crm_update_cost",
        "crm_delete_deal",
        "crm_attach_design_file",
        "crm_update_approval",
        "copy_to_crm",
        "restart_crm",
    }
)
# Обратный вызов в Django CRM (умник на хосте → контейнер на :8001).
CRM_API_URL = (os.environ.get("CRM_API_URL") or "http://127.0.0.1:8001").strip()
# Умник живёт в D:\CH-CRM\umnik — корень CRM на уровень выше, если не задан явно.
CRM_ROOT = Path(os.environ.get("CRM_ROOT") or str(ROOT.parent))
# От чьего имени идут crm_* вне чата CRM (Claude Code, тесты): в чате актор
# берётся из сессии, здесь его некому подставить и Django отвечал unauthorized.
CRM_DEFAULT_ACTOR = (os.environ.get("CRM_DEFAULT_ACTOR") or "admin").strip()
PLATFORM_OWNER_USERNAME = (os.environ.get("PLATFORM_OWNER_USERNAME") or "superadmin").strip() or "superadmin"


def crm_mode() -> bool:
    return os.environ.get("MCP_CRM_MODE", "").strip().lower() in {"1", "true", "yes"}


def edit_code_now() -> bool:
    return os.environ.get("MCP_EDIT_CODE", "").strip().lower() in {"1", "true", "yes"}

# Claude идёт через CLI и подписку (логин-пароль), а не через API-ключ.
CLAUDE_SUBSCRIPTION = "claude-подписка"
# Alias opus — актуальная Opus на аккаунте, не конкретный ID вроде claude-opus-4-8.
CLAUDE_CLI_MODEL = (os.environ.get("CLAUDE_CLI_MODEL") or "opus").strip()
# Сколько запросов к Claude выполняем одновременно: подписка одна на всех.
CLAUDE_MAX_PARALLEL = int(os.environ.get("CLAUDE_MAX_PARALLEL", "2"))
CLAUDE_TIMEOUT_SEC = int(os.environ.get("CLAUDE_TIMEOUT_SEC", "300"))

CHAT_MODELS = (
    (CLAUDE_SUBSCRIPTION, "Claude Opus — подписка"),
    ("qwen2.5:14b", "Локальный ИИ (Qwen2.5 14B)"),
)
CHAT_MODEL_LABELS = {mid: label for mid, label in CHAT_MODELS}


def _default_chat_model() -> str:
    return CLAUDE_SUBSCRIPTION


DEFAULT_CHAT_MODEL = _default_chat_model()


def chat_backend_for(model_id: str) -> str:
    mid = (model_id or DEFAULT_CHAT_MODEL).strip()
    if mid == CLAUDE_SUBSCRIPTION:
        return "claude_cli"
    if "/" not in mid:
        return "ollama"
    return "openrouter"
