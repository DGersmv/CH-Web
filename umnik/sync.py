from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.pdf_archive.plugin import PdfArchivePlugin


def main() -> None:
    plugin = PdfArchivePlugin()
    log_path = plugin.catalog.dir / "sync.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = log_path.open("a", encoding="utf-8")

    def progress(msg: str) -> None:
        line = msg
        print(line, flush=True)
        log_fp.write(line + "\n")
        log_fp.flush()

    stats = plugin.sync(progress=progress)
    print(stats.as_text(), flush=True)
    log_fp.write(stats.as_text() + "\n")
    log_fp.close()


if __name__ == "__main__":
    main()
