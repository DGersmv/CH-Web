from __future__ import annotations

import re

# NМД в имени файла = N-модульный дом
MD_WORDS = {
    "1": "одномодульный одномодульн 1модульный 1 модульный",
    "2": "двухмодульный двухмодульн двумодульный 2модульный 2 модульный",
    "3": "трехмодульный трёхмодульный трехмодульн 3модульный 3 модульный",
    "4": "четырехмодульный четырёхмодульный 4модульный 4 модульный",
    "5": "пятимодульный 5модульный 5 модульный",
    "6": "шестимодульный 6модульный 6 модульный",
    "8": "восьмимодульный восьмимодульн 8модульный 8 модульный",
    "9": "девятимодульный 9модульный 9 модульный",
    "12": "двенадцатимодульный 12модульный 12 модульный",
}

ROOM_STEMS = (
    "гостин",
    "спальн",
    "кухн",
    "сануз",
    "ванн",
    "прихож",
    "террас",
    "площад",
    "помещен",
    "комнат",
    "детск",
    "саун",
    "парн",
    "хамам",
)

NUM_WORDS = {
    "один": 1,
    "одна": 1,
    "одной": 1,
    "одного": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "двумя": 2,
    "двое": 2,
    "три": 3,
    "трех": 3,
    "трёх": 3,
    "тремя": 3,
    "трое": 3,
    "четыре": 4,
    "четырех": 4,
    "четырёх": 4,
    "четырьмя": 4,
    "пять": 5,
    "пяти": 5,
    "пятью": 5,
    "шесть": 6,
    "шести": 6,
    "шестью": 6,
}

QUERY_FILLER = frozenset(
    {
        "дом",
        "дома",
        "дому",
        "домом",
        "домов",
        "доме",
        "проект",
        "проекта",
        "проекте",
        "проекту",
        "проектом",
        "проекты",
        "жилой",
        "жилого",
        "вариант",
        "варианте",
        "найди",
        "найти",
        "ищу",
        "покажи",
        "дай",
        "хочу",
        "нужен",
        "нужна",
        "нужно",
        "файл",
        "файлы",
        "pdf",
        "документ",
        "документы",
        "где",
        "какой",
        "какая",
        "какие",
        "какое",
        "есть",
        "этот",
        "эта",
        "это",
        "для",
        "или",
        "что",
        "кто",
        "как",
        "мне",
        "пожалуйста",
        "архив",
        "архиве",
        "лежит",
        "все",
        "всех",
        "весь",
        "всю",
        "любые",
        "любой",
        "отдельно",
        "более",
        "больше",
        "менее",
        "меньше",
        "свыше",
        "метров",
        "метра",
        "квадратных",
        "квадратные",
        "квадрата",
        "квадратный",
        "планировка",
        "планировки",
        "планировок",
        "планировке",
        "планировку",
        "планировкой",
        "площадь",
        "площади",
        "площадью",
        "площадей",
        "кв",
        "квм",
        "жилая",
        "жилую",
        "жилой",
        "застройка",
        "застройки",
        "застройке",
        "застройку",
        "общая",
        "общей",
        "общий",
        "общую",
        "общее",
        "суммарная",
        "суммарной",
        "суммарный",
        "суммарную",
        "суммарное",
        "примерно",
        "около",
        "порядка",
        "ориентировочно",
        "там",
        "этот",
        *NUM_WORDS.keys(),
    }
)

ROOM_KIND_STEMS = (
    ("спальн", "спальня"),
    ("детск", "детская"),
    ("гостин", "гостиная"),
    ("кухн", "кухня"),
    ("сануз", "санузел"),
    ("ванн", "санузел"),
    ("туалет", "санузел"),
    ("прихож", "прихожая"),
    ("террас", "терраса"),
    ("саун", "сауна"),
    ("парн", "сауна"),
    ("хамам", "сауна"),
)

ROOM_NAME_RE = {
    "спальня": re.compile(r"спальн(я|ая|ой|ую|ые)|мастер.?спаль", re.I),
    "детская": re.compile(r"детск", re.I),
    "гостиная": re.compile(r"гостин", re.I),
    "кухня": re.compile(r"кухн", re.I),
    "санузел": re.compile(r"сануз|с/у|с\\у|ванн|туалет", re.I),
    "прихожая": re.compile(r"прихож|холл", re.I),
    "терраса": re.compile(r"террас", re.I),
    "сауна": re.compile(r"саун|парн|хамам", re.I),
}

