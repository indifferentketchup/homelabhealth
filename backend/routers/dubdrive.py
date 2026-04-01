"""Proxy to DubDrive file API (Tailscale / optional bearer token)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from auth_deps import get_principal
from services import dubdrive_auth

router = APIRouter()


async def _proxy_get(api_path: str, params: dict, raw: bool = False):
    """Proxy a GET to DubDrive with auto-reauth on 401."""
    base = dubdrive_auth._dubdrive_base_url()
    url = f"{base}{api_path}"

    token = await dubdrive_auth.get_token()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url, params=params, cookies=dubdrive_auth.get_cookies(token))
    except httpx.RequestError:
        raise HTTPException(502, "dubdrive_unreachable")

    if r.status_code == 401:
        # Token expired — re-login and retry once
        try:
            token = await dubdrive_auth.invalidate_and_relogin()
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(url, params=params, cookies=dubdrive_auth.get_cookies(token))
        except httpx.RequestError:
            raise HTTPException(502, "dubdrive_unreachable")

    if raw:
        return r  # caller handles content

    ct = r.headers.get("content-type")
    return Response(content=r.content, status_code=r.status_code, media_type=ct)


@router.get("/ls")
async def dubdrive_ls(
    path: str = Query("", description="Directory path for DubDrive /api/ls"),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    return await _proxy_get("/api/ls", {"path": path})


@router.get("/read")
async def dubdrive_read(
    path: str = Query(..., min_length=1),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    return await _proxy_get("/api/read", {"path": path})


@router.get("/preview")
async def dubdrive_preview(
    path: str = Query(..., min_length=1),
    principal: dict = Depends(get_principal),
) -> Response:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")

    resp = await _proxy_get("/api/raw", {"path": path}, raw=True)
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "dubdrive_error")

    content_type = (resp.headers.get("content-type") or "").lower().split(";")[0].strip()
    raw = resp.content
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
