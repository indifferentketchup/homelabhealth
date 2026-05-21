"""Web search proxy (SearXNG)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.searx import searx_search_sources

router = APIRouter()


class SearchQuery(BaseModel):
    q: str = Field(..., min_length=1)


@router.post("/")
async def search(body: SearchQuery):
    sources, _ = await searx_search_sources(body.q)
    return {"sources": sources}
