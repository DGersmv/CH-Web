from __future__ import annotations

import json
import msvcrt
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from config import ARCHIVE_ROOT, LAYOUT_PROGRAM_LIMIT, OPENROUTER_API_KEY, OPENROUTER_MAX_USD, SEARCH_LIMIT, VISION_PAGES_PER_FILE
from plugins.base import SearchHit, SyncStats, ToolSpec
from plugins.pdf_archive.extract import extract_pdf, iter_pdfs, path_meta
from plugins.pdf_archive.store import Catalog
from plugins.pdf_archive.vectors import PageIndex
from domain import blob_with_md, is_layout_query, is_query_filler, is_room_token, layout_object_tokens, map_md_token, parse_area_filter, parse_room_program, room_kind_of_name, room_list_areas, token_like_needles


STOPWORDS = frozenset(
    {
        "найди", "найти", "мне", "где", "какой", "какая", "какие", "какое",
        "файл", "файлы", "pdf", "документ", "документы", "пожалуйста",
        "нужно", "покажи", "лежит", "архиве", "архив", "есть", "этот",
        "эта", "это", "для", "или", "что", "кто", "как", "the", "дай",
        "хочу", "нужна", "нужен", "ищу",
    }
)
TYPE_STEMS = (
    "планиров", "чертеж", "чертеж", "кассет", "штамп", "лист", "акт",
    "модул",
)


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _split_query(query: str) -> tuple[list[str], list[str], list[str]]:
    unique: list[str] = list(layout_object_tokens(query))
    types: list[str] = []
    rooms: list[str] = []
    seen = set(unique)
    raw = re.findall(r"[0-9A-Za-zА-Яа-яЁё]{3,}", _norm(query))
    for token in raw:
        if token in STOPWORDS or is_query_filler(token):
            continue
        if is_room_token(token):
            rooms.append(token)
            continue
        mapped = map_md_token(token)
        if mapped in seen or token.startswith("модул") or token.startswith("эскиз"):
            continue
        if mapped != token and mapped.endswith("мд"):
            unique.append(mapped)
            seen.add(mapped)
            continue
        if any(token.startswith(stem) or stem.startswith(token) for stem in TYPE_STEMS):
            types.append(token)
        else:
            unique.append(mapped)
            seen.add(mapped)
    return unique, types, rooms


def _contains_all(text: str, tokens: list[str]) -> bool:
    blob = _norm(text)
    for t in tokens:
        needles = token_like_needles(t)
        if not any(n in blob for n in needles):
            return False
    return True


def _rrf_merge(groups: list[list[SearchHit]], limit: int) -> list[SearchHit]:
    scores: dict[str, float] = {}
    best: dict[str, SearchHit] = {}
    for group in groups:
        for i, hit in enumerate(group):
            key = hit.path
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + i)
            prev = best.get(key)
            if prev is None or (hit.page and not prev.page) or hit.score > prev.score:
                if prev and not hit.snippet:
                    hit.snippet = prev.snippet
                best[key] = hit
    ranked = sorted(best.values(), key=lambda h: scores.get(h.path, 0.0), reverse=True)
    for hit in ranked:
        hit.score = scores.get(hit.path, hit.score)
    return ranked[:limit]


def _format_hits(hits: list[SearchHit]) -> str:
    if not hits:
        return "Ничего не найдено. Если это имя объекта — его нет ни в пути, ни в имени файла."
    lines = []
    for i, hit in enumerate(hits, 1):
        extra = hit.extra or {}
        loc = extra.get("relpath") or hit.path
        page = f", стр. {hit.page}" if hit.page else ""
        kind = extra.get("kind") or ""
        lines.append(
            f"{i}. {hit.title}{page}\n"
            f"   путь: {hit.path}\n"
            f"   относительно: {loc} | вид: {kind}\n"
            f"   фрагмент: {hit.snippet[:280]}"
        )
    return "\n\n".join(lines)


