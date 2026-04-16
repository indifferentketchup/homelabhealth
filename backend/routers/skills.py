"""Skills API: Library, DAW attachments, URL fetching, SearXNG search."""

import ipaddress
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_deps import require_owner

_BLOCKED_HOSTS = {"localhost", "boolab_db", "boolab_api", "boolab_ui", "booops_ui", "notes808_ui"}


def _assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL must use http or https")
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail="URL host is not allowed")
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(host))
    except (socket.gaierror, ValueError):
        raise HTTPException(status_code=400, detail="URL host could not be resolved")
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        raise HTTPException(status_code=400, detail="URL host resolves to a non-public address")

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


@router.get("", response_model=list[dict[str, Any]])
async def list_skills(principal: dict[str, Any] = Depends(require_owner)):
    """List all skills in the library."""
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


@router.post("", response_model=dict[str, Any])
async def create_skill(payload: SkillCreate, principal: dict[str, Any] = Depends(require_owner)):
    """Create a new skill in the library."""
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
async def delete_skill(skill_id: str, principal: dict[str, Any] = Depends(require_owner)):
    """Delete a skill (cascades to daw_skills)."""
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "DELETE FROM skills WHERE id = $1::uuid RETURNING id",
            skill_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": str(result)}


@router.post("/fetch-url")
async def fetch_skill_from_url(payload: SkillFetch, principal: dict[str, Any] = Depends(require_owner)):
    """Fetch skill content from URL, detecting skills.sh pattern. Returns parsed content without saving."""
    import httpx
    
    url = payload.url.strip()
    if not re.match(r"^https?://", url):
        url = f"https://{url}"

    # Detect skills.sh pattern: https://skills.sh/<owner>/<repo>/<skill>
    match = re.match(r"^https?://skills\.sh/([^/]+)/([^/]+)/(.+)$", url)
    if match:
        owner, repo, skill_path = match.groups()
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{skill_path}/SKILL.md"

    _assert_safe_url(url)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
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
    
    return {
        "name": name,
        "description": description,
        "raw_content": content,
        "source_url": url,
    }


@router.post("/search")
async def search_skills(payload: SkillSearch, principal: dict[str, Any] = Depends(require_owner)):
    """Search skills.sh via SearXNG."""
    import httpx

    base = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")
    params = {"q": f"{payload.query} site:skills.sh", "format": "json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{base}/search", params=params)
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
async def list_daw_skills(daw_id: str, principal: dict[str, Any] = Depends(require_owner)):
    """List all skills attached to a DAW (active and inactive)."""
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.name, s.description, s.source_url, s.tags, ds.active, ds.added_at
            FROM daw_skills ds
            JOIN skills s ON s.id = ds.skill_id
            WHERE ds.daw_id = $1::uuid
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
async def attach_skill_to_daw(daw_id: str, payload: DawSkillAttach, principal: dict[str, Any] = Depends(require_owner)):
    """Attach a skill to a DAW."""
    from db import get_pool
    pool = await get_pool()
    active = payload.active if payload.active is not None else True
    async with pool.acquire() as conn:
        skill_exists = await conn.fetchval(
            "SELECT id FROM skills WHERE id = $1::uuid", payload.skill_id
        )
        if not skill_exists:
            raise HTTPException(status_code=404, detail="Skill not found")

        daw_exists = await conn.fetchval(
            "SELECT id FROM daws WHERE id = $1::uuid", daw_id
        )
        if not daw_exists:
            raise HTTPException(status_code=404, detail="DAW not found")

        await conn.execute(
            """
            INSERT INTO daw_skills (daw_id, skill_id, active)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (daw_id, skill_id) DO UPDATE SET active = EXCLUDED.active, added_at = NOW()
            """,
            daw_id,
            payload.skill_id,
            active,
        )

        row = await conn.fetchrow(
            """
            SELECT s.id, s.name, s.description, s.source_url, s.tags, ds.active
            FROM daw_skills ds
            JOIN skills s ON s.id = ds.skill_id
            WHERE ds.daw_id = $1::uuid AND ds.skill_id = $2::uuid
            """,
            daw_id,
            payload.skill_id,
        )

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "tags": row["tags"] or [],
        "active": row["active"],
    }


@router.delete("/daws/{daw_id}/{skill_id}")
async def detach_skill_from_daw(daw_id: str, skill_id: str, principal: dict[str, Any] = Depends(require_owner)):
    """Remove a skill from a DAW."""
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            DELETE FROM daw_skills
            WHERE daw_id = $1::uuid AND skill_id = $2::uuid
            RETURNING skill_id
            """,
            daw_id,
            skill_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Skill not attached to this DAW")
    return {"deleted": str(result)}


@router.patch("/daws/{daw_id}/{skill_id}", response_model=dict[str, Any])
async def toggle_daw_skill(daw_id: str, skill_id: str, active: bool | None = None, principal: dict[str, Any] = Depends(require_owner)):
    """Toggle active status of a skill on a DAW."""
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE daw_skills
            SET active = COALESCE($3, NOT active)
            WHERE daw_id = $1::uuid AND skill_id = $2::uuid
            RETURNING active
            """,
            daw_id,
            skill_id,
            active,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Skill not attached to this DAW")

        row = await conn.fetchrow(
            """
            SELECT s.id, s.name, s.description, s.source_url, s.tags, ds.active
            FROM daw_skills ds
            JOIN skills s ON s.id = ds.skill_id
            WHERE ds.daw_id = $1::uuid AND ds.skill_id = $2::uuid
            """,
            daw_id,
            skill_id,
        )

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "source_url": row["source_url"],
        "tags": row["tags"] or [],
        "active": row["active"],
    }
