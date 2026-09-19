"""Text-to-speech worker.

`pyttsx3.say()` blocks until the utterance finishes, so we run it in a
dedicated worker thread with a bounded queue. When the queue is full the
newest message wins - stale feedback is worse than none. A debounce holds
back near-duplicate messages that arrive within `dedup_seconds` of each
other so the coach does not spam the same sentence rep after rep.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional


class VoiceWorker:
    def __init__(self, rate: int = 175, volume: float = 1.0,
                 dedup_seconds: float = 2.5,
                 language: str = "en") -> None:
        self._q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=1)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_text: Optional[str] = None
        self._last_ts: float = 0.0
        self._dedup = dedup_seconds
        self.rate = rate
        self.volume = volume
        self.language = language

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="voice-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        now = time.monotonic()
        if text == self._last_text and (now - self._last_ts) < self._dedup:
            return
        self._last_text = text
        self._last_ts = now
        try:
            self._q.put_nowait(text)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(text)
            except queue.Full:
                pass

    def _run(self) -> None:
        try:
            import pyttsx3
        except Exception as e:
            print(f"voice: pyttsx3 unavailable ({e}); voice disabled")
            return
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            self._select_voice(engine)
        except Exception as e:
            print(f"voice: engine init failed ({e}); voice disabled")
            return
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if text is None:
                break
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"voice: say failed ({e})")

    def _select_voice(self, engine) -> None:
        try:
            voices = engine.getProperty("voices")
        except Exception:
            return
        wanted = self.language.lower()
        for v in voices:
            langs = [str(l).lower() for l in getattr(v, "languages", []) or []]
            name = (getattr(v, "name", "") or "").lower()
            hay = " ".join(langs) + " " + name
            if wanted in hay or (wanted == "he" and ("hebrew" in hay or "he-il" in hay)):
                engine.setProperty("voice", v.id)
                return
