from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class SearchHit:
    path: str
    title: str
    snippet: str
    score: float
    page: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str]


@dataclass
class SyncStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    errors: int = 0
    total_on_disk: int = 0
    indexed: int = 0
    message: str = ""

    def as_text(self) -> str:
        return (
            f"{self.message} | на диске {self.total_on_disk}, в базе {self.indexed}, "
            f"+{self.added} ~{self.updated} -{self.removed}, ошибок {self.errors}"
        )


class Plugin(Protocol):
    name: str
    title: str

    def tools(self) -> list[ToolSpec]:
        ...

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        ...

    def sync(self, progress: Callable[[str], None] | None = None) -> SyncStats:
        ...

    def status(self) -> dict[str, Any]:
        ...
