"""Agent-facing memory management tools and background extraction.

Provides:
  - manage_memory()        — create/update/delete memories (tool-callable)
  - search_memory()        — semantic search over stored memories (tool-callable)
  - extract_from_exchange() — auto-extract facts from a user+assistant turn
  - register_memory_hooks() — wire PostToolUse callbacks into the T2 hooks system
  - MEMORY_TOOLS           — dict for agent tool registration

Design follows LangMem's tool pattern (``create_manage_memory_tool`` /
``create_search_memory_tool``) but routes through the project's existing
MemoryEngine (SQLite + FTS5 + vector) instead of LangGraph BaseStore.

Zero external dependencies — uses httpx (already present) and stdlib only.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from services.hooks import HookContext, register
from services.memory.engine import get_engine, MemoryEngine
from services.memory.schemas import SearchResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Tool: manage_memory
# ──────────────────────────────────────────────────────────────────────

_DEFAULT_MANAGE_INSTRUCTIONS = (
    "Proactively call this tool when you:\n"
    "1. Identify a new fact, preference, or important context about the user.\n"
    "2. Receive an explicit user request to remember something.\n"
    "3. Need to update an existing memory that is incorrect or outdated.\n"
    "4. Want to record key information from the current conversation.\n"
)


async def manage_memory(
    content: str,
    action: str = "create",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create, update, or delete a persistent memory.

    Parameters
    ----------
    content : str
        The memory content (text to remember).
    action : str
        One of ``"create"``, ``"update"``, ``"delete"``.
    metadata : dict or None
        Optional metadata with supported keys:
        - ``scope`` (str): ``"shared"`` (default), ``"user"``, or ``"workspace"``
        - ``tags`` (list[str]): free-form tags for filtering
        - ``source`` (str): origin label (default ``"agent_tool"``)
        - ``user_id`` (str): user identifier for scoped memories

    Returns
    -------
    dict with keys ``status``, ``id``, and optionally ``embedded``.
    """
    _meta = dict(metadata or {})
    _meta.setdefault("source", "agent_tool")
    _meta.setdefault("scope", "shared")

    engine = get_engine()

    if action == "delete":
        # Metadata-less delete — core tier uses content-hash ID
        result = await engine.manage(content=content, action="delete", metadata=_meta)
        logger.info("memory_tools: deleted memory id=%s", result.get("id"))
        return result

    result = await engine.manage(content=content, action=action, metadata=_meta)

    if result.get("status") in ("create", "update"):
        logger.info(
            "memory_tools: %sd memory id=%s embedded=%s",
            action,
            result.get("id"),
            result.get("embedded", False),
        )
    else:
        logger.info("memory_tools: manage returned %s", result)

    return result


MANAGE_MEMORY_TOOL_SPEC: dict[str, Any] = {
    "name": "manage_memory",
    "description": _DEFAULT_MANAGE_INSTRUCTIONS,
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The memory content to store (text to remember).",
            },
            "action": {
                "type": "string",
                "enum": ["create", "update", "delete"],
                "description": "Whether to create, update, or delete a memory.",
                "default": "create",
            },
            "metadata": {
                "type": "object",
                "description": "Optional: scope, tags, source, user_id.",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["shared", "user", "workspace"],
                        "description": "Visibility scope (default 'shared').",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Free-form tags for filtering.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Origin label (default 'agent_tool').",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User identifier for scoped memories.",
                    },
                },
            },
        },
        "required": ["content"],
    },
}

# ──────────────────────────────────────────────────────────────────────
# Tool: search_memory
# ──────────────────────────────────────────────────────────────────────

_DEFAULT_SEARCH_INSTRUCTIONS = (
    "Search your long-term memories for information relevant to the current context. "
    "Use specific queries to find facts, preferences, or past information."
)


