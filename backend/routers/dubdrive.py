"""Proxy to DubDrive file API (Tailscale / optional bearer token)."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from auth_deps import get_principal

router = APIRouter()


def _dubdrive_base_url() -> str:
    raw = (os.environ.get("DUBDRIVE_URL") or "").strip().rstrip("/")
    if not raw:
        raise HTTPException(status_code=503, detail="dubdrive_not_configured")
    return raw


@router.get("/ls")
async def dubdrive_ls(
    path: str = Query("", description="Directory path for DubDrive /api/ls"),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    base = _dubdrive_base_url()
    token = (os.environ.get("DUBDRIVE_TOKEN") or "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base}/api/ls"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        try:
            r = await client.get(url, params={"path": path}, headers=headers)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"dubdrive_upstream_error: {e}") from e
    ct = r.headers.get("content-type")
    return Response(content=r.content, status_code=r.status_code, media_type=ct)


@router.get("/read")
async def dubdrive_read(
    path: str = Query(..., min_length=1, description="File path for DubDrive /api/read"),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    base = _dubdrive_base_url()
    token = (os.environ.get("DUBDRIVE_TOKEN") or "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base}/api/read"
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        try:
            r = await client.get(url, params={"path": path}, headers=headers)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"dubdrive_upstream_error: {e}") from e
    ct = r.headers.get("content-type")
    return Response(content=r.content, status_code=r.status_code, media_type=ct)
