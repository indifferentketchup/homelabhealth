"""Memory extraction from conversation exchanges.

Provides fact extraction via LLM completion and JSON parsing.
Separated from memory_tools.py for single-responsibility clarity.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from services.memory.engine import get_engine, MemoryEngine

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Extraction prompt
# ──────────────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a memory extraction system. Analyze the conversation exchange below and "
    "extract any factual statements, preferences, medical information, or important "
    "context that should be remembered.\n\n"
    "Return a JSON array of objects, each with:\n"
    '  - "content": the fact as a clear, standalone statement (10-100 characters)\n'
    '  - "category": one of "medical", "preference", "context", "personal", "other"\n'
    '  - "confidence": a float 0.0-1.0\n\n'
    "Only extract information that is explicitly stated or strongly implied. "
    "Return an empty array [] if nothing is worth remembering."
)


async def extract_from_exchange(
    user_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
    *,
    engine: MemoryEngine | None = None,
) -> list[dict[str, Any]]:
    """Analyze one user+assistant exchange and extract structured facts.

    Uses the inference provider for a single non-streaming completion.
    Extracted facts are persisted via ``MemoryEngine.manage()``.

    Parameters
    ----------
    user_text : str
        The user's message.
    assistant_text : str
        The assistant's response.
    provider : Provider
        A resolved ``Provider`` dataclass (must have ``base_url`` and
        ``api_key`` attributes).
    model : str
        The model name to use (e.g. ``"medgemma"``, ``"gpt-4o-mini"``).
    engine : MemoryEngine or None
        Override the singleton engine (e.g. for testing).

    Returns
    -------
    List of dicts with keys ``content``, ``category``, ``confidence``, ``memory_id``.
    """
    import httpx

    if not user_text or not user_text.strip():
        return []

    conversation = f"User: {user_text}\n\nAssistant: {assistant_text or ''}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": conversation},
        ],
        "stream": False,
        "max_tokens": 1024,
        "temperature": 0.1,
    }

    try:
        from services.provider_client import build_headers

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            if resp.status_code >= 400:
                logger.warning(
                    "extract_from_exchange: LLM returned %d", resp.status_code
                )
                return []

            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return []

            msg = choices[0].get("message") or {}
            raw = (msg.get("content") or "").strip()
            facts = _parse_extraction_response(raw)

    except Exception as exc:
        logger.warning(
            "extract_from_exchange: LLM call failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []

    if not facts:
        return []

    eng = engine or get_engine()
    saved: list[dict[str, Any]] = []
    for fact in facts:
        content = (fact.get("content") or "").strip()
        if not content or len(content) < 10:
            continue

        category = fact.get("category", "context")
        confidence = min(float(fact.get("confidence", 0.5)), 1.0)

        try:
            result = await eng.manage(
                content=content,
                action="create",
                metadata={
                    "source": "extraction",
                    "category": category,
                    "confidence": confidence,
                    "extraction_version": "1.0",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            saved.append({
                "content": content,
                "category": category,
                "confidence": confidence,
                "memory_id": result.get("id"),
            })
        except Exception as exc:
            logger.warning(
                "extract_from_exchange: failed to save fact: %s", exc
            )

    logger.info("extract_from_exchange: saved %d facts from exchange", len(saved))
    return saved


def _parse_extraction_response(raw: str) -> list[dict[str, Any]]:
    """Parse the LLM response, extracting a JSON array of fact objects.

    Handles markdown code fences, leading/trailing text, and malformed JSON.
    Returns an empty list on failure.
    """
    text = raw.strip()
    if not text:
        return []

    # Strip outermost markdown code fences
    if text.startswith("```"):
        # Find the first structural bracket
        start = text.find("[")
        if start == -1:
            start = text.find("{")
        if start != -1:
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
            else:
                # No closing fence — take from bracket onward
                text = text[start:].strip()
        else:
            # No bracket found despite fences — strip fences entirely
            lines = text.splitlines()
            cleaned = []
            in_fence = False
            for line in lines:
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                if not in_fence:
                    cleaned.append(line)
            text = "\n".join(cleaned).strip()

    # Try direct JSON parse
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try extracting a JSON array via regex-like search
    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start != -1 and arr_end > arr_start:
        candidate = text[arr_start : arr_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Last resort: try parsing as a single object and wrap it
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            return [obj]
        except json.JSONDecodeError:
            pass

    logger.debug("extract_from_exchange: could not parse response: %.200s", raw)
    return []
