"""Ensure the single owner row exists. Single-user app  -  password column is dead weight."""

from __future__ import annotations

import logging

from db import get_pool

logger = logging.getLogger(__name__)

SUPER_ADMIN_USERNAME = "owner"


async def ensure_super_admin() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE lower(username) = lower($1)",
            SUPER_ADMIN_USERNAME,
        )
        if row is not None:
            await conn.execute(
                "UPDATE users SET role = 'owner' WHERE lower(username) = lower($1)",
                SUPER_ADMIN_USERNAME,
            )
            return
        await conn.execute(
            """
            INSERT INTO users (username, role, display_name, avatar_emoji, bio)
            VALUES ($1, 'owner', $1, '👤', '')
            """,
            SUPER_ADMIN_USERNAME,
        )
        logger.info("Created owner user %s", SUPER_ADMIN_USERNAME)
