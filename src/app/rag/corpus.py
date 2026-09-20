"""Physiotherapy corpus ingest.

Two ingestion paths:

- `SeedCorpus.iter_chunks()`: reads pre-cleaned chunks from
  `data/corpus_seed/*.json`. This is what ships with the repo so a
  fresh install has something to retrieve out of the box.
- `PubMedFetcher`: hits the NCBI E-utilities public API (no key
  required for low volume) to pull abstracts on demand, then chunks
  and yields them in the same shape.

Each yielded chunk is a dict with the fields the retrieval layer and
the coach agent expect:
    id, text, title, section, source_url, license, evidence_level,
    tags
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, Iterator, List, Optional


_REPO_ROOT = Path(__file__).resolve().parents[3]
# Canonical location for the hand-authored seed corpus. `corpus/` is
# organised ArchiveX-style (one subfolder per topic, one chunks.json
# per subfolder) and is what the coach cites from at runtime.
CORPUS_DIR = _REPO_ROOT / "corpus"
# Legacy path kept working so older VM checkouts keep booting. New
# chunks always land under `corpus/`.
LEGACY_SEED_DIR = _REPO_ROOT / "data" / "corpus_seed"
# Backwards-compat alias for callers that import `SEED_DIR` directly.
SEED_DIR = CORPUS_DIR


def _hash_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=10)
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def chunk_text(text: str, chunk_size: int = 512,
               overlap: int = 64) -> List[str]:
    """Whitespace-tokenized sliding window. Not perfect but fast and
    lossless on plain-text abstracts."""
    words = re.split(r"\s+", (text or "").strip())
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    out: List[str] = []
    for i in range(0, len(words), step):
        piece = " ".join(words[i:i + chunk_size])
        if piece:
            out.append(piece)
        if i + chunk_size >= len(words):
            break
    return out


class SeedCorpus:
    """Iterate chunks from the on-disk corpus.

    Reads every `chunks.json` under `corpus/` (recursively, one per
    topic), plus any legacy `data/corpus_seed/*.json` files still on
    disk. Duplicate ids are deduplicated on first-seen. Chunks marked
    with `deprecated: true` are skipped so retired evidence stops being
    retrieved without breaking historical id references in session
    logs.
    """

    def __init__(self, path: Optional[Path] = None,
                 include_legacy: bool = True) -> None:
        self.path = Path(path or CORPUS_DIR)
        self.include_legacy = include_legacy

    def _iter_files(self) -> Iterator[Path]:
        # Primary: topic-per-folder ArchiveX-style corpus.
        if self.path.is_dir():
            for p in sorted(self.path.rglob("chunks.json")):
                yield p
        # Legacy: flat JSON files under data/corpus_seed. Kept for old
        # VM checkouts that have not pulled the restructured layout yet.
        if self.include_legacy and LEGACY_SEED_DIR.is_dir():
            for p in sorted(LEGACY_SEED_DIR.glob("*.json")):
                yield p

    def iter_chunks(self) -> Iterator[dict]:
        seen_ids = set()
        for p in self._iter_files():
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if item.get("deprecated"):
                    continue
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                cid = item.get("id") or _hash_id(p.name, text[:80])
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                yield {
                    "id": cid,
                    "text": text,
                    "title": item.get("title", ""),
                    "section": item.get("section", ""),
                    "source_url": item.get("source_url", ""),
                    "license": item.get("license", ""),
                    "evidence_level": item.get("evidence_level", ""),
                    "tags": item.get("tags", []),
                }


class PubMedFetcher:
    """Minimal client for NCBI E-utilities.

    Uses the public JSON endpoints. Anonymous requests are rate-limited
    to 3 per second; we sleep 0.4 seconds between calls to stay
    comfortably under the cap.
    """

    ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    UA = "PhysioLive/0.3 (+https://github.com/orarr2/PhysioLive_Product)"

    def __init__(self, sleep_s: float = 0.4) -> None:
        self.sleep_s = sleep_s

    def _get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def search(self, query: str, retmax: int = 25) -> List[str]:
        q = urllib.parse.urlencode({
            "db": "pubmed", "term": query, "retmode": "json",
            "retmax": int(retmax), "sort": "relevance",
        })
        payload = json.loads(self._get(f"{self.ESEARCH}?{q}"))
        return list(payload.get("esearchresult", {}).get("idlist", []))

    def fetch_abstract(self, pmid: str) -> Optional[dict]:
        q = urllib.parse.urlencode({
            "db": "pubmed", "id": pmid, "rettype": "abstract",
            "retmode": "text",
        })
        text = self._get(f"{self.EFETCH}?{q}").strip()
        if not text:
            return None
        # First line is usually a header, last block often includes DOI /
        # PMID. Keep the whole thing; downstream chunker slices it.
        return {
            "pmid": pmid,
            "text": text,
            "title": "",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "license": "See publisher",
            "evidence_level": "peer-reviewed",
        }

    def iter_query_chunks(self, queries: Iterable[str],
                          per_query: int = 25) -> Iterator[dict]:
        for q in queries:
            pmids = self.search(q, retmax=per_query)
            for pmid in pmids:
                time.sleep(self.sleep_s)
                item = self.fetch_abstract(pmid)
                if not item:
                    continue
                for chunk in chunk_text(item["text"]):
                    yield {
                        "id": _hash_id("pubmed", pmid, chunk[:80]),
                        "text": chunk,
                        "title": item.get("title", ""),
                        "section": "abstract",
                        "source_url": item["source_url"],
                        "license": item["license"],
                        "evidence_level": item["evidence_level"],
                        "tags": [q],
                    }
            time.sleep(self.sleep_s)
