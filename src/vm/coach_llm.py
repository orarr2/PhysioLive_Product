"""LLM caller used by the VM's coach endpoint.

Reads `COACH_PROVIDER` from the environment and dispatches:

- `groq` (default): Llama 3.3 70B on the Groq platform. OpenAI-compatible
  API at https://api.groq.com/openai/v1, requires `GROQ_API_KEY`.
- `anthropic`: Claude Haiku via the Anthropic Python SDK, requires
  `ANTHROPIC_API_KEY`.

Both providers return a single-sentence coaching message. The system
prompt forbids inventing citations - the model may only reference
facts that appear in the evidence chunks passed to it.
"""
from __future__ import annotations

import os
from typing import List, Sequence

from app.rag.query import Chunk


SYSTEM_PROMPT = (
    "You are a virtual physiotherapy coach. The user just finished one "
    "repetition of a rehabilitation exercise. You receive a rule-based "
    "verdict and a short set of evidence chunks that the retrieval "
    "layer picked for this event.\n\n"
    "Reply with exactly ONE short sentence in English (max 22 words) "
    "that either encourages the user or corrects the form issue. "
    "If you cite a fact, cite ONLY facts that appear in the evidence "
    "chunks below. Do NOT invent statistics or references. If none of "
    "the chunks is relevant, give a plain motivational sentence without "
    "citing anything. Lead with a positive note before a correction "
    "when the verdict is not 'good'."
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
    from openai import OpenAI
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = OpenAI(api_key=api_key,
                    base_url="https://api.groq.com/openai/v1")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=140,
        temperature=0.4,
        timeout=8.0,
    )
    return (resp.choices[0].message.content or "").strip()


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
        f"Verdict: {verdict_level or 'unknown'}",
        f"Rule message: {verdict_text or '(none)'}",
    ]
    if metrics:
        lines.append(f"Angles: {metrics}")
    lines.append("")
    lines.append("Evidence chunks (cite only these):")
    if chunks:
        for i, c in enumerate(chunks, 1):
            title = c.title or "untitled"
            src = c.source_url or "no url"
            snippet = (c.text or "").replace("\n", " ")
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            lines.append(f"[{i}] ({title}) {snippet}  <{src}>")
    else:
        lines.append("(no evidence retrieved)")
    lines.append("")
    lines.append("Reply now with the single-sentence coaching message.")
    return "\n".join(lines)
