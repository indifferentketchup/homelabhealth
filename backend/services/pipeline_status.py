"""Pipeline status helpers for SSE-streamed inference.

Emits phase frames with time estimates so the frontend can render a live
pipeline (loading → embedding → searching → reranking → generating).

Each stage is a context manager that:
  1. Reads the rolling-average estimate from global_settings
  2. Yields a phase frame with estimate_ms
  3. On exit, updates the rolling average (0.7 * old + 0.3 * actual)
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


def _estimate_key(stage: str, model: str | None = None) -> str:
    if stage == "loading" and model:
        return f"estimate_ms_load_{model}"
    return {
        "embedding": "estimate_ms_embed_query",
        "reranking": "estimate_ms_rerank",
        "searching": "estimate_ms_rag_search",
        "generating": "estimate_ms_chat_first_token",
    }.get(stage, "")


async def _read_estimate(conn, key: str) -> int | None:
    if not key:
        return None
    row = await conn.fetchval(
        "SELECT value FROM global_settings WHERE key = $1", key
    )
    try:
        return int(row) if row is not None else None
    except (TypeError, ValueError):
        return None


async def _update_estimate(conn, key: str, actual_ms: int) -> None:
    if not key or actual_ms <= 0:
        return
    old = await _read_estimate(conn, key)
    new_val = int(0.7 * (old or actual_ms) + 0.3 * actual_ms)
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, str(new_val),
    )


@asynccontextmanager
async def stage(
    conn,
    stage_name: str,
    *,
    model: str | None = None,
    skip_estimate_update: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Context manager that builds a phase-frame payload and times the body.

    Yields the payload dict (caller yields it as SSE). On exit, updates
    the rolling estimate. The caller is responsible for yielding the frame.
    """
    key = _estimate_key(stage_name, model)
    estimate_ms = await _read_estimate(conn, key)

    payload: dict[str, Any] = {"type": "phase", "phase": stage_name}
    if model:
        payload["model"] = model
    if estimate_ms is not None:
        payload["estimate_ms"] = estimate_ms

    start = time.monotonic()
    yield payload
    actual_ms = int((time.monotonic() - start) * 1000)

    if not skip_estimate_update:
        try:
            await _update_estimate(conn, key, actual_ms)
        except Exception:
            logger.warning("pipeline_status: estimate update failed for %s", key)


async def model_is_loaded(model: str) -> bool:
    """Probe llama-server router to check if a model is currently loaded."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get("http://hlh_chat:9610/v1/models")
            r.raise_for_status()
            for m in r.json().get("data", []):
                if m.get("id") == model:
                    return m.get("status", {}).get("value") == "loaded"
    except Exception:
        pass
    return False
