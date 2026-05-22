"""Verify B0 safeguard_version persistence: assistant INSERT stamps, user
INSERT leaves NULL, fork copies preserve source value verbatim (NULL stays
NULL for pre-B0 history; populated copies forward).

Mirrors the four INSERT/SELECT shapes in routers/chats.py:
  - User message INSERT (line ~950): no safeguard_version column → NULL
  - Assistant streaming INSERT (line ~1103): safeguard_version = current_version()
  - Fork SELECT (line ~836): reads safeguard_version
  - Fork INSERT (line ~880): writes safeguard_version verbatim from source row

If chats.py SQL drifts, this script will FAIL. That's the regression signal.

Run inside the hlh_api container:
    docker exec hlh_api python scripts/verify_safeguards_persistence.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import close_pool, get_pool, init_pool  # noqa: E402
from services.safeguards import current_version  # noqa: E402


VERSION = current_version()


async def _make_workspace(conn) -> uuid.UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO workspaces (name, system_prompt, rag_mode, owner_id)
        VALUES ($1, '', 'always', (SELECT id FROM users LIMIT 1))
        RETURNING id
        """,
        "verify-safeguards-persist-tmp",
    )
    return row["id"]


async def _make_chat(conn, workspace_id: uuid.UUID) -> uuid.UUID:
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
    return chat_id


async def _insert_user_msg(conn, chat_id: uuid.UUID, content: str) -> uuid.UUID:
    """Mirror of chats.py line ~950 user-message INSERT (no safeguard_version column)."""
    user_msg_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, content, model)
        VALUES ($1::uuid, $2::uuid, 'user', $3, $4)
        """,
        user_msg_id,
        chat_id,
        content,
        "verify-model",
    )
    return user_msg_id


async def _insert_assistant_msg(conn, chat_id: uuid.UUID, content: str) -> uuid.UUID:
    """Mirror of chats.py line ~1103 assistant-streaming INSERT (stamps current_version)."""
    assist_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, content, model, safeguard_version)
        VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4, $5)
        """,
        assist_id,
        chat_id,
        content,
        "verify-model",
        current_version(),
    )
    return assist_id


async def _insert_pre_b0_assistant_msg(conn, chat_id: uuid.UUID, content: str) -> uuid.UUID:
    """Simulate a pre-B0 assistant row that predates the safeguard_version column,
    explicitly NULL safeguard_version.
    """
    assist_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, content, model, safeguard_version)
        VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4, NULL)
        """,
        assist_id,
        chat_id,
        content,
        "verify-model",
    )
    return assist_id


async def _fork_messages(conn, source_chat_id: uuid.UUID, target_chat_id: uuid.UUID) -> int:
    """Mirror of chats.py fork SELECT (line ~836) + INSERT loop (line ~880).
    Returns count of copied rows."""
    msg_rows = await conn.fetch(
        """
        SELECT id, role, content, model, tokens_used, sources_used, safeguard_version
        FROM messages
        WHERE chat_id = $1::uuid
        ORDER BY created_at ASC, id ASC
        """,
        source_chat_id,
    )
    for r in msg_rows:
        mid = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO messages (
                id, chat_id, role, content, model, tokens_used, sources_used, forked_from, safeguard_version
            )
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid, $9)
            """,
            mid,
            target_chat_id,
            r["role"],
            r["content"],
            r["model"],
            r["tokens_used"],
            r["sources_used"],
            r["id"],
            r["safeguard_version"],
        )
    return len(msg_rows)


async def _cleanup(conn, workspace_id: uuid.UUID) -> None:
    """Workspace delete cascades via chats → messages."""
    await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", workspace_id)


