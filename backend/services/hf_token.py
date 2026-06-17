"""HF token storage  -  singleton DB row, encrypted via services.crypto.

Resolution order in callers (see model_puller._hf_headers):
  1. get(conn)  -  this module's DB-backed value
  2. HF_TOKEN env var (legacy fallback)
  3. None (no Authorization header sent)

Spec: docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md §5
"""
from __future__ import annotations

import re
from typing import Any

from services.crypto import decrypt_secret, encrypt_secret

_TOKEN_RE = re.compile(r"^hf_[A-Za-z0-9_]{20,}$")


def _validate(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        raise ValueError("HF token cannot be empty")
    if not _TOKEN_RE.match(s):
        raise ValueError("HF token must start with 'hf_' followed by 20+ alphanumeric/underscore chars")
    return s


async def get(conn: Any) -> str | None:
    row = await conn.fetchrow(
        "SELECT token_encrypted FROM hf_token_config WHERE id = 1"
    )
    if row is None or row["token_encrypted"] is None:
        return None
    return decrypt_secret(row["token_encrypted"])


async def set_token(conn: Any, raw: str) -> None:
    token = _validate(raw)
    encrypted = encrypt_secret(token)
    await conn.execute(
        """
        INSERT INTO hf_token_config (id, token_encrypted, updated_at)
        VALUES (1, $1, NOW())
        ON CONFLICT (id) DO UPDATE
        SET token_encrypted = EXCLUDED.token_encrypted,
            updated_at = NOW()
        """,
        encrypted,
    )


async def clear(conn: Any) -> None:
    await conn.execute("DELETE FROM hf_token_config")


async def masked(conn: Any) -> tuple[bool, str | None, Any]:
    """Returns (configured, masked_string, updated_at)."""
    row = await conn.fetchrow(
        "SELECT token_encrypted, updated_at FROM hf_token_config WHERE id = 1"
    )
    if row is None or row["token_encrypted"] is None:
        return False, None, None
    token = decrypt_secret(row["token_encrypted"]) or ""
    if len(token) < 8:
        return True, "hf_…" + token[-2:], row["updated_at"]
    return True, "hf_…" + token[-4:], row["updated_at"]
