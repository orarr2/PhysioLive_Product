"""Default PubMed query set used to grow the physiotherapy corpus
from the free NCBI E-utilities API. Chosen to cover the exercise
families PhysioLive coaches (squat, lunge, glute bridge, straight
leg raise, shoulder abduction) plus adjacent rehab topics that
frequently drive rule-based verdicts (dynamic valgus, torso lean,
knee-over-toe, ROM utilisation, return-to-sport criteria).

Running `python -m app.tools.build_index --pubmed 25` iterates every
query, chunks the returned abstracts, and upserts them alongside the
hand-curated seed corpus in `data/chroma/`. With ~24 queries at 25
abstracts each the store lands at 500-700 evidence chunks. Rerunning
is idempotent - chunks are deduplicated by content hash before
embedding.

Each query is a plain PubMed search string. NCBI's E-utilities does
not require an API key for low-volume anonymous use; the fetcher
sleeps 0.4 s between requests to stay well under the 3-req/sec cap.
"""
from __future__ import annotations

DEFAULT_PUBMED_QUERIES = (
    # ---- Squat variants + patellofemoral / knee mechanics ----
    "squat depth knee flexion rehabilitation",
    "patellofemoral pain syndrome squat kinematics",
    "knee over toe forward translation squat",
    "eccentric squat tempo tendon rehabilitation",
    # ---- Anterior cruciate ligament + return-to-sport ----
    "anterior cruciate ligament reconstruction return to sport",
    "dynamic knee valgus prevention female athletes",
    "symmetry index limb rehabilitation criteria",
    # ---- Lunge + quadriceps ----
    "forward lunge quadriceps activation biomechanics",
    "single leg squat hip control lower extremity",
    # ---- Glute + hip family ----
    "glute bridge hip extension gluteus maximus activation",
    "gluteus medius strengthening lower extremity injury",
    "hip abduction strengthening iliotibial band syndrome",
    "hip osteoarthritis exercise therapy outcomes",
    # ---- Straight leg raise + post-op knee ----
    "straight leg raise quadriceps setting knee surgery",
    "post-operative total knee arthroplasty exercise",
    "meniscus tear rehabilitation progressive loading",
    # ---- Shoulder ----
    "shoulder abduction rotator cuff rehabilitation",
    "shoulder impingement scapular stability exercise",
    # ---- Trunk + lumbar ----
    "low back pain lumbar spine core stability exercise",
    "torso lean squat lumbar load biomechanics",
    # ---- Concepts ----
    "range of motion utilization physiotherapy",
    "eccentric loading tendinopathy achilles patellar",
    "proprioception balance training knee ankle",
    "warm up physical therapy tissue temperature",
    "home exercise program adherence rehabilitation",
)
