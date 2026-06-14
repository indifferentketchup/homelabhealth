"""Verify B0 safeguard prepend behaves correctly inside _assembled_system_prompt.

Run inside the hlh_api container:
    docker exec hlh_api python scripts/verify_safeguards_assembler.py

Covers acceptance #3 (empty workspace prompt) and #4 (non-empty + RAG-absent)
from the B0 dispatch. Uses real DB rows + the real assembler, no mocking.
Idempotent: cleans up its own test rows on exit.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg

from db import close_pool, get_pool, init_pool  # noqa: E402
from services.prompt_assembly import _assembled_system_prompt  # noqa: E402
from services.safeguards import SAFEGUARD_SYSTEM_PROMPT  # noqa: E402


async def _make_workspace(conn: asyncpg.Connection, system_prompt: str) -> uuid.UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO workspaces (name, system_prompt, rag_mode, owner_id)
        VALUES ($1, $2, 'always',
                (SELECT id FROM users LIMIT 1))
        RETURNING id
        """,
        "verify-safeguards-tmp",
        system_prompt,
    )
    return row["id"]


async def _make_chat(conn: asyncpg.Connection, workspace_id: uuid.UUID) -> asyncpg.Record:
    chat_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO chats (id, title, workspace_id, web_search_enabled, rag_enabled, owner_id)
        VALUES ($1::uuid, 'verify-tmp', $2::uuid, FALSE, FALSE,
                (SELECT id FROM users LIMIT 1))
        """,
        chat_id,
        workspace_id,
    )
    return await conn.fetchrow(
        """
        SELECT id, workspace_id, web_search_enabled, rag_enabled
        FROM chats WHERE id = $1::uuid
        """,
        chat_id,
    )


async def _cleanup(conn: asyncpg.Connection, workspace_id: uuid.UUID) -> None:
    await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", workspace_id)


async def run() -> int:
    await init_pool()
    pool = await get_pool()
    failures: list[str] = []

    async with pool.acquire() as conn:
        # --- Acceptance #3: empty workspace prompt, no RAG ---
        ws_id = await _make_workspace(conn, "")
        try:
            chat = await _make_chat(conn, ws_id)
            assembled, rag_meta, _rag_block = await _assembled_system_prompt(
                conn,
                chat,
                user_query_for_rag=None,
                include_site_private=False,
            )
            if assembled != SAFEGUARD_SYSTEM_PROMPT:
                failures.append(
                    "Acceptance #3 FAIL: empty-workspace assembled string "
                    f"does not equal SAFEGUARD_SYSTEM_PROMPT exactly "
                    f"(got len={len(assembled)}, expected len={len(SAFEGUARD_SYSTEM_PROMPT)})"
                )
            else:
                print("✓ Acceptance #3: empty workspace prompt → assembled == SAFEGUARD exactly")
            if rag_meta is not None:
                failures.append(f"Acceptance #3 FAIL: expected rag_meta=None, got {rag_meta}")
        finally:
            await _cleanup(conn, ws_id)

        # --- Acceptance #4: non-empty workspace prompt ---
        WS_PROMPT = "Refer to me as Doc."
        ws_id = await _make_workspace(conn, WS_PROMPT)
        try:
            chat = await _make_chat(conn, ws_id)
            assembled, rag_meta, _rag_block = await _assembled_system_prompt(
                conn,
                chat,
                user_query_for_rag=None,
                include_site_private=False,
            )
            expected_prefix = SAFEGUARD_SYSTEM_PROMPT + "\n\n"
            if not assembled.startswith(expected_prefix):
                failures.append(
                    "Acceptance #4 FAIL: assembled does not start with SAFEGUARD + \\n\\n"
                )
            elif assembled[len(expected_prefix):] != WS_PROMPT:
                failures.append(
                    f"Acceptance #4 FAIL: workspace prompt mismatch after safeguard. "
                    f"Got {assembled[len(expected_prefix):]!r}"
                )
            else:
                print(
                    "✓ Acceptance #4: non-empty workspace prompt → "
                    "SAFEGUARD + \\n\\n + workspace_prompt"
                )
        finally:
            await _cleanup(conn, ws_id)

    await close_pool()

    if failures:
        print("\n".join(failures))
        return 1
    print("\nAll safeguard-assembler acceptance checks PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
