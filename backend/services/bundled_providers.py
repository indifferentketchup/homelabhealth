"""Auto-seed bundled providers — chat + embed + rerank.

A "bundled" provider is one that the homelabhealth stack runs itself
(via the docker-compose `bundled` profile). This module owns the
idempotent upsert of the three provider rows AND the apply_bundled_bindings
helper that rewrites global embedding/reranker bindings + bundled-chat-bound
workspace models on every lifespan boot and after every tier change.

Spec: docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md
      §2 (schema), §4 (auto-binding), §6 (UI implications).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


MODELS_BASE = Path(os.environ.get("HLH_MODELS_DIR", "/models"))
ACTIVE_MMPROJ = MODELS_BASE / "vision" / "active-mmproj.gguf"

BUNDLE_GROUP = "homelab-health-ai"

BUNDLED_CHAT_NAME = "HomeLab Health AI · Chat"
BUNDLED_CHAT_BASE_URL = "http://hlh_chat:9610"

BUNDLED_EMBED_NAME = "HomeLab Health AI · Embed"
BUNDLED_EMBED_BASE_URL = "http://hlh_chat:9610"
BUNDLED_EMBED_MODEL = "bge-m3"

BUNDLED_RERANK_NAME = "HomeLab Health AI · Rerank"
BUNDLED_RERANK_BASE_URL = "http://hlh_chat:9610"
BUNDLED_RERANK_MODEL = "bge-reranker"

BUNDLED_VISION_EMBED_NAME = "HomeLab Health AI · Vision Embed"
BUNDLED_VISION_EMBED_BASE_URL = "http://hlh_vision_embed:7997"
# TODO: replace with Sam's ungated repo
MEDSIGLIP_MODEL_ID = os.environ.get("HLH_MEDSIGLIP_MODEL", "google/medsiglip-448")


# Per-tier chat model aliases — must match the [section] names in
# hlh_chat/models.ini. The router dispatches by this alias.
#
# Note: 'apple-mlx' is intentionally absent — Apple MLX bundled inference is
# Phase 6 deferred. apply_bundled_bindings treats it like 'external' and
# no-ops; operators on Apple Silicon pick a chat provider manually.
TIER_CHAT_MODELS = {
    "cpu-min": "qwen-chat",
    "cpu-std": "medgemma",
    "gpu-4gb": "medgemma",
    "gpu-8gb": "medgemma",
    "gpu-16gb": "medgemma",
    "gpu-24gb+": "medgemma",
}


async def _read_system_profile(conn) -> dict[str, Any] | None:
    return await conn.fetchrow(
        "SELECT tier, setup_complete FROM system_profile WHERE id = 1"
    )


async def _rename_legacy(conn) -> None:
    """In-place rename of legacy 'bundled-chat' row, preserves UUID."""
    await conn.execute(
        "UPDATE providers SET name = $1 WHERE name = 'bundled-chat'",
        BUNDLED_CHAT_NAME,
    )


async def _upsert_bundled_row(
    conn, *, name: str, base_url: str, role: str
) -> str | None:
    row = await conn.fetchrow(
        """
        INSERT INTO providers (name, base_url, api_key, enabled, is_bundled, role, bundle_group)
        VALUES ($1, $2, NULL, TRUE, TRUE, $3, $4)
        ON CONFLICT (name) DO UPDATE
        SET base_url = EXCLUDED.base_url,
            enabled = TRUE,
            is_bundled = TRUE,
            role = EXCLUDED.role,
            bundle_group = EXCLUDED.bundle_group,
            updated_at = NOW()
        RETURNING id
        """,
        name, base_url, role, BUNDLE_GROUP,
    )
    return str(row["id"]) if row else None


async def _is_vision_sidecar_enabled() -> bool:
    """Check if the vision sidecar is reachable (profile=vision active)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as c:
            r = await c.get(f"{BUNDLED_VISION_EMBED_BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_bundled_providers(conn) -> dict[str, str] | None:
    """Idempotent upsert of bundled rows (chat + embed + rerank + optional vision_embed).

    No-op unless `system_profile.setup_complete = TRUE` AND tier ≠ 'external'.
    Returns {'chat': uuid, 'embed': uuid, 'rerank': uuid, 'vision_embed': uuid|None} or None if no-op.
    """
    profile = await _read_system_profile(conn)
    if profile is None:
        logger.info("bundled_providers: no system_profile row; skipping seed")
        return None
    if not bool(profile["setup_complete"]):
        logger.info("bundled_providers: setup_complete=false; skipping seed")
        return None
    if profile["tier"] == "external":
        logger.info("bundled_providers: tier=external; skipping seed")
        return None

    await _rename_legacy(conn)

    chat_id = await _upsert_bundled_row(
        conn, name=BUNDLED_CHAT_NAME, base_url=BUNDLED_CHAT_BASE_URL, role="chat"
    )
    embed_id = await _upsert_bundled_row(
        conn, name=BUNDLED_EMBED_NAME, base_url=BUNDLED_EMBED_BASE_URL, role="embed"
    )
    rerank_id = await _upsert_bundled_row(
        conn, name=BUNDLED_RERANK_NAME, base_url=BUNDLED_RERANK_BASE_URL, role="rerank"
    )

    vision_embed_id = None
    if await _is_vision_sidecar_enabled():
        vision_embed_id = await _upsert_bundled_row(
            conn, name=BUNDLED_VISION_EMBED_NAME, base_url=BUNDLED_VISION_EMBED_BASE_URL, role="vision_embed"
        )
        logger.info("bundled_providers: vision sidecar reachable, seeded vision_embed=%s", vision_embed_id)
    else:
        logger.info("bundled_providers: vision sidecar not reachable, skipping vision_embed seed")

    logger.info(
        "bundled_providers: ensured chat=%s embed=%s rerank=%s",
        chat_id, embed_id, rerank_id,
    )
    return {"chat": chat_id, "embed": embed_id, "rerank": rerank_id, "vision_embed": vision_embed_id}


async def apply_bundled_bindings(conn, tier: str) -> None:
    """Rewrite global embed/rerank bindings + bundled-chat-bound workspaces.

    Called from main.py lifespan AND from routers/system.py PUT /api/system/profile
    after a successful tier save. See spec §4.

    No-op when tier == 'external' (operator picks manually elsewhere).
    """
    if tier in ("external", "apple-mlx"):
        logger.info("apply_bundled_bindings: tier=%s; no-op (Apple MLX bundling is Phase 6)", tier)
        link_active_mmproj(tier)
        return

    ids = await ensure_bundled_providers(conn)
    if ids is None:
        logger.info("apply_bundled_bindings: ensure_bundled_providers no-op; skipping")
        return

    # 1. Global embedding binding (always rewrite per non-goal §0).
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ('embedding_provider_id', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ids["embed"],
    )
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ('embedding_model', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        BUNDLED_EMBED_MODEL,
    )

    # 2. Global reranker binding (always rewrite).
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ('reranker_provider_id', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        ids["rerank"],
    )
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ('reranker_model', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        BUNDLED_RERANK_MODEL,
    )

    # 3. Vision embed binding — only if provider row was seeded.
    if ids.get("vision_embed"):
        await conn.execute(
            """
            INSERT INTO global_settings (key, value) VALUES ('vision_embed_provider_id', $1)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            ids["vision_embed"],
        )
        await conn.execute(
            """
            INSERT INTO global_settings (key, value) VALUES ('vision_embed_model', $1)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            MEDSIGLIP_MODEL_ID,
        )
        logger.info("apply_bundled_bindings: vision_embed bound to provider=%s model=%s",
                     ids["vision_embed"], MEDSIGLIP_MODEL_ID)

    # 4. Symlink active mmproj for the current tier so hlh_chat picks it up.
    link_active_mmproj(tier)

    # 4. Workspace chat binding. Per spec §4 step 3, BOTH UPDATEs are required:
    # the IN (...) form doesn't subsume the IS NULL case (IN with NULL is NULL,
    # not TRUE), so we keep two statements.
    chat_model = TIER_CHAT_MODELS.get(tier)
    if chat_model is None:
        logger.warning(
            "apply_bundled_bindings: no chat model mapping for tier=%s; skipping workspace rewrite",
            tier,
        )
        return

    # Existing bundled-chat-bound workspaces — rewrite model to current tier.
    await conn.execute(
        "UPDATE workspaces SET model = $1 WHERE provider_id = $2::uuid",
        chat_model, ids["chat"],
    )
    # Unbound workspaces — bind to bundled chat with current tier model.
    await conn.execute(
        "UPDATE workspaces SET provider_id = $1::uuid, model = $2 WHERE provider_id IS NULL",
        ids["chat"], chat_model,
    )

    logger.info(
        "apply_bundled_bindings: tier=%s, rewrote globals + workspaces to chat_model=%s",
        tier, chat_model,
    )


def link_active_mmproj(tier: str) -> None:
    """Create/update symlink for the active tier's mmproj file.

    Best-effort: logs and continues on filesystem errors so the API
    starts even if the symlink can't be written. hlh_chat will simply
    start without --mmproj in that case.
    """
    from services.model_puller import MODEL_REGISTRY
    try:
        spec = MODEL_REGISTRY.get("vision", {}).get(tier)
        if spec is None:
            if ACTIVE_MMPROJ.is_symlink() or ACTIVE_MMPROJ.exists():
                ACTIVE_MMPROJ.unlink()
                logger.info("link_active_mmproj: tier=%s → cleared (no vision spec)", tier)
            return
        target = MODELS_BASE / "vision" / tier / spec.filename
        if not target.exists():
            if ACTIVE_MMPROJ.is_symlink() or ACTIVE_MMPROJ.exists():
                ACTIVE_MMPROJ.unlink()
            logger.info("link_active_mmproj: tier=%s → cleared (mmproj not yet pulled)", tier)
            return
        ACTIVE_MMPROJ.parent.mkdir(parents=True, exist_ok=True)
        rel_target = Path(tier) / spec.filename
        tmp = ACTIVE_MMPROJ.parent / (ACTIVE_MMPROJ.name + ".tmp")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(rel_target, tmp)
        os.rename(tmp, ACTIVE_MMPROJ)
        logger.info("link_active_mmproj: tier=%s → %s", tier, rel_target)
    except OSError as exc:
        logger.error("link_active_mmproj: tier=%s failed: %s", tier, exc)