GLOSSARY_FOR_MODEL = """
Словарь архива (имена файлов и папок):
- NМД = N-модульный дом: 1МД — одномодульный, 2МД — двухмодульный, 3МД — трёхмодульный и так далее.
- В1, В2, В3 — обычно варианты планировки одного объекта. «Эскиз 1» ≈ В1.
- Площадь застройки в таблицах комнат нет: ищем ближайшую сумму помещений и жилую без террас/гаража.
- Имя объекта (Васкелово, Куприенко, Крым) важнее общего слова «планировка».

Если спрашивают состав дома, комнаты или м² — search_layout с формулировкой пользователя удобен.
Если инструмент вернул список — данные есть. Перечисли площадь, спальни и полный путь.
Не пиши «нет таких данных / нет площадей», пока список не пустой.
Цифры м² называй только если они есть в результате инструмента.
""".strip()


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def blob_with_md(name: str, relpath: str) -> str:
    blob = _norm(f"{name} {relpath}")
    extra: list[str] = []
    for match in re.finditer(r"(\d+)\s*(?:мд|модул)", blob):
        num = match.group(1)
        extra.append(f"{num}мд")
        extra.append(f"{num} модульный {num}модульный")
        extra.append(MD_WORDS.get(num, ""))
    return " ".join([blob, *extra])


def map_md_token(token: str) -> str:
    t = _norm(token)
    mapping = (
        (r"^одномодул", "1мд"),
        (r"^(двух|дву)модул", "2мд"),
        (r"^(трех|трёх)модул", "3мд"),
        (r"^(четырех|четырёх)модул", "4мд"),
        (r"^пятимодул", "5мд"),
        (r"^шестимодул", "6мд"),
        (r"^девятимодул", "9мд"),
        (r"^(\d+)модул", None),
    )
    for pattern, value in mapping:
        m = re.match(pattern, t)
        if not m:
            continue
        if value is None:
            return f"{m.group(1)}мд"
        return value
    m = re.match(r"^(\d+)мд$", t)
    if m:
        return f"{m.group(1)}мд"
    return token


def is_room_token(token: str) -> bool:
    t = _norm(token)
    return any(t.startswith(stem) or stem.startswith(t) for stem in ROOM_STEMS)


def is_query_filler(token: str) -> bool:
    t = _norm(token)
    if t in QUERY_FILLER:
        return True
    if t.isdigit() and not (len(t) == 4 and t.startswith("20")):
        return True
    return False


def room_kind_from_token(token: str) -> str | None:
    t = _norm(token)
    if len(t) < 4:
        return None
    for stem, kind in ROOM_KIND_STEMS:
        if t.startswith(stem) or stem.startswith(t[: max(4, len(stem))]):
            return kind
    return None


def room_kind_of_name(name: str) -> str | None:
    n = _norm(name)
    if not n:
        return None
    if "спальни" in n and not re.search(r"спальн(я|ая)", n):
        return None
    for kind, rx in ROOM_NAME_RE.items():
        if rx.search(n):
            return kind
    return None


def parse_room_program(query: str) -> dict[str, int]:
    """'дом с тремя спальнями' → {'спальня': 3}."""
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", _norm(query))
    counts: dict[str, int] = {}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        n: int | None = None
        if t.isdigit() and not (len(t) == 4 and t.startswith("20")):
            n = int(t)
        elif t in NUM_WORDS:
            n = NUM_WORDS[t]
        if n and i + 1 < len(tokens):
            kind = room_kind_from_token(tokens[i + 1])
            if kind:
                counts[kind] = max(counts.get(kind, 0), n)
                i += 2
                continue
        kind = room_kind_from_token(t)
        if kind:
            counts[kind] = max(counts.get(kind, 0), 1)
        i += 1
    return counts


OUTDOOR_ROOM = ("террас", "крыльц", "гараж", "балкон", "навес", "веранд")


def room_list_areas(rooms: list) -> tuple[float, float]:
    total = 0.0
    living = 0.0
    for r in rooms or []:
        if not isinstance(r, dict):
            continue
        raw = r.get("area_m2")
        if raw in (None, "", "null"):
            continue
        try:
            area = float(raw)
        except (TypeError, ValueError):
            continue
        total += area
        name = _norm(str(r.get("name") or ""))
        if not any(s in name for s in OUTDOOR_ROOM):
            living += area
    return round(total, 1), round(living, 1)


