"""asyncpg pool + schema apply (schema.sql on startup)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import asyncpg
import sqlparse

_pool: asyncpg.Pool | None = None

_COLLECTION_RE = re.compile(r"[^a-zA-Z0-9_]+")

# Run before schema.sql so legacy `personas.mode` is removed before any constraint/index DDL runs.
_PERSONAS_DROP_MODE_SQL = r"""
DO $personas_drop_mode$
BEGIN
  IF to_regclass('public.personas') IS NULL THEN
    RETURN;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'personas' AND column_name = 'mode'
  ) THEN
    ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default_booops BOOLEAN DEFAULT FALSE;
    ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default_808notes BOOLEAN DEFAULT FALSE;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'personas' AND column_name = 'is_default'
    ) THEN
      UPDATE personas SET is_default_booops = TRUE
      WHERE mode = 'booops' AND is_default IS TRUE;
      UPDATE personas SET is_default_808notes = TRUE
      WHERE mode = '808notes' AND is_default IS TRUE;
    END IF;
    DROP INDEX IF EXISTS personas_one_default_per_mode;
    ALTER TABLE personas DROP CONSTRAINT IF EXISTS personas_mode_check;
    ALTER TABLE personas DROP COLUMN IF EXISTS mode;
  END IF;
END
$personas_drop_mode$;
"""


def normalize_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_pool() -> asyncpg.Pool:
    global _pool
    url = os.environ["DATABASE_URL"]
    _pool = await asyncpg.create_pool(
        normalize_database_url(url),
        min_size=1,
        max_size=10,
    )
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _split_sql(script: str) -> list[str]:
    parts: list[str] = []
    for raw in sqlparse.split(script):
        s = raw.strip()
        if s:
            parts.append(s)
    return parts


async def apply_schema() -> None:
    path = Path(__file__).resolve().parent / "schema.sql"
    sql = path.read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_PERSONAS_DROP_MODE_SQL)
        for stmt in _split_sql(sql):
            await conn.execute(stmt)
