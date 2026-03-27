"""Ensure built-in super-admin account exists (persistent DB user)."""

from __future__ import annotations

import logging

from auth_deps import pwd_context
from db import get_pool

logger = logging.getLogger(__name__)

SUPER_ADMIN_USERNAME = "samkintop"
SUPER_ADMIN_DEFAULT_PASSWORD = "Ketchup"


async def ensure_super_admin() -> None:
    """Insert samkintop if missing; does not overwrite password if user already exists."""
    h = pwd_context.hash(SUPER_ADMIN_DEFAULT_PASSWORD)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE lower(username) = lower($1)",
            SUPER_ADMIN_USERNAME,
        )
        if row is not None:
            return
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, role, display_name, avatar_emoji, bio)
            VALUES ($1, $2, 'super_admin', $1, '👤', '')
            """,
            SUPER_ADMIN_USERNAME,
            h,
        )
        logger.info("Created super-admin user %s (default password — change after first login)", SUPER_ADMIN_USERNAME)
