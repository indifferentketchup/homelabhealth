"""asyncpg pool + schema apply (schema.sql on startup)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import asyncpg
import chromadb
import sqlparse

_pool: asyncpg.Pool | None = None
_chroma_client: Any = None
_personas_table_columns_cache: frozenset[str] | None = None

_COLLECTION_RE = re.compile(r"[^a-zA-Z0-9_]+")


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


def reset_personas_mode_column_cache() -> None:
    """Invalidate cached `public.personas` column set (e.g. after apply_schema)."""
    global _personas_table_columns_cache
    _personas_table_columns_cache = None


async def personas_table_columns(conn: asyncpg.Connection) -> frozenset[str]:
    """Live column names on `public.personas` (lowercase)."""
    global _personas_table_columns_cache
    if _personas_table_columns_cache is None:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'personas'
            """
        )
        _personas_table_columns_cache = frozenset(str(r["column_name"]) for r in rows)
    return _personas_table_columns_cache


async def personas_has_mode_column(conn: asyncpg.Connection) -> bool:
    """True if `public.personas` has a `mode` column (per-app lists); False for global persona list."""
    return "mode" in await personas_table_columns(conn)


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


def init_chroma() -> None:
    """HTTP client to boolab_chroma (or CHROMA_HOST/CHROMA_PORT). Call after env is loaded."""
    global _chroma_client
    host = (os.environ.get("CHROMA_HOST") or "127.0.0.1").strip()
    port = int((os.environ.get("CHROMA_PORT") or "8000").strip())
    _chroma_client = chromadb.HttpClient(host=host, port=port)


def get_chroma() -> Any:
    if _chroma_client is None:
        raise RuntimeError("Chroma client not initialized (call init_chroma in lifespan)")
    return _chroma_client


def chroma_collection_name_for_daw(daw_id: str) -> str:
    """Chroma collection ids: alphanumeric + underscores only."""
    raw = str(daw_id).replace("-", "_")
    safe = _COLLECTION_RE.sub("_", raw).strip("_") or "unknown"
    return f"daw_{safe}_sources"


def get_chroma_collection(daw_id: str):
    client = get_chroma()
    name = chroma_collection_name_for_daw(daw_id)
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


async def apply_schema() -> None:
    path = Path(__file__).resolve().parent / "schema.sql"
    sql = path.read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        for stmt in _split_sql(sql):
            await conn.execute(stmt)
    reset_personas_mode_column_cache()
