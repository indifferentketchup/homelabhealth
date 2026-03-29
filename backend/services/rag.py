"""Retrieve + rerank + format RAG context for system prompt."""

from __future__ import annotations

import logging
from typing import Any

from db import get_chroma_collection
from services.embeddings import embed_text

logger = logging.getLogger(__name__)

TOP_K_RETRIEVE = 20
TOP_AFTER_RERANK = 6

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


async def retrieve_context(query: str, daw_id: str, source_ids: list[str]) -> str:
    if not query.strip() or not source_ids:
        return ""

    try:
        q_emb = await embed_text(query)
    except Exception as e:
        logger.warning("RAG query embed failed: %s", e)
        return ""

    try:
        collection = get_chroma_collection(daw_id)
        q = collection.query(
            query_embeddings=[q_emb],
            n_results=min(TOP_K_RETRIEVE, max(1, TOP_K_RETRIEVE)),
            where={"source_id": {"$in": list(source_ids)}},
        )
    except Exception as e:
        logger.warning("RAG Chroma query failed: %s", e)
        return ""

    docs = (q.get("documents") or [[]])[0]
    metas = (q.get("metadatas") or [[]])[0]
    if not docs:
        return ""

    passages: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        name = (meta or {}).get("source_name") or "source"
        label = f"[SOURCE: {name}]\n{doc}"
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
        return ""

    block = (
        "### Context from sources:\n"
        "Answer using ONLY the provided source material below. Do not use outside knowledge. Always cite the source label when referencing content. If the answer is not in the sources, say so.\n\n"
        + "\n\n".join(top)
    )
    logger.info("RAG context injected chunks=%d chars=%d", len(top), len(block))
    return block
