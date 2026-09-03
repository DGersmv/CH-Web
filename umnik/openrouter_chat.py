from __future__ import annotations

import os
import re
from typing import Any

import requests

from config import OPENROUTER_API_KEY, OPENROUTER_CHAT_MODEL, OPENROUTER_MAX_TOKENS, OPENROUTER_PROXY


class OpenRouterChatError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    key = (OPENROUTER_API_KEY or "").strip()
    if not key:
        raise OpenRouterChatError("Нет OPENROUTER_API_KEY в .env")
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "http://127.0.0.1:7860",
        "X-Title": "Scan Pdf Archive",
        "Content-Type": "application/json",
    }


def _proxies() -> dict[str, str] | None:
    proxy = (OPENROUTER_PROXY or "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "\n".join(p for p in parts if p)
    return str(content)


def _sanitize_error(text: str) -> str:
    text = re.sub(r"keys/[a-f0-9]+", "keys/…", text, flags=re.I)
    return " ".join(text.split())[:280]


def complete(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if os.environ.get("MCP_NO_OPENROUTER"):
        raise OpenRouterChatError("MCP не вызывает OpenRouter")
    mid = (model or OPENROUTER_CHAT_MODEL).strip()
    limit = int(max_tokens or OPENROUTER_MAX_TOKENS)
    payload: dict[str, Any] = {
        "model": mid,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": limit,
        "usage": {"include": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=_headers(),
            proxies=_proxies(),
            timeout=180,
        )
    except requests.RequestException as exc:
        raise OpenRouterChatError(f"OpenRouter сеть: {exc}") from exc
    if resp.status_code == 402 and limit > 2048:
        return complete(
            messages,
            tools=tools,
            temperature=temperature,
            model=model,
            max_tokens=2048,
        )
    if resp.status_code >= 400:
        raise OpenRouterChatError(
            f"OpenRouter HTTP {resp.status_code}: {_sanitize_error(resp.text)}"
        )
    body = resp.json()
    msg = ((body.get("choices") or [{}])[0].get("message") or {})
    usage = body.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        cost = usage.get("total_cost") or 0
    try:
        cost_f = float(cost or 0)
    except (TypeError, ValueError):
        cost_f = 0.0
    tool_calls = msg.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        tool_calls = [tool_calls] if tool_calls else []
    return {
        "content": _as_text(msg.get("content")),
        "reasoning": _as_text(msg.get("reasoning") or msg.get("reasoning_content")),
        "tool_calls": tool_calls,
        "cost": cost_f,
        "raw": msg,
    }


def tool_call_name(call: Any) -> str:
    if not isinstance(call, dict):
        return ""
    fn = call.get("function") or {}
    if isinstance(fn, dict):
        return str(fn.get("name") or "")
    return str(call.get("name") or "")


def tool_call_args(call: Any) -> Any:
    if not isinstance(call, dict):
        return {}
    fn = call.get("function") or {}
    if isinstance(fn, dict):
        return fn.get("arguments")
    return call.get("arguments")


def tool_call_id(call: Any, index: int) -> str:
    if isinstance(call, dict) and call.get("id"):
        return str(call["id"])
    return f"call_{index}"
