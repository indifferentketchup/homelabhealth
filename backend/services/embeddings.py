"""Embedding helpers — infinity-emb backend."""
from __future__ import annotations
import logging
import os
import httpx

logger = logging.getLogger(__name__)

EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://100.93.187.4:7997")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")


async def embed_text(text: str) -> list[float]:
    text = text.replace('\x00', '')
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{EMBEDDING_URL}/embeddings",
                json={"model": EMBEDDING_MODEL, "input": text},
            )
            r.raise_for_status()
            return r.json()["data"][0]["embedding"]
    except Exception as e:
        logger.error("embed_text failed: %s", e)
        return []


async def embed_batch(texts: list[str]) -> list[list[float]]:
    texts = [t.replace('\x00', '') for t in texts]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{EMBEDDING_URL}/embeddings",
                json={"model": EMBEDDING_MODEL, "input": texts},
            )
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
    except Exception as e:
        logger.error("embed_batch failed: %s", e)
        return []
