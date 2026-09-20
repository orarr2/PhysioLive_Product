# Contributing to the PhysioLive corpus

The corpus is small on purpose. Each chunk you add is retrieved thousands
of times over the life of the app, so quality beats quantity.

## What belongs here

- Professional-body guidance (APTA, WHO, JOSPT clinical pages).
- Peer-reviewed reviews and RCT abstracts on rehabilitation, biomechanics,
  return-to-sport criteria, or motion analysis.
- Definitions of measurement constructs (ROM utilisation, symmetry index,
  patellofemoral joint reaction force).
- Internal engineering notes that explain how the system measures
  something (rep-counter confirmation, camera view choice) - use the
  `design-note` or `setup-note` evidence level and set `source_url` to
  `internal`.

## What does NOT belong here

- Marketing copy or product manuals.
- Blog posts without an underlying study.
- Full copyrighted text longer than a short quotation. Paraphrase and
  link to the source; the goal is grounded coaching, not republishing.
- Personal opinions with no cited source.

## Adding a chunk

1. Pick the right subfolder (`squat/`, `knee/`, `hip/`, `shoulder/`,
   `general/`). Create a new one if the topic clearly does not fit any
   existing folder.
2. Open the folder's `chunks.json` and append a new object with this
   shape:

   ```json
   {
     "id": "<topic>-<slug>-<NN>",
     "title": "Short title",
     "section": "topic-or-category",
     "text": "The actual chunk. 2-4 sentences, paraphrased not quoted.",
     "source_url": "https://...",
     "license": "Reference only - see <source>",
     "evidence_level": "review",
     "tags": ["squat", "knee"],
     "body_part": "knee"
   }
   ```

3. Update `corpus/INDEX.md` (append a row and adjust the counts).
4. Rebuild the ChromaDB index locally to verify:

   ```
   python -m app.tools.build_index
   ```

5. Commit the JSON, the INDEX row, and any new folder README together.

## Style rules

- Keep chunks to **2-4 sentences** (roughly 40 to 120 words). Long
  chunks make the LLM's citation prompt sloppy.
- Never paste more than one direct quote per chunk, and if you do, keep
  it under 15 words and wrap it in quotation marks.
- Prefer active voice and imperative clinical phrasing over passive
  academic voice. The LLM tends to mirror the register it retrieves.
- Do not include emoji or dashes fancier than `-` in the text.

## Rebuilding the vector index

The ingest script picks up every `corpus/*/chunks.json` automatically.
After adding a chunk:

```
python -m app.tools.build_index
```

Optional PubMed enrichment (adds fresh abstracts on top of the seed):

```
python -m app.tools.build_index --pubmed 25
```

## Deprecating a chunk

Do not delete an id you have already published; users may have session
history that references it. Instead, blank the `text` field and set
`deprecated: true`. The ingest script skips deprecated entries but
downstream logs stay readable.
