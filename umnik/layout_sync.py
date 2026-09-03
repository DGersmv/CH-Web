from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import OPENROUTER_API_KEY, OPENROUTER_MAX_USD, OPENROUTER_MODEL
from plugins.pdf_archive.plugin import PdfArchivePlugin


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRouter layout sync")
    parser.add_argument("--pilot", default="", help="name filter, empty = all planir")
    parser.add_argument("--batch", type=int, default=5000)
    parser.add_argument("--max-usd", type=float, default=OPENROUTER_MAX_USD)
    parser.add_argument("--skip-pilot", action="store_true")
    args = parser.parse_args()
    if not (OPENROUTER_API_KEY or "").strip():
        print("Missing OPENROUTER_API_KEY in .env", flush=True)
        sys.exit(1)
    print(f"model: {OPENROUTER_MODEL}, budget: ${args.max_usd:.2f}", flush=True)
    from config import OPENROUTER_PROXY

    if OPENROUTER_PROXY:
        host = urlparse(OPENROUTER_PROXY).hostname or "set"
        print(f"proxy: {host}", flush=True)
    else:
        print("proxy: none", flush=True)
    print("opening catalog...", flush=True)
    plugin = PdfArchivePlugin()
    print("refresh names...", flush=True)
    plugin.index_names(progress=print)
    pending_n = len(plugin.catalog.pending_layout_paths(limit=20000))
    print(f"pending layouts: {pending_n}", flush=True)
    spent = plugin.catalog.layout_spent_usd()
    print(
        f"catalog ok, sheets={plugin.catalog.layout_sheet_count()}, spent=${spent:.4f}",
        flush=True,
    )
    total = 0
    if not args.skip_pilot and not args.pilot:
        print("pilot: vaskelovo", flush=True)
        total += plugin.sync_layout(
            progress=print,
            batch=10,
            name_contains="васкелово",
            max_usd=min(1.0, args.max_usd),
        )
    print("queue: planir files", flush=True)
    while True:
        spent = plugin.catalog.layout_spent_usd()
        if spent >= args.max_usd:
            print(f"stop: budget ${args.max_usd:.2f}", flush=True)
            break
        n = plugin.sync_layout(
            progress=print,
            batch=args.batch,
            name_contains=args.pilot,
            max_usd=args.max_usd,
        )
        total += n
        if n == 0:
            print("queue empty", flush=True)
            break
    spent = plugin.catalog.layout_spent_usd()
    sheets = plugin.catalog.layout_sheet_count()
    print(
        f"done files={total}, sheets={sheets}, spent=${spent:.4f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
