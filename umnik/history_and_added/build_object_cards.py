#!/usr/bin/env python3
"""
build_object_cards.py — второй слой поверх реестра: карточки объектов
(комнаты/площади), собранные из УЖЕ распознанных ранее чертежей
(таблица layout_sheets/layout_rooms в catalog.db, source='openrouter',
итог прошлых прогонов layout_sync.py). Новых запросов к OpenRouter
не делает — только читает то, что уже есть в базе.

Пишет два CSV рядом со скриптом:
  sheet_cards.csv  — один лист чертежа = одна строка
  object_cards.csv — сгруппировано по (объект, вариант)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # D:\Scan_Pdf
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlite3
from domain import room_kind_of_name, room_list_areas

ARCHIVE_ROOT = Path(r"D:\Общая_Рабочая")
DB_PATH = ROOT / "data" / "pdf_archive" / "catalog.db"
OUT_DIR = Path(__file__).resolve().parent


def relpath(p: str) -> str:
    try:
        return str(Path(p).relative_to(ARCHIVE_ROOT))
    except ValueError:
        return p


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    sheets = conn.execute(
        """
        SELECT id, path, page, object, version, sheet_type, title, done_at
        FROM layout_sheets
        ORDER BY object, version, path, page
        """
    ).fetchall()

    rooms_by_sheet: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT sheet_id, name, area_m2, where_txt FROM layout_rooms"):
        rooms_by_sheet.setdefault(int(r["sheet_id"]), []).append(
            {"name": r["name"], "area_m2": r["area_m2"], "where_txt": r["where_txt"]}
        )

    sheet_rows = []
    grouped: dict[tuple[str, str], dict] = {}

    for s in sheets:
        sid = int(s["id"])
        rooms = rooms_by_sheet.get(sid, [])
        total, living = room_list_areas(rooms)
        counts: dict[str, int] = {}
        for r in rooms:
            kind = room_kind_of_name(r.get("name") or "")
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
        rooms_text = "; ".join(
            f"{r['name']} {r['area_m2']}м²" if r.get("area_m2") is not None else str(r["name"])
            for r in rooms
        )
        counts_text = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))

        sheet_rows.append(
            {
                "object": s["object"] or "",
                "version": s["version"] or "",
                "sheet_type": s["sheet_type"] or "",
                "title": s["title"] or "",
                "path": relpath(s["path"]),
                "page": s["page"],
                "area_total_m2": total,
                "area_living_m2": living,
                "room_counts": counts_text,
                "rooms": rooms_text,
            }
        )

        key = (s["object"] or "", s["version"] or "")
        g = grouped.setdefault(
            key,
            {"rooms": [], "paths": [], "sheet_types": set(), "counts": {}},
        )
        g["rooms"].extend(rooms)
        g["paths"].append(f"{relpath(s['path'])} (стр.{s['page']})")
        if s["sheet_type"]:
            g["sheet_types"].add(s["sheet_type"])
        for k, v in counts.items():
            g["counts"][k] = g["counts"].get(k, 0) + v

    object_rows = []
    for (obj, ver), g in sorted(grouped.items()):
        total, living = room_list_areas(g["rooms"])
        counts_text = ", ".join(f"{k}:{v}" for k, v in sorted(g["counts"].items()))
        rooms_text = "; ".join(
            f"{r['name']} {r['area_m2']}м²" if r.get("area_m2") is not None else str(r["name"])
            for r in g["rooms"]
        )
        object_rows.append(
            {
                "object": obj,
                "version": ver,
                "sheet_types": ", ".join(sorted(g["sheet_types"])),
                "sheets_n": len(g["paths"]),
                "area_total_m2": total,
                "area_living_m2": living,
                "room_counts": counts_text,
                "rooms": rooms_text,
                "sources": " | ".join(g["paths"]),
            }
        )

    sheet_csv = OUT_DIR / "sheet_cards.csv"
    object_csv = OUT_DIR / "object_cards.csv"

    with sheet_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(sheet_rows[0].keys()))
        w.writeheader()
        w.writerows(sheet_rows)

    with object_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(object_rows[0].keys()))
        w.writeheader()
        w.writerows(object_rows)

    print(f"Листов (sheet_cards):   {len(sheet_rows)}")
    print(f"Объект+вариант (object_cards): {len(object_rows)}")
    print(f"Записано: {sheet_csv}")
    print(f"          {object_csv}")


if __name__ == "__main__":
    main()
