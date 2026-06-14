"""Retrieve + rerank + format RAG context for system prompt."""

from __future__ import annotations

import logging
import math
import os
import re
import time
import uuid
from collections import Counter
from typing import Any

import httpx

from db import get_pool
from services.embeddings import EmbeddingError, embed_query, format_vector

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pure-Python BM25 (Okapi) — no external dependencies
# --------------------------------------------------------------------------- #

_WORD_RE = re.compile(r"\w+")

# How many candidate chunks BM25 selects before the vector search.
# With ~40k chunks and TOP_K_RETRIEVE=40, 10x = 400 candidates → 100x reduction.
_BM25_CANDIDATE_MULTIPLIER = 10
_BM25_K1 = 1.5
_BM25_B = 0.75


def _bm25_tokenize(text: str) -> list[str]:
    """Lowercase word-only tokens, minimum 2 chars."""
    return [t.lower() for t in _WORD_RE.findall(text) if len(t) >= 2]


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    *,
    avgdl: float,
    num_docs: int,
    doc_freq: Counter[str],
) -> float:
    """Okapi BM25 score for a single document against the query."""
    if not query_tokens or not doc_tokens:
        return 0.0

    dl = len(doc_tokens)
    if dl == 0:
        return 0.0

    tf_counter = Counter(doc_tokens)
    score = 0.0
    k1 = _BM25_K1
    b = _BM25_B
    N = num_docs

    for term in set(query_tokens):
        tf = tf_counter.get(term, 0)
        if tf == 0:
            continue
        n = doc_freq.get(term, 0)
        # Smooth IDF (same as Okapi BM25 default)
        idf = math.log(1.0 + (N - n + 0.5) / (n + 0.5))
        if idf <= 0:
            continue
        numerator = tf * (k1 + 1.0)
        denominator = tf + k1 * (1.0 - b + b * (dl / avgdl))
        score += idf * numerator / denominator

    return score


async def _bm25_prefilter(
    query: str,
    source_ids: list[str],
    top_k: int,
) -> list[uuid.UUID] | None:
    """Fetch chunks for *source_ids*, score with BM25, return top-*top_k* IDs.

    Returns ``None`` on any failure so callers fall through gracefully to the
    full vector scan (current behaviour).
    """
    if not query.strip() or not source_ids:
        return None

    query_tokens = _bm25_tokenize(query)
    if not query_tokens:
        return None

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sc.id, sc.text
                FROM source_chunks sc
                WHERE sc.source_id = ANY($1::uuid[])
                  AND sc.embedding IS NOT NULL
                """,
                [uuid.UUID(sid) for sid in source_ids],
            )
    except Exception as e:
        logger.warning("BM25 pre-filter fetch failed, falling back: %s", e)
        return None

    if not rows:
        return None

    total_candidates = len(rows)
    texts: list[str] = [r["text"] for r in rows]

    tokenized: list[list[str]] = [_bm25_tokenize(t) for t in texts]

    doc_freq: Counter[str] = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))

    avgdl = sum(len(t) for t in tokenized) / max(len(tokenized), 1)
    N = len(tokenized)

    scored: list[tuple[float, uuid.UUID]] = []
    for i, tokens in enumerate(tokenized):
        score = _bm25_score(query_tokens, tokens, avgdl=avgdl, num_docs=N, doc_freq=doc_freq)
        if score > 0:
            scored.append((score, rows[i]["id"]))

    if not scored:
        logger.info("BM25 pre-filter: no non-zero scores out of %d candidates", total_candidates)
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    top_ids = [sid for _score, sid in scored[:top_k]]

    logger.info(
        "BM25 pre-filter: %d → %d candidates (%.1f%% retained)",
        total_candidates,
        len(top_ids),
        100.0 * len(top_ids) / total_candidates if total_candidates else 0,
    )
    return top_ids

# Reranker URL + model come from the active reranker provider in global_settings;
# RERANKER_URL / RERANKER_MODEL env vars were removed in the 2026-05-21 providers cutover.
# RERANKER_TIMEOUT stays as runtime tuning.
RERANKER_TIMEOUT = float(os.environ.get("RERANKER_TIMEOUT", "15"))

# Env-var defaults — used only as a fallback if a DB setting is absent/unparseable.
_DEFAULTS: dict[str, float | int | bool] = {
    "rag_similarity_threshold": float(os.environ.get("RAG_SIMILARITY_THRESHOLD", "0.35")),
    "memory_similarity_threshold": float(os.environ.get("MEMORY_SIMILARITY_THRESHOLD", "0.45")),
    "rag_rerank_score_min": float(os.environ.get("RAG_RERANK_SCORE_MIN", "0.05")),
    "rag_bm25_enabled": True,
}

MEMORY_TOP_K = 3
TOP_K_RETRIEVE = 40
TOP_AFTER_RERANK = 10

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

    Resolves provider + model from global_settings.reranker_provider_id /
    reranker_model. If unset, returns None (caller uses flashrank).

    Soft-fails on ANY exception (DB unreachable, key-decrypt failure, malformed
    config, network error, parser error) — a misconfigured reranker must not
    take down RAG-enabled chat turns. The outer try/except is intentionally
    broad and is the load-bearing safety net here.
    """
    if not passages:
        return passages
    try:
        # Lazy import: avoids any circular risk and keeps top-level imports clean.
        from services.provider_client import build_headers, resolve_reranker_provider

        binding = await resolve_reranker_provider()
        if binding is None:
            return None  # No reranker provider configured → use flashrank fallback.
        provider, model = binding

        async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
            _t0 = time.monotonic()
            r = await client.post(
                f"{provider.base_url}/v1/rerank",
                json={
                    "model": model,
                    "query": query,
                    "documents": [p["text"] for p in passages],
                    "return_documents": False,
                },
                headers=build_headers(provider),
            )
            r.raise_for_status()
            logger.debug("rerank _rerank_infinity: %.0fms", (time.monotonic() - _t0) * 1000)
            results = r.json().get("results") or []

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
    except Exception as e:
        # Catches: DB errors during resolve, RuntimeError from key decrypt,
        # httpx network/timeout errors, raise_for_status, JSON parse errors,
        # and anything else. RAG must degrade, not break.
        logger.warning("infinity-rerank soft-failed (%s); falling back", e)
        return None


