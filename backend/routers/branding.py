"""Branding config (`branding_config` table)."""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from deps import _SCHEMA_MODE_VALUE, require_admin
from db import get_pool

router = APIRouter()

BRANDING_ASSETS_DIR = Path("/data/branding/assets")
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
ASSET_SLOTS = frozenset({"banner", "logo", "favicon", "icon", "og_banner"})

_LIBRARY_STEM_SAFE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

DEFAULT_BRANDING: dict[str, Any] = {
    "accentColor": "#7c3aed",
    "accentCyan": "#c084fc",
    "accentPurple": "#e879f9",
    "bgColor": "#080808",
    "bgPanel": "#0f0a1a",
    "bgCard": "#130d20",
    "textColor": "#f0f0f0",
    "textDim": "#9d8fbb",
    "borderColor": "#1e1530",
    "fontFamily": "Rajdhani, sans-serif",
    "fontSizeBase": 15,
    "baseFontSize": 15,
    "fsNav": 13,
    "fsChat": 15,
    "fsInput": 14,
    "fsHeading": 18,
    "fsCode": 13,
    "chatMaxWidth": 850,
    "sidebarWidth": 280,
    "title": "Workspace",
    "subtitle": "// pick your desk. open a workspace.",
    "bannerUrl": "",
    "logoUrl": "",
    "faviconUrl": "",
    "ogBannerUrl": "",
    "appGlyphIcon": "Music2",
}


def _ensure_assets_dir() -> None:
    BRANDING_ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _config_as_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        return json.loads(raw)
    return {}


def _main_branding_flat_key_for_slot(slot: str) -> str:
    """Map asset slot to top-level branding JSON key (`icon` and `favicon` both -> `faviconUrl`)."""
    if slot == "banner":
        return "bannerUrl"
    if slot == "logo":
        return "logoUrl"
    if slot in ("favicon", "icon"):
        return "faviconUrl"
    if slot == "og_banner":
        return "ogBannerUrl"
    raise HTTPException(status_code=400, detail="invalid slot")


def _asset_path_pattern(slot: str) -> str:
    return f"{_SCHEMA_MODE_VALUE}_{slot}.*"


def _find_asset_file(slot: str) -> Path | None:
    _ensure_assets_dir()
    matches = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern(slot)))
    if matches:
        return matches[0]
    if slot == "favicon":
        alt = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern("icon")))
        return alt[0] if alt else None
    if slot == "icon":
        alt = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern("favicon")))
        return alt[0] if alt else None
    return None


def _delete_existing_asset_files(slot: str) -> None:
    _ensure_assets_dir()
    for p in BRANDING_ASSETS_DIR.glob(_asset_path_pattern(slot)):
        p.unlink(missing_ok=True)


async def _persist_branding_patch(patch: dict[str, Any]) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = $1",
            _SCHEMA_MODE_VALUE,
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ($1, $2::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            _SCHEMA_MODE_VALUE,
            json.dumps(merged_stored),
        )
    return merged_stored


@router.get("/")
async def get_branding():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = $1",
            _SCHEMA_MODE_VALUE,
        )
    current = _config_as_dict(row["config"]) if row else {}
    return {**DEFAULT_BRANDING, **current}


@router.put("/")
@router.patch("/")
async def patch_branding(
    patch: dict[str, Any] = Body(default_factory=dict),
    _owner: dict = Depends(require_admin),
):
    return await _persist_branding_patch(patch)


@router.post("/upload/{slot}")
async def upload_branding_asset(
    slot: str,
    file: UploadFile = File(...),
    _owner: dict = Depends(require_admin),
):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMG_EXT:
        raise HTTPException(status_code=400, detail="invalid image type")

    _ensure_assets_dir()
    _delete_existing_asset_files(slot)

    dest = BRANDING_ASSETS_DIR / f"{_SCHEMA_MODE_VALUE}_{slot}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    public_url = f"/api/branding/asset/{slot}"
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_branding_patch({key: public_url})
    return {key: public_url}


@router.api_route("/asset/{slot}", methods=["GET", "HEAD"])
async def get_branding_asset(slot: str):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    path = _find_asset_file(slot)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(path))
    if not media_type:
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "none"})


@router.delete("/asset/{slot}")
async def delete_branding_asset(slot: str, _owner: dict = Depends(require_admin)):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    _ensure_assets_dir()
    _delete_existing_asset_files(slot)
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_branding_patch({key: ""})
    return {"ok": True}


@router.api_route("/persona/asset/{stem}", methods=["GET", "HEAD"])
async def get_persona_asset(stem: str):
    if not _LIBRARY_STEM_SAFE.match(stem):
        raise HTTPException(status_code=400, detail="invalid stem")
    path = BRANDING_ASSETS_DIR / f"persona_{stem}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/png", headers={"Accept-Ranges": "none"})


@router.get("/assets/library")
async def list_asset_library():
    """All committed default assets under `backend/assets/` (for pickers)."""
    _ensure_assets_dir()
    src = Path(__file__).resolve().parent.parent / "assets"
    library: dict[str, list[str]] = {}
    if not src.is_dir():
        return library
    for mode_dir in sorted(src.iterdir()):
        if not mode_dir.is_dir():
            continue
        library[mode_dir.name] = [
            f"/api/branding/assets/library/{mode_dir.name}/{f.name}"
            for f in sorted(mode_dir.iterdir())
            if f.is_file() and f.suffix.lower() in ALLOWED_IMG_EXT
        ]
    return library


@router.get("/assets/library/{mode}/{filename}")
async def serve_library_asset(mode: str, filename: str):
    if "/" in mode or "\\" in mode or ".." in mode:
        raise HTTPException(status_code=400, detail="invalid mode")
    if not _LIBRARY_STEM_SAFE.match(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    base = (Path(__file__).resolve().parent.parent / "assets" / mode).resolve()
    src = (base / filename).resolve()
    try:
        src.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not src.is_file() or src.suffix.lower() not in ALLOWED_IMG_EXT:
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(src))
    return FileResponse(src, media_type=media_type or "application/octet-stream")
