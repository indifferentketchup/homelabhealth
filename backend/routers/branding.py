"""BooOps branding config (`branding_config` table, mode `booops`)."""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from auth_deps import require_admin
from db import get_pool

router = APIRouter()

BRANDING_ASSETS_DIR = Path("/data/branding/assets")
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
CARD_ICON_SLOTS = frozenset({"cardBooops", "card808notes"})
ASSET_SLOTS = frozenset({"banner", "logo", "favicon", "icon", "og_banner"}) | CARD_ICON_SLOTS

_LIBRARY_STEM_SAFE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

DEFAULT_BOOOPS_BRANDING: dict[str, Any] = {
    "accentColor": "#ff2d78",
    "accentCyan": "#00e5ff",
    "accentPurple": "#9b5de5",
    "bgColor": "#080b14",
    "bgPanel": "#0d1120",
    "bgCard": "#0f1525",
    "textColor": "#cde0ff",
    "textDim": "#5a7a9e",
    "borderColor": "#1e2d50",
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
    "appGlyphIcon": "Bot",
    "bannerUrl": "",
    "logoUrl": "",
    "faviconUrl": "",
    "ogBannerUrl": "",
}

DEFAULT_808NOTES_BRANDING: dict[str, Any] = {
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
    "title": "808notes",
    "subtitle": "// pick your desk. open a daw workspace.",
    "bannerUrl": "",
    "logoUrl": "",
    "faviconUrl": "",
    "ogBannerUrl": "",
    "appGlyphIcon": "Music2",
}

DEFAULT_BOOCODE_BRANDING: dict[str, Any] = {
    "accentColor": "#f97316",
    "accentCyan": "#fbbf24",
    "accentPurple": "#c2410c",
    "bgColor": "#0a0604",
    "bgPanel": "#120a06",
    "bgCard": "#1a0e08",
    "textColor": "#f5e6d3",
    "textDim": "#9a7a5a",
    "borderColor": "#3a1f0c",
    "fontFamily": "JetBrains Mono, monospace",
    "fontSizeBase": 15,
    "baseFontSize": 15,
    "fsNav": 13,
    "fsChat": 15,
    "fsInput": 14,
    "fsHeading": 18,
    "fsCode": 13,
    "chatMaxWidth": 1200,
    "sidebarWidth": 260,
    "title": "BooCode",
    "subtitle": "// architect at 3am. terminal amber, code awareness.",
    "bannerUrl": "",
    "logoUrl": "",
    "faviconUrl": "",
    "ogBannerUrl": "",
    "appGlyphIcon": "Terminal",
}

DEFAULT_BOOLAB_BRANDING: dict[str, Any] = {
    "title": "BooLab",
    "tagline": "// pick your lab bench.",
    "hubDisplayFont": "JetBrains Mono",
    "hubMonoFont": "Share Tech Mono",
    "accentColor": "#5dcf8f",
    "bgColor": "#050807",
    "bgPanel": "#0a100c",
    "bgCard": "#0d1510",
    "textColor": "rgba(200, 230, 210, 0.92)",
    "textDim": "rgba(120, 160, 140, 0.65)",
    "borderColor": "rgba(93, 207, 143, 0.18)",
    "bannerUrl": "",
    "logoUrl": "",
    "faviconUrl": "",
    "ogBannerUrl": "",
    "appGlyphIcon": "FlaskConical",
    "booopsCard": {
        "icon": "Bot",
        "iconUrl": "",
        "iconSize": 44,
        "accent": "#4ade80",
        "title": "BooOps",
        "description": "LLM chat — personas, DAWs, memory.",
    },
    "notes808Card": {
        "icon": "Music2",
        "iconUrl": "",
        "iconSize": 44,
        "accent": "#34d399",
        "title": "808notes",
        "description": "Music notes, sources, and project context.",
    },
    "hubCardsTextAlign": "center",
    "hubCardsFontScale": 1.0,
    # Hero title, tagline, section labels, footer (~0.75–1.5).
    "hubLandingFontScale": 1.0,
    # Hero logo tile + glyph, hub card icons (~0.75–1.35).
    "hubLandingIconScale": 1.0,
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
    """Map asset slot to top-level branding JSON key (`icon` and `favicon` both → `faviconUrl`)."""
    if slot == "banner":
        return "bannerUrl"
    if slot == "logo":
        return "logoUrl"
    if slot in ("favicon", "icon"):
        return "faviconUrl"
    if slot == "og_banner":
        return "ogBannerUrl"
    raise HTTPException(status_code=400, detail="invalid slot")


_PREFIX_BOOOPS = "booops"
_PREFIX_808NOTES = "808notes"
_PREFIX_BOOLAB = "boolab"
_PREFIX_BOOCODE = "boocode"


def _asset_path_pattern(prefix: str, slot: str) -> str:
    return f"{prefix}_{slot}.*"


def _find_asset_file(prefix: str, slot: str) -> Path | None:
    _ensure_assets_dir()
    matches = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern(prefix, slot)))
    if matches:
        return matches[0]
    if slot == "favicon":
        alt = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern(prefix, "icon")))
        return alt[0] if alt else None
    if slot == "icon":
        alt = sorted(BRANDING_ASSETS_DIR.glob(_asset_path_pattern(prefix, "favicon")))
        return alt[0] if alt else None
    return None


