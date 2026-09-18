"""Снимок индекса архива: офисный indexer заливает, облачный query забирает."""
from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import (
    DATA_DIR,
    EMBEDDING_MODEL,
    INDEX_S3_ACCESS_KEY,
    INDEX_S3_BUCKET,
    INDEX_S3_ENDPOINT,
    INDEX_S3_PREFIX,
    INDEX_S3_REGION,
    INDEX_S3_SECRET_KEY,
    INDEX_SNAPSHOT_DIR,
)
from plugins.base import SyncStats

ARCHIVE_DIRNAME = "pdf_archive"
MANIFEST_NAME = "manifest.json"
LATEST_ARCHIVE = "latest.tar.gz"
LIVE_GENERATION = "remote_generation.txt"
SKIP_NAMES = {"sync.lock", "layout.lock", "vision.lock", "sync.log"}

Log = Callable[[str], None]


def archive_dir(data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / ARCHIVE_DIRNAME


def remote_configured() -> bool:
    return bool(INDEX_S3_BUCKET or INDEX_SNAPSHOT_DIR)


def _log(progress: Log | None, message: str) -> None:
    if progress:
        progress(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _object_key(name: str) -> str:
    prefix = (INDEX_S3_PREFIX or "").strip().strip("/")
    return f"{prefix}/{name}" if prefix else name


def _s3():
    import boto3

    kwargs = {
        "aws_access_key_id": INDEX_S3_ACCESS_KEY or None,
        "aws_secret_access_key": INDEX_S3_SECRET_KEY or None,
        "region_name": INDEX_S3_REGION or None,
    }
    if INDEX_S3_ENDPOINT:
        kwargs["endpoint_url"] = INDEX_S3_ENDPOINT
    return boto3.client("s3", **{k: v for k, v in kwargs.items() if v})


def checkpoint_catalog(plugin) -> None:
    catalog = getattr(plugin, "catalog", None)
    if catalog is None:
        return
    checkpoint = getattr(catalog, "checkpoint", None)
    if callable(checkpoint):
        checkpoint()


def close_stores(plugin) -> None:
    for name in ("pages", "catalog"):
        store = getattr(plugin, name, None)
        closer = getattr(store, "close", None) if store is not None else None
        if callable(closer):
            closer()


def reopen_stores(plugin) -> None:
    from plugins.pdf_archive.store import Catalog
    from plugins.pdf_archive.vectors import PageIndex

    plugin.catalog = Catalog()
    plugin.pages = PageIndex()


def copy_live_index(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in SKIP_NAMES:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)


def write_manifest(dest: Path, *, indexed: int, layout_sheets: int, generation: str) -> Path:
    payload = {
        "generation": generation,
        "indexed": indexed,
        "layout_sheets": layout_sheets,
        "embedding_model": EMBEDDING_MODEL,
        "created_at": generation,
    }
    path = dest / MANIFEST_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def pack_snapshot(src: Path, tar_path: Path) -> None:
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src, arcname=ARCHIVE_DIRNAME)


def unpack_snapshot(tar_path: Path, dest_parent: Path) -> Path:
    dest_parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        kwargs = {}
        if hasattr(tarfile, "data_filter"):
            kwargs["filter"] = "data"
        tar.extractall(dest_parent, **kwargs)
    extracted = dest_parent / ARCHIVE_DIRNAME
    if not extracted.is_dir():
        raise FileNotFoundError(f"в архиве нет папки {ARCHIVE_DIRNAME}")
    return extracted


def _put_bytes(name: str, data: bytes, content_type: str) -> None:
    if INDEX_S3_BUCKET:
        _s3().put_object(
            Bucket=INDEX_S3_BUCKET,
            Key=_object_key(name),
            Body=data,
            ContentType=content_type,
        )
        return
    if INDEX_SNAPSHOT_DIR:
        path = Path(INDEX_SNAPSHOT_DIR)
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(data)
        return
    raise RuntimeError("не задан INDEX_S3_BUCKET и INDEX_SNAPSHOT_DIR")


def _get_bytes(name: str) -> bytes | None:
    if INDEX_S3_BUCKET:
        try:
            obj = _s3().get_object(Bucket=INDEX_S3_BUCKET, Key=_object_key(name))
        except Exception as exc:
            if "NoSuchKey" in type(exc).__name__ or "404" in str(exc):
                return None
            raise
        return obj["Body"].read()
    if INDEX_SNAPSHOT_DIR:
        path = Path(INDEX_SNAPSHOT_DIR) / name
        if not path.is_file():
            return None
        return path.read_bytes()
    return None


def read_remote_manifest() -> dict | None:
    raw = _get_bytes(MANIFEST_NAME)
    if not raw:
        return None
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else None


def local_generation(data_dir: Path | None = None) -> str:
    path = archive_dir(data_dir) / LIVE_GENERATION
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def publish(plugin, progress: Log | None = None) -> SyncStats:
    stats = SyncStats()
    log = lambda m: _log(progress, m)
    if not remote_configured():
        stats.message = "удалённый индекс не настроен"
        log(stats.message)
        return stats
    live = archive_dir()
    if not live.is_dir():
        stats.message = f"нет каталога индекса: {live}"
        log(stats.message)
        return stats
    generation = _now_iso()
    indexed = int(plugin.catalog.count()) if getattr(plugin, "catalog", None) else 0
    layout_sheets = (
        int(plugin.catalog.layout_sheet_count()) if getattr(plugin, "catalog", None) else 0
    )
    log("готовлю снимок индекса…")
    checkpoint_catalog(plugin)
    close_stores(plugin)
    staging = Path(tempfile.mkdtemp(prefix="umnik-index-"))
    tar_path = staging / LATEST_ARCHIVE
    try:
        packed = staging / ARCHIVE_DIRNAME
        copy_live_index(live, packed)
        write_manifest(packed, indexed=indexed, layout_sheets=layout_sheets, generation=generation)
        (packed / LIVE_GENERATION).write_text(generation, encoding="utf-8")
        pack_snapshot(packed, tar_path)
        manifest_bytes = (packed / MANIFEST_NAME).read_bytes()
        log("заливаю индекс…")
        _put_bytes(LATEST_ARCHIVE, tar_path.read_bytes(), "application/gzip")
        _put_bytes(MANIFEST_NAME, manifest_bytes, "application/json")
        (live / LIVE_GENERATION).write_text(generation, encoding="utf-8")
        stats.indexed = indexed
        stats.message = f"индекс опубликован {generation}"
        log(stats.message)
    finally:
        reopen_stores(plugin)
        shutil.rmtree(staging, ignore_errors=True)
    return stats


def pull(plugin, progress: Log | None = None) -> SyncStats:
    stats = SyncStats()
    log = lambda m: _log(progress, m)
    if not remote_configured():
        stats.message = "удалённый индекс не настроен"
        log(stats.message)
        return stats
    remote = read_remote_manifest()
    if not remote:
        stats.message = "на сервере ещё нет снимка индекса"
        log(stats.message)
        return stats
    generation = str(remote.get("generation") or "")
    if generation and generation == local_generation():
        stats.indexed = int(remote.get("indexed") or 0)
        stats.skipped = 1
        stats.message = "индекс уже актуален"
        log(stats.message)
        return stats
    blob = _get_bytes(LATEST_ARCHIVE)
    if not blob:
        stats.message = "нет latest.tar.gz"
        log(stats.message)
        stats.errors = 1
        return stats
    log(f"скачиваю индекс {generation or 'latest'}…")
    incoming_parent = Path(tempfile.mkdtemp(prefix="umnik-index-in-"))
    tar_path = incoming_parent / LATEST_ARCHIVE
    live = archive_dir()
    backup = live.with_name(f"{ARCHIVE_DIRNAME}.bak")
    try:
        tar_path.write_bytes(blob)
        extracted = unpack_snapshot(tar_path, incoming_parent)
        close_stores(plugin)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if live.exists():
            live.replace(backup)
        shutil.copytree(extracted, live)
        if generation:
            (live / LIVE_GENERATION).write_text(generation, encoding="utf-8")
        stats.indexed = int(remote.get("indexed") or 0)
        stats.updated = 1
        stats.message = f"индекс обновлён {generation}"
        log(stats.message)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception as exc:
        stats.errors = 1
        stats.message = f"ошибка загрузки индекса: {exc}"
        log(stats.message)
        if backup.exists() and not live.exists():
            backup.replace(live)
        return stats
    finally:
        reopen_stores(plugin)
        shutil.rmtree(incoming_parent, ignore_errors=True)
    return stats
