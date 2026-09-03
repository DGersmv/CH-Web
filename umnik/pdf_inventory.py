#!/usr/bin/env python3
"""
pdf_inventory.py — инвентаризация архива PDF.

Ничего не изменяет и не удаляет. Только читает файлы и пишет два CSV
рядом со скриптом (или туда, куда укажешь ключом --out).

Запуск:
    python pdf_inventory.py "C:\\Projects"            (Windows)
    python pdf_inventory.py "/Users/dmitry/Projects"  (Mac)

Ключи:
    --out DIR         куда положить CSV (по умолчанию — текущая папка)
    --titleblock      дополнительно выгрузить текст из правого нижнего
                      угла каждого чертежа в titleblocks.txt
"""

import argparse
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

try:
    import pymupdf as fitz          # PyMuPDF 1.24 и новее
except ImportError:
    try:
        import fitz                 # старое имя того же пакета
    except ImportError:
        sys.exit("Не установлен PyMuPDF. Выполни: pip install pymupdf")

# Форматы ISO A в миллиметрах, допуск ±6 мм на обрезку/поля
A_FORMATS = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
}
TOLERANCE_MM = 6
PT_TO_MM = 25.4 / 72.0

# Пороги классификации — подкрути под свой архив, если сводка выглядит странно
MIN_CHARS_FOR_TEXT = 50      # меньше символов на странице → это не текстовый документ
RASTER_RATIO_SCAN = 0.5      # растр закрывает больше половины листа → скан
VECTOR_PATHS_DRAWING = 200   # столько векторных путей бывает только на чертеже


def sheet_format(w_mm: float, h_mm: float) -> str:
    """Возвращает 'A3', 'A1' и т.п. либо 'нестанд.' — с учётом обеих ориентаций."""
    short, long = sorted((w_mm, h_mm))
    for name, (fs, fl) in A_FORMATS.items():
        if abs(short - fs) <= TOLERANCE_MM and abs(long - fl) <= TOLERANCE_MM:
            return name
    return "нестанд."


def file_sha256(path: Path) -> str:
    """Хэш файла — ловит точные дубли, даже если имена файлов разные."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def raster_coverage(page) -> float:
    """Доля площади листа, закрытая растровыми картинками (0.0 … 1.0)."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") == 1:  # 1 = растровое изображение
            x0, y0, x1, y1 = block["bbox"]
            covered += abs(x1 - x0) * abs(y1 - y0)
    return min(covered / page_area, 1.0)


def classify(chars: int, raster: float, paths: int, fmt: str) -> str:
    """drawing — чертёж, scan — скан бумаги, text — текстовый документ."""
    if chars < MIN_CHARS_FOR_TEXT and raster > RASTER_RATIO_SCAN:
        return "scan"
    if paths >= VECTOR_PATHS_DRAWING:
        return "drawing"
    if fmt in ("A0", "A1", "A2") or (fmt == "нестанд." and chars < 400):
        return "drawing"
    if chars < MIN_CHARS_FOR_TEXT:
        return "scan" if raster > 0.1 else "empty"
    return "text"


def corner_text(page) -> str:
    """Текст из правого нижнего угла листа — там обычно сидит штамп."""
    r = page.rect
    box = fitz.Rect(r.x0 + r.width * 0.60, r.y0 + r.height * 0.72, r.x1, r.y1)
    return page.get_text("text", clip=box).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="папка с PDF (обходится рекурсивно)")
    ap.add_argument("--out", default=".", help="куда положить CSV")
    ap.add_argument("--titleblock", action="store_true",
                    help="выгрузить текст штампов в titleblocks.txt")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.is_dir():
        sys.exit(f"Папка не найдена: {root}")
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(root.rglob("*.pdf")) + sorted(root.rglob("*.PDF"))
    pdfs = sorted(set(pdfs))
    if not pdfs:
        sys.exit(f"В {root} не найдено ни одного PDF")

    print(f"Найдено файлов: {len(pdfs)}. Читаю…", flush=True)

    files_rows, pages_rows, blocks = [], [], []
    hashes, kinds, formats, producers = Counter(), Counter(), Counter(), Counter()
    total_pages = 0

    for n, path in enumerate(pdfs, 1):
        if n % 25 == 0:
            print(f"  …{n}/{len(pdfs)}", flush=True)
        try:
            digest = file_sha256(path)
            doc = fitz.open(path)
        except Exception as exc:
            files_rows.append({
                "path": str(path), "name": path.name, "sha256": "",
                "size_mb": round(path.stat().st_size / 1e6, 2),
                "pages": 0, "producer": "", "creator": "", "error": str(exc)[:120],
            })
            continue

        hashes[digest] += 1
        meta = doc.metadata or {}
        producer = (meta.get("producer") or "").strip()
        producers[producer or "(пусто)"] += 1

        files_rows.append({
            "path": str(path), "name": path.name, "sha256": digest[:16],
            "size_mb": round(path.stat().st_size / 1e6, 2),
            "pages": doc.page_count, "producer": producer,
            "creator": (meta.get("creator") or "").strip(), "error": "",
        })

        for i, page in enumerate(doc, 1):
            total_pages += 1
            w_mm = round(page.rect.width * PT_TO_MM)
            h_mm = round(page.rect.height * PT_TO_MM)
            fmt = sheet_format(w_mm, h_mm)
            chars = len(page.get_text("text").strip())
            imgs = len(page.get_images(full=True))
            raster = round(raster_coverage(page), 3)
            try:
                paths_n = len(page.get_drawings())
            except Exception:
                paths_n = 0
            kind = classify(chars, raster, paths_n, fmt)

            kinds[kind] += 1
            formats[fmt] += 1
            pages_rows.append({
                "file": path.name, "path": str(path), "sha256": digest[:16],
                "page": i, "w_mm": w_mm, "h_mm": h_mm, "format": fmt,
                "orientation": "альбом" if w_mm > h_mm else "портрет",
                "chars": chars, "images": imgs, "raster_ratio": raster,
                "vector_paths": paths_n, "kind": kind,
            })

            if args.titleblock and kind == "drawing":
                snippet = corner_text(page)
                if snippet:
                    blocks.append(f"=== {path.name} | стр. {i} | {fmt} ===\n{snippet}\n")

        doc.close()

    pages_csv = out_dir / "pages.csv"
    files_csv = out_dir / "files.csv"
    with pages_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(pages_rows[0].keys()))
        w.writeheader()
        w.writerows(pages_rows)
    with files_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(files_rows[0].keys()))
        w.writeheader()
        w.writerows(files_rows)
    if args.titleblock and blocks:
        (out_dir / "titleblocks.txt").write_text("\n".join(blocks), encoding="utf-8")

    dupes = sum(c - 1 for c in hashes.values() if c > 1)
    print("\n" + "=" * 46)
    print(f"Файлов:            {len(pdfs)}")
    print(f"Страниц:           {total_pages}")
    print(f"Точных дублей:     {dupes}")
    print("\nПо видам страниц:")
    for k, c in kinds.most_common():
        print(f"  {k:<10} {c:>6}  ({c * 100 // max(total_pages, 1)}%)")
    print("\nПо форматам листа:")
    for k, c in formats.most_common(8):
        print(f"  {k:<10} {c:>6}")
    print("\nЧем сделаны (producer), топ-5:")
    for k, c in producers.most_common(5):
        print(f"  {c:>4}  {k[:60]}")
    print("=" * 46)
    print(f"\nЗаписано: {pages_csv}\n          {files_csv}")
    if args.titleblock and blocks:
        print(f"          {out_dir / 'titleblocks.txt'}")


if __name__ == "__main__":
    main()
