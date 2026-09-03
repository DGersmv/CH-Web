"""Claude Desktop говорит stdio; этот мост ходит в наш HTTP MCP."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ["MCP_NO_OPENROUTER"] = "1"
os.environ.pop("OPENROUTER_API_KEY", None)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import anyio

    from config import MCP_HTTP_URL
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server.stdio import stdio_server

    url = (sys.argv[1] if len(sys.argv) > 1 else MCP_HTTP_URL).strip()

    async def _pipe(src, dst) -> None:
        async for item in src:
            if isinstance(item, Exception):
                continue
            await dst.send(item)

    async def _run() -> None:
        async with streamable_http_client(url) as (http_read, http_write):
            async with stdio_server() as (stdio_read, stdio_write):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(_pipe, stdio_read, http_write)
                    tg.start_soon(_pipe, http_read, stdio_write)

    anyio.run(_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
