"""Curator - grow the knowledge base by fetching new reference videos
and new evidence chunks.

Two subcommands:

- `videos`: given a list of YouTube URLs, downloads them with `yt-dlp`
  into `data/reference_videos/<exercise>/` so the signature builder can
  process them into angle signatures.
- `evidence`: expands the RAG index with fresh PubMed abstracts for the
  default (or a custom) list of physiotherapy queries.

Usage:
    python -m app.tools.curator videos --exercise squat urls.txt
    python -m app.tools.curator evidence --per-query 25
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


def _has_ytdlp() -> bool:
    return shutil.which("yt-dlp") is not None


def cmd_videos(args) -> None:
    if not _has_ytdlp():
        print("yt-dlp not found on PATH. install with: pip install yt-dlp")
        sys.exit(1)
    urls = _load_urls(args.urls)
    if not urls:
        print("no URLs to download")
        return
    out_dir = _ROOT / "data" / "reference_videos" / args.exercise
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        template = str(out_dir / (f"{args.exercise}_%(id)s.%(ext)s"))
        cmd = ["yt-dlp",
               "-f", "mp4/best[ext=mp4]",
               "-o", template,
               "--no-playlist",
               "--restrict-filenames",
               url]
        if args.max_duration:
            cmd += ["--match-filters", f"duration<{args.max_duration}"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"  failed: {e}")
            continue
    print("done. run 'python -m app.tools.build_signatures' next.")


def cmd_evidence(args) -> None:
    from app.rag.corpus import PubMedFetcher
    from app.rag.embedder import Embedder
    from app.rag.store import Store

    queries = _load_urls(args.queries) if args.queries \
        else list(DEFAULT_QUERIES)
    fetcher = PubMedFetcher()
    embedder = Embedder()
    store = Store()
    seen = 0
    batch: List[dict] = []
    for chunk in fetcher.iter_query_chunks(queries,
                                           per_query=args.per_query):
        batch.append(chunk)
        seen += 1
        if len(batch) >= 32:
            _flush(batch, embedder, store)
            batch = []
    if batch:
        _flush(batch, embedder, store)
    print(f"ingested {seen} chunks. store now holds "
          f"{store.count_evidence()}.")


def _flush(batch, embedder, store):
    texts = [c["text"] for c in batch]
    embs = embedder.embed(texts).tolist()
    ids = [c["id"] for c in batch]
    metas = [_meta(c) for c in batch]
    store.add_evidence(ids, texts, embs, metas)
    print(f"  +{len(batch)} (total {store.count_evidence()})")


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


def _load_urls(path: str) -> List[str]:
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


DEFAULT_QUERIES = (
    "physical therapy knee rehabilitation squat",
    "patellofemoral pain rehabilitation exercise",
    "anterior cruciate ligament rehabilitation range of motion",
    "gluteus medius strengthening lower extremity",
    "low back pain core stability exercise",
    "shoulder impingement rehabilitation rotator cuff",
    "hip abduction strengthening dynamic knee valgus",
    "post-operative knee replacement physiotherapy",
    "elderly balance training fall prevention",
    "tendon rehabilitation loading progression",
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)

    v = sp.add_parser("videos", help="download reference videos")
    v.add_argument("urls", type=str,
                   help="path to a text file of URLs, one per line")
    v.add_argument("--exercise", type=str, required=True)
    v.add_argument("--max-duration", type=int, default=180,
                   help="skip videos longer than this many seconds")

    e = sp.add_parser("evidence", help="expand the RAG evidence store")
    e.add_argument("--queries", type=str, default=None,
                   help="text file of custom queries; one per line")
    e.add_argument("--per-query", type=int, default=25)

    args = ap.parse_args()
    if args.cmd == "videos":
        cmd_videos(args)
    else:
        cmd_evidence(args)


if __name__ == "__main__":
    main()
