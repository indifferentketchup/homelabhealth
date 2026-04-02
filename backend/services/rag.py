"""Retrieve + rerank + format RAG context for system prompt."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from db import get_pool
from services.embeddings import embed_text

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = float(os.environ.get("RAG_SIMILARITY_THRESHOLD", "0.35"))
MEMORY_SIMILARITY_THRESHOLD = float(os.environ.get("MEMORY_SIMILARITY_THRESHOLD", "0.45"))
MEMORY_TOP_K = 3

_RAG_KEYWORDS = frozenset(
    [
        "file",
        "function",
        "class",
        "method",
        "import",
        "module",
        "script",
        "config",
        "dockerfile",
        "compose",
        "schema",
        "migration",
        "endpoint",
        "route",
        "api",
        "review",
        "show",
        "explain",
        "find",
        "search",
        "look",
        "check",
        "read",
        "what is",
        "how does",
        "how do",
        "where is",
        "where are",
        "what does",
        "tell me about",
        "describe",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".sql",
        ".yml",
        ".yaml",
        ".json",
        ".md",
        ".env",
        ".sh",
        ".toml",
        "boolab",
        "booops",
        "808notes",
        "dubdrive",
        "bourbites",
        "impulse",
        "ollamactl",
        "bosscord",
        "broccolini",
        "tweak",
        "dashgaard",
        "malwatch",
        "caddy",
        "docker",
        "postgres",
        "pgvector",
        "ollama",
        "fastapi",
    ]
)

_RAG_INTENT_GATE_ENABLED = os.environ.get("RAG_INTENT_GATE_ENABLED", "true").lower() == "true"
_RAG_MIN_WORDS = int(os.environ.get("RAG_MIN_WORDS_FOR_INTENT", "8"))

TOP_K_RETRIEVE = 40
TOP_AFTER_RERANK = 10

_RANKER: Any = None


def _ranker():
    global _RANKER
    if _RANKER is None:
        from flashrank import Ranker

        _RANKER = Ranker(model_name="ms-marco-MiniLM-L-12-v2", max_length=256)
    return _RANKER


def _reranked_passage_text(p: dict[str, Any]) -> str:
    t = p.get("text")
    return str(t) if t is not None else ""


def should_retrieve(query: str, mode: str) -> bool:
    """
    Returns True if RAG retrieval should run for this query.
    808notes always retrieves. BooOps uses intent gate.
    """
    if mode == "808notes":
        return True
    if not _RAG_INTENT_GATE_ENABLED:
        return True
    q = query.strip().lower()
    words = q.split()
    if len(words) >= _RAG_MIN_WORDS:
        return True
    for kw in _RAG_KEYWORDS:
        if kw in q:
            return True
    return False


async def retrieve_memory_facts(query: str, mode: str, conn: Any) -> list[str]:
    """
    Top-K memory facts for the query via pgvector cosine distance (same operator as source_chunks).
    Returns empty list if embedding fails or no matches.
    """
    try:
        emb = await embed_text(query)
        if not emb:
            return []
        rows = await conn.fetch(
            """
            SELECT content
            FROM memory_entries
            WHERE is_deleted = false
              AND embedding IS NOT NULL
              AND mode = $3
              AND (embedding <=> $1::vector) < $2
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            str(emb),
            MEMORY_SIMILARITY_THRESHOLD,
            mode,
            MEMORY_TOP_K,
        )
        return [r["content"] for r in rows]
    except Exception as e:
        logger.warning("retrieve_memory_facts failed: %s", e)
        return []


async def retrieve_context(query: str, daw_id: str, source_ids: list[str]) -> tuple[str, int]:
    del daw_id  # retained for call-site compatibility; scope is source_ids only
    if not query.strip() or not source_ids:
        return "", 0

    try:
        q_emb = await embed_text(query)
    except Exception as e:
        logger.warning("RAG query embed failed: %s", e)
        return "", 0

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sc.text, s.name AS source_name
                FROM source_chunks sc
                JOIN sources s ON s.id = sc.source_id
                WHERE sc.source_id = ANY($4::uuid[])
                  AND sc.embedding IS NOT NULL
                  AND (sc.embedding <=> $2::vector) < $3
                ORDER BY sc.embedding <=> $2::vector
                LIMIT $1
                """,
                TOP_K_RETRIEVE,
                str(q_emb),
                SIMILARITY_THRESHOLD,
                [uuid.UUID(sid) for sid in source_ids],
            )
    except Exception as e:
        logger.warning("RAG vector query failed: %s", e)
        return "", 0

    logger.info("RAG threshold=%.2f chunks_passed=%d", SIMILARITY_THRESHOLD, len(rows))

    if not rows:
        return "", 0

    passages: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        name = row["source_name"] or "source"
        label = f"[SOURCE: {name}]\n{row['text']}"
        passages.append({"id": str(i), "text": label})

    try:
        from flashrank import RerankRequest

        reranked = _ranker().rerank(RerankRequest(query=query, passages=passages))
        top = [_reranked_passage_text(p) for p in reranked[:TOP_AFTER_RERANK]]
    except Exception as e:
        logger.debug("RAG rerank skipped: %s", e)
        top = [_reranked_passage_text(p) for p in passages[:TOP_AFTER_RERANK]]

    top = [t for t in top if t and str(t).strip()]
    if not top:
        return "", 0

    n_chunks = len(top)
    block = (
        "### Context from sources:\n"
        "Answer using ONLY the provided source material below. Do not use outside knowledge. Always cite the source label when referencing content. If the answer is not in the sources, say so.\n\n"
        + "\n\n".join(top)
    )
    logger.info("RAG context injected chunks=%d chars=%d", n_chunks, len(block))
    return block, n_chunks
