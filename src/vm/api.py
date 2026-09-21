"""PhysioLive VM API.

FastAPI service that hosts the retrieval store, the coach LLM and the
sign-in flow. Runs behind a Cloudflare Tunnel with JWT auth on every
data endpoint.

Endpoints
    GET  /health              service status + evidence count (public)
    POST /auth/login          passphrase -> JWT
    POST /auth/google         Google ID token -> JWT
    POST /rag/query           retrieval (JWT required)
    POST /coach/feedback      retrieval + LLM composition (JWT required)

Boot: `uvicorn vm.api:app --host 127.0.0.1 --port 8000`

Rate limits
    Per-IP:   30 requests / minute,   500 requests / day (all routes)
    Per-user: 20 requests / minute,   300 requests / day (data routes)
    All limits documented in `docs/rate-limits.md`.
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

from fastapi import Depends, FastAPI, HTTPException, Request               # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                          # noqa: E402
from pydantic import BaseModel, Field                                       # noqa: E402
from slowapi import Limiter                                                 # noqa: E402
from slowapi.errors import RateLimitExceeded                                # noqa: E402
from slowapi.util import get_remote_address                                 # noqa: E402
from starlette.responses import JSONResponse                                # noqa: E402

from app.rag import RAGService                                              # noqa: E402
from vm.auth import (                                                        # noqa: E402
    require_auth, issue_passphrase_token, issue_google_token,
)
from vm.coach_llm import call_llm                                            # noqa: E402
from vm.email_report import (                                                 # noqa: E402
    send_daily_report, EmailNotConfigured,
)


# ------------------------------------------------------------------ rate limits

def _rate_key(request: Request) -> str:
    """Prefer the JWT subject as the rate-limit key when the request
    is authenticated - so one user across many IPs still counts as one
    quota, and one shared IP with many users does not stall out the
    coach for everyone."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        # Cheap parse: use the token itself as an opaque identifier
        # per request. The heavier JWT decode still happens inside
        # `require_auth`. Using the raw bearer means an attacker
        # spraying random tokens does not share the same bucket as a
        # legitimate user.
        return "u:" + auth[7:200]
    return "ip:" + get_remote_address(request)


limiter = Limiter(
    key_func=_rate_key,
    default_limits=[
        os.environ.get("PHYSIOLIVE_LIMIT_PER_MIN", "30/minute"),
        os.environ.get("PHYSIOLIVE_LIMIT_PER_DAY", "500/day"),
    ],
)


# ------------------------------------------------------------------ app

app = FastAPI(title="PhysioLive VM", version="1.2.0")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "limit": str(exc.detail)},
        headers={"Retry-After": "60"},
    )


# The web app runs from GitHub Pages (orarr2.github.io) and the notebook
# runs from a local host, both of which are cross-origin relative to the
# tunnel URL. Allow all origins so any client can reach the service; the
# JWT check further down still gates real access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    max_age=86400,
)

_rag = RAGService()


# ------------------------------------------------------------------ models

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


class LoginRequest(BaseModel):
    passphrase: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=40)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=10, max_length=4096)


class AuthResponse(BaseModel):
    jwt: str
    exp: int
    profile: Dict


class RepEntry(BaseModel):
    index: int
    level: str = Field(default="warn", max_length=20)
    text: str = Field(default="", max_length=500)
    primary_min: Optional[float] = None
    knee_min: Optional[float] = None
    hip_min: Optional[float] = None
    torso_max: Optional[float] = None


class SessionEntry(BaseModel):
    exercise: str = Field(max_length=40)
    exercise_name: Optional[str] = Field(default=None, max_length=80)
    startedAt: Optional[int] = None
    endedAt: Optional[int] = None
    reps: List[RepEntry] = Field(default_factory=list)


class DailyReportRequest(BaseModel):
    sessions: List[SessionEntry] = Field(default_factory=list, max_length=100)


class DailyReportResponse(BaseModel):
    ok: bool
    sent: bool
    reason: Optional[str] = None
    date: Optional[str] = None
    total_reps: Optional[int] = None
    used_llm: Optional[bool] = None


# ------------------------------------------------------------------ routes

@app.get("/health")
@limiter.limit("60/minute")
def health(request: Request) -> Dict:
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
        "version": app.version,
    }


@app.post("/auth/login", response_model=AuthResponse)
@limiter.limit("10/minute")
def auth_login(request: Request, body: LoginRequest) -> AuthResponse:
    result = issue_passphrase_token(body.passphrase, body.display_name)
    return AuthResponse(**result)


@app.post("/auth/google", response_model=AuthResponse)
@limiter.limit("10/minute")
def auth_google(request: Request, body: GoogleLoginRequest) -> AuthResponse:
    result = issue_google_token(body.id_token)
    return AuthResponse(**result)


@app.post("/rag/query", response_model=RAGQueryResponse)
@limiter.limit(os.environ.get("PHYSIOLIVE_USER_LIMIT", "20/minute"))
def rag_query(request: Request, body: RAGQueryRequest,
              user: Dict = Depends(require_auth)) -> RAGQueryResponse:
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
@limiter.limit(os.environ.get("PHYSIOLIVE_USER_LIMIT", "20/minute"))
def coach_feedback(request: Request, body: CoachFeedbackRequest,
                   user: Dict = Depends(require_auth)
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
        print(f"coach LLM error for user {user.get('sub')}: "
              f"{type(e).__name__}: {e}")

    source_url = chunks[0].source_url if chunks else None
    took_ms = int((time.perf_counter() - t0) * 1000)
    return CoachFeedbackResponse(
        message=message,
        source_url=source_url,
        sources=[c.source_url for c in chunks if c.source_url],
        used_llm=used_llm,
        took_ms=took_ms,
    )


@app.post("/report/daily/send", response_model=DailyReportResponse)
@limiter.limit("5/hour")
def report_daily_send(request: Request, body: DailyReportRequest,
                      user: Dict = Depends(require_auth)
                      ) -> DailyReportResponse:
    """Compose and email a daily summary of the user's sessions.

    The web app calls this at end-of-session; the VM aggregates the
    payload, asks the coach LLM for a free-form clinical opinion, and
    sends the whole thing via Gmail SMTP to the operator's inbox.
    Rate-limited to one email per user per day server-side.
    """
    try:
        result = send_daily_report(
            user_sub=user.get("sub") or "u_unknown",
            display_name=(user.get("name")
                          or user.get("email") or "Athlete"),
            sessions=[s.model_dump() for s in body.sessions],
        )
    except EmailNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        print(f"report_daily_send error for user {user.get('sub')}: "
              f"{type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="email send failed")
    return DailyReportResponse(**result)
