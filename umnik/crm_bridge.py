"""HTTP к Django CRM. Вызывается только с сервера умника, не из сети."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar

from config import CRM_API_URL, CRM_DEFAULT_ACTOR, MCP_TOKEN

ACTOR: ContextVar[str] = ContextVar("crm_actor", default="")


def _request(method: str, path: str, *, query: dict | None = None, body: dict | None = None) -> dict:
    base = (CRM_API_URL or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "CRM_API_URL пуст"}
    url = f"{base}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    actor = ACTOR.get() or os.environ.get("CRM_ACTOR", "").strip() or CRM_DEFAULT_ACTOR
    headers = {"Accept": "application/json", "X-Umnik-Actor": actor}
    if MCP_TOKEN:
        headers["Authorization"] = f"Bearer {MCP_TOKEN}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict):
                payload.setdefault("ok", False)
                payload.setdefault("error", f"http_{exc.code}")
                return payload
        except json.JSONDecodeError:
            pass
        return {"ok": False, "error": f"http_{exc.code}", "detail": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": "crm_unreachable", "detail": str(exc)}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "bad_payload"}
    return payload


def dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def whoami() -> str:
    return dump(_request("GET", "/api/umnik/me/"))


def search_deals(query: str = "", limit: int = 20) -> str:
    return dump(_request("GET", "/api/umnik/deals/", query={"q": query, "limit": str(limit)}))


def get_deal(deal_id: str = "", project_code: str = "") -> str:
    if str(deal_id).strip():
        return dump(_request("GET", f"/api/umnik/deals/{int(deal_id)}/"))
    return dump(_request("GET", "/api/umnik/deals/lookup/", query={"project_code": project_code}))


def update_deal(deal_id: str, **fields) -> str:
    body = {k: v for k, v in fields.items() if v not in (None, "")}
    return dump(_request("PATCH", f"/api/umnik/deals/{int(deal_id)}/", body=body))


def update_config(deal_id: str, **fields) -> str:
    body = {k: v for k, v in fields.items() if v is not None}
    return dump(_request("PATCH", f"/api/umnik/deals/{int(deal_id)}/config/", body=body))


def update_cost(deal_id: str, materials_total: str = "", work_total: str = "") -> str:
    return dump(
        _request(
            "PATCH",
            f"/api/umnik/deals/{int(deal_id)}/cost/",
            body={"materials_total": materials_total, "work_total": work_total},
        )
    )


def update_approval(
    deal_id: str,
    slug: str,
    status: str = "",
    comment: str = "",
    notes: str = "",
    append_note: str = "",
) -> str:
    body: dict = {"slug": slug}
    if str(status).strip():
        body["status"] = str(status).strip()
    if str(comment).strip():
        body["comment"] = comment
    if str(notes).strip():
        body["notes"] = notes
    if str(append_note).strip():
        body["append_note"] = append_note
    return dump(_request("PATCH", f"/api/umnik/deals/{int(deal_id)}/approval/", body=body))


def attach_design_file(
    deal_id: str,
    slug: str,
    source_path: str = "",
    attachment_id: str = "",
    title: str = "",
) -> str:
    body = {"slug": slug, "title": title}
    if str(attachment_id).strip():
        body["attachment_id"] = str(attachment_id).strip()
    if str(source_path).strip():
        body["source_path"] = str(source_path).strip()
    return dump(_request("POST", f"/api/umnik/deals/{int(deal_id)}/design-file/", body=body))


def delete_deal(deal_id: str = "", project_code: str = "") -> str:
    pk = str(deal_id or "").strip()
    if not pk and (project_code or "").strip():
        found = _request("GET", "/api/umnik/deals/lookup/", query={"project_code": project_code})
        if not found.get("ok"):
            return dump(found)
        pk = str((found.get("deal") or {}).get("id") or "")
    try:
        num = int(pk)
    except (TypeError, ValueError):
        return dump({"ok": False, "error": "invalid deal_id"})
    return dump(_request("DELETE", f"/api/umnik/deals/{num}/"))
