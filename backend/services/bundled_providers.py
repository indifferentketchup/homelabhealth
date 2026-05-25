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
from typing import Any

logger = logging.getLogger(__name__)


BUNDLE_GROUP = "homelab-health-ai"

BUNDLED_CHAT_NAME = "HomeLab Health AI · Chat"
BUNDLED_CHAT_BASE_URL = "http://hlh_chat:9610"

BUNDLED_EMBED_NAME = "HomeLab Health AI · Embed"
BUNDLED_EMBED_BASE_URL = "http://hlh_infer:9611"
BUNDLED_EMBED_MODEL = "BAAI/bge-m3"

BUNDLED_RERANK_NAME = "HomeLab Health AI · Rerank"
BUNDLED_RERANK_BASE_URL = "http://hlh_infer:9611"
BUNDLED_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


# Per-tier chat model ids — bare filenames llama.cpp's server returns when
# launched with --model <path>. Matches docker-compose.yml HLH_CHAT_MODEL_PATH
# default + per-tier overrides.
#
# Note: 'apple-mlx' is intentionally absent — Apple MLX bundled inference is
# Phase 6 deferred. apply_bundled_bindings treats it like 'external' and
# no-ops; operators on Apple Silicon pick a chat provider manually.
TIER_CHAT_MODELS = {
    "cpu-min": "Qwen3.5-0.8B-Q8_0.gguf",
    "cpu-std": "medgemma-1.5-4b-it-Q4_K_M.gguf",
    "gpu-4gb": "medgemma-1.5-4b-it-Q4_K_M.gguf",
    "gpu-8gb": "medgemma-1.5-4b-it-Q8_0.gguf",
    "gpu-16gb": "medgemma-27b-it-Q4_K_M.gguf",
    "gpu-24gb+": "medgemma-27b-it-Q4_K_M.gguf",
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


async def ensure_bundled_providers(conn) -> dict[str, str] | None:
    """Idempotent upsert of the three bundled rows.

    No-op unless `system_profile.setup_complete = TRUE` AND tier ≠ 'external'.
    Returns {'chat': uuid, 'embed': uuid, 'rerank': uuid} or None if no-op.
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

    logger.info(
        "bundled_providers: ensured chat=%s embed=%s rerank=%s",
        chat_id, embed_id, rerank_id,
    )
    return {"chat": chat_id, "embed": embed_id, "rerank": rerank_id}


async def apply_bundled_bindings(conn, tier: str) -> None:
    """Rewrite global embed/rerank bindings + bundled-chat-bound workspaces.

    Called from main.py lifespan AND from routers/system.py PUT /api/system/profile
    after a successful tier save. See spec §4.

    No-op when tier == 'external' (operator picks manually elsewhere).
    """
    if tier in ("external", "apple-mlx"):
        logger.info("apply_bundled_bindings: tier=%s; no-op (Apple MLX bundling is Phase 6)", tier)
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

    # 3. Workspace chat binding. Per spec §4 step 3, BOTH UPDATEs are required:
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
