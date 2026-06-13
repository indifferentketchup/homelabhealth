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

# Per-alias symlinks pointing at the chat GGUF the active tier downloaded.
# models.ini's [medgemma] and [qwen-chat] sections point at these, so a single
# static models.ini works across every tier — apply_bundled_bindings re-aims
# the link when the operator picks a tier. Mirrors the link_active_mmproj
# pattern; same best-effort error handling.
ACTIVE_MEDGEMMA = MODELS_BASE / "active-medgemma.gguf"
ACTIVE_QWEN = MODELS_BASE / "active-qwen.gguf"

BUNDLE_GROUP = "homelab-health-ai"

BUNDLED_CHAT_NAME = "HomeLab Health AI · Chat"
BUNDLED_CHAT_BASE_URL = "http://hlh_chat:9610"

BUNDLED_EMBED_NAME = "HomeLab Health AI · Embed"
BUNDLED_EMBED_BASE_URL = "http://hlh_chat:9610"
BUNDLED_EMBED_MODEL = "qwen3-embed"

BUNDLED_RERANK_NAME = "HomeLab Health AI · Rerank"
BUNDLED_RERANK_BASE_URL = "http://hlh_chat:9610"
BUNDLED_RERANK_MODEL = "qwen3-reranker"


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


async def ensure_bundled_providers(conn) -> dict[str, str] | None:
    """Idempotent upsert of bundled rows (chat + embed + rerank).

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
        link_active_mmproj(tier)
        link_active_chat(tier)
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

    # 3. Symlink the active mmproj for the current tier so the [medgemma] chat
    #    preset loads it and the chat model can read images.
    link_active_mmproj(tier)
    link_active_chat(tier)

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


def migrate_legacy_chat_paths() -> None:
    """One-time: move chat GGUFs from /models/chat/<tier>/<file> → /models/<file>.

    v1.1.4 and earlier downloaded chat models to a per-tier subdir; v1.1.5
    switched to flat paths so a single static models.ini serves every tier.
    If the flat target exists already, we drop the legacy copy. Best-effort;
    a partial migration is harmless — the puller will re-fetch any missing
    file on next pull.
    """
    legacy_root = MODELS_BASE / "chat"
    if not legacy_root.is_dir():
        return
    try:
        for tier_dir in legacy_root.iterdir():
            if not tier_dir.is_dir():
                continue
            for src in tier_dir.iterdir():
                if not src.is_file() or src.suffix != ".gguf":
                    continue
                dst = MODELS_BASE / src.name
                try:
                    if dst.exists():
                        src.unlink()
                        logger.info("migrate_legacy_chat_paths: dropped duplicate %s", src)
                    else:
                        src.rename(dst)
                        logger.info("migrate_legacy_chat_paths: moved %s → %s", src, dst)
                except OSError as exc:
                    logger.warning("migrate_legacy_chat_paths: %s → %s failed: %s", src, dst, exc)
    except OSError as exc:
        logger.warning("migrate_legacy_chat_paths: walk failed: %s", exc)


def link_active_chat(tier: str) -> None:
    """Symlink active-medgemma.gguf / active-qwen.gguf at the tier's downloaded chat GGUF.

    models.ini's [medgemma] and [qwen-chat] sections point at these symlinks,
    so a single static config serves every tier. Best-effort: logs and
    continues on filesystem errors; hlh_chat will simply fail to load that
    alias if the symlink is missing (the operator sees the chat error).

    The puller writes chat GGUFs at the flat /models/<filename> path (see
    _FLAT_DEST_ROLES in model_puller); this function picks the file matching
    the active tier and aims the right alias's symlink at it.
    """
    from services.model_puller import MODEL_REGISTRY

    alias = TIER_CHAT_MODELS.get(tier)
    if alias is None:
        logger.info("link_active_chat: tier=%s → no bundled chat (external/apple-mlx)", tier)
        return
    spec = MODEL_REGISTRY.get("chat", {}).get(tier)
    if spec is None:
        logger.info("link_active_chat: tier=%s → no chat spec; skipping", tier)
        return
    link = ACTIVE_MEDGEMMA if alias == "medgemma" else ACTIVE_QWEN

    try:
        target = MODELS_BASE / spec.filename
        if not target.exists():
            if link.is_symlink() or link.exists():
                link.unlink()
            logger.info("link_active_chat: tier=%s alias=%s → cleared (chat not yet pulled)", tier, alias)
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        rel_target = Path(spec.filename)  # same dir; symlink target is just the filename
        tmp = link.parent / (link.name + ".tmp")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(rel_target, tmp)
        os.rename(tmp, link)
        logger.info("link_active_chat: tier=%s alias=%s → %s", tier, alias, rel_target)
    except OSError as exc:
        logger.error("link_active_chat: tier=%s alias=%s failed: %s", tier, alias, exc)