async def run() -> int:
    await init_pool()
    pool = await get_pool()
    failures: list[str] = []

    async with pool.acquire() as conn:
        ws_id = await _make_workspace(conn)
        try:
            # --- Test 1: assistant INSERT stamps current_version ---
            chat_id = await _make_chat(conn, ws_id)
            await _insert_user_msg(conn, chat_id, "What is hypertension?")
            assist_id = await _insert_assistant_msg(conn, chat_id, "Educational reply text.")
            row = await conn.fetchrow(
                "SELECT role, safeguard_version FROM messages WHERE id = $1::uuid",
                assist_id,
            )
            if row["safeguard_version"] != VERSION:
                failures.append(
                    f"Test 1 FAIL: assistant safeguard_version expected {VERSION!r}, "
                    f"got {row['safeguard_version']!r}"
                )
            else:
                print(f"✓ Test 1: assistant INSERT stamps safeguard_version={VERSION!r}")

            # --- Test 2: user INSERT leaves NULL ---
            user_id = await conn.fetchval(
                "SELECT id FROM messages WHERE chat_id = $1::uuid AND role='user'",
                chat_id,
            )
            user_row = await conn.fetchrow(
                "SELECT role, safeguard_version FROM messages WHERE id = $1::uuid",
                user_id,
            )
            if user_row["safeguard_version"] is not None:
                failures.append(
                    f"Test 2 FAIL: user safeguard_version expected NULL, "
                    f"got {user_row['safeguard_version']!r}"
                )
            else:
                print("✓ Test 2: user INSERT leaves safeguard_version=NULL")

            # --- Test 3: fork preserves NULL for pre-B0 assistant rows ---
            pre_b0_chat = await _make_chat(conn, ws_id)
            await _insert_user_msg(conn, pre_b0_chat, "Pre-B0 question.")
            pre_b0_assist = await _insert_pre_b0_assistant_msg(
                conn, pre_b0_chat, "Pre-B0 reply."
            )
            forked_chat = await _make_chat(conn, ws_id)
            copied = await _fork_messages(conn, pre_b0_chat, forked_chat)
            # Find the forked copy of the pre-B0 assistant message
            forked_copy = await conn.fetchrow(
                """
                SELECT role, safeguard_version
                FROM messages
                WHERE chat_id = $1::uuid AND forked_from = $2::uuid
                """,
                forked_chat,
                pre_b0_assist,
            )
            if forked_copy is None:
                failures.append("Test 3 FAIL: forked copy of pre-B0 assistant row not found")
            elif forked_copy["safeguard_version"] is not None:
                failures.append(
                    f"Test 3 FAIL: forked copy of pre-B0 row expected NULL, "
                    f"got {forked_copy['safeguard_version']!r}"
                )
            else:
                print(
                    f"✓ Test 3: fork preserves NULL safeguard_version on pre-B0 row "
                    f"(copied {copied} messages)"
                )

            # --- Test 4: fork preserves current_version for B0 assistant rows ---
            b0_chat = await _make_chat(conn, ws_id)
            await _insert_user_msg(conn, b0_chat, "B0 question.")
            b0_assist = await _insert_assistant_msg(conn, b0_chat, "B0 reply.")
            forked_b0 = await _make_chat(conn, ws_id)
            await _fork_messages(conn, b0_chat, forked_b0)
            forked_b0_copy = await conn.fetchrow(
                """
                SELECT role, safeguard_version
                FROM messages
                WHERE chat_id = $1::uuid AND forked_from = $2::uuid
                """,
                forked_b0,
                b0_assist,
            )
            if forked_b0_copy is None:
                failures.append("Test 4 FAIL: forked copy of B0 assistant row not found")
            elif forked_b0_copy["safeguard_version"] != VERSION:
                failures.append(
                    f"Test 4 FAIL: forked copy of B0 row expected {VERSION!r}, "
                    f"got {forked_b0_copy['safeguard_version']!r}"
                )
            else:
                print(f"✓ Test 4: fork preserves safeguard_version={VERSION!r} on B0 row")
        finally:
            await _cleanup(conn, ws_id)

    await close_pool()

    if failures:
        print("\n".join(failures))
        return 1
    print(f"\nAll safeguard-persistence acceptance checks PASS (version: {VERSION}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
