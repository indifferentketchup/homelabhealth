"""Seed committed default branding + persona assets from `backend/assets/` on startup."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from db import get_pool, personas_has_mode_column, personas_table_columns
from routers.branding import (
    BRANDING_ASSETS_DIR,
    _config_as_dict,
    _ensure_assets_dir,
    _persist_808notes_patch,
    _persist_boolab_patch,
    _persist_booops_patch,
)

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent
_ASSETS_ROOT = _BACKEND_ROOT / "assets"

_BRANDING_MODES = ("booops", "808notes", "boolab")
_FILE_SLOTS = ("banner", "logo", "icon", "og-banner")

# Explicit slot → branding config keys (not derived from slot names).
_SLOT_TO_CONFIG_KEY: dict[str, str] = {
    "banner": "bannerUrl",
    "logo": "logoUrl",
    "icon": "faviconUrl",
    "og-banner": "ogBannerUrl",
}

_PERSIST_BY_MODE: dict[str, Any] = {
    "booops": _persist_booops_patch,
    "808notes": _persist_808notes_patch,
    "boolab": _persist_boolab_patch,
}

_STEM_SAFE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _emptyish_url(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


async def _seed_branding() -> None:
    pool = await get_pool()
    for mode in _BRANDING_MODES:
        persist = _PERSIST_BY_MODE[mode]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config FROM branding_config WHERE mode = $1::text",
                mode,
            )
        current = _config_as_dict(row["config"]) if row else {}
        patch: dict[str, str] = {}
        for slot in _FILE_SLOTS:
            key = _SLOT_TO_CONFIG_KEY[slot]
            if not _emptyish_url(current.get(key)):
                continue
            src = _ASSETS_ROOT / mode / f"{slot}.png"
            if not src.is_file():
                logger.warning("Branding seed: missing repo asset %s", src)
                continue
            dest = BRANDING_ASSETS_DIR / f"{mode}_{slot}.png"
            try:
                shutil.copy2(src, dest)
            except OSError as exc:
                logger.warning("Branding seed: could not copy %s -> %s: %s", src, dest, exc)
                continue
            patch[key] = f"/api/branding/{mode}/asset/{slot}"
        if patch:
            await persist(patch)
            logger.info("Branding seed: mode=%s keys=%s", mode, sorted(patch.keys()))


async def _seed_personas() -> None:
    persona_dir = _ASSETS_ROOT / "personas"
    if not persona_dir.is_dir():
        return
    json_files = sorted(persona_dir.glob("*.json"))
    if not json_files:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        cols = await personas_table_columns(conn)
        has_mode = await personas_has_mode_column(conn)
        for jf in json_files:
            stem = jf.stem
            if not _STEM_SAFE.match(stem):
                logger.warning("Persona seed: skip unsafe stem %r", stem)
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logger.warning("Persona seed: invalid JSON %s: %s", jf, exc)
                continue
            name = (data.get("name") or "").strip()
            if not name:
                continue
            mode = data.get("mode") or "booops"
            if mode not in ("booops", "808notes"):
                mode = "booops"
            emoji = (data.get("emoji") or "🤖").strip() or "🤖"
            prompt = data.get("system_prompt") or ""

            existing = await conn.fetchrow(
                "SELECT id, icon_url FROM personas WHERE name = $1::text",
                name,
            )
            if existing is None:
                if has_mode:
                    await conn.execute(
                        """
                        INSERT INTO personas (name, system_prompt, avatar_emoji, is_default, mode)
                        VALUES ($1::text, $2::text, $3::text, FALSE, $4::text)
                        """,
                        name,
                        prompt,
                        emoji,
                        mode,
                    )
                else:
                    if "avatar_emoji" not in cols:
                        await conn.execute(
                            """
                            INSERT INTO personas (name, system_prompt, is_default)
                            VALUES ($1::text, $2::text, FALSE)
                            """,
                            name,
                            prompt,
                        )
                    else:
                        await conn.execute(
                            """
                            INSERT INTO personas (name, system_prompt, avatar_emoji, is_default)
                            VALUES ($1::text, $2::text, $3::text, FALSE)
                            """,
                            name,
                            prompt,
                            emoji,
                        )
                logger.info("Persona seed: inserted %s", name)
                ins = await conn.fetchrow(
                    "SELECT id, icon_url FROM personas WHERE name = $1::text",
                    name,
                )
            else:
                ins = existing

            if ins is None:
                continue
            pid = ins["id"]
            png = persona_dir / f"{stem}.png"
            if not png.is_file():
                logger.warning("Persona seed: missing image %s", png)
                continue
            dest = BRANDING_ASSETS_DIR / f"persona_{stem}.png"
            try:
                shutil.copy2(png, dest)
            except OSError as exc:
                logger.warning("Persona seed: could not copy %s -> %s: %s", png, dest, exc)
                continue
            icon_url = f"/api/branding/persona/asset/{stem}"
            if _emptyish_url(ins["icon_url"]):
                await conn.execute(
                    "UPDATE personas SET icon_url = $2, updated_at = NOW() WHERE id = $1::uuid",
                    pid,
                    icon_url,
                )


async def seed_default_assets() -> None:
    _ensure_assets_dir()
    await _seed_branding()
    await _seed_personas()
