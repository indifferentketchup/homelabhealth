#!/usr/bin/env python3
"""Verify MedGemma thinking blocks are stripped before chat SSE / persistence."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.reasoning_strip import ThinkingStreamFilter, strip_thinking_text  # noqa: E402


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def test_unit() -> None:
    lab_thought = (
        "thought\nThe user wants lab results.\n\nConstraint Checklist & Confidence Score:\n"
        "1. Do NOT diagnose? YES.\n\n"
        "General context about TSH.\n\nHere are the specific results you have:\n\n"
        "**Comprehensive Metabolic Panel (CMP)**\n* Sodium: 142"
    )
    out = strip_thinking_text(lab_thought)
    if out.lower().startswith("thought") or "constraint checklist" in out.lower():
        fail(f"lab strip leaked thinking: {out[:120]!r}")
    if "Here are the specific results" not in out:
        fail(f"lab strip removed answer: {out!r}")
    ok("strip_thinking_text removes lab planning block")

    glued = (
        'thought\n1. **Identify the core request:** Say "hi".\n'
        '4. **Check constraint:** "Hi!" is one sentence and short.Hi!'
    )
    out2 = strip_thinking_text(glued)
    if out2 != "Hi!":
        fail(f"glued strip expected 'Hi!', got {out2!r}")
    ok("strip_thinking_text handles glued short answer")

    filt = ThinkingStreamFilter()
    parts: list[str] = []
    for piece in ["thought", "\n", "planning only", "\n\nHere are results:\n", "Hello"]:
        parts.extend(filt.feed(piece))
    parts.extend(filt.flush())
    joined = "".join(parts)
    if "planning only" in joined or joined.lower().startswith("thought"):
        fail(f"stream filter leaked thinking: {joined!r}")
    if "Here are results" not in joined:
        fail(f"stream filter dropped answer: {joined!r}")
    ok("ThinkingStreamFilter streams answer only")


async def test_live_hlh_chat() -> None:
    import httpx

    payload = {
        "model": "medgemma",
        "messages": [{"role": "user", "content": "Say hi in one short sentence."}],
        "stream": True,
        "max_tokens": 256,
    }
    filt = ThinkingStreamFilter()
    visible: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "http://hlh_chat:9610/v1/chat/completions",
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    fail(f"hlh_chat returned {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    chunk = json.loads(raw)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        visible.extend(filt.feed(piece))
    except httpx.HTTPError as e:
        fail(f"cannot reach hlh_chat: {e}")

    visible.extend(filt.flush())
    text = "".join(visible)
    if not text.strip():
        fail("live stream produced no visible content after strip")
    lower = text.lower()
    if lower.startswith("thought") or "constraint checklist" in lower or "**identify" in lower:
        fail(f"live stream leaked thinking: {text[:200]!r}")
    ok(f"live hlh_chat stream visible={text[:120]!r}")


def main() -> None:
    test_unit()
    asyncio.run(test_live_hlh_chat())


if __name__ == "__main__":
    main()
