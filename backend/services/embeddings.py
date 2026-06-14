"""Embedding helpers — provider-resolved per call (no env-var URL/MODEL).

The active embedding provider + model live in `global_settings`
(`embedding_provider_id`, `embedding_model`). If either is absent, every
call raises `EmbeddingError("Embedding model not configured. Set one in
Settings → Embedding.")`.

Pipeline-shape env vars (EMBEDDING_DIM, EMBEDDING_BATCH_SIZE,
EMBEDDING_TIMEOUT, EMBEDDING_QUERY_INSTRUCTION) stay as runtime tuning.
"""
from __future__ import annotations

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_TIMEOUT = float(os.environ.get("EMBEDDING_TIMEOUT", "120"))
EMBEDDING_QUERY_INSTRUCTION = os.environ.get(
    "EMBEDDING_QUERY_INSTRUCTION",
    "Given a web search query, retrieve relevant passages.",
)


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend fails or returns a malformed response."""


def _clean(text: str) -> str:
    return text.replace("\x00", "")


async def _post(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    inputs: list[str],
) -> list[list[float]]:
    _t0 = time.monotonic()
    r = await client.post(
        f"{base_url}/v1/embeddings",
        json={"model": model, "input": inputs},
        headers=headers,
    )
    r.raise_for_status()
    logger.debug("embed _post: n=%d %.0fms", len(inputs), (time.monotonic() - _t0) * 1000)
    data = r.json().get("data") or []
    if len(data) != len(inputs):
        raise EmbeddingError(f"backend returned {len(data)} vectors for {len(inputs)} inputs")
    out: list[list[float]] = []
    for i, item in enumerate(data):
        emb = item.get("embedding")
        if not isinstance(emb, list) or len(emb) != EMBEDDING_DIM:
            raise EmbeddingError(
                f"malformed embedding at index {i}: len={len(emb) if isinstance(emb, list) else 'n/a'}"
            )
        out.append(emb)
    return out


async def _resolve() -> tuple[str, str, dict[str, str]]:
    """Resolve (base_url, model, headers) for the active embedding provider.

    Imported lazily to avoid a top-level cycle (provider_client raises
    EmbeddingError from this module).
    """
    from services.provider_client import build_headers, resolve_embedding_provider
    provider, model = await resolve_embedding_provider()
    return provider.base_url, model, build_headers(provider)


async def embed_text(text: str) -> list[float]:
    """Embed a single string. Raises EmbeddingError on failure."""
    cleaned = _clean(text)
    base_url, model, headers = await _resolve()
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            result = await _post(client, base_url, headers, model, [cleaned])
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"embed_text failed: {e}") from e
    return result[0]


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts in one (or a few) HTTP round-trips.

    Chunks into EMBEDDING_BATCH_SIZE sub-batches. Raises EmbeddingError on any
    failure — the caller is responsible for marking the ingest as failed rather
    than inserting null-embedding rows.
    """
    if not texts:
        return []
    cleaned = [_clean(t) for t in texts]
    base_url, model, headers = await _resolve()
    out: list[list[float]] = []
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            for start in range(0, len(cleaned), EMBEDDING_BATCH_SIZE):
                sub = cleaned[start : start + EMBEDDING_BATCH_SIZE]
                out.extend(await _post(client, base_url, headers, model, sub))
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"embed_batch failed: {e}") from e
    if len(out) != len(cleaned):
        raise EmbeddingError(f"batch size mismatch: got {len(out)} for {len(cleaned)} inputs")
    return out


async def embed_query(text: str) -> list[float]:
    """Embed a search query. The configured embedding model may require an instruction prefix on queries; documents stay raw."""
    cleaned = _clean(text)
    prefixed = f"Instruct: {EMBEDDING_QUERY_INSTRUCTION}\nQuery: {cleaned}"
    base_url, model, headers = await _resolve()
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            result = await _post(client, base_url, headers, model, [prefixed])
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"embed_query failed: {e}") from e
    return result[0]


def format_vector(emb: list[float]) -> str:
    """
    Serialize an embedding for pgvector's `::vector` text cast.
    Explicit precision avoids repr-variance issues (e.g. numpy scalar reprs).
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"
