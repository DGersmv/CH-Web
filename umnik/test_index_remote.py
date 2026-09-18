from pathlib import Path
import tempfile

from index_remote import (
    ARCHIVE_DIRNAME,
    copy_live_index,
    pack_snapshot,
    unpack_snapshot,
    write_manifest,
)


def test_pack_and_unpack_snapshot():
    with tempfile.TemporaryDirectory() as raw:
        tmp_path = Path(raw)
        src = tmp_path / "live" / ARCHIVE_DIRNAME
        src.mkdir(parents=True)
        (src / "catalog.db").write_text("catalog", encoding="utf-8")
        (src / "sync.lock").write_text("skip-me", encoding="utf-8")
        chroma = src / "chroma"
        chroma.mkdir()
        (chroma / "vec.bin").write_bytes(b"abc")

        staged = tmp_path / "staged" / ARCHIVE_DIRNAME
        copy_live_index(src, staged)
        assert (staged / "catalog.db").read_text(encoding="utf-8") == "catalog"
        assert not (staged / "sync.lock").exists()
        write_manifest(staged, indexed=12, layout_sheets=3, generation="2026-09-18T00:00:00+00:00")

        tar_path = tmp_path / "latest.tar.gz"
        pack_snapshot(staged, tar_path)
        extracted = unpack_snapshot(tar_path, tmp_path / "out")
        assert extracted.name == ARCHIVE_DIRNAME
        assert (extracted / "catalog.db").read_text(encoding="utf-8") == "catalog"
        assert (extracted / "chroma" / "vec.bin").read_bytes() == b"abc"
        manifest = (extracted / "manifest.json").read_text(encoding="utf-8")
        assert "intfloat/multilingual-e5-base" in manifest
        assert "12" in manifest


if __name__ == "__main__":
    test_pack_and_unpack_snapshot()
    print("ok")
