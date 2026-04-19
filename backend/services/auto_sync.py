"""BooCode repo auto-sync scheduler.

Periodic background loop. Polls for boocode DAWs with `repo_auto_sync=true`
whose `repo_last_synced_at` is older than AUTO_SYNC_INTERVAL_SECONDS (or NULL),
and fires `sync_daw_repo` under a bounded semaphore.

NOTE: 808notes has no auto-sync equivalent to mirror (manual-only). This is a
net-new mechanism introduced by BooCode Phase 3.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from db import get_pool
from services.repo_ingest import sync_daw_repo

logger = logging.getLogger(__name__)

AUTO_SYNC_INTERVAL_SECONDS = int(os.environ.get("BOOCODE_AUTO_SYNC_INTERVAL", "300"))
AUTO_SYNC_CONCURRENCY = int(os.environ.get("BOOCODE_AUTO_SYNC_CONCURRENCY", "2"))


async def _due_daw_ids(interval_seconds: int) -> list[uuid.UUID]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM daws
            WHERE mode = 'boocode'
              AND repo_auto_sync = true
              AND repo_path IS NOT NULL AND length(trim(repo_path)) > 0
              AND (repo_sync_status IS NULL OR repo_sync_status <> 'syncing')
              AND (
                  repo_last_synced_at IS NULL
                  OR repo_last_synced_at < NOW() - make_interval(secs => $1)
              )
            """,
            interval_seconds,
        )
    return [r["id"] for r in rows]


async def _run_one(sem: asyncio.Semaphore, daw_id: uuid.UUID) -> None:
    async with sem:
        try:
            result = await sync_daw_repo(daw_id)
            logger.info("auto_sync: daw_id=%s result=%s", daw_id, result)
        except Exception:
            logger.exception("auto_sync: sync_daw_repo crashed daw_id=%s", daw_id)


async def auto_sync_loop() -> None:
    interval = AUTO_SYNC_INTERVAL_SECONDS
    sem = asyncio.Semaphore(AUTO_SYNC_CONCURRENCY)
    logger.info(
        "boocode auto_sync_loop start: interval=%ds concurrency=%d",
        interval,
        AUTO_SYNC_CONCURRENCY,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            ids = await _due_daw_ids(interval)
            if not ids:
                continue
            logger.info("boocode auto_sync: %d due DAW(s)", len(ids))
            await asyncio.gather(*[_run_one(sem, i) for i in ids])
        except asyncio.CancelledError:
            logger.info("boocode auto_sync_loop cancelled — exiting")
            raise
        except Exception:
            logger.exception("boocode auto_sync_loop tick failed; continuing")
