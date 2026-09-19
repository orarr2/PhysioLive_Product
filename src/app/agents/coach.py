"""Coach agent - one-sentence, citation-grounded verbal feedback.

The coach runs in a background thread so a slow LLM call does not stall
the live loop. It takes a rep verdict plus the top few retrieved chunks
and asks the language model for a short, evidence-grounded message. The
model is instructed to cite only the chunks it was given; if the API is
unavailable or the environment variable is missing, the coach quietly
falls back to the deterministic rule message so the pipeline keeps
running.

Environment:
    ANTHROPIC_API_KEY   the key used to authenticate the model call
    COACH_MODEL         override the default model id
"""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..rag.query import Chunk


DEFAULT_MODEL = os.environ.get("COACH_MODEL", "claude-haiku-4-5")

SYSTEM_PROMPT = (
    "You are a virtual physiotherapy coach. The user just finished a "
    "repetition of an exercise. You will receive a rule-based verdict "
    "and a short set of evidence chunks that the retrieval layer picked "
    "for this event.\n\n"
    "Reply with exactly ONE short sentence in English (max 22 words) "
    "that either encourages the user or corrects the form issue. "
    "If you cite a fact, cite ONLY facts that appear in the evidence "
    "chunks. Do NOT invent statistics or references. If none of the "
    "chunks is relevant, give a plain motivational sentence without "
    "citing anything."
)


@dataclass
class CoachRequest:
    exercise: str
    verdict_level: str
    verdict_text: str
    angles: dict
    chunks: List[Chunk]


@dataclass
class CoachResponse:
    text: str
    source_urls: List[str]
    used_llm: bool


class CoachAgent:
    def __init__(self, model: str = DEFAULT_MODEL,
                 api_key: Optional[str] = None,
                 timeout_s: float = 3.0) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.timeout_s = timeout_s
        self._client = None
        self._client_error: Optional[str] = None
        self._q: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=2)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_ts: float = 0.0
        self._min_gap = 3.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="coach-agent")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def request(self, req: CoachRequest,
                on_response: Callable[[CoachResponse], None]) -> None:
        """Async: schedule a coach reply and hand it to `on_response`.

        The debounce keeps the coach quiet when reps close faster than
        the coach can generate a message.
        """
        now = time.monotonic()
        if now - self._last_ts < self._min_gap:
            return
        self._last_ts = now
        try:
            self._q.put_nowait((req, on_response))
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait((req, on_response))
            except queue.Full:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            req, cb = item
            try:
                response = self._handle(req)
            except Exception as e:
                response = CoachResponse(text=req.verdict_text or "",
                                         source_urls=[], used_llm=False)
                print(f"coach: {type(e).__name__}: {e}")
            try:
                cb(response)
            except Exception as e:
                print(f"coach callback error: {e}")

    def _handle(self, req: CoachRequest) -> CoachResponse:
        client = self._ensure_client()
        if client is None:
            return CoachResponse(text=req.verdict_text or "",
                                 source_urls=[c.source_url for c in req.chunks
                                              if c.source_url],
                                 used_llm=False)
        prompt = _build_user_prompt(req)
        message = client.messages.create(
            model=self.model,
            max_tokens=140,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(message).strip()
        if not text:
            text = req.verdict_text or ""
        return CoachResponse(
            text=text,
            source_urls=[c.source_url for c in req.chunks if c.source_url],
            used_llm=True,
        )

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            return None
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
            return self._client
        except Exception as e:
            self._client_error = f"{type(e).__name__}: {e}"
            print(f"coach: anthropic client unavailable ({e})")
            return None


def _build_user_prompt(req: CoachRequest) -> str:
    lines = [
        f"Exercise: {req.exercise}",
        f"Verdict: {req.verdict_level or 'unknown'}",
        f"Rule message: {req.verdict_text or '(none)'}",
    ]
    if req.angles:
        lines.append(f"Angles: {req.angles}")
    lines.append("")
    lines.append("Evidence chunks:")
    if req.chunks:
        for i, c in enumerate(req.chunks, 1):
            title = c.title or "untitled"
            src = c.source_url or "no url"
            snippet = (c.text or "").replace("\n", " ")
            snippet = snippet[:400] + ("..." if len(c.text) > 400 else "")
            lines.append(f"[{i}] ({title}) {snippet}  <{src}>")
    else:
        lines.append("(no evidence retrieved)")
    lines.append("")
    lines.append("Reply now with the single-sentence coaching message.")
    return "\n".join(lines)


def _extract_text(message) -> str:
    try:
        parts = getattr(message, "content", None) or []
        for p in parts:
            t = getattr(p, "text", None)
            if t:
                return t
    except Exception:
        pass
    return ""