def parse_area_filter(query: str) -> dict[str, float]:
    """Фильтр м²: 'более 120' → min; 'жилая 145 застройка 161' → цели, не порог."""
    q = _norm(query)
    if not re.search(r"м\s*[²2]|кв\.?\s*м|квадрат|площад|метр|планир|жилая|застрой", q):
        return {}
    out: dict[str, float] = {}
    m = re.search(
        r"(более|больше|свыше|от|минимум|не\s*менее|>|>=)\s*(\d+(?:[.,]\d+)?)", q
    )
    if m:
        out["min_m2"] = float(m.group(2).replace(",", "."))
    m = re.search(
        r"(менее|меньше|до|максимум|не\s*более|<|<=)\s*(\d+(?:[.,]\d+)?)", q
    )
    if m:
        out["max_m2"] = float(m.group(2).replace(",", "."))
    m = re.search(r"жилая[^\d]{0,32}(\d+(?:[.,]\d+)?)", q)
    if m:
        out["target_living"] = float(m.group(1).replace(",", "."))
    m = re.search(r"застройк\w*[^\d]{0,32}(\d+(?:[.,]\d+)?)", q)
    if m:
        out["target_total"] = float(m.group(1).replace(",", "."))
    if "target_living" in out or "target_total" in out:
        out.pop("min_m2", None)
        return out
    if not out:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м\s*[²2]|кв\.?\s*м|квадрат)", q)
        if m:
            val = float(m.group(1).replace(",", "."))
            if re.search(r"примерно|около|порядка|ориентир|~", q):
                out["target_total"] = val
            else:
                out["min_m2"] = val
    return out


def token_like_needles(token: str) -> list[str]:
    t = _norm(token)
    m = re.match(r"^(\d+)мд$", t)
    if m:
        n = m.group(1)
        return [f"{n}мд", f"{n} модул", f"{n}модул"]
    return [t]


def layout_object_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    q = _norm(query)
    for match in re.finditer(r"(\d+)\s*модул", q):
        tokens.append(f"{match.group(1)}мд")
    sketch = re.search(r"эскиз\s*(\d+)\b", q)
    if sketch:
        tokens.append(f"в{sketch.group(1)}")
    seen = set(tokens)
    for raw in re.findall(r"[0-9A-Za-zА-Яа-яЁё]{3,}", q):
        if raw in QUERY_FILLER or is_room_token(raw) or is_query_filler(raw):
            continue
        if raw.startswith("модул") or raw.startswith("эскиз"):
            continue
        mapped = map_md_token(raw)
        if mapped in seen:
            continue
        seen.add(mapped)
        if mapped != raw and mapped.endswith("мд"):
            tokens.append(mapped)
            continue
        tokens.append(mapped)
    return tokens[:8]


def is_layout_query(query: str) -> bool:
    q = _norm(query)
    if parse_room_program(query) or parse_area_filter(query):
        return True
    keys = (
        "планир",
        "спальн",
        "саун",
        "парн",
        "проем",
        "площад",
        "квадрат",
        "гостин",
        "кухн",
        "чертеж",
        "модульн",
        "экспликац",
        "помещен",
        "строител",
    )
    return any(k in q for k in keys)


LAYOUT_SKIP_STEMS = (
    "электр",
    "электро",
    "кассет",
    "кжд",
    "спецификац",
    "ведомост",
    "штамп",
    "сборки пола",
    "сборки потол",
    "план стен",
    "перекрыт",
    "фундамент",
)

LAYOUT_SKIP_FOLDERS = (
    "\\стены\\",
    "\\спец\\",
    "\\рамка\\",
    "\\пол\\",
    "\\полы\\",
    "\\потолок\\",
    "\\потолки\\",
    "\\кж\\",
    "\\осв\\",
    "\\фасад\\",
)


def is_layout_candidate(path: str, name: str, blob: str) -> bool:
    """PDF похож на планировку помещений, а не на стены/электрику/спецификацию."""
    p = _norm(path).replace("/", "\\")
    n = _norm(name)
    b = _norm(blob or f"{name} {path}")
    has_planir = "планир" in b
    if any(s in p for s in LAYOUT_SKIP_FOLDERS) and not has_planir:
        return False
    if any(s in b for s in LAYOUT_SKIP_STEMS) and not has_planir:
        return False
    if not has_planir and any(s in b for s in ("фасад", "разрез", "узел")):
        return False
    if has_planir:
        return True
    if re.search(r"(^|[^0-9a-zа-я])в\d", n):
        return True
    compact = n.replace(" ", "")
    if re.search(r"\d+мд", compact):
        return True
    return False
