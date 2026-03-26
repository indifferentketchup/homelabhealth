"""Web search proxy (SearXNG)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.searx import searx_search_sources

router = APIRouter()


class SearchQuery(BaseModel):
    q: str = Field(..., min_length=1)
    mode: str | None = Field(default="booops", description="booops | 808notes — SearXNG prefs from DB")


@router.post("/")
async def search(body: SearchQuery):
    m = (body.mode or "booops").strip().lower()
    if m not in ("booops", "808notes"):
        m = "booops"
    sources, _ = await searx_search_sources(body.q, mode=m)
    return {"sources": sources}
