"""Auto-seed bundled inference providers — Phase 1.

A "bundled" provider is one that the homelabhealth stack runs itself
(via the docker-compose `chat` profile / Phase 1's hlh_chat sidecar).
This module owns the (idempotent) upsert of those provider rows.

Phase 1 ships the chat provider only. Phase 2 will extend with
embedding + reranker bundled providers (separate functions, same
pattern).

Design: hlh_phase1_design.md §services/bundled_providers.py
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


BUNDLED_CHAT_NAME = "bundled-chat"
BUNDLED_CHAT_BASE_URL = "http://hlh_chat:9610"


async def _read_system_profile(conn) -> dict[str, Any] | None:
    return await conn.fetchrow(
        "SELECT tier, setup_complete FROM system_profile WHERE id = 1"
    )


async def ensure_bundled_chat_provider(conn) -> str | None:
    """Idempotent upsert of the bundled-chat provider row.

    No-op unless `system_profile.setup_complete = TRUE` AND `tier <> 'external'`.
    On conflict (existing row with name='bundled-chat'), refresh base_url +
    enabled=TRUE but preserve the operator's api_key value (if they manually
    set one for any reason).

    Returns the provider uuid as a string, or None if no-op.
    """
    profile = await _read_system_profile(conn)
    if profile is None:
        logger.info("bundled_providers: no system_profile row; skipping seed")
        return None
    if not bool(profile["setup_complete"]):
        logger.info("bundled_providers: setup_complete=false; skipping bundled-chat seed")
        return None
    if profile["tier"] == "external":
        logger.info("bundled_providers: tier=external; skipping bundled-chat seed")
        return None

    row = await conn.fetchrow(
        """
        INSERT INTO providers (name, base_url, api_key, enabled)
        VALUES ($1, $2, NULL, TRUE)
        ON CONFLICT (name) DO UPDATE
        SET base_url = EXCLUDED.base_url,
            enabled = TRUE,
            updated_at = NOW()
        RETURNING id
        """,
        BUNDLED_CHAT_NAME,
        BUNDLED_CHAT_BASE_URL,
    )
    pid = str(row["id"]) if row else None
    if pid:
        logger.info(
            "bundled_providers: ensured %s provider at %s (id=%s)",
            BUNDLED_CHAT_NAME, BUNDLED_CHAT_BASE_URL, pid,
        )
    return pid
