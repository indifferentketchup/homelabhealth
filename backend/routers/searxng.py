"""SearXNG configuration (DB + optional settings.yml sync)."""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import _SCHEMA_MODE_VALUE, require_admin
from db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


class SearxngConfigUpdate(BaseModel):
    safe_search: int | None = None
    image_proxy: bool | None = None
    enabled_engines: list[str] | None = None
    autocomplete: str | None = None


class SearxngConfigResponse(BaseModel):
    mode: str
    safe_search: int
    image_proxy: bool
    enabled_engines: list[str] = Field(default_factory=list)
    autocomplete: str = ""


def _split_engines(csv: str | None) -> list[str]:
    if not csv:
        return []
    return [p.strip().lower() for p in csv.split(",") if p.strip()]


def _engine_name_from_yaml_item(item: Any) -> str | None:
    if not isinstance(item, dict) or not item:
        return None
    name = item.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip().lower()
    if len(item) == 1:
        k = next(iter(item))
        if isinstance(k, str) and k.strip():
            return k.strip().lower()
    return None


def _set_engine_disabled_in_yaml_item(item: dict[str, Any], disabled: bool) -> None:
    if "name" in item:
        item["disabled"] = disabled
        return
    if len(item) == 1:
        key, val = next(iter(item.items()))
        if not isinstance(val, dict):
            item[key] = {"disabled": disabled}
        else:
            val["disabled"] = disabled


def _write_searxng_settings_yaml(
    *,
    safe_search: int,
    image_proxy: bool,
    enabled_names: set[str],
    autocomplete: str,
) -> None:
    """If SEARXNG_SETTINGS_YML points to a file, merge toggles into SearXNG's YAML."""
    path = (os.environ.get("SEARXNG_SETTINGS_YML") or "").strip()
    if not path:
        return
    if not os.path.isfile(path):
        logger.warning("SEARXNG_SETTINGS_YML set but file missing: %s", path)
        return

    try:
        with open(path, encoding="utf-8") as f:
            settings: dict[str, Any] = yaml.safe_load(f) or {}
    except OSError as e:
        logger.warning("Could not read SearXNG settings %s: %s", path, e)
        return

    search_block = settings.setdefault("search", {})
    if not isinstance(search_block, dict):
        search_block = {}
        settings["search"] = search_block
    search_block["safe_search"] = safe_search
    ac = (autocomplete or "").strip()
    if ac:
        search_block["autocomplete"] = ac
    elif "autocomplete" in search_block:
        search_block["autocomplete"] = ""

    server_block = settings.setdefault("server", {})
    if not isinstance(server_block, dict):
        server_block = {}
        settings["server"] = server_block
    server_block["image_proxy"] = bool(image_proxy)

    engines_block = settings.get("engines")
    # When no engines selected, do not rewrite YAML `disabled` flags (would disable everything).
    if isinstance(engines_block, list) and enabled_names:
        for item in engines_block:
            if not isinstance(item, dict):
                continue
            eng = _engine_name_from_yaml_item(item)
            if not eng:
                continue
            _set_engine_disabled_in_yaml_item(item, eng not in enabled_names)

    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                settings,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
    except OSError as e:
        logger.warning("Could not write SearXNG settings %s: %s", path, e)


@router.get("/", response_model=SearxngConfigResponse)
async def get_searxng_config():
    mode = _SCHEMA_MODE_VALUE
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT safe_search, image_proxy, enabled_engines, autocomplete
            FROM searxng_config WHERE mode = $1
            """,
            mode,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    return SearxngConfigResponse(
        mode=mode,
        safe_search=int(row["safe_search"]),
        image_proxy=bool(row["image_proxy"]),
        enabled_engines=_split_engines(row["enabled_engines"]),
        autocomplete=(row["autocomplete"] or "").strip(),
    )


@router.patch("/")
async def update_searxng_config(
    body: SearxngConfigUpdate,
    _owner: dict = Depends(require_admin),
):
    mode = _SCHEMA_MODE_VALUE
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT safe_search, image_proxy, enabled_engines, autocomplete
            FROM searxng_config WHERE mode = $1
            """,
            mode,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Config not found")

        safe_search = int(body.safe_search if body.safe_search is not None else row["safe_search"])
        if safe_search not in (0, 1, 2):
            raise HTTPException(status_code=400, detail="safe_search must be 0, 1, or 2")

        image_proxy = bool(body.image_proxy) if body.image_proxy is not None else bool(row["image_proxy"])

        if body.enabled_engines is not None:
            engines_list = [e.strip().lower() for e in body.enabled_engines if e and str(e).strip()]
            # Empty list = omit `engines` on search requests / use SearXNG instance defaults.
            engines_csv = ",".join(engines_list) if engines_list else ""
        else:
            engines_csv = row["enabled_engines"] or ""
            engines_list = _split_engines(engines_csv)

        autocomplete = body.autocomplete.strip() if body.autocomplete is not None else (row["autocomplete"] or "")

        await conn.execute(
            """
            UPDATE searxng_config
            SET safe_search = $2,
                image_proxy = $3,
                enabled_engines = $4,
                autocomplete = $5,
                updated_at = NOW()
            WHERE mode = $1
            """,
            mode,
            safe_search,
            image_proxy,
            engines_csv,
            autocomplete,
        )

    enabled_set = set(engines_list)
    _write_searxng_settings_yaml(
        safe_search=safe_search,
        image_proxy=image_proxy,
        enabled_names=enabled_set,
        autocomplete=autocomplete,
    )

    return {
        "status": "updated",
        "mode": mode,
        "safe_search": safe_search,
        "image_proxy": image_proxy,
        "enabled_engines": engines_list,
        "autocomplete": autocomplete,
    }
