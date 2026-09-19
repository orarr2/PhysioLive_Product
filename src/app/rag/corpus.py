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


SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "corpus_seed"


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
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or SEED_DIR)

    def iter_chunks(self) -> Iterator[dict]:
        if not self.path.is_dir():
            return
        for p in sorted(self.path.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                yield {
                    "id": item.get("id") or _hash_id(p.name, text[:80]),
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
