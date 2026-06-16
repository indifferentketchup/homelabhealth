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

import logging
import uuid
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from db import get_pool
from services.crypto import decrypt_secret

logger = logging.getLogger(__name__)


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


async def resolve_bundled_vl_provider(role: str) -> tuple[Provider, str] | None:
    """Resolve a bundled VL provider (role 'embed-vl' or 'rerank-vl').

    Returns (Provider, serving-alias) or None when the row is absent — which is
    every tier below gpu-24gb+ (the VL rows are seeded only there, folder D), or
    external / setup-incomplete. The serving alias is the boofinity model name
    (qwen3-vl-embed / qwen3-vl-rerank) that hlh_swap routes; it is fixed per role,
    not stored in bundled_models (the snapshot model_id is repo@snapshot).

    Callers (vision.py ingest, rag.py retrieval) treat None as "VL path closed".
    """
    from services.bundled_providers import (
        BUNDLED_VL_EMBED_MODEL,
        BUNDLED_VL_RERANK_MODEL,
    )

    alias_by_role = {
        "embed-vl": BUNDLED_VL_EMBED_MODEL,
        "rerank-vl": BUNDLED_VL_RERANK_MODEL,
    }
    alias = alias_by_role.get(role)
    if alias is None:
        return None

    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT tier, setup_complete FROM system_profile WHERE id = 1"
        )
        if not profile or not profile["setup_complete"] or profile["tier"] == "external":
            return None
        row = await conn.fetchrow(
            """
            SELECT id, name, base_url, api_key, enabled
              FROM providers
             WHERE is_bundled = TRUE AND role = $1 AND enabled = TRUE
             LIMIT 1
            """,
            role,
        )
    if row is None:
        return None
    return _row_to_provider(row), alias


def build_headers(provider: Provider, extra: dict | None = None) -> dict[str, str]:
    """OpenAI-compatible headers, plus Authorization if the provider has a key."""
    h: dict[str, str] = {"Content-Type": "application/json"}
    if extra:
        h.update(extra)
    if provider.api_key:
        h["Authorization"] = f"Bearer {provider.api_key}"
    return h


async def async_llm_call(
    provider: Provider,
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout_s: float = 60.0,
    response_format: dict | None = None,
    extra_body: dict | None = None,
) -> str:
    """Non-streaming chat completion via OpenAI-compatible /v1/chat/completions.

    Returns choices[0].message.content stripped, or '' on any failure (HTTP error,
    parse error, empty choices -- all logged at WARNING).

    Callers must apply de-identification to message content BEFORE calling this
    helper when routing to an external (non-bundled) provider. This helper does
    not perform de-identification.

    For STREAMING use the existing _stream_inference path, not this.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if extra_body:
        payload.update(extra_body)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                logger.warning("async_llm_call: no choices in response (model=%s)", model)
                return ""
            msg = (choices[0].get("message") or {})
            return (msg.get("content") or "").strip()
    except Exception as exc:
        logger.warning("async_llm_call failed (model=%s): %s: %s", model, type(exc).__name__, exc)
        return ""
