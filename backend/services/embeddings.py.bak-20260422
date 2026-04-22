"""Embedding helpers — infinity-emb backend (OpenAI-compatible /embeddings)."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://100.93.187.4:7997")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_TIMEOUT = float(os.environ.get("EMBEDDING_TIMEOUT", "120"))


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend fails or returns a malformed response."""


def _clean(text: str) -> str:
    return text.replace("\x00", "")


async def _post(client: httpx.AsyncClient, inputs: list[str]) -> list[list[float]]:
    r = await client.post(
        f"{EMBEDDING_URL}/embeddings",
        json={"model": EMBEDDING_MODEL, "input": inputs},
    )
    r.raise_for_status()
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


async def embed_text(text: str) -> list[float]:
    """Embed a single string. Raises EmbeddingError on failure."""
    cleaned = _clean(text)
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            result = await _post(client, [cleaned])
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
    out: list[list[float]] = []
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
            for start in range(0, len(cleaned), EMBEDDING_BATCH_SIZE):
                sub = cleaned[start : start + EMBEDDING_BATCH_SIZE]
                out.extend(await _post(client, sub))
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"embed_batch failed: {e}") from e
    if len(out) != len(cleaned):
        raise EmbeddingError(f"batch size mismatch: got {len(out)} for {len(cleaned)} inputs")
    return out


def format_vector(emb: list[float]) -> str:
    """
    Serialize an embedding for pgvector's `::vector` text cast.
    Explicit precision avoids repr-variance issues (e.g. numpy scalar reprs).
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"
