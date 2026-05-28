"""Vision container lifecycle wrapper (hlh_orchestra client).

Wraps the hlh_orchestra HTTP API for start/stop operations.
Tracks last-used timestamp in global_settings (multi-worker safe).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://hlh_orchestra:9620")
ORCHESTRA_TOKEN = os.environ.get("ORCHESTRA_TOKEN", "")


async def mark_vision_used(conn) -> None:
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ('vision_last_used_ms', $1)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        str(int(time.time() * 1000)),
    )


async def vision_last_used_ms(conn) -> float:
    val = await conn.fetchval(
        "SELECT value FROM global_settings WHERE key = 'vision_last_used_ms'"
    )
    try:
        return float(val) if val else 0
    except (TypeError, ValueError):
        return 0


async def _orchestra(method: str, path: str) -> dict[str, Any]:
    if not ORCHESTRA_TOKEN:
        raise RuntimeError("ORCHESTRA_TOKEN not configured")
    headers = {"X-Orchestra-Token": ORCHESTRA_TOKEN}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        r = await client.request(method, f"{ORCHESTRA_URL}{path}", headers=headers)
        r.raise_for_status()
        return r.json()


async def vision_status() -> dict[str, Any]:
    return await _orchestra("GET", "/vision/status")


async def ensure_vision_running() -> None:
    """Start hlh_vision_embed if not running; wait until model loads."""
    status_data = await vision_status()
    if status_data["status"] == "running":
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                r = await client.get("http://hlh_vision_embed:7997/health")
                if r.status_code == 200:
                    return
        except Exception:
            pass

    if status_data["status"] != "running":
        await _orchestra("POST", "/vision/start")

    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
                r = await client.get("http://hlh_vision_embed:7997/health")
                if r.status_code == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(2.0)

    raise RuntimeError("vision did not become healthy within 120s")


async def stop_vision() -> None:
    await _orchestra("POST", "/vision/stop")
