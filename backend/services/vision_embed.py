"""MedSigLIP vision embedding via infinity-emb sidecar (hlh_vision_embed).

Encodes images and text into a shared 1152-dim embedding space for
image classification, zero-shot classification, and semantic image retrieval.
Not generative — see services/vision.py for MedGemma chat-based vision.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from services.provider_client import (
    Provider,
    build_headers,
    resolve_vision_embed_provider,
)

logger = logging.getLogger(__name__)

VISION_EMBED_DIM = 1152
_TIMEOUT = httpx.Timeout(60.0)


class VisionEmbedError(Exception):
    pass


async def _get_provider() -> tuple[Provider, str]:
    binding = await resolve_vision_embed_provider()
    if binding is None:
        raise VisionEmbedError("Vision embedding not configured")
    return binding


async def embed_image(image_b64: str, mime_type: str = "image/png") -> list[float]:
    provider, model = await _get_provider()
    data_uri = f"data:{mime_type};base64,{image_b64}"
    payload = {"model": model, "input": [data_uri]}
    headers = build_headers(provider)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{provider.base_url}/v1/embeddings",
            headers=headers,
            json=payload,
        )
    if r.status_code >= 400:
        raise VisionEmbedError(f"infinity-emb returned HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    embedding = body.get("data", [{}])[0].get("embedding")
    if not isinstance(embedding, list):
        raise VisionEmbedError("malformed /v1/embeddings response (no embedding list)")
    return embedding


async def embed_text(text: str) -> list[float]:
    provider, model = await _get_provider()
    payload = {"model": model, "input": [text]}
    headers = build_headers(provider)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{provider.base_url}/v1/embeddings",
            headers=headers,
            json=payload,
        )
    if r.status_code >= 400:
        raise VisionEmbedError(f"infinity-emb returned HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    embedding = body.get("data", [{}])[0].get("embedding")
    if not isinstance(embedding, list):
        raise VisionEmbedError("malformed /v1/embeddings response (no embedding list)")
    return embedding


async def classify_image(
    image_b64: str,
    labels: list[str],
    mime_type: str = "image/png",
) -> list[dict[str, Any]]:
    """Zero-shot classification: embed image + each label, return cosine scores."""
    import math

    image_emb = await embed_image(image_b64, mime_type)

    provider, model = await _get_provider()
    headers = build_headers(provider)
    payload = {"model": model, "input": labels}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{provider.base_url}/v1/embeddings",
            headers=headers,
            json=payload,
        )
    if r.status_code >= 400:
        raise VisionEmbedError(f"infinity-emb returned HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    label_embeddings = [d["embedding"] for d in body.get("data", [])]
    if len(label_embeddings) != len(labels):
        raise VisionEmbedError(f"expected {len(labels)} label embeddings, got {len(label_embeddings)}")

    results = []
    for label, label_emb in zip(labels, label_embeddings):
        dot = sum(a * b for a, b in zip(image_emb, label_emb))
        norm_a = math.sqrt(sum(x * x for x in image_emb))
        norm_b = math.sqrt(sum(x * x for x in label_emb))
        score = dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0
        results.append({"label": label, "score": round(score, 4)})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
