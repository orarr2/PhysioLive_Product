# Legacy corpus seed

The scientific corpus has moved to the top-level `corpus/` folder, which
is organised ArchiveX-style with one subfolder per topic:

```
corpus/
  README.md
  INDEX.md
  CONTRIBUTING.md
  squat/    chunks.json + README.md
  knee/     chunks.json + README.md
  hip/      chunks.json + README.md
  shoulder/ chunks.json + README.md
  general/  chunks.json + README.md
```

`src/app/rag/corpus.py` reads `corpus/**/chunks.json` first, then falls
back to any legacy JSON files still in this folder. Old VM checkouts
keep booting; new evidence lands under `corpus/` and gets richer
documentation.

Delete this file (and this folder) once every deployment has pulled
past the corpus restructure commit.
