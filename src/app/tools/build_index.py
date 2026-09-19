"""Build the local ChromaDB index.

Usage:
    python -m app.tools.build_index                       # seed only
    python -m app.tools.build_index --pubmed 25           # + 25 PubMed
                                                          #   hits per query

The script ingests the seed corpus that ships with the repo and,
optionally, a batch of PubMed abstracts covering physiotherapy topics.
Every chunk is embedded and upserted into the persistent Chroma store
at `data/chroma/`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from app.rag.corpus import PubMedFetcher, SeedCorpus, chunk_text  # noqa: E402
from app.rag.embedder import Embedder                              # noqa: E402
from app.rag.store import Store                                    # noqa: E402


DEFAULT_PUBMED_QUERIES = (
    "physical therapy knee rehabilitation squat",
    "patellofemoral pain rehabilitation exercise",
    "anterior cruciate ligament rehabilitation range of motion",
    "gluteus medius strengthening lower extremity",
    "low back pain core stability exercise",
    "shoulder impingement rehabilitation rotator cuff",
    "hip abduction strengthening dynamic knee valgus",
    "post-operative knee replacement physiotherapy",
)


def _batch(iterable, size: int):
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pubmed", type=int, default=0,
                    help="fetch this many PubMed hits per query")
    ap.add_argument("--queries", nargs="*", default=None,
                    help="override the default PubMed query set")
    ap.add_argument("--chunk-size", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=64)
    args = ap.parse_args()

    embedder = Embedder()
    store = Store()

    total = 0
    for group in _batch(_iter_all(args), 32):
        texts = [g["text"] for g in group]
        embs = embedder.embed(texts).tolist()
        ids = [g["id"] for g in group]
        metas = [_meta(g) for g in group]
        store.add_evidence(ids, texts, embs, metas)
        total += len(group)
        print(f"upsert +{len(group)} (total {total})")

    print(f"done. evidence count: {store.count_evidence()}")


def _iter_all(args):
    for c in SeedCorpus().iter_chunks():
        yield c
    if args.pubmed > 0:
        queries = args.queries or list(DEFAULT_PUBMED_QUERIES)
        fetcher = PubMedFetcher()
        for c in fetcher.iter_query_chunks(queries,
                                           per_query=args.pubmed):
            yield c


def _meta(chunk: dict) -> dict:
    tags = chunk.get("tags") or []
    if isinstance(tags, list):
        tags_str = ",".join(str(t) for t in tags)
    else:
        tags_str = str(tags)
    return {
        "title": chunk.get("title", ""),
        "section": chunk.get("section", ""),
        "source_url": chunk.get("source_url", ""),
        "license": chunk.get("license", ""),
        "evidence_level": chunk.get("evidence_level", ""),
        "tags": tags_str,
        "body_part": chunk.get("body_part", ""),
    }


if __name__ == "__main__":
    main()