async def retrieve_memory_facts(query: str, conn: Any) -> list[str]:
    """
    Top-K memory facts for the query via pgvector cosine distance (same operator as source_chunks).
    Returns empty list if embedding fails or no matches.
    """
    settings = await _load_rag_settings()
    try:
        emb = await embed_query(query)
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
              AND (1 - (embedding <=> $1::vector)) >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            format_vector(emb),
            float(settings["memory_similarity_threshold"]),
            MEMORY_TOP_K,
        )
        return [r["content"] for r in rows]
    except Exception as e:
        logger.warning("retrieve_memory_facts failed: %s", e)
        return []


async def retrieve_context(
    query: str,
    source_ids: list[str],
    priority_source_ids: list[str] | None = None,
) -> tuple[str, int]:
    """Retrieve and rerank chunks across ``source_ids``.

    ``priority_source_ids`` are sources the user explicitly attached to the
    chat ("send to chat"). They are still drawn from the same pool, but their
    chunks are ordered first in the injected context and bypass the rerank-min
    gate so an explicitly attached document is always read.
    """
    if not query.strip() or not source_ids:
        return "", 0

    priority_set = {str(s) for s in (priority_source_ids or [])}

    settings = await _load_rag_settings()
    sim_threshold = float(settings["rag_similarity_threshold"])
    rerank_min = float(settings["rag_rerank_score_min"])

    # BM25 keyword pre-filter — narrows the candidate pool before the expensive
    # vector search. When enabled and non-empty, only chunks that pass BM25
    # scoring participate in the pgvector cosine distance query.
    # Priority (attached) sources are excluded from BM25 filtering so that
    # explicitly attached documents are always eligible for retrieval.
    non_priority_ids = [sid for sid in source_ids if sid not in priority_set]
    bm25_ids: list[uuid.UUID] | None = None
    if bool(settings.get("rag_bm25_enabled", True)) and non_priority_ids:
        bm25_top_k = TOP_K_RETRIEVE * _BM25_CANDIDATE_MULTIPLIER
        bm25_ids = await _bm25_prefilter(query, non_priority_ids, bm25_top_k)

    try:
        q_emb = await embed_query(query)
    except EmbeddingError as e:
        logger.warning("RAG query embed failed: %s", e)
        return "", 0

    if q_emb is None:
        logger.warning("RAG embed_query returned None; skipping retrieval")
        return "", 0

    q_vec = format_vector(q_emb)

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            pool_ids = [uuid.UUID(sid) for sid in non_priority_ids]
            if bm25_ids:
                rows = await conn.fetch(
                    """
                    SELECT sc.id, sc.text, sc.source_id, s.name AS source_name
                    FROM source_chunks sc
                    JOIN sources s ON s.id = sc.source_id
                    WHERE sc.source_id = ANY($4::uuid[])
                      AND sc.embedding IS NOT NULL
                      AND (1 - (sc.embedding <=> $2::vector)) >= $3
                      AND sc.id = ANY($5::uuid[])
                    ORDER BY sc.embedding <=> $2::vector
                    LIMIT $1
                    """,
                    TOP_K_RETRIEVE,
                    q_vec,
                    sim_threshold,
                    pool_ids,
                    bm25_ids,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT sc.id, sc.text, sc.source_id, s.name AS source_name
                    FROM source_chunks sc
                    JOIN sources s ON s.id = sc.source_id
                    WHERE sc.source_id = ANY($4::uuid[])
                      AND sc.embedding IS NOT NULL
                      AND (1 - (sc.embedding <=> $2::vector)) >= $3
                    ORDER BY sc.embedding <=> $2::vector
                    LIMIT $1
                    """,
                    TOP_K_RETRIEVE,
                    q_vec,
                    sim_threshold,
                    pool_ids,
                )
            # Attached (priority) sources are always retrieved without BM25 gating
            # so that explicitly attached documents can never be crowded out.
            priority_rows = []
            if priority_set:
                priority_rows = await conn.fetch(
                    """
                    SELECT sc.id, sc.text, sc.source_id, s.name AS source_name
                    FROM source_chunks sc
                    JOIN sources s ON s.id = sc.source_id
                    WHERE sc.source_id = ANY($3::uuid[])
                      AND sc.embedding IS NOT NULL
                    ORDER BY sc.embedding <=> $2::vector
                    LIMIT $1
                    """,
                    TOP_K_RETRIEVE,
                    q_vec,
                    [uuid.UUID(sid) for sid in priority_set],
                )
    except Exception as e:
        logger.warning("RAG vector query failed: %s", e)
        return "", 0

    logger.info("RAG threshold=%.2f chunks_passed=%d", sim_threshold, len(rows))

    # Merge global + priority rows, deduped by chunk id (priority kept either way).
    merged_rows = list(rows)
    seen_chunks = {row["id"] for row in rows}
    for row in priority_rows:
        if row["id"] not in seen_chunks:
            seen_chunks.add(row["id"])
            merged_rows.append(row)

    if not merged_rows:
        return "", 0

    passages: list[dict[str, Any]] = []
    passage_source: dict[str, str] = {}
    for i, row in enumerate(merged_rows):
        name = row["source_name"] or "source"
        pid = str(i)
        passage_source[pid] = str(row["source_id"])
        passages.append(
            {
                "id": pid,
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

    priority_texts: list[str] = []
    other_texts: list[str] = []
    dropped_low_score = 0
    for p in reranked:
        t = p.get("text")
        if not (t and str(t).strip()):
            continue
        # Explicitly attached sources are always read, in rerank order, and skip
        # the rerank-min gate. Everything else must clear the gate.
        if passage_source.get(str(p.get("id"))) in priority_set:
            priority_texts.append(str(t))
            continue
        score = p.get("score")
        if isinstance(score, (int, float)) and float(score) < rerank_min:
            dropped_low_score += 1
            continue
        other_texts.append(str(t))

    # Priority (attached) chunks first; backfill with the rest up to the cap.
    top_texts = (priority_texts + other_texts)[:TOP_AFTER_RERANK]

    if dropped_low_score:
        logger.info("RAG dropped %d chunks below rerank_min=%.2f", dropped_low_score, rerank_min)
    if priority_texts:
        logger.info("RAG priority(attached) chunks=%d", len(priority_texts))

    if not top_texts:
        logger.info("RAG no chunks survived rerank gate; returning empty context")
        return "", 0

    block = (
        "### Retrieved source documents:\n"
        "STRICT RULES for answering:\n"
        "1. Use ONLY the exact information from the source documents below. Do NOT add, infer, or fabricate any details.\n"
        "2. Quote values, names, locations, dates, and results EXACTLY as they appear in the source. Do not paraphrase numbers, lab names, addresses, or test results.\n"
        "3. If a piece of information (lab name, location, provider, result value) is not explicitly stated in the sources, say \"not specified in the document\" — do NOT guess or fill in from general knowledge.\n"
        "4. Cite the [SOURCE: ...] label when referencing content.\n"
        "5. Never invent medical data, test results, reference ranges, or provider names.\n\n"
        + "\n\n".join(top_texts)
    )
    logger.info("RAG context injected chunks=%d chars=%d", len(top_texts), len(block))
    return block, len(top_texts)
