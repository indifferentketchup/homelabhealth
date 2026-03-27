"""Ollama embedding calls."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

BATCH_SIZE = 32
EMBED_RETRIES = 3
EMBED_RETRY_DELAY_S = 5.0

logger = logging.getLogger(__name__)


def _ollama_embeddings_url() -> str:
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    return f"{base}/api/embeddings"


def _embedding_model() -> str:
    return (
        os.environ.get("OLLAMA_EMBEDDING_MODEL")
        or os.environ.get("EMBEDDING_MODEL")
        or "qwen3-embedding:latest"
    ).strip()


async def embed_text(text: str) -> list[float]:
    url = _ollama_embeddings_url()
    model = _embedding_model()
    last_err: Exception | None = None
    for attempt in range(EMBED_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                r = await client.post(url, json={"model": model, "prompt": text})
                r.raise_for_status()
                data = r.json()
                emb = data.get("embedding")
                if not isinstance(emb, list):
                    raise ValueError("Ollama embeddings response missing embedding array")
                return emb
        except (httpx.HTTPError, ValueError) as e:
            last_err = e
            logger.warning(
                "embed attempt %d/%d failed: %s",
                attempt + 1,
                EMBED_RETRIES,
                e,
            )
            if attempt + 1 < EMBED_RETRIES:
                await asyncio.sleep(EMBED_RETRY_DELAY_S)
    assert last_err is not None
    raise last_err


async def embed_batch(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        for t in batch:
            out.append(await embed_text(t))
    return out
