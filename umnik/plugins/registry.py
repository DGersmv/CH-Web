from __future__ import annotations

from plugins.base import Plugin
from config import ENABLED_PLUGINS


def load_plugins() -> list[Plugin]:
    plugins: list[Plugin] = []
    for name in ENABLED_PLUGINS:
        if name == "pdf_archive":
            from plugins.pdf_archive.plugin import PdfArchivePlugin

            plugins.append(PdfArchivePlugin())
        elif name == "workspace":
            from plugins.workspace import WorkspacePlugin

            plugins.append(WorkspacePlugin())
        else:
            raise ValueError(f"Неизвестный плагин: {name}")
    return plugins
