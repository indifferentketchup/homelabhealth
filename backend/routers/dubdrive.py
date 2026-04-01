"""Proxy to DubDrive file API (Tailscale / optional bearer token)."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from auth_deps import get_principal

router = APIRouter()

_DEFAULT_DUBDRIVE_URL = "http://100.114.205.53:9200"


def _dubdrive_base_url() -> str:
    raw = (os.environ.get("DUBDRIVE_URL") or "").strip().rstrip("/")
    if raw:
        return raw
    return _DEFAULT_DUBDRIVE_URL.rstrip("/")


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
    cookies: dict[str, str] = {}
    if token:
        cookies["dubdrive_token"] = token
    url = f"{base}/api/ls"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params={"path": path}, headers={}, cookies=cookies)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="dubdrive_unreachable") from None
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
    cookies: dict[str, str] = {}
    if token:
        cookies["dubdrive_token"] = token
    url = f"{base}/api/read"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params={"path": path}, headers={}, cookies=cookies)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="dubdrive_unreachable") from None
    ct = r.headers.get("content-type")
    return Response(content=r.content, status_code=r.status_code, media_type=ct)


@router.get("/preview")
async def dubdrive_preview(
    path: str = Query(..., min_length=1),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")

    base = _dubdrive_base_url()
    token = (os.environ.get("DUBDRIVE_TOKEN") or "").strip()
    cookies: dict[str, str] = {}
    if token:
        cookies["dubdrive_token"] = token

    url = f"{base}/api/raw"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url, params={"path": path}, cookies=cookies)
    except httpx.RequestError:
        raise HTTPException(502, "dubdrive_unreachable")

    if r.status_code != 200:
        raise HTTPException(r.status_code, "dubdrive_error")

    content_type = (r.headers.get("content-type") or "").lower().split(";")[0].strip()
    raw = r.content
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""

    if content_type == "application/pdf" or ext == "pdf":
        from services.chunking import parse_pdf

        text = parse_pdf(raw)
    elif (
        content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or ext == "docx"
    ):
        from services.chunking import parse_docx

        text = parse_docx(raw)
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")

    return JSONResponse({"text": text, "ext": ext})
