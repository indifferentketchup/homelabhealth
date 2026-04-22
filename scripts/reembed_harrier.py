"""Re-embed all rows in source_chunks and repo_chunks using the currently
configured embedding backend (Harrier, post-Phase-1 swap).

DOCUMENT-mode: uses embed_batch with raw text — no query-instruction prefix.
Safe to re-run; UPDATEs overwrite stale vectors.

Invocation (must run inside the boolab_api container so env + Python path
match prod exactly):
    docker exec -i boolab_api python3 -m scripts.reembed_harrier
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from db import close_pool, get_pool, init_pool
from services.embeddings import (
    EMBEDDING_BATCH_SIZE,
    EmbeddingError,
    embed_batch,
    format_vector,
)

logger = logging.getLogger("reembed_harrier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# (table, text_column). source_chunks first — lighter payloads surface errors fast.
TABLES: list[tuple[str, str]] = [
    ("source_chunks", "text"),
    ("repo_chunks", "content"),
]


async def reembed_table(table: str, text_col: str) -> tuple[int, float]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, {text_col} AS content FROM {table} "
            f"WHERE {text_col} IS NOT NULL ORDER BY id"
        )
    total = len(rows)
    if total == 0:
        logger.info("%s: 0 rows, skipping", table)
        return 0, 0.0

    batch = EMBEDDING_BATCH_SIZE
    num_batches = (total + batch - 1) // batch
    t0 = time.time()
    done = 0

    for i in range(0, total, batch):
        sub = rows[i : i + batch]
        texts = [r["content"] for r in sub]
        lo, hi = i + 1, i + len(sub)
        batch_idx = i // batch + 1

        try:
            vectors = await embed_batch(texts)
        except EmbeddingError as e:
            logger.error(
                "%s batch %d/%d (rows %d-%d) embed_batch failed: %s",
                table, batch_idx, num_batches, lo, hi, e,
            )
            raise

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for row, vec in zip(sub, vectors):
                        await conn.execute(
                            f"UPDATE {table} SET embedding = $1::vector WHERE id = $2",
                            format_vector(vec),
                            row["id"],
                        )
        except Exception as e:
            logger.error(
                "%s batch %d/%d (rows %d-%d) UPDATE failed: %s",
                table, batch_idx, num_batches, lo, hi, e,
            )
            raise

        done += len(sub)
        elapsed = time.time() - t0
        logger.info(
            "%s batch %d/%d (rows %d-%d of %d) elapsed=%.1fs",
            table, batch_idx, num_batches, lo, hi, total, elapsed,
        )

    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 else 0.0
    logger.info("%s DONE: %d rows in %.2fs (%.1f rows/sec)", table, done, elapsed, rate)
    return done, elapsed


async def main() -> int:
    await init_pool()
    try:
        grand_t0 = time.time()
        grand_rows = 0
        for table, text_col in TABLES:
            n, _ = await reembed_table(table, text_col)
            grand_rows += n
        grand_elapsed = time.time() - grand_t0
        logger.info(
            "ALL DONE: %d rows across %d tables in %.2fs",
            grand_rows, len(TABLES), grand_elapsed,
        )
    finally:
        await close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
