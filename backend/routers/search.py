"""Web search proxy (SearXNG)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.audit import AuditEventHandle, audit_event
from services.searx import searx_search_sources

router = APIRouter()


class SearchQuery(BaseModel):
    q: str = Field(..., min_length=1)


@router.post("/")
async def search(
    body: SearchQuery,
    audit: AuditEventHandle = Depends(audit_event),
):
    sources, _ = await searx_search_sources(body.q)
    async with audit.targeting("search", None):
        pass
    return {"sources": sources}
