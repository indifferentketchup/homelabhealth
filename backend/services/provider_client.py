"""Shared resolver for providers + per-role bindings.

Replaces the four duplicated `_openai_headers()` / `_inference_base()` helpers
that previously read OPENAI_API_KEY / INFERENCE_URL inline in every caller.

Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §4

Public surface:
    Provider                       — frozen dataclass; api_key is plaintext post-decrypt
    resolve_provider(id)           — fetch+decrypt; 404/409 if missing/disabled
    resolve_provider_for_workspace(ws_id) -> (Provider, model)
    resolve_embedding_provider() -> (Provider, model)   raises EmbeddingError if unset
    resolve_reranker_provider() -> (Provider, model) | None   None = flashrank fallback
    build_headers(provider, extra=None) -> dict
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException

from db import get_pool
from services.crypto import decrypt_secret


_CHAT_NOT_CONFIGURED = (
    "No provider configured for this workspace. "
    "Open Settings → Workspace to pick one."
)
_EMBEDDING_NOT_CONFIGURED = (
    "Embedding model not configured. Set one in Settings → Embedding."
)


@dataclass(frozen=True)
class Provider:
    id: uuid.UUID
    name: str
    base_url: str        # already rstrip('/')
    api_key: str | None  # plaintext after decrypt_secret; None = no Authorization header
    enabled: bool


def _row_to_provider(row) -> Provider:
    return Provider(
        id=row["id"],
        name=row["name"],
        base_url=(row["base_url"] or "").rstrip("/"),
        api_key=decrypt_secret(row["api_key"]),
        enabled=bool(row["enabled"]),
    )


async def resolve_provider(provider_id: uuid.UUID) -> Provider:
    """Fetch a provider row by id; decrypt the key.

    Raises HTTPException(404) if not found; HTTPException(409) if disabled.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, base_url, api_key, enabled
              FROM providers WHERE id = $1::uuid
            """,
            provider_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="provider not found")
    if not bool(row["enabled"]):
        raise HTTPException(status_code=409, detail="provider is disabled")
    return _row_to_provider(row)


async def resolve_provider_for_workspace(
    workspace_id: uuid.UUID,
) -> tuple[Provider, str]:
    """Look up the provider + model pinned to a workspace.

    Raises HTTPException(400) with the exact spec message
    `'No provider configured for this workspace. Open Settings → Workspace to pick one.'`
    if the workspace exists but `provider_id` is NULL. Raises 404 if the
    workspace itself is missing.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        ws = await conn.fetchrow(
            """
            SELECT id, provider_id, model FROM workspaces WHERE id = $1::uuid
            """,
            workspace_id,
        )
        if ws is None:
            raise HTTPException(status_code=404, detail="workspace not found")
        if ws["provider_id"] is None:
            raise HTTPException(status_code=400, detail=_CHAT_NOT_CONFIGURED)
        prov = await conn.fetchrow(
            """
            SELECT id, name, base_url, api_key, enabled
              FROM providers WHERE id = $1::uuid
            """,
            ws["provider_id"],
        )
        if prov is None:
            # Workspace row references a deleted provider — shouldn't happen
            # because of ON DELETE SET NULL, but defend against it.
            raise HTTPException(status_code=400, detail=_CHAT_NOT_CONFIGURED)
        if not bool(prov["enabled"]):
            raise HTTPException(status_code=400, detail=_CHAT_NOT_CONFIGURED)
    model = (ws["model"] or "").strip()
    if not model:
        # CHECK constraint should prevent this, but defend against it.
        raise HTTPException(status_code=400, detail=_CHAT_NOT_CONFIGURED)
    return _row_to_provider(prov), model


async def _resolve_role_binding(
    provider_key: str,
    model_key: str,
) -> tuple[Provider, str] | None:
    """Look up a (provider_id, model) pair stored in global_settings.

    Returns None if either key is absent or empty. Returns None and ignores
    a stale provider id if the row no longer exists or is disabled.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM global_settings WHERE key = ANY($1::text[])",
            [provider_key, model_key],
        )
        settings = {r["key"]: r["value"] for r in rows}
        raw_pid = (settings.get(provider_key) or "").strip()
        raw_model = (settings.get(model_key) or "").strip()
        if not raw_pid or not raw_model:
            return None
        try:
            pid = uuid.UUID(raw_pid)
        except ValueError:
            return None
        prov = await conn.fetchrow(
            """
            SELECT id, name, base_url, api_key, enabled
              FROM providers WHERE id = $1::uuid
            """,
            pid,
        )
    if prov is None or not bool(prov["enabled"]):
        return None
    return _row_to_provider(prov), raw_model


async def resolve_embedding_provider() -> tuple[Provider, str]:
    """Look up the global embedding provider + model.

    Raises EmbeddingError with the exact spec message
    `'Embedding model not configured. Set one in Settings → Embedding.'`
    if not configured. (Imported lazily to avoid a top-level import cycle
    between services.embeddings and services.provider_client.)
    """
    binding = await _resolve_role_binding("embedding_provider_id", "embedding_model")
    if binding is None:
        from services.embeddings import EmbeddingError
        raise EmbeddingError(_EMBEDDING_NOT_CONFIGURED)
    return binding


async def resolve_reranker_provider() -> tuple[Provider, str] | None:
    """Look up the global reranker provider + model.

    Returns None if not configured — the caller should fall back to flashrank.
    """
    return await _resolve_role_binding("reranker_provider_id", "reranker_model")


async def resolve_bundled_chat_provider() -> tuple[Provider, str] | None:
    """Look up the bundled chat provider + model alias for the active tier.

    Used by internal services (compaction, vision) that need LLM access but
    have no workspace context. Returns None on external tier, setup incomplete,
    or provider row missing/disabled — callers should skip gracefully.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT tier, setup_complete FROM system_profile WHERE id = 1"
        )
        if not profile or not profile["setup_complete"] or profile["tier"] == "external":
            return None
        row = await conn.fetchrow(
            """
            SELECT p.id, p.name, p.base_url, p.api_key, p.enabled,
                   bm.model_id AS chat_model
              FROM providers p
              JOIN bundled_models bm ON bm.role = 'chat' AND bm.tier = $1
             WHERE p.is_bundled = TRUE AND p.role = 'chat' AND p.enabled = TRUE
             LIMIT 1
            """,
            profile["tier"],
        )
    if row is None:
        return None
    model = (row["chat_model"] or "").strip()
    if not model:
        return None
    return _row_to_provider(row), model


def build_headers(provider: Provider, extra: dict | None = None) -> dict[str, str]:
    """OpenAI-compatible headers, plus Authorization if the provider has a key."""
    h: dict[str, str] = {"Content-Type": "application/json"}
    if extra:
        h.update(extra)
    if provider.api_key:
        h["Authorization"] = f"Bearer {provider.api_key}"
    return h
