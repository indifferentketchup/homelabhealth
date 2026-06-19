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
        "unloading": "estimate_ms_unload",
        "swapping": "estimate_ms_swap",
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
            logger.warning(
                "pipeline_status: estimate update failed for %s", key, exc_info=True
            )


async def model_is_loaded(model: str) -> bool:
    """Check the hlh_swap front-door for whether a model is currently resident.

    Delegates to infer_backend_state (which probes http://hlh_swap:9620) so the
    front-door is the single source of truth. Anything other than a confirmed
    "loaded" (swapping, unavailable, or an unreachable front-door) returns False,
    so the caller falls through to its warmup path rather than skipping it.
    """
    state = await infer_backend_state(model)
    return state.get("state") == "loaded"


async def infer_backend_state(model: str, tier: str | None = None) -> dict[str, Any]:
    """Map a model's hlh_swap front-door status to a backend-state payload.

    GETs the front-door http://hlh_swap:9620/v1/models and resolves the alias to
    one of:
      - loaded:      the child process is up and the model is resident
      - swapping:    listed but not yet loaded (llama-swap is starting the child)
      - unavailable: not listed, or the front-door is unreachable

    When a tier is given, the resource policy decorates the payload: whether the
    model may be co-resident with other roles, and (for the chat roles) whether
    Gemma offloads to CPU or goes unavailable under VRAM pressure. The frontend
    renders the swapping phase from this.
    """
    from services.resource_policy import coresident, gemma_degradation

    state = "unavailable"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get("http://hlh_swap:9620/v1/models")
            r.raise_for_status()
            for m in r.json().get("data", []):
                if m.get("id") == model:
                    loaded = m.get("status", {}).get("value") == "loaded"
                    state = "loaded" if loaded else "swapping"
                    break
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        logger.warning("infer_backend_state: probe to hlh_swap failed: %s", exc)
    except Exception as exc:
        logger.warning("infer_backend_state: unexpected probe error: %s", exc, exc_info=True)

    payload: dict[str, Any] = {"model": model, "state": state}
    if tier:
        payload["coresident"] = sorted(coresident(tier))
        payload["gemma_under_pressure"] = gemma_degradation(tier)
    return payload
