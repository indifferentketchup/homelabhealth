"""Retrieve + rerank + format RAG context for system prompt."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import httpx

from db import get_pool
from services.embeddings import EmbeddingError, embed_text, format_vector

logger = logging.getLogger(__name__)

RERANKER_URL = os.environ.get("RERANKER_URL", "http://100.93.187.4:7998").rstrip("/")
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_TIMEOUT = float(os.environ.get("RERANKER_TIMEOUT", "15"))

# Env-var defaults — used only as a fallback if a DB setting is absent/unparseable.
_DEFAULTS: dict[str, float | int | bool] = {
    "rag_similarity_threshold": float(os.environ.get("RAG_SIMILARITY_THRESHOLD", "0.35")),
    "memory_similarity_threshold": float(os.environ.get("MEMORY_SIMILARITY_THRESHOLD", "0.45")),
    "rag_rerank_score_min": float(os.environ.get("RAG_RERANK_SCORE_MIN", "0.05")),
    "rag_intent_gate_enabled": os.environ.get("RAG_INTENT_GATE_ENABLED", "true").lower() == "true",
    "rag_min_words_for_intent": int(os.environ.get("RAG_MIN_WORDS_FOR_INTENT", "4")),
}

MEMORY_TOP_K = 3
TOP_K_RETRIEVE = 40
TOP_AFTER_RERANK = 10

REPO_TOP_K_DEFAULT = 20
REPO_SIMILARITY_THRESHOLD_FALLBACK = 0.3

_SETTINGS_TTL_SECONDS = 30.0
_settings_cache: dict[str, Any] = {}
_settings_cache_at: float = 0.0


async def _load_rag_settings() -> dict[str, Any]:
    """
    Read RAG-tunable settings from global_settings with a short TTL cache.
    Values in the DB are stored as strings — coerce to the default's type.
    Falls back silently to defaults on any failure (e.g. missing key).
    """
    global _settings_cache, _settings_cache_at
    now = time.monotonic()
    if _settings_cache and (now - _settings_cache_at) < _SETTINGS_TTL_SECONDS:
        return _settings_cache

    out: dict[str, Any] = dict(_DEFAULTS)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM global_settings WHERE key = ANY($1::text[])",
                list(_DEFAULTS.keys()),
            )
        for r in rows:
            k = r["key"]
            raw = r["value"]
            if raw is None:
                continue
            default = _DEFAULTS[k]
            try:
                if isinstance(default, bool):
                    out[k] = str(raw).strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int) and not isinstance(default, bool):
                    out[k] = int(float(str(raw).strip()))
                elif isinstance(default, float):
                    out[k] = float(str(raw).strip())
                else:
                    out[k] = raw
            except (ValueError, TypeError):
                logger.warning("global_settings %s has unparseable value %r; using default", k, raw)
    except Exception as e:
        logger.warning("RAG settings load failed, using defaults: %s", e)

    _settings_cache = out
    _settings_cache_at = now
    return out


def invalidate_rag_settings_cache() -> None:
    """Call from the settings PATCH endpoint after updating any RAG key."""
    global _settings_cache, _settings_cache_at
    _settings_cache = {}
    _settings_cache_at = 0.0


_RANKER: Any = None


def _ranker():
    global _RANKER
    if _RANKER is None:
        from flashrank import Ranker

        _RANKER = Ranker(model_name="ms-marco-MiniLM-L-12-v2", max_length=256)
    return _RANKER


async def _rerank_infinity(query: str, passages: list[dict]) -> list[dict] | None:
    """
    Rerank via the GPU-backed infinity-rerank service. Returns the passages
    sorted by relevance with a `score` field attached, or None on any failure
    so the caller can fall back to flashrank → similarity order.
    """
    if not passages:
        return passages
    try:
        async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
            r = await client.post(
                f"{RERANKER_URL}/rerank",
                json={
                    "model": RERANKER_MODEL,
                    "query": query,
                    "documents": [p["text"] for p in passages],
                    "return_documents": False,
                },
            )
            r.raise_for_status()
            results = r.json().get("results") or []
    except Exception as e:
        logger.warning("infinity-rerank unreachable, will fall back: %s", e)
        return None

    out: list[dict] = []
    for item in results:
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(passages):
            continue
        merged = dict(passages[idx])
        score = item.get("relevance_score")
        if isinstance(score, (int, float)):
            merged["score"] = float(score)
        out.append(merged)
    if not out:
        logger.warning("infinity-rerank returned no usable results; falling back")
        return None
    return out


async def should_retrieve(query: str, mode: str) -> bool:
    """
    Returns True if RAG retrieval should run for this query.
    808notes always retrieves. BooOps uses a simple length-based intent gate;
    relevance filtering is handled post-retrieval by the similarity and
    rerank-score thresholds.
    """
    if mode == "808notes":
        return True
    settings = await _load_rag_settings()
    if not settings["rag_intent_gate_enabled"]:
        return True
    words = query.strip().split()
    return len(words) >= int(settings["rag_min_words_for_intent"])


async def retrieve_repo_chunks(
    conn: Any,
    daw_id: str,
    query: str,
    top_k: int = REPO_TOP_K_DEFAULT,
    similarity_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve repo_chunks for a BooCode DAW via pgvector cosine distance.

    Returns a list of dicts:
        {path, language, symbol_kind, symbol_name, content, similarity}

    Returns [] on empty query or embedding failure (logs a warning, does not raise).
    """
    q = (query or "").strip()
    if not q or not daw_id:
        return []

    if similarity_threshold is None:
        settings = await _load_rag_settings()
        try:
            similarity_threshold = float(settings.get(
                "rag_similarity_threshold",
                REPO_SIMILARITY_THRESHOLD_FALLBACK,
            ))
        except (TypeError, ValueError):
            similarity_threshold = REPO_SIMILARITY_THRESHOLD_FALLBACK

    try:
        emb = await embed_text(q)
    except EmbeddingError as e:
        logger.warning("repo_rag embed failed: %s", e)
        return []
    if not emb:
        logger.warning("repo_rag embed returned empty vector")
        return []

    q_vec = format_vector(emb)
    try:
        rows = await conn.fetch(
            """
            SELECT rf.path, rf.language, rc.symbol_kind, rc.symbol_name, rc.content,
                   1 - (rc.embedding <=> $1::vector) AS similarity
            FROM repo_chunks rc
            JOIN repo_files rf ON rf.id = rc.file_id
            WHERE rc.daw_id = $2::uuid
              AND rc.embedding IS NOT NULL
            ORDER BY rc.embedding <=> $1::vector
            LIMIT $3
            """,
            q_vec,
            uuid.UUID(daw_id) if not isinstance(daw_id, uuid.UUID) else daw_id,
            int(top_k),
        )
    except Exception as e:
        logger.warning("repo_rag vector query failed: %s", e)
        return []

    results: list[dict[str, Any]] = []
    for r in rows:
        sim = float(r["similarity"]) if r["similarity"] is not None else 0.0
        if sim < float(similarity_threshold):
            continue
        results.append({
            "path": r["path"],
            "language": r["language"],
            "symbol_kind": r["symbol_kind"],
            "symbol_name": r["symbol_name"],
            "content": r["content"],
            "similarity": sim,
        })

    top1 = results[0]["similarity"] if results else 0.0
    logger.info(
        "repo_rag retrieved daw_id=%s top_k=%d threshold=%.2f kept=%d top1=%.3f",
        daw_id, top_k, float(similarity_threshold), len(results), top1,
    )
    return results


