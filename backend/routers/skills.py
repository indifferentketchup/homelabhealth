"""Skills API: Library, DAW attachments, URL fetching, SearXNG search."""

from __future__ import annotations

import re
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_owner

router = APIRouter()


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    source_url: str | None = Field(None, max_length=2048)
    raw_content: str = Field(..., min_length=1)
    tags: list[str] | None = Field(None)


class SkillUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    source_url: str | None = Field(None, max_length=2048)
    raw_content: str | None = Field(None, min_length=1)
    tags: list[str] | None = Field(None)


class SkillFetch(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class SkillSearch(BaseModel):
    query: str = Field(..., min_length=1, max_length=255)


class DawSkillAttach(BaseModel):
    skill_id: str = Field(..., min_length=1)
    active: bool | None = True


@router.get("/", response_model=list[dict[str, Any]])
async def list_skills():
    """List all skills in the library."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, description, source_url, tags, created_at, updated_at
            FROM skills
            ORDER BY created_at DESC
            """
        )
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "source_url": row["source_url"],
            "tags": row["tags"] or [],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/", response_model=dict[str, Any])
async def create_skill(payload: SkillCreate):
    """Create a new skill in the library."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO skills (name, description, source_url, raw_content, tags)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, description, source_url, tags, created_at
            """,
            payload.name,
            payload.description,
            payload.source_url,
            payload.raw_content,
            payload.tags if payload.tags is not None else [],
        )
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "tags": row["tags"] or [],
        "created_at": row["created_at"].isoformat(),
    }


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill (cascades to daw_skills)."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "DELETE FROM skills WHERE id = $1 RETURNING id",
            skill_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": str(result)}


@router.post("/fetch-url")
async def fetch_skill_from_url(payload: SkillFetch):
    """Fetch skill content from URL, detecting skills.sh pattern."""
    await require_owner()
    from db import get_pool
    import httpx
    
    url = payload.url
    
    # Detect skills.sh pattern: skills.sh/<owner>/<repo>/<skill>
    match = re.match(r"skills\.sh/([^/]+)/([^/]+)/(.+)", url)
    if match:
        owner, repo, skill_path = match.groups()
        # Convert to raw GitHub URL: raw.githubusercontent.com/<owner>/<repo>/main/<skill_path>/SKILL.md
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{skill_path}/SKILL.md"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.text
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")
    
    # Parse skill metadata from markdown frontmatter or comments
    # Expected format: # Skill Name\nDescription... or <!-- name: X -->\n<!-- description: Y -->
    name = "Untitled Skill"
    description = None
    
    lines = content.split("\n")
    if lines:
        first_line = lines[0].strip()
        if first_line.startswith("# "):
            name = first_line[2:].strip()
        if len(lines) > 1:
            second_line = lines[1].strip()
            if second_line and not second_line.startswith("#"):
                description = second_line
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO skills (name, description, source_url, raw_content)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, description, source_url, created_at
            """,
            name,
            description,
            url,
            content,
        )
    
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "created_at": row["created_at"].isoformat(),
    }


@router.post("/search")
async def search_skills(payload: SkillSearch):
    """Search skills.sh via SearXNG."""
    await require_owner()
    import httpx
    
    query = f"{payload.query} site:skills.sh"
    searxng_url = f"http://100.114.205.53:8888/search?q={query}&format=json"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(searxng_url)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"SearXNG error: {e}")
    
    results = []
    for result in data.get("results", [])[:10]:
        title = result.get("title", "")
        url = result.get("url", "")
        snippet = result.get("content", "")[:200]
        # Extract skill path from URL
        skill_path = url.replace("https://skills.sh/", "").replace("http://skills.sh/", "")
        results.append({
            "title": title,
            "url": url,
            "skill_path": skill_path,
            "snippet": snippet,
            "engine": result.get("engine", "unknown"),
        })
    
    return {"results": results}


@router.get("/daws/{daw_id}", response_model=list[dict[str, Any]])
async def list_daw_skills(daw_id: str):
    """List all skills attached to a DAW (active and inactive)."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.name, s.description, s.source_url, s.tags, ds.active, ds.added_at
            FROM daw_skills ds
            JOIN skills s ON s.id = ds.skill_id
            WHERE ds.daw_id = $1
            ORDER BY ds.added_at DESC
            """,
            daw_id,
        )
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "source_url": row["source_url"],
            "tags": row["tags"] or [],
            "active": row["active"],
            "added_at": row["added_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/daws/{daw_id}", response_model=dict[str, Any])
async def attach_skill_to_daw(daw_id: str, payload: DawSkillAttach):
    """Attach a skill to a DAW."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check skill exists
        skill_exists = await conn.fetchval("SELECT id FROM skills WHERE id = $1", payload.skill_id)
        if not skill_exists:
            raise HTTPException(status_code=404, detail="Skill not found")
        
        # Check DAW exists
        daw_exists = await conn.fetchval("SELECT id FROM daws WHERE id = $1", daw_id)
        if not daw_exists:
            raise HTTPException(status_code=404, detail="DAW not found")
        
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO daw_skills (daw_id, skill_id, active)
                VALUES ($1, $2, $3)
                ON CONFLICT (daw_id, skill_id) DO UPDATE SET active = $3, added_at = NOW()
                RETURNING ds.id, s.name, s.description, s.source_url, s.tags, ds.active
                FROM skills s
                """,
                daw_id,
                payload.skill_id,
                payload.active if payload.active is not None else True,
            )
        except asyncpg.exceptions.UniqueViolation:
            raise HTTPException(status_code=409, detail="Skill already attached to DAW")
    
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "tags": row["tags"] or [],
        "active": row["active"],
    }


@router.delete("/daws/{daw_id}/{skill_id}")
async def detach_skill_from_daw(daw_id: str, skill_id: str):
    """Remove a skill from a DAW."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            DELETE FROM daw_skills 
            WHERE daw_id = $1 AND skill_id = $2 
            RETURNING skill_id
            """,
            daw_id,
            skill_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Skill not attached to this DAW")
    return {"deleted": str(result)}


@router.patch("/daws/{daw_id}/{skill_id}", response_model=dict[str, Any])
async def toggle_daw_skill(daw_id: str, skill_id: str, active: bool | None = None):
    """Toggle active status of a skill on a DAW."""
    await require_owner()
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE daw_skills 
            SET active = COALESCE($3, NOT active)
            WHERE daw_id = $1 AND skill_id = $2
            RETURNING ds.id, s.name, s.description, s.source_url, s.tags, ds.active
            FROM skills s WHERE s.id = ds.skill_id
            """,
            daw_id,
            skill_id,
            active,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Skill not attached to this DAW")
    
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "tags": row["tags"] or [],
        "active": row["active"],
    }
