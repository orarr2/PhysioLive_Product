# PhysioLive Scientific Corpus

Curated collection of physiotherapy evidence used by the PhysioLive
coach. Every real-time coaching sentence the LLM produces has to cite
a chunk that lives here or in an on-demand PubMed pull; the corpus is
what keeps the model honest.

## Two layers

**Seed corpus** (this folder). Hand-authored chunks, topic-first with
one subfolder per body region or theme and one `chunks.json` per
subfolder. Each chunk carries its own source URL, license and evidence
level. Current count: ~15 chunks. Optimised for clarity and coverage
of the core rules the app enforces (squat depth, knee alignment, torso
lean, glute-medius / knee valgus, warm-up, pain).

**PubMed layer** (grown on demand). Running the ingest script pulls
peer-reviewed open-access abstracts from NCBI's E-utilities API using
the query set in `src/app/rag/pubmed_queries.py` (~24 queries covering
squat, lunge, glute bridge, straight leg raise, shoulder abduction,
ACL rehab, patellofemoral pain, hip osteoarthritis, tendinopathy,
proprioception, and adherence). At the default 25 abstracts per query
the store reaches roughly **500-700 evidence chunks** after ingest,
all with source URLs on `pubmed.ncbi.nlm.nih.gov`.

The seed layer is committed to git and always available. The PubMed
layer is an on-demand build step - it lives only in the ChromaDB
files on each install (kept out of git so we do not redistribute
third-party abstract text).

## Layout

```
corpus/
  README.md               <- this file
  INDEX.md                <- table of every chunk (title, source, license, evidence, tags)
  CONTRIBUTING.md         <- how to add or update evidence
  squat/                  <- squat depth, knee-over-toe, torso lean, tempo
    README.md
    chunks.json
  knee/                   <- dynamic valgus, ROM utilisation, glute-medius, symmetry index
    README.md
    chunks.json
  hip/                    <- glute bridge, leg raise, hip flexion targets
    README.md
    chunks.json
  shoulder/               <- shoulder abduction, scapular control
    README.md
    chunks.json
  general/                <- measurement notes, warm-up, pain rules, camera setup
    README.md
    chunks.json
```

Every `chunks.json` is a JSON array of chunk objects with the same
schema:

```json
{
  "id": "squat-depth-01",
  "title": "Squat depth and knee flexion",
  "section": "squat technique",
  "text": "During a rehabilitation squat, knee flexion ...",
  "source_url": "https://www.apta.org/",
  "license": "Reference only - see APTA general guidance",
  "evidence_level": "guideline",
  "tags": ["squat", "knee", "ROM", "rehabilitation"],
  "body_part": "knee"
}
```

## Evidence levels

| level          | meaning                                                             |
|----------------|---------------------------------------------------------------------|
| `guideline`    | official professional-body guidance (APTA, WHO, JOSPT clinical pgs) |
| `review`       | narrative or systematic review from a peer-reviewed journal          |
| `RCT`          | randomised controlled trial abstract or excerpt                     |
| `definition`   | authoritative definition of a construct (e.g. ROM utilisation)      |
| `design-note`  | internal engineering note on how the system measures something      |
| `setup-note`   | practical setup guidance (camera view, lighting)                    |

The retrieval layer does not preferentially weight by level, but the
coach agent's system prompt tells it to prefer higher-quality entries
when both apply. When you add a chunk, pick the strictest level that
honestly describes the source.

## Sources currently referenced

| source                                     | typical evidence level | notes |
|--------------------------------------------|------------------------|-------|
| American Physical Therapy Association (APTA) | guideline              | https://www.apta.org/ |
| Journal of Orthopaedic and Sports Physical Therapy (JOSPT) | review | https://www.jospt.org/ |
| NIH National Library of Medicine (PMC)     | review, RCT            | https://www.ncbi.nlm.nih.gov/pmc/ |
| World Health Organization                  | guideline              | https://www.who.int/ |
| Physiotherapy Evidence Database (PEDro)    | definition             | https://www.pedro.org.au/ |
| internal engineering notes                 | design-note            | authored in this repo |

## How the coach uses the corpus

1. On every rep-close verdict the browser sends a short summary to the
   VM: `{exercise, verdict_level, verdict_text, metrics}`.
2. The VM composes a retrieval query from those fields and asks
   ChromaDB for the top-k nearest chunks (embedded with the ONNX
   version of `all-MiniLM-L6-v2`).
3. The retrieved chunks are passed to the LLM with a system prompt
   that forbids inventing citations. The LLM is required to cite at
   most one chunk when it references a fact and never to invent URLs
   or statistics.
4. The web app renders the coach message alongside the top chunk's
   `source_url` so a user can inspect the underlying evidence.

## Growing the corpus

- To add a hand-picked chunk to the seed layer: see `CONTRIBUTING.md`.
- To pull PubMed abstracts on top of the seed and reach ~500 chunks:

  ```
  python -m app.tools.build_index --pubmed 25
  ```

  This iterates every query in `src/app/rag/pubmed_queries.py`,
  fetches 25 open-access abstracts per query from NCBI E-utilities,
  chunks them, tags each chunk with the search query it came from,
  embeds them via the ONNX all-MiniLM-L6-v2 model, and upserts them
  alongside the seed chunks into `data/chroma/`. Runtime on a
  free-tier VM is ~5-10 minutes (rate-limited to 3 requests per
  second at the NCBI side).

  Only open-access abstracts are stored; the full text is left to
  the publisher. Every entry keeps a `pubmed.ncbi.nlm.nih.gov/<pmid>`
  source URL so the coach can cite it directly in the UI.

- To override the query set (e.g. focus on a single body region):

  ```
  python -m app.tools.build_index --pubmed 40 \
      --queries "meniscus rehabilitation" "ACL reconstruction outcomes"
  ```

- To verify the final size:

  ```
  python -c "from app.rag.store import Store; print(Store().count_evidence())"
  ```

## Provenance

The seed corpus in this folder is authored from open guidance material.
Every entry is either (a) paraphrased from the linked source under fair
use, with the source URL preserved for verification, or (b) an
internal note about how the system measures something. No copyrighted
text is reproduced verbatim beyond definition-length snippets.
