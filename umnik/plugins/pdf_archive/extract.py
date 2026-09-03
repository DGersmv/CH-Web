from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from config import (
    ARCHIVE_ROOT,
    MAX_CHARS_PAGE,
    MAX_PAGES_EMBED,
    MIN_CHARS_EMBED,
    SKIP_DIR_NAMES,
    SKIP_DIR_PREFIXES,
)

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

from pdf_inventory import PT_TO_MM, classify, corner_text, raster_coverage, sheet_format


def should_skip_dir(name: str) -> bool:
    low = name.lower()
    if low in SKIP_DIR_NAMES:
        return True
    return any(low.startswith(p) for p in SKIP_DIR_PREFIXES)


def iter_pdfs(root: Path | None = None):
    root = Path(root or ARCHIVE_ROOT)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fn in filenames:
            if fn.lower().endswith(".pdf"):
                yield Path(dirpath) / fn


def path_meta(path: Path, root: Path | None = None) -> tuple[str, str, str]:
    root = Path(root or ARCHIVE_ROOT)
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.parts
    year = parts[0] if parts and parts[0][:4].isdigit() else ""
    project = ""
    if len(parts) >= 2:
        project = parts[1]
    elif parts:
        project = parts[0]
    return str(rel), year, project


@dataclass
class PageExtract:
    page: int
    text: str
    kind: str
    titleblock: str
    chars: int


@dataclass
class FileExtract:
    path: Path
    pages: int
    kind: str
    titleblock: str
    snippet: str
    pages_data: list[PageExtract]
    error: str = ""


def _clean(text: str, limit: int) -> str:
    text = " ".join(text.split())
    for noise in ("GSPublisherVersion", "Acrobat Distiller"):
        text = text.replace(noise, " ")
    return " ".join(text.split())[:limit]


def extract_pdf(path: Path) -> FileExtract:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        return FileExtract(
            path=path,
            pages=0,
            kind="error",
            titleblock="",
            snippet="",
            pages_data=[],
            error=str(exc)[:200],
        )

    pages_data: list[PageExtract] = []
    kinds: list[str] = []
    titleblocks: list[str] = []
    snippet_parts: list[str] = []

    try:
        for i, page in enumerate(doc, 1):
            w_mm = round(page.rect.width * PT_TO_MM)
            h_mm = round(page.rect.height * PT_TO_MM)
            fmt = sheet_format(w_mm, h_mm)
            raw = page.get_text("text") or ""
            text = _clean(raw, MAX_CHARS_PAGE)
            chars = len(text)
            try:
                raster = raster_coverage(page)
            except Exception:
                raster = 0.0
            kind = classify(chars, raster, 0, fmt)
            kinds.append(kind)
            stamp = ""
            if kind == "drawing" or chars < 400:
                try:
                    stamp = _clean(corner_text(page), 800)
                except Exception:
                    stamp = ""
            if stamp:
                titleblocks.append(stamp)
            if i <= MAX_PAGES_EMBED and chars >= MIN_CHARS_EMBED:
                pages_data.append(
                    PageExtract(
                        page=i,
                        text=text,
                        kind=kind,
                        titleblock=stamp,
                        chars=chars,
                    )
                )
            if len(snippet_parts) < 3 and (text or stamp):
                snippet_parts.append(stamp or text[:400])
    finally:
        doc.close()

    kind = max(set(kinds), key=kinds.count) if kinds else "empty"
    titleblock = " | ".join(dict.fromkeys(titleblocks))[:1500]
    snippet = " ".join(snippet_parts)[:1200]
    return FileExtract(
        path=path,
        pages=len(kinds),
        kind=kind,
        titleblock=titleblock,
        snippet=snippet,
        pages_data=pages_data,
    )
