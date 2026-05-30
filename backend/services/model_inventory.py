"""Unified inventory of loaded inference models from the llama-server router.

Every bundled model (chat, tasks, embed, rerank, and the on-demand
medgemma-vision preset) is served by the router and reported via /v1/models.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ROUTER_URL = "http://hlh_chat:9610"

TIER_RAM_BUDGET_MIB: dict[str, int] = {
    "cpu-min": 6000,
    "cpu-std": 12000,
    "gpu-4gb": 8000,
    "gpu-8gb": 12000,
    "gpu-16gb": 20000,
    "gpu-24gb+": 28000,
}

MODEL_RAM_MIB: dict[str, int] = {
    "medgemma": 4800,
    "medgemma-vision": 3500,  # MedGemma-4b + mmproj, loaded on demand for ingestion
    "qwen-chat": 1900,
    "gemma-tasks": 450,
    "bge-m3": 700,
    "bge-reranker": 700,
}


async def fetch_router_state() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get(f"{ROUTER_URL}/v1/models")
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.warning("router state probe failed")
        return []

    out = []
    for m in data.get("data", []):
        model_id = m.get("id")
        status = m.get("status", {})
        state = status.get("value") if isinstance(status, dict) else None
        out.append({
            "provider": "router",
            "id": model_id,
            "state": state or "unknown",
            "ram_mib": MODEL_RAM_MIB.get(model_id, 0) if state == "loaded" else 0,
        })
    return out


TIER_CHAT_MODEL: dict[str, str] = {
    "cpu-min": "qwen-chat",
    "cpu-std": "medgemma",
    "gpu-4gb": "medgemma",
    "gpu-8gb": "medgemma",
    "gpu-16gb": "medgemma",
    "gpu-24gb+": "medgemma",
}

ALL_CHAT_MODELS = set(TIER_CHAT_MODEL.values())


async def get_inventory(tier: str) -> dict[str, Any]:
    active_chat = TIER_CHAT_MODEL.get(tier)
    router_models = await fetch_router_state()
    router_models = [
        m for m in router_models
        if m["id"] not in ALL_CHAT_MODELS or m["id"] == active_chat
    ]
    all_models = router_models
    loaded_ram = sum(m["ram_mib"] for m in all_models if m["state"] == "loaded")
    budget = TIER_RAM_BUDGET_MIB.get(tier, TIER_RAM_BUDGET_MIB["cpu-std"])
    return {
        "tier": tier,
        "budget_mib": budget,
        "loaded_ram_mib": loaded_ram,
        "budget_pct": round(100 * loaded_ram / budget, 1) if budget else 0,
        "models": all_models,
        "fetched_at_ms": int(time.time() * 1000),
    }
