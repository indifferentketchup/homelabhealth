"""Seed a single default 'Assistant' persona on first startup. Idempotent."""

from __future__ import annotations

import logging

from db import get_pool

logger = logging.getLogger(__name__)


async def seed_default_assets() -> None:
    """Insert a single default persona if the personas table is empty."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM personas")
        if existing and existing > 0:
            return
        await conn.execute(
            """
            INSERT INTO personas (name, system_prompt, avatar_emoji, is_default_808notes)
            VALUES ($1::text, $2::text, $3::text, TRUE)
            """,
            "Assistant",
            "You are a helpful AI assistant.",
            "🤖",
        )
        logger.info("Seeded default persona: Assistant")