def _delete_existing_asset_files(prefix: str, slot: str) -> None:
    _ensure_assets_dir()
    for p in BRANDING_ASSETS_DIR.glob(_asset_path_pattern(prefix, slot)):
        p.unlink(missing_ok=True)


async def _persist_booops_patch(patch: dict[str, Any]) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'booops'",
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_BOOOPS_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ('booops', $1::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            json.dumps(merged_stored),
        )
    return merged_stored


async def _persist_808notes_patch(patch: dict[str, Any]) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = '808notes'",
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_808NOTES_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ('808notes', $1::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            json.dumps(merged_stored),
        )
    return merged_stored


async def _persist_boocode_patch(patch: dict[str, Any]) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'boocode'",
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_BOOCODE_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ('boocode', $1::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            json.dumps(merged_stored),
        )
    return merged_stored


def _card_key_for_icon_slot(slot: str) -> str:
    if slot == "cardBooops":
        return "booopsCard"
    if slot == "card808notes":
        return "notes808Card"
    raise ValueError("invalid card icon slot")


async def _persist_boolab_patch(patch: dict[str, Any]) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'boolab'",
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_BOOLAB_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ('boolab', $1::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            json.dumps(merged_stored),
        )
    return merged_stored


def _merge_boolab_response(current: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge defaults + DB; nested card dicts replaced entirely from stored JSON."""
    base = {**DEFAULT_BOOLAB_BRANDING, **current}
    for key in ("booopsCard", "notes808Card"):
        if isinstance(current.get(key), dict):
            merged_card = {**(DEFAULT_BOOLAB_BRANDING.get(key) or {}), **current[key]}
            base[key] = merged_card
    return base


@router.get("/booops")
async def get_branding_booops():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'booops'",
        )
    current = _config_as_dict(row["config"]) if row else {}
    return {**DEFAULT_BOOOPS_BRANDING, **current}


@router.get("/808notes")
async def get_branding_808notes():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = '808notes'",
        )
    current = _config_as_dict(row["config"]) if row else {}
    return {**DEFAULT_808NOTES_BRANDING, **current}


@router.get("/boolab")
async def get_branding_boolab():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'boolab'",
        )
    current = _config_as_dict(row["config"]) if row else {}
    return _merge_boolab_response(current)


@router.put("/booops")
async def put_branding(
    patch: dict[str, Any] = Body(default_factory=dict),
    _owner: dict = Depends(require_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'booops'",
        )
        current = _config_as_dict(row["config"]) if row else {}
        merged_stored = {**DEFAULT_BOOOPS_BRANDING, **current, **patch}
        await conn.execute(
            """INSERT INTO branding_config (mode, config) VALUES ('booops', $1::jsonb)
               ON CONFLICT (mode) DO UPDATE SET config = EXCLUDED.config""",
            json.dumps(merged_stored),
        )
    return merged_stored


@router.put("/808notes")
@router.patch("/808notes")
async def patch_branding_808notes(
    patch: dict[str, Any] = Body(default_factory=dict),
    _owner: dict = Depends(require_admin),
):
    return await _persist_808notes_patch(patch)


@router.put("/boolab")
@router.patch("/boolab")
async def patch_branding_boolab(
    patch: dict[str, Any] = Body(default_factory=dict),
    _owner: dict = Depends(require_admin),
):
    merged = await _persist_boolab_patch(patch)
    return _merge_boolab_response(merged)


@router.post("/booops/upload/{slot}")
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
    _delete_existing_asset_files(_PREFIX_BOOOPS, slot)

    dest = BRANDING_ASSETS_DIR / f"{_PREFIX_BOOOPS}_{slot}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    public_url = f"/api/branding/booops/asset/{slot}"
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_booops_patch({key: public_url})
    return {key: public_url}


@router.post("/808notes/upload/{slot}")
async def upload_branding_asset_808notes(
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
    _delete_existing_asset_files(_PREFIX_808NOTES, slot)

    dest = BRANDING_ASSETS_DIR / f"{_PREFIX_808NOTES}_{slot}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    public_url = f"/api/branding/808notes/asset/{slot}"
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_808notes_patch({key: public_url})
    return {key: public_url}


@router.post("/boolab/upload/{slot}")
async def upload_branding_asset_boolab(
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
    _delete_existing_asset_files(_PREFIX_BOOLAB, slot)

    dest = BRANDING_ASSETS_DIR / f"{_PREFIX_BOOLAB}_{slot}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    public_url = f"/api/branding/boolab/asset/{slot}"
    if slot in CARD_ICON_SLOTS:
        card_key = _card_key_for_icon_slot(slot)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config FROM branding_config WHERE mode = 'boolab'",
            )
        raw = _config_as_dict(row["config"]) if row else {}
        current = _merge_boolab_response(raw)
        prev_card = current.get(card_key) if isinstance(current.get(card_key), dict) else {}
        base_def = DEFAULT_BOOLAB_BRANDING.get(card_key) or {}
        merged_card = {
            **(base_def if isinstance(base_def, dict) else {}),
            **prev_card,
            "iconUrl": public_url,
        }
        await _persist_boolab_patch({card_key: merged_card})
        return {card_key: merged_card}

    key = _main_branding_flat_key_for_slot(slot)
    await _persist_boolab_patch({key: public_url})
    return {key: public_url}


@router.api_route("/booops/asset/{slot}", methods=["GET", "HEAD"])
async def get_branding_asset(slot: str):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    path = _find_asset_file(_PREFIX_BOOOPS, slot)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(path))
    if not media_type:
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "none"})


@router.api_route("/808notes/asset/{slot}", methods=["GET", "HEAD"])
async def get_branding_asset_808notes(slot: str):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    path = _find_asset_file(_PREFIX_808NOTES, slot)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(path))
    if not media_type:
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "none"})


@router.api_route("/boolab/asset/{slot}", methods=["GET", "HEAD"])
async def get_branding_asset_boolab(slot: str):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    path = _find_asset_file(_PREFIX_BOOLAB, slot)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(path))
    if not media_type:
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "none"})


@router.delete("/booops/asset/{slot}")
async def delete_branding_asset(slot: str, _owner: dict = Depends(require_admin)):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    _ensure_assets_dir()
    _delete_existing_asset_files(_PREFIX_BOOOPS, slot)
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_booops_patch({key: ""})
    return {"ok": True}


@router.delete("/808notes/asset/{slot}")
async def delete_branding_asset_808notes(slot: str, _owner: dict = Depends(require_admin)):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    _ensure_assets_dir()
    _delete_existing_asset_files(_PREFIX_808NOTES, slot)
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_808notes_patch({key: ""})
    return {"ok": True}


@router.get("/boocode")
async def get_branding_boocode():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM branding_config WHERE mode = 'boocode'",
        )
    current = _config_as_dict(row["config"]) if row else {}
    return {**DEFAULT_BOOCODE_BRANDING, **current}


@router.put("/boocode")
@router.patch("/boocode")
async def patch_branding_boocode(
    patch: dict[str, Any] = Body(default_factory=dict),
    _owner: dict = Depends(require_admin),
):
    return await _persist_boocode_patch(patch)


@router.post("/boocode/upload/{slot}")
async def upload_branding_asset_boocode(
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
    _delete_existing_asset_files(_PREFIX_BOOCODE, slot)

    dest = BRANDING_ASSETS_DIR / f"{_PREFIX_BOOCODE}_{slot}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    public_url = f"/api/branding/boocode/asset/{slot}"
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_boocode_patch({key: public_url})
    return {key: public_url}


@router.api_route("/boocode/asset/{slot}", methods=["GET", "HEAD"])
async def get_branding_asset_boocode(slot: str):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    path = _find_asset_file(_PREFIX_BOOCODE, slot)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(path))
    if not media_type:
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "none"})


@router.delete("/boocode/asset/{slot}")
async def delete_branding_asset_boocode(slot: str, _owner: dict = Depends(require_admin)):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    _ensure_assets_dir()
    _delete_existing_asset_files(_PREFIX_BOOCODE, slot)
    key = _main_branding_flat_key_for_slot(slot)
    await _persist_boocode_patch({key: ""})
    return {"ok": True}


@router.delete("/boolab/asset/{slot}")
async def delete_branding_asset_boolab(slot: str, _owner: dict = Depends(require_admin)):
    if slot not in ASSET_SLOTS:
        raise HTTPException(status_code=400, detail="invalid slot")
    _ensure_assets_dir()
    _delete_existing_asset_files(_PREFIX_BOOLAB, slot)
    if slot in CARD_ICON_SLOTS:
        card_key = _card_key_for_icon_slot(slot)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config FROM branding_config WHERE mode = 'boolab'",
            )
        raw = _config_as_dict(row["config"]) if row else {}
        current = _merge_boolab_response(raw)
        prev_card = current.get(card_key) if isinstance(current.get(card_key), dict) else {}
        base_def = DEFAULT_BOOLAB_BRANDING.get(card_key) or {}
        merged_card = {**(base_def if isinstance(base_def, dict) else {}), **prev_card, "iconUrl": ""}
        await _persist_boolab_patch({card_key: merged_card})
        return {"ok": True}

    key = _main_branding_flat_key_for_slot(slot)
    await _persist_boolab_patch({key: ""})
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