async def search_memory(
    query: str,
    limit: int = 10,
    scope: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search stored memories using hybrid (vector + keyword) search.

    Parameters
    ----------
    query : str
        The search text.
    limit : int
        Maximum number of results (default 10, max 50).
    scope : str or None
        Optional scope filter: ``None`` (all), ``"shared"``, ``"user"``, or ``"workspace"``.
    user_id : str or None
        Optional user ID filter.

    Returns
    -------
    List of result dicts with keys: ``content``, ``score``, ``snippet``, ``source``.
    """
    limit = min(max(limit, 1), 50)
    engine = get_engine()
    scoped = "shared"
    if scope:
        scoped = scope
    elif user_id:
        scoped = "user"

    results = await engine.search(
        query=query,
        limit=limit,
        scope=scoped,
        user_id=user_id,
    )

    return [_search_result_to_dict(r) for r in results]


def _search_result_to_dict(r: SearchResult) -> dict[str, Any]:
    return {
        "content": r.snippet,
        "score": round(float(r.score), 4),
        "snippet": (r.snippet or "")[:300],
        "source": r.source or "memory",
    }


SEARCH_MEMORY_TOOL_SPEC: dict[str, Any] = {
    "name": "search_memory",
    "description": _DEFAULT_SEARCH_INSTRUCTIONS,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant memories.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default 10, max 50).",
                "default": 10,
            },
            "scope": {
                "type": "string",
                "enum": ["shared", "user", "workspace"],
                "description": "Optional scope filter.",
            },
            "user_id": {
                "type": "string",
                "description": "Optional user ID filter.",
            },
        },
        "required": ["query"],
    },
}

# ──────────────────────────────────────────────────────────────────────
# Tool registry (for agent tool binding)
# ──────────────────────────────────────────────────────────────────────

MEMORY_TOOLS: dict[str, dict[str, Any]] = {
    "manage_memory": MANAGE_MEMORY_TOOL_SPEC,
    "search_memory": SEARCH_MEMORY_TOOL_SPEC,
}

MEMORY_TOOL_FUNCTIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "manage_memory": manage_memory,
    "search_memory": search_memory,
}


# ──────────────────────────────────────────────────────────────────────
# Background extraction
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


# ──────────────────────────────────────────────────────────────────────
# Hook registration
# ──────────────────────────────────────────────────────────────────────


async def _post_tool_memory_hook(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any,
    ctx: HookContext,
    duration_ms: float,
) -> None:
    """PostToolUse callback that logs memory operations and triggers
    lightweight metadata enrichment on ``manage_memory`` calls."""
    if tool_name not in ("manage_memory", "search_memory"):
        return

    action = tool_input.get("action", "create")
    content = (tool_input.get("content") or "")[:120]

    logger.debug(
        "memory_hook: %s %s (%.2fms) chat=%s user=%s",
        tool_name,
        action,
        duration_ms,
        ctx.chat_id or "?",
        ctx.user_id or "?",
    )

    # For manage_memory "create" with substantial content, add a short
    # audit trail via the daily tier.
    if tool_name == "manage_memory" and action == "create" and len(content) > 20:
        try:
            engine = get_engine()
            engine.daily.append(
                entry_text=(
                    f"**Agent memory created** ({content[:80]}…)"
                ),
                reason="agent_tool",
                user_id=ctx.user_id,
            )
        except Exception as exc:
            logger.debug("memory_hook: daily append skipped: %s", exc)

    # For search_memory, log the query for future analytics
    if tool_name == "search_memory":
        query = (tool_input.get("query") or "")[:120]
        logger.info(
            "memory_hook: search query=%r limit=%s (%.2fms)",
            query,
            tool_input.get("limit", 10),
            duration_ms,
        )


def register_memory_hooks() -> None:
    """Register PostToolUse and Stop hooks for memory operations.

    Call this once at application startup (e.g. in ``main.py`` lifespan).
    Safe to call multiple times — callbacks are append-only but
    registering duplicates is harmless for these lightweight hooks.
    """
    register("post_tool_execution", _post_tool_memory_hook)
    logger.info("memory_tools: registered PostToolUse memory hook")


# ──────────────────────────────────────────────────────────────────────
# Inference job helper
# ──────────────────────────────────────────────────────────────────────

_EXTRACTION_MIN_TEXT_LENGTH = 40
"""Minimum combined text length to trigger background extraction."""


async def run_background_extraction(
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
) -> list[dict[str, Any]]:
    """Convenience entry point called from inference_job.py post-completion.

    Skips extraction when text is too short (avoids wasting inference
    tokens on trivial exchanges).

    Returns the list of extracted facts (empty if nothing extracted).
    """
    combined = (user_message_text or "") + (assistant_text or "")
    if len(combined.strip()) < _EXTRACTION_MIN_TEXT_LENGTH:
        return []

    try:
        return await extract_from_exchange(
            user_text=user_message_text,
            assistant_text=assistant_text,
            provider=provider,
            model=model,
        )
    except Exception as exc:
        logger.warning(
            "run_background_extraction: failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []


__all__ = [
    # Tools
    "manage_memory",
    "search_memory",
    # Tool specs for agent registration
    "MEMORY_TOOLS",
    "MEMORY_TOOL_FUNCTIONS",
    "MANAGE_MEMORY_TOOL_SPEC",
    "SEARCH_MEMORY_TOOL_SPEC",
    # Extraction
    "extract_from_exchange",
    "run_background_extraction",
    # Hooks
    "register_memory_hooks",
]
