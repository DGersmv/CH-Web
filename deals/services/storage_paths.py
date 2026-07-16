import re
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify


def slugify_safe(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    slug = slugify(cleaned, allow_unicode=True)
    return slug or fallback


def get_files_root() -> Path:
    return Path(settings.CRM_FILES_ROOT)


def get_client_root(client) -> Path:
    if client is None:
        return get_files_root() / "clients" / "client-unknown"
    return get_files_root() / "clients" / f"{client.id}-{slugify_safe(client.full_name, 'client')}"


def get_deal_root(deal) -> Path:
    client = deal.client if deal and deal.client_id else None
    return get_client_root(client) / "projects" / f"{deal.id}-{slugify_safe(deal.project_code, 'project')}"


def get_version_root(project_version) -> Path:
    return get_deal_root(project_version.deal) / "versions" / f"v{project_version.version_number}"


def ensure_deal_dirs(deal) -> None:
    deal_root = get_deal_root(deal)
    for suffix in (
        Path("incoming/client/photos"),
        Path("incoming/client/docs"),
        Path("incoming/client/voice"),
        Path("incoming/designer/plans_pdf"),
        Path("incoming/designer/dwg"),
        Path("incoming/designer/reference"),
        Path("incoming/sales/photos"),
        Path("incoming/sales/docs"),
        Path("outgoing/client"),
        Path("system"),
        Path("archive"),
    ):
        (deal_root / suffix).mkdir(parents=True, exist_ok=True)


def ensure_version_dirs(project_version) -> None:
    version_root = get_version_root(project_version)
    for suffix in (
        Path("plan"),
        Path("quote"),
    ):
        (version_root / suffix).mkdir(parents=True, exist_ok=True)


def ensure_library_dirs() -> None:
    library_root = get_files_root() / "library"
    for section in ("layouts", "photos", "videos"):
        for module_group in ("m1", "m2", "m3", "m4", "m5", "m6plus"):
            (library_root / section / module_group).mkdir(parents=True, exist_ok=True)
    (library_root / "contracts").mkdir(parents=True, exist_ok=True)
    for supplier_category in (
        "finishing",
        "plumbing",
        "electrical",
        "floor_heating",
        "stoves_fireplaces",
        "windows",
        "furniture",
    ):
        (library_root / "suppliers" / supplier_category).mkdir(parents=True, exist_ok=True)
