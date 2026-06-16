"""One-shot embed-cutover reingest (folder C, 2026-06-16).

Switching the bundled embedder from the Qwen3-Embedding GGUF (Q8_0, llama.cpp
last-token pooling) to the boofinity safetensors model produces numerically
different 1024-dim vectors that are NOT comparable to the stored
`source_chunks.embedding` rows. Retrieval silently degrades until the corpus is
re-embedded, so the cutover fires `reingest-all` itself, exactly once, on the
first boot where the new embed backend is actually ready.

Guard (see design.md §C5):
  * `global_settings['embed_cutover_boofinity_done']` sentinel → at-most-once.
  * tier == 'external' → no-op WITHOUT setting the sentinel (operator owns their
    embedder; a later switch to bundled should still trigger).
  * readiness gate: the embed `bundled_models` row is `status='ready'` AND a live
    `/v1/embeddings` probe through the front-door returns a 1024-vector. On any
    failure, return WITHOUT setting the sentinel so the next boot retries — never
    fire reingest against a cold/down backend.

Run from main.py lifespan after apply_bundled_bindings + seed_registry, inside
the existing try/except so a cutover failure logs but does not block startup.
"""

from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

_SENTINEL_KEY = "embed_cutover_boofinity_done"
_REBUILD_KEY = "retrieval_rebuilding"


async def _embed_backend_ready(conn) -> bool:
    """True iff the embed row is 'ready' AND a live probe returns a 1024-vector.

    The probe goes through the configured embedding provider (the front-door,
    post C2), exercising the exact path RAG uses. Any failure → not ready.
    """
    status = await conn.fetchval(
        "SELECT status FROM bundled_models WHERE role = 'embed' LIMIT 1"
    )
    if status != "ready":
        logger.info("embed_cutover: embed row status=%s (not ready); deferring", status)
        return False
    try:
        from services.embeddings import embed_query
        vec = await embed_query("readiness probe")
    except Exception as e:  # noqa: BLE001
        logger.info("embed_cutover: embed probe failed (%s); deferring", e)
        return False
    if not isinstance(vec, list) or len(vec) != 1024:
        logger.info("embed_cutover: embed probe returned bad vector; deferring")
        return False
    return True


async def run_embed_cutover(pool) -> None:
    """Fire the one-shot reingest if the embed cutover hasn't run and is ready."""
    async with pool.acquire() as conn:
        done = await conn.fetchval(
            "SELECT value FROM global_settings WHERE key = $1", _SENTINEL_KEY
        )
        if done is not None:
            logger.info("embed_cutover: sentinel present; no-op")
            return

        profile = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
        tier = profile["tier"] if profile else None
        if tier == "external":
            logger.info("embed_cutover: tier=external; no-op (sentinel left unset)")
            return

        if not await _embed_backend_ready(conn):
            return

        # Ready: set the sentinel FIRST (at-most-once even on a crash mid-reingest),
        # then raise the rebuild banner, then enqueue the reingest.
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        await conn.execute(
            "INSERT INTO global_settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO NOTHING",
            _SENTINEL_KEY, now,
        )
        await conn.execute(
            "INSERT INTO global_settings (key, value) VALUES ($1, 'true') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            _REBUILD_KEY,
        )

    from routers.sources import reingest_all_sources_impl
    result = await reingest_all_sources_impl(pool)
    logger.info(
        "embed_cutover: fired reingest-all (queued=%s skipped=%s total=%s)",
        result.get("queued"), result.get("skipped_no_file"), result.get("total"),
    )

    # If nothing was queued (empty corpus), the ingest completion hook never
    # fires, so clear the banner here to avoid a stuck 'true'.
    if not result.get("queued"):
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO global_settings (key, value) VALUES ($1, 'false') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                _REBUILD_KEY,
            )
        logger.info("embed_cutover: empty corpus; cleared retrieval_rebuilding immediately")
