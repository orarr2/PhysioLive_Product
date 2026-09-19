"""RAG service - retrieve a small set of relevant chunks for a live
event.

Intended call sites:

- `RAGService.search(query, filters, k=5)`: general retrieval used by
  the coach agent right after a rep verdict fires.
- `RAGService.search_for_verdict(exercise, verdict, angles, k=5)`:
  convenience wrapper that composes a natural-language query from the
  verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .embedder import Embedder
from .store import Store


@dataclass
class Chunk:
    id: str
    text: str
    title: str
    source_url: str
    license: str
    tags: List[str]
    score: float


class RAGService:
    def __init__(self, store: Optional[Store] = None,
                 embedder: Optional[Embedder] = None) -> None:
        self.store = store or Store()
        self.embedder = embedder or Embedder()

    def is_ready(self) -> bool:
        try:
            return self.store.count_evidence() > 0
        except Exception:
            return False

    def search(self, query: str, k: int = 5,
               where: Optional[dict] = None) -> List[Chunk]:
        if not query:
            return []
        try:
            qvec = self.embedder.embed_one(query).tolist()
            raw = self.store.query_evidence(qvec, k=k, where=where)
        except Exception as e:
            print(f"rag search error ({type(e).__name__}): {e}")
            return []
        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]
        out: List[Chunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            meta = meta or {}
            out.append(Chunk(
                id=cid, text=doc,
                title=meta.get("title", ""),
                source_url=meta.get("source_url", ""),
                license=meta.get("license", ""),
                tags=list(meta.get("tags", []) or []),
                score=float(1.0 - dist) if dist is not None else 0.0,
            ))
        return out

    def search_for_verdict(self, exercise: str, verdict_level: str,
                           verdict_text: str, angles: dict,
                           k: int = 5) -> List[Chunk]:
        # We used to add `where={"body_part": <derived>}` to keep the
        # LLM inside the relevant anatomy, but Chroma's filter matched
        # nothing on the free-tier VM (metadata comparison quirk). The
        # embedding query already picks the right chunks - "Squat" plus
        # the rule message pulls knee content out of the seed corpus
        # naturally - so we skip the filter and lean on similarity.
        query = _compose_query(exercise, verdict_level, verdict_text,
                               angles)
        return self.search(query, k=k)


def _body_part_for(exercise: str) -> Optional[str]:
    ex = (exercise or "").lower()
    if "squat" in ex or "lunge" in ex or "knee" in ex:
        return "knee"
    if "shoulder" in ex:
        return "shoulder"
    if "back" in ex or "spine" in ex or "cat" in ex or "pelvic" in ex:
        return "back"
    return None


def _compose_query(exercise: str, verdict_level: str, verdict_text: str,
                   angles: dict) -> str:
    parts = [exercise or "exercise"]
    if verdict_level and verdict_level != "good":
        parts.append(verdict_text or verdict_level)
    if angles:
        # The metrics dict can arrive shaped either like the notebook
        # (e.g. `knee_min_deg`) or like the web app (`knee`, `hip`,
        # `shoulder`). Pick whichever key is present and surface it as
        # natural language so the embedding query captures the joint of
        # interest.
        kmin = (angles.get("knee_min_deg") or angles.get("knee_min")
                or angles.get("knee"))
        if kmin is not None:
            parts.append(
                f"knee flexion around {int(float(kmin))} degrees")
        hmin = angles.get("hip_min") or angles.get("hip")
        if hmin is not None:
            parts.append(
                f"hip angle around {int(float(hmin))} degrees")
    parts.append("rehabilitation form correction")
    return " - ".join(str(p) for p in parts if p)
