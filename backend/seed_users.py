"""Ensure built-in site owner DB account (samkintop) exists."""

from __future__ import annotations

import logging

from auth_deps import pwd_context
from db import get_pool

logger = logging.getLogger(__name__)

SUPER_ADMIN_USERNAME = "samkintop"
SUPER_ADMIN_DEFAULT_PASSWORD = "Ketchup"


async def ensure_super_admin() -> None:
    """Insert samkintop as role owner if missing; migrate legacy super_admin row; never overwrites password."""
    h = pwd_context.hash(SUPER_ADMIN_DEFAULT_PASSWORD)
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
            INSERT INTO users (username, password_hash, role, display_name, avatar_emoji, bio)
            VALUES ($1, $2, 'owner', $1, '👤', '')
            """,
            SUPER_ADMIN_USERNAME,
            h,
        )
        logger.info("Created owner user %s (default password — change after first login)", SUPER_ADMIN_USERNAME)
