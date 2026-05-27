"""Vision embedding endpoints — MedSigLIP (Phase A3).

POST /api/vision/embed    — embed an image or text into 1152-dim space
POST /api/vision/search   — semantic search over image_chunks
POST /api/vision/classify — zero-shot image classification
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from deps import get_principal
from services.vision_embed import (
    VISION_EMBED_DIM,
    VisionEmbedError,
    classify_image,
    embed_image,
    embed_text,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class EmbedRequest(BaseModel):
    image: str | None = Field(default=None, description="Base64-encoded image")
    text: str | None = Field(default=None, description="Text to embed")
    mime_type: str = Field(default="image/png")


class SearchRequest(BaseModel):
    image: str | None = Field(default=None, description="Base64-encoded image for search")
    text: str | None = Field(default=None, description="Text query for search")
    mime_type: str = Field(default="image/png")
    top_k: int = Field(default=5, ge=1, le=100)


class ClassifyRequest(BaseModel):
    image: str = Field(..., description="Base64-encoded image")
    labels: list[str] = Field(..., min_length=1, max_length=50)
    mime_type: str = Field(default="image/png")


def _require_setup_complete():
    async def _check(_: dict[str, Any] = Depends(get_principal)):
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT setup_complete FROM system_profile WHERE id = 1")
        if not row or not bool(row["setup_complete"]):
            raise HTTPException(status_code=403, detail="Setup not complete")
    return Depends(_check)


@router.post("/embed")
async def vision_embed(
    body: EmbedRequest,
    _: None = _require_setup_complete(),
):
    if not body.image and not body.text:
        raise HTTPException(status_code=400, detail="Provide either 'image' or 'text'")
    try:
        if body.image:
            embedding = await embed_image(body.image, body.mime_type)
        else:
            embedding = await embed_text(body.text)
        return {"embedding": embedding, "dim": len(embedding)}
    except VisionEmbedError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/search")
async def vision_search(
    body: SearchRequest,
    _: None = _require_setup_complete(),
):
    if not body.image and not body.text:
        raise HTTPException(status_code=400, detail="Provide either 'image' or 'text'")
    try:
        if body.image:
            embedding = await embed_image(body.image, body.mime_type)
        else:
            embedding = await embed_text(body.text)
    except VisionEmbedError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_id, description, image_path, metadata,
                   1 - (embedding <=> $1::vector) AS score
              FROM image_chunks
             ORDER BY embedding <=> $1::vector
             LIMIT $2
            """,
            str(embedding),
            body.top_k,
        )
    return {
        "results": [
            {
                "id": str(r["id"]),
                "source_id": str(r["source_id"]) if r["source_id"] else None,
                "description": r["description"],
                "image_path": r["image_path"],
                "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                "score": round(float(r["score"]), 4),
            }
            for r in rows
        ]
    }


@router.post("/classify")
async def vision_classify(
    body: ClassifyRequest,
    _: None = _require_setup_complete(),
):
    try:
        classifications = await classify_image(body.image, body.labels, body.mime_type)
        return {"classifications": classifications}
    except VisionEmbedError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
