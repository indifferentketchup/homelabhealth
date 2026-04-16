"""Context files attached to project DAWs (`daw_context_files`)."""

from __future__ import annotations

import io
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

from auth_deps import get_principal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db import get_pool

router = APIRouter()

UPLOAD_DIR = Path("/data/uploads/context_files")
TEXT_EXT = {".txt", ".md"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
BINARY_PLACEHOLDER = "[Binary file — content not extractable]"


def _preview(content: str, n: int = 200) -> str:
    s = re.sub(r"\s+", " ", (content or "").strip())
    return s[:n] if len(s) <= n else s[:n]


def _extract_text(filename: str, raw: bytes) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in TEXT_EXT:
        return raw.decode("utf-8", errors="replace")
    if ext in PDF_EXT:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise HTTPException(status_code=500, detail="pypdf is not installed") from e
        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
        return "\n".join(parts).strip() or BINARY_PLACEHOLDER
    if ext in DOCX_EXT:
        try:
            import docx
        except ImportError as e:
            raise HTTPException(status_code=500, detail="python-docx is not installed") from e
        d = docx.Document(io.BytesIO(raw))
        paras = [p.text for p in d.paragraphs if p.text]
        return "\n".join(paras).strip() or BINARY_PLACEHOLDER
    return BINARY_PLACEHOLDER


def _list_file_path(file_id: uuid.UUID) -> Path | None:
    if not UPLOAD_DIR.is_dir():
        return None
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    return matches[0] if matches else None


def _delete_stored_file(file_id: uuid.UUID) -> None:
    p = _list_file_path(file_id)
    if p and p.is_file():
        try:
            p.unlink()
        except OSError:
            pass


def _row_list(r: Any) -> dict[str, Any]:
    content = r["content"] or ""
    return {
        "id": str(r["id"]),
        "daw_id": str(r["daw_id"]),
        "filename": r["filename"],
        "content_preview": _preview(content),
        "file_url": f"/api/daw-context-files/{r['id']}/download",
        "embeddable": bool(r["embeddable"]),
        "sort_order": int(r["sort_order"] or 0),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


class DawContextFilePatch(BaseModel):
    embeddable: bool | None = None
    sort_order: int | None = None


@router.get("/")
async def list_context_files(
    daw_id: uuid.UUID = Query(...),
    _: dict = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if not daw_exists:
            raise HTTPException(status_code=404, detail="DAW not found")
        rows = await conn.fetch(
            """
            SELECT id, daw_id, filename, content, file_url, embeddable, sort_order, created_at
            FROM daw_context_files
            WHERE daw_id = $1::uuid
            ORDER BY sort_order ASC NULLS LAST, created_at ASC
            """,
            daw_id,
        )
    return [_row_list(r) for r in rows]


def _parse_embeddable(raw: str | None) -> bool:
    if raw is None or raw == "":
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


@router.post("/")
async def upload_context_file(
    daw_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    embeddable: str | None = Form("false"),
    _: dict = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if not daw_exists:
            raise HTTPException(status_code=404, detail="DAW not found")

    orig = (file.filename or "upload").strip() or "upload"
    ext = Path(orig).suffix.lower() or ".bin"
    raw = await file.read()
    content = _extract_text(orig, raw)

    file_id = uuid.uuid4()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{file_id}{ext}"
    dest.write_bytes(raw)

    emb = _parse_embeddable(embeddable)
    file_url = f"/api/daw-context-files/{file_id}/download"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO daw_context_files (id, daw_id, filename, content, file_url, embeddable, sort_order)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, 0)
            RETURNING id, daw_id, filename, content, file_url, embeddable, sort_order, created_at
            """,
            file_id,
            daw_id,
            orig,
            content,
            file_url,
            emb,
        )
    return _row_list(row)


@router.patch("/{file_id}")
async def patch_context_file(
    file_id: uuid.UUID,
    body: DawContextFilePatch,
    _: dict = Depends(get_principal),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, daw_id, filename, content, file_url, embeddable, sort_order, created_at
            FROM daw_context_files WHERE id = $1::uuid
            """,
            file_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Context file not found")
        if not data:
            return _row_list(row)
        new_emb = data.get("embeddable", row["embeddable"])
        new_sort = data.get("sort_order", row["sort_order"])
        updated = await conn.fetchrow(
            """
            UPDATE daw_context_files
            SET embeddable = $2, sort_order = $3
            WHERE id = $1::uuid
            RETURNING id, daw_id, filename, content, file_url, embeddable, sort_order, created_at
            """,
            file_id,
            new_emb,
            new_sort,
        )
    return _row_list(updated)


@router.delete("/{file_id}")
async def delete_context_file(file_id: uuid.UUID, _: dict = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT daw_id FROM daw_context_files WHERE id = $1::uuid",
            file_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Context file not found")
    _delete_stored_file(file_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM daw_context_files WHERE id = $1::uuid",
            file_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Context file not found")
    return {"ok": True}


@router.get("/{file_id}/download")
async def download_context_file(
    file_id: uuid.UUID,
    _: dict = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT daw_id FROM daw_context_files WHERE id = $1::uuid",
            file_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="File not found")
    path = _list_file_path(file_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        str(path),
        filename=path.name,
        media_type=media_type or "application/octet-stream",
    )
