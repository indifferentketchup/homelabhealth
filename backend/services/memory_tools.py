"""Agent-facing memory management tools and background extraction.

Provides:
  - manage_memory()        — create/update/delete memories (tool-callable)
  - search_memory()        — semantic search over stored memories (tool-callable)
  - extract_from_exchange  — re-exported from memory_extraction (backward compat)
  - register_memory_hooks  — re-exported from memory_hooks (backward compat)
  - run_background_extraction — re-exported from memory_hooks (backward compat)
  - MEMORY_TOOLS           — dict for agent tool registration

Design follows LangMem's tool pattern (``create_manage_memory_tool`` /
``create_search_memory_tool``) but routes through the project's existing
MemoryEngine (SQLite + FTS5 + vector) instead of LangGraph BaseStore.

Zero external dependencies — uses httpx (already present) and stdlib only.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from services.memory.schemas import SearchResult

# Re-export extraction and hooks for backward compatibility
from services.memory_extraction import extract_from_exchange  # noqa: F401
from services.memory_hooks import (  # noqa: F401
    register_memory_hooks,
    run_background_extraction,
)

logger = logging.getLogger(__name__)

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
    from services.memory.engine import get_engine

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
    from services.memory.engine import get_engine

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

MEMORY_TOOLS: dict[str, dict[str, Any]] = {
    "manage_memory": MANAGE_MEMORY_TOOL_SPEC,
    "search_memory": SEARCH_MEMORY_TOOL_SPEC,
}

MEMORY_TOOL_FUNCTIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "manage_memory": manage_memory,
    "search_memory": search_memory,
}

__all__ = [
    # Tools
    "manage_memory",
    "search_memory",
    # Tool specs for agent registration
    "MEMORY_TOOLS",
    "MEMORY_TOOL_FUNCTIONS",
    "MANAGE_MEMORY_TOOL_SPEC",
    "SEARCH_MEMORY_TOOL_SPEC",
    # Extraction (re-exported)
    "extract_from_exchange",
    # Hooks (re-exported)
    "run_background_extraction",
    "register_memory_hooks",
]
