from __future__ import annotations

from pathlib import Path

from config import DATA_DIR, EMBEDDING_DEVICE, EMBEDDING_MODEL, SEARCH_LIMIT
from plugins.base import SearchHit
from plugins.pdf_archive.extract import FileExtract, path_meta


class PageIndex:
    def __init__(self, data_dir: Path | None = None):
        self.dir = Path(data_dir or DATA_DIR) / "pdf_archive" / "chroma"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._model = None

    def _embedder(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)
        return self._model

    def _col(self):
        if self._collection is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.dir))
            self._collection = self._client.get_or_create_collection(
                name="pdf_pages",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        model = self._embedder()
        prefixed = [f"passage: {t}" for t in texts]
        return model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False).tolist()

    def encode_query(self, query: str) -> list[float]:
        model = self._embedder()
        vec = model.encode([f"query: {query}"], normalize_embeddings=True, show_progress_bar=False)
        return vec[0].tolist()

    def upsert_file(self, extracted: FileExtract) -> None:
        col = self._col()
        prefix = _id_prefix(extracted.path)
        self.delete_file(extracted.path)
        if not extracted.pages_data:
            return
        ids = []
        docs = []
        metas = []
        rel, year, project = path_meta(extracted.path)
        for page in extracted.pages_data:
            ids.append(f"{prefix}::p{page.page}")
            docs.append(page.text)
            metas.append(
                {
                    "path": str(extracted.path),
                    "name": extracted.path.name,
                    "relpath": rel,
                    "page": page.page,
                    "kind": page.kind or "",
                    "year": year or "",
                    "project": project or "",
                    "titleblock": (page.titleblock or "")[:300],
                }
            )
        embeddings = self.encode_passages(docs)
        col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)

    def delete_file(self, path: Path | str) -> None:
        col = self._col()
        try:
            col.delete(where={"path": str(path)})
        except Exception:
            pass

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[SearchHit]:
        col = self._col()
        if col.count() == 0:
            return []
        q = self.encode_query(query)
        result = col.query(
            query_embeddings=[q],
            n_results=min(limit, max(col.count(), 1)),
            include=["documents", "metadatas", "distances"],
        )
        hits: list[SearchHit] = []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            meta = meta or {}
            hits.append(
                SearchHit(
                    path=str(meta.get("path") or ""),
                    title=str(meta.get("name") or Path(str(meta.get("path") or "")).name),
                    snippet=(doc or "")[:500],
                    score=1.0 / (60 + i),
                    page=int(meta.get("page") or 0) or None,
                    extra={
                        "kind": meta.get("kind"),
                        "year": meta.get("year"),
                        "project": meta.get("project"),
                        "relpath": meta.get("relpath"),
                        "distance": dist,
                        "via": "vector",
                    },
                )
            )
        return hits


def _id_prefix(path: Path) -> str:
    import hashlib

    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:20]
