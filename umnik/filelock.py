from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


class LockBusy(OSError):
    pass


def _lock(fp: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fp: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = open(path, "a+b")
    try:
        if fp.tell() == 0:
            fp.write(b"0")
            fp.flush()
        fp.seek(0)
        _lock(fp)
    except OSError as exc:
        fp.close()
        raise LockBusy from exc
    try:
        yield
    finally:
        try:
            fp.seek(0)
            _unlock(fp)
        except OSError:
            pass
        fp.close()
