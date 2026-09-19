# Corpus seed

Small, pre-cleaned physiotherapy chunks that ship with the repo so a
fresh install has something to retrieve out of the box. Each entry is
plain JSON:

```json
{
  "id": "unique-id",
  "title": "short title",
  "section": "topic-or-category",
  "text": "the actual chunk shown to the coach agent",
  "source_url": "link to the underlying source",
  "license": "how the source may be reused",
  "evidence_level": "guideline | review | RCT | design-note",
  "tags": ["squat", "knee"],
  "body_part": "knee | shoulder | back | any"
}
```

To grow the corpus at query time, run:

```
python -m app.tools.build_index --pubmed 25
```

which fetches 25 PubMed abstracts per default query, chunks them and
upserts them alongside the seed chunks into `data/chroma/`.
