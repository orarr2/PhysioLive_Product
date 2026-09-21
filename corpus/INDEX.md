# Corpus INDEX

Full listing of every **seed** chunk shipped with the repo. The 500-700
PubMed abstracts added on top of the seed by
`python -m app.tools.build_index --pubmed 25` are NOT listed here -
they live in `data/chroma/` per install, keyed by PMID, with source
URLs pointing at pubmed.ncbi.nlm.nih.gov. Verify their count on a
running VM with:

```
python -c "from app.rag.store import Store; print(Store().count_evidence())"
```

or on the deployed service:

```
curl -s https://<tunnel>.trycloudflare.com/health | jq .chunks_count
```

Regenerate the seed table below by hand after adding a new entry, or
(once wired) via `python -m app.tools.corpus_index --write`.

## Chunks

| id | title | topic | body part | evidence | source |
|---|---|---|---|---|---|
| `squat-depth-01`     | Squat depth and knee flexion              | squat    | knee | guideline    | [APTA](https://www.apta.org/) |
| `squat-kot-01`       | Knee alignment over the ankle             | squat    | knee | review       | [JOSPT](https://www.jospt.org/) |
| `squat-torso-01`     | Torso lean during a bodyweight squat      | squat    | back | review       | [NIH PMC](https://www.ncbi.nlm.nih.gov/pmc/) |
| `squat-tempo-01`     | Eccentric and concentric tempo            | squat    | knee | review       | [JOSPT](https://www.jospt.org/) |
| `knee-valgus-01`     | Dynamic knee valgus                       | knee     | knee | review       | [NIH PMC](https://www.ncbi.nlm.nih.gov/pmc/) |
| `knee-rom-01`        | Range of motion utilisation               | knee     | knee | definition   | [PEDro](https://www.pedro.org.au/) |
| `knee-symmetry-01`   | Symmetry index between limbs              | knee     | knee | review       | [JOSPT](https://www.jospt.org/) |
| `hip-glute-medius-01`| Gluteus medius and knee tracking          | hip      | hip  | review       | [NIH PMC](https://www.ncbi.nlm.nih.gov/pmc/) |
| `hip-bridge-01`      | Glute bridge and hip extension            | hip      | hip  | review       | [JOSPT](https://www.jospt.org/) |
| `hip-leg-raise-01`   | Straight leg raise and quadriceps set     | hip      | hip  | review       | [NIH PMC](https://www.ncbi.nlm.nih.gov/pmc/) |
| `shoulder-abduct-01` | Shoulder abduction targets                | shoulder | shoulder | review    | [JOSPT](https://www.jospt.org/) |
| `general-two-tick-01`| Rep counting needs two-tick confirmation  | general  | any  | design-note  | internal notes |
| `general-camera-01`  | Camera view for squat analysis            | general  | any  | setup-note   | internal notes |
| `general-warmup-01`  | Warm-up before rehabilitation exercise    | general  | any  | guideline    | [WHO](https://www.who.int/) |
| `general-pain-01`    | Pain during exercise                      | general  | any  | guideline    | [WHO](https://www.who.int/) |

## Counts

- Total chunks: 15
- Topics: squat (4), knee (3), hip (3), shoulder (1), general (4)
- Guideline: 3
- Review: 8
- Definition: 1
- Design / setup notes: 3

## When to regenerate

Update this file whenever you:
- add or remove a chunk in any `corpus/*/chunks.json`;
- change a chunk's `title`, `evidence_level`, or `source_url`;
- add a new topic subfolder.

Keeping the counts in sync helps reviewers spot silent drops in
evidence quality.
