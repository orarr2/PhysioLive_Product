"""ChromaDB persistent store.

Holds two collections:

- `evidence`: physiotherapy knowledge chunks with metadata
  (title, section, source_url, license, tags, evidence_level).
- `signatures`: reference angle-signatures per exercise (small).

The store lives under `data/chroma/` by default. Every collection is
created on first use so a fresh checkout does not need a bootstrap
step.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional


DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "chroma"


class Store:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or DEFAULT_PATH)
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._evidence = None
        self._signatures = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        import chromadb
        self._client = chromadb.PersistentClient(path=str(self.path))
        return self._client

    def evidence(self):
        if self._evidence is not None:
            return self._evidence
        client = self._ensure_client()
        self._evidence = client.get_or_create_collection(
            name="evidence", metadata={"hnsw:space": "cosine"})
        return self._evidence

    def signatures(self):
        if self._signatures is not None:
            return self._signatures
        client = self._ensure_client()
        self._signatures = client.get_or_create_collection(
            name="signatures", metadata={"hnsw:space": "cosine"})
        return self._signatures

    # -- evidence ----------------------------------------------------------

    def add_evidence(self, ids: List[str], texts: List[str],
                     embeddings: List[List[float]],
                     metadatas: List[dict]) -> None:
        self.evidence().upsert(
            ids=list(ids), documents=list(texts),
            embeddings=[list(map(float, e)) for e in embeddings],
            metadatas=list(metadatas),
        )

    def query_evidence(self, embedding: List[float], k: int = 5,
                       where: Optional[dict] = None) -> dict:
        return self.evidence().query(
            query_embeddings=[list(map(float, embedding))],
            n_results=k, where=where or {},
        )

    def count_evidence(self) -> int:
        return int(self.evidence().count())
