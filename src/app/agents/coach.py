"""Coach agent client.

Turns each rep verdict into a natural, citation-grounded one-sentence
message by calling the PhysioLive VM's `/coach/feedback` endpoint.
The VM handles the retrieval (RAG) and the LLM call; the client just
sends the rep summary and consumes the reply.

Runs in a background thread so a slow VM round-trip does not stall the
live loop. When the VM URL or token is missing, or the request fails,
the client quietly falls back to the plain rule text so the pipeline
keeps moving.

Environment:
    PHYSIOLIVE_VM_URL       origin of the coach service, e.g.
                            https://physiolive.example.com
    PHYSIOLIVE_JWT          signed JWT returned by /auth/login. When
                            unset the client also accepts the legacy
                            PHYSIOLIVE_API_TOKEN for older notebook
                            checkouts.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class CoachRequest:
    exercise: str
    verdict_level: str
    verdict_text: str
    angles: dict = field(default_factory=dict)
    chunks: List = field(default_factory=list)  # retained for API-compat


@dataclass
class CoachResponse:
    text: str
    source_urls: List[str]
    used_llm: bool


class CoachAgent:
    def __init__(self, vm_url: Optional[str] = None,
                 api_token: Optional[str] = None,
                 timeout_s: float = 3.5) -> None:
        self.vm_url = (vm_url or os.environ.get("PHYSIOLIVE_VM_URL")
                       or "").rstrip("/")
        # Prefer a signed JWT; fall back to the legacy shared token
        # for notebook installs that have not migrated.
        self.api_token = (api_token
                          or os.environ.get("PHYSIOLIVE_JWT")
                          or os.environ.get("PHYSIOLIVE_API_TOKEN") or "")
        # Retained for backward-compat with old notebook check.
        self.api_key = self.api_token
        self.timeout_s = timeout_s
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
        """Async: schedule a coach reply and hand it to `on_response`."""
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
        if not self.vm_url:
            return CoachResponse(text=req.verdict_text or "",
                                 source_urls=[], used_llm=False)
        try:
            import requests
        except Exception as e:
            print(f"coach: requests unavailable ({e})")
            return CoachResponse(text=req.verdict_text or "",
                                 source_urls=[], used_llm=False)
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        payload = {
            "exercise": req.exercise,
            "verdict_level": req.verdict_level,
            "verdict_text": req.verdict_text,
            "metrics": req.angles or {},
        }
        r = requests.post(f"{self.vm_url}/coach/feedback",
                          json=payload, headers=headers,
                          timeout=self.timeout_s)
        if r.status_code != 200:
            print(f"coach: HTTP {r.status_code} {r.text[:200]}")
            return CoachResponse(text=req.verdict_text or "",
                                 source_urls=[], used_llm=False)
        data = r.json()
        return CoachResponse(
            text=(data.get("message") or req.verdict_text or ""),
            source_urls=list(data.get("sources") or []),
            used_llm=bool(data.get("used_llm")),
        )
