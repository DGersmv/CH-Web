from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from config import DATA_DIR, SEARCH_LIMIT
from domain import (
    is_layout_candidate,
    layout_object_tokens,
    parse_area_filter,
    parse_room_program,
    room_kind_of_name,
    room_list_areas,
    token_like_needles,
)
from plugins.base import SearchHit
from plugins.pdf_archive.extract import FileExtract, path_meta

SKIP_LAYOUT_PATH = (
    "электрик",
    "электро",
    "кассет",
    "спецификац",
    "ведомост",
    "двери",
    "фасад",
    "разрез",
    "узел",
    "кжд",
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Catalog:
    def __init__(self, data_dir: Path | None = None):
        self.dir = Path(data_dir or DATA_DIR) / "pdf_archive"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "catalog.db"
        self._lock = threading.Lock()
        self.conn = _connect(self.db_path)
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                name TEXT,
                relpath TEXT,
                size INTEGER,
                mtime REAL,
                pages INTEGER,
                kind TEXT,
                titleblock TEXT,
                snippet TEXT,
                year TEXT,
                project TEXT,
                error TEXT,
                indexed_at REAL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                name, relpath, titleblock, snippet, path UNINDEXED
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS names (
                path TEXT PRIMARY KEY,
                name TEXT,
                relpath TEXT,
                blob TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_names_blob ON names(blob);
            CREATE TABLE IF NOT EXISTS page_vision (
                path TEXT NOT NULL,
                page INTEGER NOT NULL,
                ocr_text TEXT,
                vl_json TEXT,
                summary TEXT,
                blob TEXT,
                error TEXT,
                done_at REAL,
                PRIMARY KEY (path, page)
            );
            CREATE TABLE IF NOT EXISTS layout_sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                page INTEGER NOT NULL,
                object TEXT,
                version TEXT,
                sheet_type TEXT,
                title TEXT,
                source TEXT,
                facts_blob TEXT,
                cost_usd REAL,
                error TEXT,
                done_at REAL,
                UNIQUE(path, page)
            );
            CREATE INDEX IF NOT EXISTS idx_layout_sheets_path ON layout_sheets(path);
            CREATE INDEX IF NOT EXISTS idx_layout_sheets_object ON layout_sheets(object);
            CREATE TABLE IF NOT EXISTS layout_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id INTEGER NOT NULL,
                name TEXT,
                area_m2 REAL,
                where_txt TEXT,
                source TEXT,
                FOREIGN KEY(sheet_id) REFERENCES layout_sheets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_layout_rooms_sheet ON layout_rooms(sheet_id);
            CREATE TABLE IF NOT EXISTS layout_openings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id INTEGER NOT NULL,
                kind TEXT,
                size_raw TEXT,
                width_mm REAL,
                height_mm REAL,
                where_txt TEXT,
                source TEXT,
                FOREIGN KEY(sheet_id) REFERENCES layout_sheets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_layout_openings_sheet ON layout_openings(sheet_id);
            CREATE TABLE IF NOT EXISTS layout_walls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id INTEGER NOT NULL,
                length_mm REAL,
                thickness_mm REAL,
                material TEXT,
                note TEXT,
                source TEXT,
                FOREIGN KEY(sheet_id) REFERENCES layout_sheets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_layout_walls_sheet ON layout_walls(sheet_id);
            """
        )
        self.conn.commit()

    def snapshot(self) -> dict[str, tuple[int, float]]:
        rows = self.conn.execute("SELECT path, size, mtime FROM files").fetchall()
        return {r["path"]: (r["size"], r["mtime"]) for r in rows}

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()
        return int(row["n"] if row else 0)

    def upsert(self, extracted: FileExtract, size: int, mtime: float, indexed_at: float) -> None:
        rel, year, project = path_meta(extracted.path)
        path = str(extracted.path)
        name = extracted.path.name
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO files (
                    path, name, relpath, size, mtime, pages, kind, titleblock,
                    snippet, year, project, error, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, relpath=excluded.relpath, size=excluded.size,
                    mtime=excluded.mtime, pages=excluded.pages, kind=excluded.kind,
                    titleblock=excluded.titleblock, snippet=excluded.snippet,
                    year=excluded.year, project=excluded.project, error=excluded.error,
                    indexed_at=excluded.indexed_at
                """,
                (
                    path,
                    name,
                    rel,
                    size,
                    mtime,
                    extracted.pages,
                    extracted.kind,
                    extracted.titleblock,
                    extracted.snippet,
                    year,
                    project,
                    extracted.error,
                    indexed_at,
                ),
            )
            self.conn.execute("DELETE FROM files_fts WHERE path = ?", (path,))
            self.conn.execute(
                """
                INSERT INTO files_fts (name, relpath, titleblock, snippet, path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, rel, extracted.titleblock, extracted.snippet, path),
            )
            self.conn.commit()

    def delete(self, path: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM files_fts WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM names WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM page_vision WHERE path = ?", (path,))
            ids = [
                r["id"]
                for r in self.conn.execute(
                    "SELECT id FROM layout_sheets WHERE path = ?", (path,)
                ).fetchall()
            ]
            for sid in ids:
                self.conn.execute("DELETE FROM layout_rooms WHERE sheet_id = ?", (sid,))
                self.conn.execute("DELETE FROM layout_openings WHERE sheet_id = ?", (sid,))
                self.conn.execute("DELETE FROM layout_walls WHERE sheet_id = ?", (sid,))
            self.conn.execute("DELETE FROM layout_sheets WHERE path = ?", (path,))
            self.conn.commit()

    def upsert_names(self, items: list[tuple[str, str, str, str]]) -> int:
        if not items:
            return 0
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO names (path, name, relpath, blob) VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, relpath=excluded.relpath, blob=excluded.blob
                """,
                items,
            )
            self.conn.commit()
        return len(items)

    def names_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM names").fetchone()
        return int(row["n"] if row else 0)

    def search_names(self, tokens: list[str], limit: int = SEARCH_LIMIT) -> list[SearchHit]:
        tokens = [t for t in tokens if t]
        if not tokens:
            return []
        parts = []
        args: list = []
        for t in tokens:
            needles = token_like_needles(t)
            parts.append("(" + " OR ".join(["blob LIKE ?"] * len(needles)) + ")")
            args.extend(f"%{n}%" for n in needles)
        args.append(limit * 3)
        rows = self.conn.execute(
            f"SELECT path, name, relpath FROM names WHERE {' AND '.join(parts)} LIMIT ?",
            args,
        ).fetchall()
        hits: list[SearchHit] = []
        for i, row in enumerate(rows):
            info = self.get(row["path"])
            snippet = ""
            extra = {"relpath": row["relpath"], "via": "name"}
            if info:
                snippet = (info.get("titleblock") or info.get("snippet") or "")[:500]
                extra.update(
                    {
                        "kind": info.get("kind"),
                        "pages": info.get("pages"),
                        "year": info.get("year"),
                        "project": info.get("project"),
                    }
                )
            hits.append(
                SearchHit(
                    path=row["path"],
                    title=row["name"],
                    snippet=snippet or row["relpath"],
                    score=2.0 / (1 + i),
                    extra=extra,
                )
            )
        return hits[:limit]

    def get(self, path: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        return dict(row) if row else None

    def fts_search(self, query: str, limit: int = SEARCH_LIMIT) -> list[SearchHit]:
        tokens = [t for t in _fts_tokens(query) if t]
        hits: list[SearchHit] = []
        seen: set[str] = set()

        if tokens:
            match = " OR ".join(f'"{t}"' if " " in t else t for t in tokens)
            try:
                rows = self.conn.execute(
                    """
                    SELECT files.path, files.name, files.relpath, files.titleblock,
                           files.snippet, files.kind, files.pages, files.year, files.project
                    FROM files_fts
                    JOIN files ON files.path = files_fts.path
                    WHERE files_fts MATCH ?
                    ORDER BY bm25(files_fts)
                    LIMIT ?
                    """,
                    (match, limit * 2),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for i, row in enumerate(rows):
                path = row["path"]
                if path in seen:
                    continue
                seen.add(path)
                snippet = row["titleblock"] or row["snippet"] or ""
                hits.append(
                    SearchHit(
                        path=path,
                        title=row["name"],
                        snippet=snippet[:500],
                        score=1.0 / (60 + i),
                        extra={
                            "kind": row["kind"],
                            "pages": row["pages"],
                            "year": row["year"],
                            "project": row["project"],
                            "relpath": row["relpath"],
                            "via": "fts",
                        },
                    )
                )

        like = f"%{query.strip()}%"
        rows = self.conn.execute(
            """
            SELECT path, name, relpath, titleblock, snippet, kind, pages, year, project
            FROM files
            WHERE name LIKE ? OR relpath LIKE ? OR titleblock LIKE ?
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()
        base = len(hits)
        for j, row in enumerate(rows):
            path = row["path"]
            if path in seen:
                continue
            seen.add(path)
            snippet = row["titleblock"] or row["snippet"] or ""
            hits.append(
                SearchHit(
                    path=path,
                    title=row["name"],
                    snippet=snippet[:500],
                    score=1.0 / (60 + base + j),
                    extra={
                        "kind": row["kind"],
                        "pages": row["pages"],
                        "year": row["year"],
                        "project": row["project"],
                        "relpath": row["relpath"],
                        "via": "like",
                    },
                )
            )
        return hits[:limit]

    def vision_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(DISTINCT path) AS n FROM page_vision").fetchone()
        return int(row["n"] if row else 0)

    def has_vision(self, path: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM page_vision WHERE path = ? LIMIT 1", (path,)
        ).fetchone()
        return bool(row)

    def upsert_vision(
        self,
        path: str,
        page: int,
        ocr_text: str,
        vl_json: str,
        summary: str,
        blob: str,
        error: str = "",
        done_at: float = 0.0,
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO page_vision (path, page, ocr_text, vl_json, summary, blob, error, done_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path, page) DO UPDATE SET
                    ocr_text=excluded.ocr_text, vl_json=excluded.vl_json,
                    summary=excluded.summary, blob=excluded.blob,
                    error=excluded.error, done_at=excluded.done_at
                """,
                (path, page, ocr_text, vl_json, summary, blob, error, done_at),
            )
            self.conn.commit()

    def vision_for_file(self, path: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM page_vision WHERE path = ? ORDER BY page", (path,)
        ).fetchall()
        return [dict(r) for r in rows]

    def pending_vision_paths(self, limit: int = 40) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT n.path
            FROM names n
            LEFT JOIN page_vision v ON v.path = n.path
            WHERE v.path IS NULL
            ORDER BY
              CASE
                WHEN n.blob LIKE '%планир%' THEN 0
                WHEN n.blob LIKE '%этаж%' THEN 1
                WHEN n.blob LIKE '%черт%' THEN 2
                ELSE 3
              END,
              n.name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [r["path"] for r in rows]

    def search_vision(self, tokens: list[str], limit: int = SEARCH_LIMIT) -> list[SearchHit]:
        tokens = [t for t in tokens if t]
        if not tokens:
            return []
        where = " AND ".join(["v.blob LIKE ?" for _ in tokens])
        args: list = [f"%{t}%" for t in tokens]
        args.append(limit * 3)
        rows = self.conn.execute(
            f"""
            SELECT v.path, v.page, v.summary, v.ocr_text, n.name, n.relpath
            FROM page_vision v
            LEFT JOIN names n ON n.path = v.path
            WHERE {where}
            LIMIT ?
            """,
            args,
        ).fetchall()
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for i, row in enumerate(rows):
            path = row["path"]
            if path in seen:
                continue
            seen.add(path)
            hits.append(
                SearchHit(
                    path=path,
                    title=row["name"] or Path(path).name,
                    snippet=(row["summary"] or row["ocr_text"] or "")[:600],
                    score=3.0 / (1 + i),
                    page=int(row["page"] or 0) or None,
                    extra={"relpath": row["relpath"] or "", "via": "vision"},
                )
            )
        return hits[:limit]


    def layout_spent_usd(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS n FROM layout_sheets"
        ).fetchone()
        return float(row["n"] if row else 0)

    def layout_sheet_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM layout_sheets").fetchone()
        return int(row["n"] if row else 0)

    def pending_layout_paths(
        self, limit: int = 40, name_contains: str = ""
    ) -> list[str]:
        needle = (name_contains or "").strip().lower().replace("ё", "е")
        rows = self.conn.execute(
            "SELECT path, name, blob FROM names"
        ).fetchall()
        done_paths = {
            r["path"]
            for r in self.conn.execute("SELECT DISTINCT path FROM layout_sheets")
        }
        done_names_ok = {
            Path(p).name.lower()
            for p in done_paths
            if "загрузк" not in p.lower().replace("ё", "е")
        }
        ranked: list[tuple[tuple, str]] = []
        for row in rows:
            path = row["path"]
            name_l = (row["name"] or "").lower()
            blob = (row["blob"] or "")
            blob_n = blob.lower().replace("ё", "е")
            if path in done_paths:
                continue
            if needle and needle not in blob_n and needle not in name_l:
                continue
            if not is_layout_candidate(path, row["name"] or "", blob):
                continue
            if "загрузк" in blob_n and name_l in done_names_ok:
                continue
            zagr = 1 if "загрузк" in blob_n else 0
            planir = 0 if "планир" in blob_n else 1
            ranked.append(((zagr, planir, name_l), path))
        ranked.sort(key=lambda x: x[0])
        return [p for _k, p in ranked[:limit]]

    def upsert_layout(
        self,
        path: str,
        page: int,
        object_name: str,
        version: str,
        data: dict,
        facts_blob: str,
        cost_usd: float = 0.0,
        source: str = "openrouter",
        error: str = "",
        done_at: float = 0.0,
    ) -> int:
        with self._lock:
            old = self.conn.execute(
                "SELECT id FROM layout_sheets WHERE path = ? AND page = ?",
                (path, page),
            ).fetchone()
            if old:
                sid = int(old["id"])
                self.conn.execute("DELETE FROM layout_rooms WHERE sheet_id = ?", (sid,))
                self.conn.execute("DELETE FROM layout_openings WHERE sheet_id = ?", (sid,))
                self.conn.execute("DELETE FROM layout_walls WHERE sheet_id = ?", (sid,))
                self.conn.execute(
                    """
                    UPDATE layout_sheets SET
                        object=?, version=?, sheet_type=?, title=?, source=?,
                        facts_blob=?, cost_usd=?, error=?, done_at=?
                    WHERE id=?
                    """,
                    (
                        object_name,
                        version,
                        str(data.get("sheet") or "")[:80],
                        str(data.get("title") or "")[:200],
                        source,
                        facts_blob,
                        cost_usd,
                        error,
                        done_at,
                        sid,
                    ),
                )
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO layout_sheets (
                        path, page, object, version, sheet_type, title, source,
                        facts_blob, cost_usd, error, done_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        path,
                        page,
                        object_name,
                        version,
                        str(data.get("sheet") or "")[:80],
                        str(data.get("title") or "")[:200],
                        source,
                        facts_blob,
                        cost_usd,
                        error,
                        done_at,
                    ),
                )
                sid = int(cur.lastrowid)
            for room in data.get("rooms") or []:
                if not isinstance(room, dict):
                    continue
                name = str(room.get("name") or "").strip()
                if not name:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO layout_rooms (sheet_id, name, area_m2, where_txt, source)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        name[:80],
                        _as_float(room.get("area_m2")),
                        str(room.get("where") or "")[:80],
                        source,
                    ),
                )
            for op in data.get("openings") or []:
                if not isinstance(op, dict):
                    continue
                kind = str(op.get("kind") or "проём").strip()
                size_raw = str(op.get("size") or op.get("size_raw") or "").strip()
                w_mm, h_mm = _opening_mm(size_raw)
                self.conn.execute(
                    """
                    INSERT INTO layout_openings (
                        sheet_id, kind, size_raw, width_mm, height_mm, where_txt, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        kind[:40],
                        size_raw[:80],
                        w_mm,
                        h_mm,
                        str(op.get("where") or "")[:80],
                        source,
                    ),
                )
            for wall in data.get("walls") or []:
                if not isinstance(wall, dict):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO layout_walls (
                        sheet_id, length_mm, thickness_mm, material, note, source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        _as_float(wall.get("length_mm") or wall.get("length")),
                        _as_float(wall.get("thickness_mm") or wall.get("thickness")),
                        str(wall.get("material") or "")[:80],
                        str(wall.get("note") or "")[:200],
                        source,
                    ),
                )
            self.conn.commit()
        return sid

    def search_layout(self, query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
        program = parse_room_program(query)
        area = parse_area_filter(query)
        tokens = layout_object_tokens(query)
        if program or area:
            want_house = "дом" in (query or "").lower().replace("ё", "е")
            return self._search_layout_program(
                program,
                tokens,
                limit=limit,
                want_house=want_house,
                area=area,
            )
        if not tokens:
            raw = (query or "").strip().lower().replace("ё", "е")
            tokens = [
                t
                for t in raw.split()
                if len(t) >= 3 and t not in ("или", "все", "всех")
            ][:8]
        if not tokens:
            return []
        return self._search_layout_tokens(tokens, limit=limit)

    def _hydrate_sheet(self, row: sqlite3.Row, *, with_openings: bool = True) -> dict:
        sid = int(row["id"])
        rooms = self.conn.execute(
            "SELECT name, area_m2, where_txt FROM layout_rooms WHERE sheet_id=?",
            (sid,),
        ).fetchall()
        openings: list = []
        walls: list = []
        if with_openings:
            openings = self.conn.execute(
                """
                SELECT kind, size_raw, width_mm, height_mm, where_txt
                FROM layout_openings WHERE sheet_id=?
                """,
                (sid,),
            ).fetchall()
            walls = self.conn.execute(
                "SELECT length_mm, thickness_mm, material, note FROM layout_walls WHERE sheet_id=?",
                (sid,),
            ).fetchall()
        counts: dict[str, int] = {}
        for r in rooms:
            kind = room_kind_of_name(r["name"] or "")
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
        rooms_list = [dict(r) for r in rooms]
        total, living = room_list_areas(rooms_list)
        return {
            "path": row["path"],
            "page": row["page"],
            "object": row["object"],
            "version": row["version"],
            "sheet_type": row["sheet_type"],
            "title": row["title"],
            "facts": row["facts_blob"],
            "rooms": rooms_list,
            "openings": [dict(r) for r in openings],
            "walls": [dict(r) for r in walls],
            "room_counts": counts,
            "area_total": total,
            "area_living": living,
        }

    def _search_layout_tokens(self, tokens: list[str], limit: int) -> list[dict]:
        where, args = _layout_token_where(
            tokens,
            [
                "LOWER(REPLACE(s.path, 'ё', 'е'))",
                "LOWER(REPLACE(IFNULL(s.object,''), 'ё', 'е'))",
                "IFNULL(s.facts_blob,'')",
            ],
        )
        args.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT s.id, s.path, s.page, s.object, s.version, s.sheet_type, s.title,
                   s.facts_blob, s.source
            FROM layout_sheets s
            WHERE {where}
            ORDER BY s.done_at DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
        return [self._hydrate_sheet(row) for row in rows]

    def _search_layout_program(
        self,
        program: dict[str, int],
        tokens: list[str],
        limit: int,
        want_house: bool = False,
        area: dict | None = None,
    ) -> list[dict]:
        sql = """
            SELECT s.id, s.path, s.page, s.object, s.version, s.sheet_type, s.title,
                   s.facts_blob, s.source
            FROM layout_sheets s
        """
        args: list = []
        if tokens:
            where, tok_args = _layout_token_where(
                tokens,
                [
                    "LOWER(REPLACE(s.path, 'ё', 'е'))",
                    "LOWER(REPLACE(IFNULL(s.object,''), 'ё', 'е'))",
                ],
            )
            sql += f" WHERE {where}"
            args.extend(tok_args)
        rows = self.conn.execute(sql, args).fetchall()
        area_f = area or {}
        rooms_by: dict[int, list[dict]] = {}
        for r in self.conn.execute(
            "SELECT sheet_id, name, area_m2, where_txt FROM layout_rooms"
        ):
            rooms_by.setdefault(int(r["sheet_id"]), []).append(
                {"name": r["name"], "area_m2": r["area_m2"], "where_txt": r["where_txt"]}
            )
        scored: list[tuple[tuple, dict]] = []
        for row in rows:
            path_l = (row["path"] or "").lower().replace("ё", "е")
            if any(skip in path_l for skip in SKIP_LAYOUT_PATH):
                continue
            st = (row["sheet_type"] or "").lower()
            if any(x in st for x in ("фасад", "разрез", "спецификац", "узел", "3d")):
                continue
            rooms = rooms_by.get(int(row["id"]), [])
            counts: dict[str, int] = {}
            for r in rooms:
                kind = room_kind_of_name(r.get("name") or "")
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
            if program and any(counts.get(kind, 0) < need for kind, need in program.items()):
                continue
            is_house = counts.get("спальня", 0) >= 1
            if want_house and not is_house:
                continue
            total, living = room_list_areas(rooms)
            min_m2 = area_f.get("min_m2")
            max_m2 = area_f.get("max_m2")
            target_living = area_f.get("target_living")
            target_total = area_f.get("target_total")
            size = total or living
            if min_m2 is not None and size < min_m2:
                continue
            if max_m2 is not None and size > max_m2:
                continue
            if (target_living is not None or target_total is not None) and not size:
                continue
            extra = sum(counts.get(kind, 0) - need for kind, need in (program or {}).items())
            dump = 1 if "загрузк" in path_l else 0
            not_plan_dir = 0 if "планир" in path_l else 1
            not_house = 0 if is_house else 1
            stem = Path(row["path"]).stem.lower().replace("ё", "е")
            if "генплан" in stem:
                continue
            item = {
                "path": row["path"],
                "page": row["page"],
                "object": row["object"],
                "version": row["version"],
                "sheet_type": row["sheet_type"],
                "title": row["title"],
                "facts": row["facts_blob"],
                "rooms": rooms,
                "openings": [],
                "walls": [],
                "room_counts": counts,
                "area_total": total,
                "area_living": living,
            }
            if target_living is not None or target_total is not None:
                dist = 0.0
                if target_living is not None:
                    dist += abs((living or 0) - target_living)
                if target_total is not None:
                    dist += abs((total or 0) - target_total)
                scored.append(((dist, dump, not_plan_dir, -int(row["id"])), item))
            elif min_m2 or max_m2:
                scored.append(((-size, dump, not_plan_dir, -int(row["id"])), item))
            else:
                scored.append(((not_house, extra, dump, not_plan_dir, -int(row["id"])), item))
        scored.sort(key=lambda x: x[0])
        seen_file: set[str] = set()
        seen_bucket: set[str] = set()
        out: list[dict] = []
        overflow: list[dict] = []
        for _key, item in scored:
            file_key = _layout_object_key(item)
            if file_key in seen_file:
                continue
            seen_file.add(file_key)
            bucket = _project_bucket(item.get("path") or "")
            if bucket in seen_bucket:
                overflow.append(item)
                continue
            seen_bucket.add(bucket)
            out.append(item)
            if len(out) >= limit:
                break
        if len(out) < limit:
            for item in overflow:
                out.append(item)
                if len(out) >= limit:
                    break
        return out


def _layout_token_where(tokens: list[str], fields: list[str]) -> tuple[str, list]:
    parts: list[str] = []
    args: list = []
    for t in tokens:
        needles = token_like_needles(t)
        alts = []
        for n in needles:
            alts.append("(" + " OR ".join(f"{f} LIKE ?" for f in fields) + ")")
            args.extend([f"%{n}%"] * len(fields))
        parts.append("(" + " OR ".join(alts) + ")")
    return " AND ".join(parts), args


def _layout_object_key(item: dict) -> str:
    import re

    raw = (Path(item.get("path") or "").stem or item.get("object") or "").lower()
    raw = raw.replace("ё", "е")
    raw = re.sub(r"\s*в\d+\S*$", "", raw)
    raw = re.sub(r"\s*\(\d+\)$", "", raw)
    return raw.strip() or (item.get("path") or "")


_BUCKET_SKIP = frozenset(
    {
        "d:",
        "c:",
        "общая_рабочая",
        "планировки",
        "загрузки",
        "дома",
        "pdf",
        "сборка",
        "desktop",
        "downloads",
        "документы",
    }
)


def _project_bucket(path: str) -> str:
    import re

    p = Path(path)
    folders: list[str] = []
    for part in p.parts[:-1]:
        t = part.lower().replace("ё", "е").strip()
        if len(t) <= 2 or t in _BUCKET_SKIP or "загрузк" in t:
            continue
        if re.fullmatch(r"20\d{2}", t):
            continue
        folders.append(t)
    if folders:
        return folders[-1]
    return _layout_object_key({"path": path})


def _as_float(value) -> float | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", ".").replace("м²", "").replace("м2", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _opening_mm(size_raw: str) -> tuple[float | None, float | None]:
    import re

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*[xх×]\s*(\d+(?:[.,]\d+)?)", size_raw or "", re.I)
    if not m:
        return None, None
    return _as_float(m.group(1)), _as_float(m.group(2))


def _fts_tokens(query: str) -> list[str]:
    import re

    raw = re.findall(r"[0-9A-Za-zА-Яа-яЁё]{2,}", query)
    return [t.replace('"', "") for t in raw][:12]