async def retrieve_memory_facts(query: str, mode: str, conn: Any) -> list[str]:
    """
    Top-K memory facts for the query via pgvector cosine distance (same operator as source_chunks).
    Returns empty list if embedding fails or no matches.
    """
    settings = await _load_rag_settings()
    try:
        emb = await embed_text(query)
    except EmbeddingError as e:
        logger.warning("memory query embed failed: %s", e)
        return []
    try:
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
            format_vector(emb),
            float(settings["memory_similarity_threshold"]),
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

    settings = await _load_rag_settings()
    sim_threshold = float(settings["rag_similarity_threshold"])
    rerank_min = float(settings["rag_rerank_score_min"])

    try:
        q_emb = await embed_text(query)
    except EmbeddingError as e:
        logger.warning("RAG query embed failed: %s", e)
        return "", 0

    q_vec = format_vector(q_emb)

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
                q_vec,
                sim_threshold,
                [uuid.UUID(sid) for sid in source_ids],
            )
    except Exception as e:
        logger.warning("RAG vector query failed: %s", e)
        return "", 0

    logger.info("RAG threshold=%.2f chunks_passed=%d", sim_threshold, len(rows))

    if not rows:
        return "", 0

    passages: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        name = row["source_name"] or "source"
        passages.append(
            {
                "id": str(i),
                "text": f"[SOURCE: {name}]\n{row['text']}",
            }
        )

    reranked = await _rerank_infinity(query, passages)
    rerank_backend = "infinity"
    if reranked is None:
        rerank_backend = "flashrank"
        try:
            from flashrank import RerankRequest

            reranked = _ranker().rerank(RerankRequest(query=query, passages=passages))
        except Exception:
            logger.exception("RAG rerank failed; falling back to similarity order")
            rerank_backend = "similarity"
            reranked = passages  # already in similarity order
    logger.info("RAG rerank backend=%s passages=%d", rerank_backend, len(passages))

    top_texts: list[str] = []
    dropped_low_score = 0
    for p in reranked[:TOP_AFTER_RERANK]:
        score = p.get("score")
        if isinstance(score, (int, float)) and float(score) < rerank_min:
            dropped_low_score += 1
            continue
        t = p.get("text")
        if t and str(t).strip():
            top_texts.append(str(t))

    if dropped_low_score:
        logger.info("RAG dropped %d chunks below rerank_min=%.2f", dropped_low_score, rerank_min)

    if not top_texts:
        logger.info("RAG no chunks survived rerank gate; returning empty context")
        return "", 0

    block = (
        "### Context from sources:\n"
        "Answer using ONLY the provided source material below. Do not use outside knowledge. "
        "Always cite the source label when referencing content. If the answer is not in the sources, say so.\n\n"
        + "\n\n".join(top_texts)
    )
    logger.info("RAG context injected chunks=%d chars=%d", len(top_texts), len(block))
    return block, len(top_texts)
