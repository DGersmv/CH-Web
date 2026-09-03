from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import VISION_INTERVAL_SEC
from plugins.pdf_archive.plugin import PdfArchivePlugin


def main() -> None:
    plugin = PdfArchivePlugin()
    while True:
        n = plugin.sync_vision(progress=print, batch=8)
        if n == 0:
            time.sleep(VISION_INTERVAL_SEC * 8)
        else:
            time.sleep(VISION_INTERVAL_SEC)


if __name__ == "__main__":
    main()
