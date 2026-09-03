from __future__ import annotations

import threading
import time
from typing import Callable

from config import SYNC_INTERVAL_SEC
from plugins.base import Plugin, SyncStats


class Watcher:
    def __init__(self, plugins: list[Plugin], interval: int = SYNC_INTERVAL_SEC):
        self.plugins = plugins
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Event()
        self.lock = threading.Lock()
        self.running = False
        self.message = "ожидание"
        self.last_stats: dict[str, SyncStats] = {}
        self.last_finished: float | None = None

    def start(self, run_immediately: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            kwargs={"run_immediately": run_immediately},
            daemon=True,
            name="pdf-index-watcher",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def kick(self) -> None:
        threading.Thread(target=self.sync_once, daemon=True, name="pdf-index-now").start()

    def status_text(self) -> str:
        with self.lock:
            running = self.running
            msg = self.message
            ts = self.last_finished
            stats = self.last_stats
        when = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "ещё не было"
        extra = ""
        if stats:
            bits = [s.as_text() for s in stats.values()]
            extra = "\n" + "\n".join(bits)
        state = "идёт обновление" if running else "индекс готов"
        return f"{state}: {msg}\nпоследний прогон: {when}{extra}"

    def sync_once(self) -> None:
        if self._busy.is_set():
            return
        self._busy.set()
        with self.lock:
            self.running = True
            self.message = "синхронизация…"
        try:
            collected: dict[str, SyncStats] = {}
            for plugin in self.plugins:

                def progress(m: str, name: str = plugin.name) -> None:
                    with self.lock:
                        self.message = f"{name}: {m}"

                collected[plugin.name] = plugin.sync(progress=progress)
            with self.lock:
                self.last_stats = collected
                self.last_finished = time.time()
                self.message = "готово"
        except Exception as exc:
            with self.lock:
                self.message = f"ошибка: {exc}"
        finally:
            with self.lock:
                self.running = False
            self._busy.clear()

    def _loop(self, run_immediately: bool, on_tick: Callable[[], None] | None = None) -> None:
        if run_immediately:
            self.sync_once()
        while not self._stop.wait(self.interval):
            self.sync_once()
            if on_tick:
                on_tick()
