"""Embedding helpers (backend disabled until an embedding provider is configured)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def embed_text(text: str) -> list[float]:
    del text
    logger.warning("Embeddings disabled — no embedding backend configured")
    return []


async def embed_batch(texts: list[str]) -> list[list[float]]:
    if texts:
        logger.warning("Embeddings disabled — no embedding backend configured")
    return []
