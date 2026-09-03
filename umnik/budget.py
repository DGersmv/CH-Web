"""Счётчик денег OpenRouter: общий и по пользователю.

Ключ один на всех, а чат теперь открыт всей сети — без потолка один человек
может выжечь баланс за вечер. Считаем на диск, чтобы перезапуск не обнулял.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from config import CHAT_MAX_USD_PER_USER, DATA_DIR, OPENROUTER_MAX_USD

STATE = DATA_DIR / "chat_budget.json"


class Budget:
    def __init__(self, total_limit: float, user_limit: float, path: Path = STATE):
        self.total_limit = float(total_limit)
        self.user_limit = float(user_limit)
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _blank(self) -> dict:
        return {"day": self._today(), "total": 0.0, "users": {}, "asks": {}}

    def _load(self) -> dict:
        if not self.path.is_file():
            return self._blank()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._blank()
        if not isinstance(data, dict):
            return self._blank()
        data.setdefault("day", self._today())
        data.setdefault("total", 0.0)
        data.setdefault("users", {})
        data.setdefault("asks", {})
        return data

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def _roll_day(self) -> None:
        """Лимиты суточные: новый день — новый бюджет."""
        if self._data.get("day") != self._today():
            self._data = self._blank()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def add(self, user: str, usd: float) -> None:
        value = float(usd or 0)
        if value <= 0:
            return
        with self._lock:
            self._roll_day()
            self._data["total"] = round(self._data.get("total", 0.0) + value, 6)
            users = self._data["users"]
            users[user] = round(users.get(user, 0.0) + value, 6)
            self._save()

    def hit(self, user: str, model: str) -> None:
        """Счётчик вопросов. Подписка одна на всех, лимиты у неё общие."""
        with self._lock:
            self._roll_day()
            asks = self._data["asks"]
            key = f"{user} · {model}"
            asks[key] = int(asks.get(key, 0)) + 1
            self._save()

    def asks(self) -> list[tuple[str, int]]:
        with self._lock:
            self._roll_day()
            items = sorted(self._data["asks"].items(), key=lambda kv: -kv[1])
        return [(k, int(v)) for k, v in items]

    def spent(self, user: str | None = None) -> float:
        with self._lock:
            self._roll_day()
            if user is None:
                return round(float(self._data.get("total", 0.0)), 4)
            return round(float(self._data["users"].get(user, 0.0)), 4)

    def deny_reason(self, user: str) -> str | None:
        """Текст отказа, если лимит выбран. None — можно спрашивать дальше."""
        with self._lock:
            self._roll_day()
            total = float(self._data.get("total", 0.0))
            mine = float(self._data["users"].get(user, 0.0))
        if self.total_limit > 0 and total >= self.total_limit:
            return (
                f"Общий дневной лимит выбран: ${total:.2f} из ${self.total_limit:.2f}. "
                "Завтра счётчик обнулится, либо подними OPENROUTER_MAX_USD в .env."
            )
        if self.user_limit > 0 and mine >= self.user_limit:
            return (
                f"Твой дневной лимит выбран: ${mine:.2f} из ${self.user_limit:.2f}. "
                "Спроси у владельца сервера или подожди до завтра."
            )
        return None

    def report(self, user: str | None = None) -> str:
        total = self.spent()
        line = f"расход сегодня: ${total:.3f}"
        if self.total_limit > 0:
            line += f" из ${self.total_limit:.2f}"
        if user:
            mine = self.spent(user)
            line += f" · ты: ${mine:.3f}"
            if self.user_limit > 0:
                line += f" из ${self.user_limit:.2f}"
        return line

    def top_users(self, limit: int = 5) -> list[tuple[str, float]]:
        with self._lock:
            self._roll_day()
            items = sorted(
                self._data["users"].items(), key=lambda kv: kv[1], reverse=True
            )
        return [(name, round(float(val), 4)) for name, val in items[:limit]]


BUDGET = Budget(OPENROUTER_MAX_USD, CHAT_MAX_USD_PER_USER)
