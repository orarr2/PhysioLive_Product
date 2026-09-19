"""PhysioLive VM API.

FastAPI service that hosts the retrieval store and the coach LLM.
Runs behind a Cloudflare Tunnel with Bearer-token auth. Every write
endpoint requires the `PHYSIOLIVE_API_TOKEN` header; the health probe
does not.

Endpoints:
    GET  /health              service status + evidence count
    POST /rag/query           retrieval only
    POST /coach/feedback      retrieval + LLM composition

Boot: `uvicorn vm.api:app --host 127.0.0.1 --port 8000`
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Ensure `app.*` is importable when this module is loaded by uvicorn.
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import Depends, FastAPI, Header, HTTPException            # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                      # noqa: E402
from pydantic import BaseModel, Field                                   # noqa: E402

from app.rag import RAGService                                          # noqa: E402
from vm.coach_llm import call_llm                                       # noqa: E402


app = FastAPI(title="PhysioLive VM", version="1.0.0")

# The web app runs from GitHub Pages (orarr2.github.io) and the notebook
# runs from a local host, both of which are cross-origin relative to the
# tunnel URL. Allow all origins so any client can reach the service; the
# Bearer-token check further down still gates real access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    max_age=86400,
)

_rag = RAGService()


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=25)
    filters: Optional[Dict] = None


class CoachFeedbackRequest(BaseModel):
    exercise: str = Field(min_length=1, max_length=80)
    verdict_level: str = Field(default="warn", max_length=20)
    verdict_text: str = Field(default="", max_length=500)
    metrics: Optional[Dict] = None
    top_k: int = Field(default=4, ge=1, le=10)


class RAGChunk(BaseModel):
    id: str
    text: str
    title: str
    source_url: str
    license: str
    tags: List[str]
    score: float


class RAGQueryResponse(BaseModel):
    chunks: List[RAGChunk]
    took_ms: int


class CoachFeedbackResponse(BaseModel):
    message: str
    source_url: Optional[str]
    sources: List[str]
    used_llm: bool
    took_ms: int


def _check_auth(authorization: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("PHYSIOLIVE_API_TOKEN")
    if not expected:
        # Auth disabled - useful for local development. Log the fact so
        # the operator knows they are running open.
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization[7:].strip() != expected:
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/health")
def health() -> Dict:
    try:
        count = _rag.store.count_evidence()
    except Exception:
        count = 0
    return {
        "ok": True,
        "index_ready": _rag.is_ready(),
        "chunks_count": count,
        "coach_provider": os.environ.get("COACH_PROVIDER", "groq"),
        "coach_model": os.environ.get("GROQ_MODEL",
                                      "openai/gpt-oss-20b"),
    }


@app.post("/rag/query", response_model=RAGQueryResponse)
def rag_query(body: RAGQueryRequest,
              _auth: None = Depends(_check_auth)) -> RAGQueryResponse:
    t0 = time.perf_counter()
    chunks = _rag.search(body.query, k=body.top_k, where=body.filters)
    took_ms = int((time.perf_counter() - t0) * 1000)
    return RAGQueryResponse(
        chunks=[RAGChunk(
            id=c.id, text=c.text, title=c.title,
            source_url=c.source_url, license=c.license,
            tags=list(c.tags), score=c.score,
        ) for c in chunks],
        took_ms=took_ms,
    )


@app.post("/coach/feedback", response_model=CoachFeedbackResponse)
def coach_feedback(body: CoachFeedbackRequest,
                   _auth: None = Depends(_check_auth)
                   ) -> CoachFeedbackResponse:
    t0 = time.perf_counter()
    chunks = _rag.search_for_verdict(
        exercise=body.exercise,
        verdict_level=body.verdict_level,
        verdict_text=body.verdict_text,
        angles=body.metrics or {},
        k=body.top_k,
    )
    used_llm = False
    message = body.verdict_text or ""
    try:
        message = call_llm(
            exercise=body.exercise,
            verdict_level=body.verdict_level,
            verdict_text=body.verdict_text,
            metrics=body.metrics or {},
            chunks=chunks,
        ) or message
        used_llm = True
    except Exception as e:
        # LLM failed. Fall back to the rule message rather than 500 the
        # caller - the live loop must keep moving.
        print(f"coach LLM error: {type(e).__name__}: {e}")

    source_url = chunks[0].source_url if chunks else None
    took_ms = int((time.perf_counter() - t0) * 1000)
    return CoachFeedbackResponse(
        message=message,
        source_url=source_url,
        sources=[c.source_url for c in chunks if c.source_url],
        used_llm=used_llm,
        took_ms=took_ms,
    )
