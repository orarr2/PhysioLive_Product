"""LLM caller used by the VM's coach endpoint.

Reads `COACH_PROVIDER` from the environment and dispatches:

- `groq` (default): calls the OpenAI-compatible chat endpoint at
  `https://api.groq.com/openai/v1/chat/completions` directly with
  `httpx`. Requires `GROQ_API_KEY`. Default model is
  `openai/gpt-oss-20b`; upgrade to `openai/gpt-oss-120b` via the
  `GROQ_MODEL` env var when instruction following matters more than
  latency.
- `anthropic`: Claude Haiku via the Anthropic Python SDK, requires
  `ANTHROPIC_API_KEY`.

The system prompt is written to force the model to compose a NEW
sentence rather than parrot the rule-based verdict text that appears
in the user message. Smaller models (like gpt-oss-20b) can otherwise
just echo the first "message"-like string they find; the explicit "do
not repeat" instruction is what keeps them honest.
"""
from __future__ import annotations

import os
from typing import List, Sequence

import httpx

from app.rag.query import Chunk


SYSTEM_PROMPT = (
    "You are a virtual physiotherapy coach. After each repetition you "
    "receive:\n"
    "  1. A rule-based verdict identifying the form issue.\n"
    "  2. A small set of evidence chunks retrieved from the "
    "     physiotherapy literature.\n\n"
    "Your job is to COMPOSE A NEW SENTENCE (maximum 22 words) that "
    "coaches the user. Requirements:\n"
    "  - Do NOT copy or paraphrase the rule verdict verbatim. Restate "
    "    it in your own words, with a specific correction cue.\n"
    "  - When the verdict is not 'good', lead with a short "
    "    encouragement clause before the correction.\n"
    "  - You MAY cite ONE fact from the evidence chunks; when you do, "
    "    make the citation part of the sentence naturally. Do NOT "
    "    invent statistics, journal names or URLs that are not in the "
    "    evidence.\n"
    "  - Never emit multiple sentences. Never emit lists. Never quote "
    "    the rule verdict word for word.\n"
    "  - If none of the chunks is relevant, output a plain "
    "    encouragement without any citation.\n\n"
    "Output only the sentence. No preamble, no headings, no quotes."
)


def call_llm(exercise: str, verdict_level: str, verdict_text: str,
             metrics: dict, chunks: Sequence[Chunk]) -> str:
    provider = os.environ.get("COACH_PROVIDER", "groq").lower()
    user_prompt = _build_user_prompt(exercise, verdict_level, verdict_text,
                                     metrics, chunks)
    if provider == "groq":
        return _call_groq(user_prompt)
    if provider == "anthropic":
        return _call_anthropic(user_prompt)
    raise ValueError(f"unknown COACH_PROVIDER: {provider!r}")


def _call_groq(user_prompt: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    # Default picked in 2026-09 because it appears on every free-tier
    # Groq key without extra access. Override via GROQ_MODEL if you need
    # bigger (openai/gpt-oss-120b) or specialised (qwen/qwen3-8-27b).
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 140,
            "temperature": 0.6,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "") or "").strip()


def _call_anthropic(user_prompt: str) -> str:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model, max_tokens=140,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = getattr(msg, "content", None) or []
    return "".join(getattr(p, "text", "") for p in parts).strip()


def _build_user_prompt(exercise: str, verdict_level: str, verdict_text: str,
                       metrics: dict, chunks: Sequence[Chunk]) -> str:
    lines: List[str] = [
        f"Exercise: {exercise}",
        f"Detected form issue (severity {verdict_level or 'unknown'}): "
        f"{verdict_text or '(none)'}",
    ]
    if metrics:
        pretty = ", ".join(
            f"{k}={_num_str(v)}" for k, v in metrics.items()
            if v is not None
        )
        if pretty:
            lines.append(f"Measured angles: {pretty}")
    lines.append("")
    lines.append("Retrieved evidence (cite only from this list):")
    if chunks:
        for i, c in enumerate(chunks, 1):
            title = c.title or "untitled"
            src = c.source_url or "no url"
            snippet = (c.text or "").replace("\n", " ")
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            lines.append(f"[{i}] ({title}) {snippet}  <{src}>")
    else:
        lines.append("(no evidence retrieved - fall back to a plain "
                     "encouragement)")
    lines.append("")
    lines.append("Compose your new one-sentence coaching message now. "
                 "Do NOT repeat the detected-issue text verbatim.")
    return "\n".join(lines)


def _num_str(v) -> str:
    try:
        return f"{float(v):.1f}"
    except Exception:
        return str(v)
