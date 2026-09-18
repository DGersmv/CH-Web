"""Узкие операции на хосте: только docker compose restart app."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from config import CRM_ROOT, PLATFORM_OWNER_USERNAME
from crm_bridge import ACTOR, whoami


def current_actor() -> str:
    return (ACTOR.get() or os.environ.get("CRM_ACTOR") or "").strip()


def actor_may_restart(actor: str = "", caps: dict | None = None) -> bool:
    name = (actor or current_actor()).strip()
    if isinstance(caps, dict):
        if caps.get("can_restart_crm") or caps.get("can_edit_code"):
            return True
        if caps.get("is_superuser"):
            return True
        if caps.get("is_platform_owner"):
            return True
    owner = (PLATFORM_OWNER_USERNAME or "superadmin").strip() or "superadmin"
    return bool(name) and name == owner


def confirm_owner_via_crm(actor: str) -> bool:
    token = ACTOR.set(actor)
    try:
        raw = whoami()
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    finally:
        ACTOR.reset(token)
    if isinstance(data, dict) and data.get("ok"):
        return bool(
            data.get("can_restart_crm")
            or data.get("can_edit_code")
            or data.get("is_platform_owner")
            or data.get("is_superuser")
        )
    return actor_may_restart(actor)


def restart_crm_app() -> dict:
    compose = CRM_ROOT / "docker-compose.yml"
    if not compose.is_file():
        return {"ok": False, "error": "no_compose", "answer": f"Нет {compose}"}
    docker = shutil.which("docker") or "/usr/bin/docker"
    if not Path(docker).exists() and docker.startswith("/"):
        return {"ok": False, "error": "no_docker", "answer": "docker не найден на хосте."}
    cmd = [docker, "compose", "-f", str(compose), "restart", "app"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(CRM_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": "restart_failed", "answer": str(exc)}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:800]
        return {"ok": False, "error": "restart_failed", "answer": detail or "docker compose restart app не удался"}
    return {
        "ok": True,
        "via": "compose",
        "answer": "Перезапускаю контейнер CRM (app). База и умник не тронуты.",
    }
