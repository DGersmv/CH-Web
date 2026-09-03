from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

from config import (
    OLLAMA_VL_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_PROXY,
    VISION_DPI,
    VISION_MAX_SIDE,
)

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

VL_PROMPT = """Это архитектурный чертёж или планировка. Внимательно прочитай подписи на листе.
Верни ТОЛЬКО JSON без markdown:
{
  "sheet": "планировка|фасад|разрез|узел|спецификация|другое",
  "rooms": [{"name": "гостиная", "area_m2": 18.4, "where": "слева"}],
  "walls": [{"material": "каркас/брус/неизвестно", "note": "если подписано"}],
  "openings": [{"kind": "дверь|окно|проём", "size": "2100x2300", "where": "справа"}],
  "dimensions": ["5855 мм"],
  "title": "кратко штамп или имя проекта",
  "notes": "ещё важное"
}
Правила: area_m2 только если площадь явно написана на листе, иначе null.
Проёмы, двери, окна, ворота — все, что подписано размером или обозначено на плане, в openings. Не выдумывай.
Не выдумывай комнаты и метры. Если лист нечитаемый — rooms [].
Русские названия комнат сохраняй как на чертеже.
"""


def render_page_jpeg(path: Path, page_no: int = 1) -> bytes:
    doc = fitz.open(path)
    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(VISION_DPI / 72, VISION_DPI / 72), alpha=False)
        from PIL import Image

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        w, h = img.size
        scale = min(1.0, VISION_MAX_SIDE / max(w, h))
        if scale < 1:
            img = img.resize((int(w * scale), int(h * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


def ocr_jpeg(data: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract

        img = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(img, lang="rus+eng")
        return " ".join(text.split())[:4000]
    except Exception:
        pass
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(data)).convert("RGB")
        engine = _rapid()
        result, _ = engine(np.array(img))
        if not result:
            return ""
        lines = [row[1] for row in result if len(row) > 1]
        return " ".join(str(x) for x in lines)[:4000]
    except Exception:
        pass
    try:
        from rapidocr import RapidOCR
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(data)).convert("RGB")
        result = RapidOCR()(np.array(img))
        if hasattr(result, "txts") and result.txts:
            return " ".join(result.txts)[:4000]
        return ""
    except Exception:
        return ""


_RAPID = None


def _rapid():
    global _RAPID
    if _RAPID is None:
        from rapidocr_onnxruntime import RapidOCR

        _RAPID = RapidOCR()
    return _RAPID


def parse_vl_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"raw": text[:2000], "rooms": []}
    try:
        data = json.loads(match.group(0))
        if not isinstance(data, dict):
            return {"raw": text[:2000], "rooms": []}
        return data
    except json.JSONDecodeError:
        return {"raw": text[:2000], "rooms": []}


def summarize_vl(data: dict, ocr: str) -> str:
    parts = []
    sheet = data.get("sheet")
    if sheet:
        parts.append(f"лист: {sheet}")
    title = data.get("title")
    if title:
        parts.append(str(title))
    rooms = data.get("rooms") or []
    for room in rooms[:12]:
        if not isinstance(room, dict):
            continue
        name = room.get("name") or ""
        area = room.get("area_m2")
        where = room.get("where") or ""
        bit = name
        if area not in (None, "", "null"):
            bit += f" {area} м²"
        if where:
            bit += f" ({where})"
        if bit.strip():
            parts.append(bit.strip())
    walls = data.get("walls") or []
    for wall in walls[:6]:
        if isinstance(wall, dict):
            w = " ".join(str(wall.get(k) or "") for k in ("material", "note")).strip()
            if w:
                parts.append("стены: " + w)
    openings = data.get("openings") or []
    if openings:
        bits = []
        for op in openings[:12]:
            if isinstance(op, dict):
                bits.append(
                    " ".join(
                        str(op.get(k) or "") for k in ("kind", "size", "where")
                    ).strip()
                )
            else:
                bits.append(str(op))
        bits = [b for b in bits if b]
        if bits:
            parts.append(f"проёмы ({len(bits)}): " + "; ".join(bits))
    dims = data.get("dimensions") or []
    if dims:
        parts.append("размеры: " + ", ".join(str(d) for d in dims[:8]))
    notes = data.get("notes")
    if notes:
        parts.append(str(notes)[:300])
    if ocr:
        parts.append("ocr: " + ocr[:400])
    return " | ".join(parts)[:1800]


def ask_vl(image_jpeg: bytes) -> str:
    import ollama

    resp = ollama.chat(
        model=OLLAMA_VL_MODEL,
        messages=[
            {
                "role": "user",
                "content": VL_PROMPT,
                "images": [image_jpeg],
            }
        ],
        options={"temperature": 0.1, "num_ctx": 4096},
    )
    return (resp.get("message") or {}).get("content") or ""


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _proxy_dict() -> dict[str, str] | None:
    proxy = (OPENROUTER_PROXY or "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def ask_openrouter(image_jpeg: bytes) -> tuple[str, float]:
    import requests

    if os.environ.get("MCP_NO_OPENROUTER"):
        raise OpenRouterError("MCP не вызывает OpenRouter")
    key = (OPENROUTER_API_KEY or "").strip()
    if not key:
        raise OpenRouterError("Нет OPENROUTER_API_KEY в .env")
    b64 = base64.b64encode(image_jpeg).decode("ascii")
    payload = {
        "model": OPENROUTER_MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VL_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "http://127.0.0.1:7860",
                "X-Title": "Scan Pdf Archive",
            },
            proxies=_proxy_dict(),
            timeout=180,
        )
    except requests.RequestException as exc:
        raise OpenRouterError(f"OpenRouter сеть: {exc}") from exc
    if resp.status_code >= 400:
        raise OpenRouterError(
            f"OpenRouter HTTP {resp.status_code}: {resp.text[:400]}",
            status=resp.status_code,
        )
    body = resp.json()
    text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if isinstance(text, list):
        parts = []
        for block in text:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        text = "\n".join(p for p in parts if p)
    usage = body.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        cost = usage.get("total_cost") or 0
    try:
        cost_f = float(cost or 0)
    except (TypeError, ValueError):
        cost_f = 0.0
    return str(text), cost_f