class PdfArchivePlugin:
    name = "pdf_archive"
    title = "Архив PDF"

    def __init__(self):
        self.catalog = Catalog()
        self.pages = PageIndex()
        self.root = ARCHIVE_ROOT

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_pdf",
                description=(
                    "Найти PDF по имени файла, объекта, папке, году, 1МД/2МД или любой подписи. "
                    "Если тот же проект — можно передать scope."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Поисковый запрос: имя файла, проект, год, суть документа",
                        },
                        "scope": {
                            "type": "string",
                            "description": (
                                "Имя объекта или фрагмент пути с прошлого шага. "
                                "Файлы без этого фрагмента в пути отбрасываются."
                            ),
                        },
                    },
                    "required": ["query"],
                },
                handler=self._tool_search,
            ),
            ToolSpec(
                name="get_pdf_info",
                description="Карточка одного PDF по полному пути: страницы, вид, штамп, сниппет, папка.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Полный путь к PDF, как вернул search_pdf",
                        }
                    },
                    "required": ["path"],
                },
                handler=self._tool_info,
            ),
            ToolSpec(
                name="look_at_drawing",
                description=(
                    "Комнаты и площади одного PDF из уже готовых таблиц. "
                    "Не ходит в облако."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Полный путь к PDF"}
                    },
                    "required": ["path"],
                },
                handler=self._tool_look,
            ),
            ToolSpec(
                name="search_layout",
                description=(
                    "Планировки из базы комнат и площадей. "
                    "Спальни, сауна, м², объект, проёмы — любой такой вопрос."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Объект и что нужно: Васкелово проёмы, Куприенко гостиная",
                        }
                    },
                    "required": ["query"],
                },
                handler=self._tool_layout,
            ),
        ]

    def _tool_search(self, query: str = "", scope: str = "", **_: object) -> str:
        q = (query or "").strip()
        sc = (scope or "").strip()
        if sc and sc.lower() not in q.lower():
            q = f"{sc} {q}".strip()
        if parse_room_program(q) or parse_area_filter(q):
            return (
                "Запрос про планировку/площадь/состав — искал в таблицах комнат, не в тексте PDF.\n\n"
                + self._tool_layout(q)
            )
        if is_layout_query(q) and not layout_object_tokens(q):
            return (
                "Запрос про комнаты/планировки — искал в таблицах.\n\n"
                + self._tool_layout(q)
            )
        hits = self.search(q, limit=SEARCH_LIMIT)
        if sc:
            needle = sc.lower().replace("ё", "е")
            hits = [
                h for h in hits
                if needle in (h.path or "").lower().replace("ё", "е")
                or needle in (h.title or "").lower().replace("ё", "е")
            ]
        return _format_hits(hits)

    def _tool_layout(self, query: str = "", **_: object) -> str:
        q = query or ""
        program = parse_room_program(q)
        area = parse_area_filter(q)
        if area.get("target_living") or area.get("target_total"):
            limit = 15
        elif area:
            limit = max(LAYOUT_PROGRAM_LIMIT, 250)
        elif program:
            limit = LAYOUT_PROGRAM_LIMIT
        else:
            limit = SEARCH_LIMIT
        rows = self.catalog.search_layout(q, limit=limit)
        if not rows:
            if program or area:
                bits = []
                if program:
                    bits.append(", ".join(f"{n}× {k}" for k, n in program.items()))
                if area.get("min_m2") is not None:
                    bits.append(f"от {area['min_m2']} м²")
                if area.get("max_m2") is not None:
                    bits.append(f"до {area['max_m2']} м²")
                return "В таблицах планировок нет листов: " + "; ".join(bits)
            return (
                "В таблицах планировок пока нет фактов по этому запросу. "
                "Если это имя объекта — вызови search_pdf по имени, не по комнатам."
            )
        want_openings = any(
            x in _norm(q) for x in ("проем", "двер", "окн", "стен")
        )
        header = ""
        if program or area:
            need = []
            if area.get("target_living") is not None:
                need.append(f"жилая ~{area['target_living']} м²")
            if area.get("target_total") is not None:
                need.append(f"общая/застройка ~{area['target_total']} м²")
            if area.get("min_m2") is not None:
                need.append(f"≥{area['min_m2']} м²")
            if area.get("max_m2") is not None:
                need.append(f"≤{area['max_m2']} м²")
            if program:
                need.append(", ".join(f"≥{n} {k}" for k, n in program.items()))
            if area.get("target_living") or area.get("target_total"):
                header = (
                    f"Ближайшие к {'; '.join(need)}. "
                    f"Точного совпадения может не быть — цифры из таблиц комнат, "
                    f"площадь застройки в штампе может отличаться. Перечисли с путём:\n\n"
                )
            else:
                header = (
                    f"Найдено {len(rows)} планировок ({'; '.join(need) or 'фильтр'}). "
                    f"Это факты из таблиц, данные есть. Перечисли с м² и путём:\n\n"
                )
        blocks = []
        for row in rows:
            counts = row.get("room_counts") or {}
            label = Path(row["path"]).stem
            total = row.get("area_total")
            living = row.get("area_living")
            if total is None:
                total, living = room_list_areas(row.get("rooms") or [])
            if program or area:
                matched = []
                for r in row.get("rooms") or []:
                    kind = room_kind_of_name(r.get("name") or "")
                    if program and kind not in program:
                        continue
                    if not program:
                        break
                    bit = r.get("name") or ""
                    if r.get("area_m2") is not None:
                        bit += f" {r['area_m2']} м²"
                    matched.append(bit.strip())
                count_txt = ", ".join(f"{k} {v}" for k, v in counts.items() if v)
                if total:
                    area_txt = f"{total} м²"
                    if living and abs(living - total) >= 1:
                        area_txt += f" (без террас/гаража {living} м²)"
                else:
                    area_txt = "площадь не размечена"
                extra = "; ".join(matched)
                line = f"{label} — {area_txt}"
                if count_txt:
                    line += f" | {count_txt}"
                if extra:
                    line += f" | {extra}"
                blocks.append(f"{line}\nпуть: {row['path']}")
                continue
            rooms = []
            beds = []
            other = []
            for r in row.get("rooms") or []:
                bit = r.get("name") or ""
                if r.get("area_m2") is not None:
                    bit += f" {r['area_m2']} м²"
                if r.get("where_txt"):
                    bit += f" ({r['where_txt']})"
                if not bit.strip():
                    continue
                name_l = _norm(r.get("name") or "")
                if "спальн" in name_l:
                    beds.append(bit.strip())
                else:
                    other.append(bit.strip())
                rooms.append(bit.strip())
            count_txt = ""
            if total:
                living_bit = ""
                if living and abs(living - total) >= 1:
                    living_bit = f" (без террас/гаража {living} м²)"
                count_txt += f"площадь: {total} м²{living_bit}\n"
            if counts:
                count_txt += (
                    "состав: "
                    + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
                    + "\n"
                )
            openings = row.get("openings") or []
            op_line = ""
            if want_openings:
                op_bits = []
                for op in openings:
                    op_bits.append(
                        " ".join(
                            str(op.get(k) or "")
                            for k in ("kind", "size_raw", "where_txt")
                        ).strip()
                    )
                op_line = (
                    f"проёмы ({len(openings)}): "
                    f"{'; '.join(b for b in op_bits if b) or 'нет'}\n"
                )
            walls_line = ""
            if want_openings:
                walls = []
                for w in row.get("walls") or []:
                    walls.append(
                        " ".join(
                            str(w.get(k) or "")
                            for k in ("material", "length_mm", "note")
                        ).strip()
                    )
                walls_line = f"стены: {'; '.join(w for w in walls if w) or 'нет'}\n"
            room_line = "; ".join(beds + other[:8]) or "нет"
            label = Path(row["path"]).stem
            blocks.append(
                f"{label} {row.get('version') or ''} стр.{row.get('page')}\n"
                f"путь: {row['path']}\n"
                f"лист: {row.get('sheet_type') or ''} {row.get('title') or ''}\n"
                f"{count_txt}"
                f"комнаты: {room_line}\n"
                f"{op_line}{walls_line}".rstrip()
            )
        return header + "\n\n".join(blocks)

    def _tool_info(self, path: str = "", **_: object) -> str:
        row = self.catalog.get(path.strip().strip('"'))
        if not row:
            return f"В индексе нет файла: {path}"
        return json.dumps(
            {
                "path": row["path"],
                "name": row["name"],
                "relpath": row["relpath"],
                "pages": row["pages"],
                "kind": row["kind"],
                "year": row["year"],
                "project": row["project"],
                "titleblock": row["titleblock"],
                "snippet": row["snippet"],
                "error": row["error"],
                "vision": self._vision_block(path.strip().strip('"')),
            },
            ensure_ascii=False,
            indent=2,
        )

    def _tool_look(self, path: str = "", **_: object) -> str:
        p = Path((path or "").strip().strip('"'))
        if not p.is_file():
            return f"Файл не найден: {path}"
        if os.environ.get("MCP_NO_OPENROUTER"):
            if self.catalog.search_layout(p.name, limit=3):
                return self._tool_layout(p.name)
            return (
                "MCP не вызывает OpenRouter. Ищи search_layout "
                "или дождись очереди layout_sync."
            )
        blob = _norm(f"{p.name} {p.as_posix()}")
        skip = (
            "электрик",
            "электро",
            "кассет",
            "фасад",
            "разрез",
            "узел",
            "спецификац",
            "ведомост",
            "кжд",
        )
        if any(s in blob for s in skip):
            return (
                "Это не планировка помещений (электрика/фасад/конструкции). "
                "Для поиска дома по комнатам вызови search_layout, например «3 спальни»."
            )
        try:
            self.analyze_layout(p)
        except Exception:
            try:
                self.analyze_pdf(p)
            except Exception as exc:
                return f"Не удалось распознать чертёж: {exc}"
        layout = self.catalog.search_layout(p.name, limit=3)
        if layout:
            return self._tool_layout(p.name)
        facts = self.catalog.vision_for_file(str(p))
        if not facts:
            return "Распознавание не вернуло данных."
        return json.dumps(
            [{"page": f.get("page"), "summary": f.get("summary"), "error": f.get("error")} for f in facts],
            ensure_ascii=False,
            indent=2,
        )

    def _vision_block(self, path: str) -> list[dict]:
        return [
            {"page": r.get("page"), "summary": r.get("summary"), "error": r.get("error")}
            for r in self.catalog.vision_for_file(path)
        ]

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[SearchHit]:
        q = (query or "").strip()
        if not q:
            return []
        unique, types, rooms = _split_query(q)
        must = unique or types
        vis_tokens = unique + rooms if (unique or rooms) else [_norm(q)[:40]]
        try:
            vision_hits = self.catalog.search_vision(vis_tokens, limit=limit)
        except Exception:
            vision_hits = []
        if unique:
            vision_hits = [h for h in vision_hits if _contains_all(f"{h.path} {h.title}", unique)]

        name_hits = self.catalog.search_names(must, limit=limit) if must else []
        if unique and not name_hits:
            name_hits = self._live_name_search(unique, types, limit=limit)

        if unique:
            name_hits = [
                h for h in name_hits
                if _contains_all(f"{h.path} {h.title}", unique)
            ]
            if types:
                name_hits.sort(
                    key=lambda h: (
                        0 if _contains_all(f"{h.path} {h.title}", types) else 1,
                        -h.score,
                    )
                )

        if rooms:
            content_q = " ".join(rooms)
            fts = self.catalog.fts_search(content_q, limit=limit * 2)
            try:
                vec = self.pages.search(content_q, limit=limit * 2)
            except Exception:
                vec = []
            content = _rrf_merge([vision_hits, fts, vec], limit=limit * 2)
            content = [
                h for h in content
                if any(stem in _norm(f"{h.snippet} {h.title}") for room in rooms for stem in (room, room[:5]))
                or (h.extra or {}).get("via") == "vision"
            ]
            if unique:
                content = [
                    h for h in content
                    if _contains_all(f"{h.path} {h.title}", unique)
                ]
            if vision_hits:
                return _rrf_merge([vision_hits, content, name_hits], limit=limit)
            if not content and unique:
                for hit in name_hits:
                    extra = " [чертёж ещё в очереди на зрение — могу распознать look_at_drawing]"
                    if extra not in (hit.snippet or ""):
                        hit.snippet = (hit.snippet or "") + extra
                return name_hits[:limit]
            return (content + [h for h in name_hits if h.path not in {c.path for c in content}])[:limit]

        if unique:
            if vision_hits:
                return _rrf_merge([vision_hits, name_hits], limit=limit)
            return name_hits[:limit]

        fts = self.catalog.fts_search(q, limit=limit)
        try:
            vec = self.pages.search(q, limit=limit)
        except Exception:
            vec = []
        merged = _rrf_merge([name_hits, vision_hits, fts, vec], limit=limit * 2)
        years = re.findall(r"20\d{2}", q)
        needles = unique + types
        for hit in merged:
            blob = _norm(f"{hit.path} {hit.title}")
            if any(y in hit.path for y in years):
                hit.score += 1.2
            hit.score += 0.35 * sum(1 for n in needles if n in blob)
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:limit]

    def index_names(self, progress: Callable[[str], None] | None = None) -> int:
        log = progress or (lambda _m: None)
        log("Сканирую имена PDF…")
        items: list[tuple[str, str, str, str]] = []
        for path in iter_pdfs(self.root):
            rel, _year, _project = path_meta(path)
            blob = blob_with_md(path.name, rel)
            items.append((str(path), path.name, rel, blob))
        n = self.catalog.upsert_names(items)
        log(f"Имён в каталоге: {n}")
        return n

    def analyze_pdf(self, path: Path, max_pages: int = VISION_PAGES_PER_FILE) -> int:
        from plugins.pdf_archive.vision import (
            ask_vl,
            ocr_jpeg,
            parse_vl_json,
            render_page_jpeg,
            summarize_vl,
        )

        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # type: ignore

        doc = fitz.open(path)
        n_pages = min(doc.page_count, max_pages)
        doc.close()
        done = 0
        for page_no in range(1, n_pages + 1):
            err = ""
            ocr = ""
            summary = ""
            payload = "{}"
            try:
                jpeg = render_page_jpeg(path, page_no)
                ocr = ocr_jpeg(jpeg)
                raw = ask_vl(jpeg)
                data = parse_vl_json(raw)
                payload = json.dumps(data, ensure_ascii=False)
                summary = summarize_vl(data, ocr)
            except Exception as exc:
                err = str(exc)[:300]
            blob = _norm(f"{path.name} {summary} {ocr}")
            self.catalog.upsert_vision(
                str(path),
                page_no,
                ocr,
                payload,
                summary,
                blob,
                error=err,
                done_at=time.time(),
            )
            done += 1
        return done

    def analyze_layout(self, path: Path, max_pages: int = VISION_PAGES_PER_FILE) -> float:
        from plugins.pdf_archive.vision import (
            OpenRouterError,
            ask_openrouter,
            parse_vl_json,
            render_page_jpeg,
            summarize_vl,
        )

        if os.environ.get("MCP_NO_OPENROUTER"):
            raise RuntimeError("MCP не вызывает OpenRouter")
        if not (OPENROUTER_API_KEY or "").strip():
            raise RuntimeError("Нет OPENROUTER_API_KEY в .env")
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # type: ignore

        doc = fitz.open(path)
        n_pages = min(doc.page_count, max_pages)
        doc.close()
        obj, ver = _object_version(path)
        total = 0.0
        for page_no in range(1, n_pages + 1):
            err = ""
            data: dict = {}
            cost = 0.0
            summary = ""
            try:
                jpeg = render_page_jpeg(path, page_no)
                raw, cost = ask_openrouter(jpeg)
                total += cost
                data = parse_vl_json(raw)
                summary = summarize_vl(data, "")
            except OpenRouterError:
                raise
            except Exception as exc:
                err = str(exc)[:300]
            facts = _norm(f"{path.name} {obj} {ver} {summary}")
            self.catalog.upsert_layout(
                str(path),
                page_no,
                obj,
                ver,
                data,
                facts,
                cost_usd=cost,
                source="openrouter",
                error=err,
                done_at=time.time(),
            )
            self.catalog.upsert_vision(
                str(path),
                page_no,
                "",
                json.dumps(data, ensure_ascii=False),
                summary,
                facts,
                error=err,
                done_at=time.time(),
            )
        return total

    def sync_layout(
        self,
        progress: Callable[[str], None] | None = None,
        batch: int = 20,
        name_contains: str = "",
        max_usd: float | None = None,
    ) -> int:
        log = progress or (lambda _m: None)
        budget = OPENROUTER_MAX_USD if max_usd is None else max_usd
        lock_path = self.catalog.dir / "layout.lock"
        lock_fp = open(lock_path, "a+b")
        try:
            if lock_fp.tell() == 0:
                lock_fp.write(b"0")
                lock_fp.flush()
            lock_fp.seek(0)
            msvcrt.locking(lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_fp.close()
            log("очередь OpenRouter уже идёт")
            return 0
        try:
            from plugins.pdf_archive.vision import OpenRouterError

            spent = self.catalog.layout_spent_usd()
            if spent >= budget:
                log(f"лимит ${budget:.2f}, уже ${spent:.4f}")
                return 0
            paths = self.catalog.pending_layout_paths(
                limit=batch, name_contains=name_contains
            )
            if not paths:
                log("очередь планировок пуста")
                return 0
            n = 0
            for i, path_s in enumerate(paths, 1):
                spent = self.catalog.layout_spent_usd()
                if spent >= budget:
                    log(f"стоп: лимит ${budget:.2f}")
                    break
                path = Path(path_s)
                log(f"OpenRouter {i}/{len(paths)} ${spent:.4f}: {path.name}")
                if not path.is_file():
                    continue
                try:
                    cost = self.analyze_layout(path)
                    n += 1
                    log(f"  ок +${cost:.4f}")
                except OpenRouterError as exc:
                    log(f"OpenRouter: {exc}")
                    if getattr(exc, "status", 0) in (401, 402, 403):
                        break
                except Exception as exc:
                    log(f"ошибка {path.name}: {exc}")
            return n
        finally:
            try:
                lock_fp.seek(0)
                msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            lock_fp.close()

    def sync_vision(self, progress: Callable[[str], None] | None = None, batch: int = 6) -> int:
        log = progress or (lambda _m: None)
        lock_path = self.catalog.dir / "vision.lock"
        lock_fp = open(lock_path, "a+b")
        try:
            if lock_fp.tell() == 0:
                lock_fp.write(b"0")
                lock_fp.flush()
            lock_fp.seek(0)
            msvcrt.locking(lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_fp.close()
            log("зрение уже идёт в другом процессе")
            return 0
        try:
            paths = self.catalog.pending_vision_paths(limit=batch)
            if not paths:
                log("очередь зрения пуста")
                return 0
            n = 0
            for i, path_s in enumerate(paths, 1):
                path = Path(path_s)
                log(f"зрение {i}/{len(paths)}: {path.name}")
                if not path.is_file():
                    continue
                try:
                    self.analyze_pdf(path)
                    n += 1
                except Exception as exc:
                    log(f"ошибка зрения {path.name}: {exc}")
            return n
        finally:
            try:
                lock_fp.seek(0)
                msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            lock_fp.close()

    def _live_name_search(
        self, unique: list[str], types: list[str], limit: int
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for path in iter_pdfs(self.root):
            rel, _year, _project = path_meta(path)
            blob = blob_with_md(path.name, rel)
            if not all(t in blob for t in unique):
                continue
            extra = {"relpath": rel, "via": "disk"}
            score = 2.0
            if types and any(t in blob for t in types):
                score += 1.0
            hits.append(
                SearchHit(
                    path=str(path),
                    title=path.name,
                    snippet=rel,
                    score=score,
                    extra=extra,
                )
            )
            if len(hits) >= limit * 3:
                break
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    def status(self) -> dict:
        return {
            "plugin": self.name,
            "root": str(self.root),
            "indexed": self.catalog.count(),
            "vision_files": self.catalog.vision_count(),
            "layout_sheets": self.catalog.layout_sheet_count(),
            "layout_usd": round(self.catalog.layout_spent_usd(), 4),
            "root_exists": self.root.is_dir(),
        }

    def sync(self, progress: Callable[[str], None] | None = None) -> SyncStats:
        stats = SyncStats()
        log = progress or (lambda _m: None)
        if not self.root.is_dir():
            stats.message = f"Папка не найдена: {self.root}"
            return stats

        lock_path = self.catalog.dir / "sync.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fp = open(lock_path, "a+b")
        try:
            if lock_fp.tell() == 0:
                lock_fp.write(b"0")
                lock_fp.flush()
            lock_fp.seek(0)
            msvcrt.locking(lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_fp.close()
            stats.message = "Индексация уже идёт в другом процессе"
            log(stats.message)
            stats.indexed = self.catalog.count()
            return stats

        try:
            return self._sync_body(stats, log)
        finally:
            try:
                lock_fp.seek(0)
                msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            lock_fp.close()

    def _sync_body(self, stats: SyncStats, log: Callable[[str], None]) -> SyncStats:
        log("Сканирую PDF на диске…")
        disk: dict[str, tuple[Path, int, float]] = {}
        for path in iter_pdfs(self.root):
            try:
                st = path.stat()
            except OSError:
                stats.errors += 1
                continue
            disk[str(path)] = (path, st.st_size, st.st_mtime)

        stats.total_on_disk = len(disk)
        self.catalog.upsert_names(
            [
                (str(p), p.name, path_meta(p)[0], blob_with_md(p.name, path_meta(p)[0]))
                for p, _size, _mtime in disk.values()
            ]
        )
        known = self.catalog.snapshot()
        to_index: list[tuple[Path, int, float, str]] = []
        for path_s, (path, size, mtime) in disk.items():
            old = known.get(path_s)
            if old is None:
                to_index.append((path, size, mtime, "add"))
            elif old[0] != size or abs(old[1] - mtime) > 1:
                to_index.append((path, size, mtime, "update"))
            else:
                stats.skipped += 1

        gone = [p for p in known if p not in disk]
        for path_s in gone:
            self.catalog.delete(path_s)
            self.pages.delete_file(path_s)
            stats.removed += 1

        n = len(to_index)
        log(f"К обработке: {n} файлов, без изменений: {stats.skipped}, удалить: {len(gone)}")
        for i, (path, size, mtime, action) in enumerate(to_index, 1):
            if i == 1 or i % 10 == 0 or i == n:
                log(f"Индексация {i}/{n}: {path.name}")
            try:
                extracted = extract_pdf(path)
                now = time.time()
                self.catalog.upsert(extracted, size=size, mtime=mtime, indexed_at=now)
                if not extracted.error:
                    self.pages.upsert_file(extracted)
                if action == "add":
                    stats.added += 1
                else:
                    stats.updated += 1
            except Exception as exc:
                stats.errors += 1
                log(f"Ошибка {path}: {exc}")

        stats.indexed = self.catalog.count()
        stats.message = "Индекс обновлён"
        log(stats.as_text())
        return stats


def _object_version(path: Path) -> tuple[str, str]:
    stem = path.stem
    match = re.search(r"(в\s*\d+)\s*$", stem, re.I)
    version = ""
    obj = stem
    if match:
        version = re.sub(r"\s+", "", match.group(1)).lower()
        obj = stem[: match.start()].strip(" -_")
    return _norm(obj), version
