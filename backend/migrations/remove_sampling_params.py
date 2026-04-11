"""Remove sampling parameter columns from daws table and global_settings rows."""

from __future__ import annotations

import asyncio
import asyncpg


async def migrate(conn: asyncpg.Connection) -> None:
    """Drop sampling parameter columns from daws table and delete global_settings rows."""
    await conn.execute("""
        ALTER TABLE daws
        DROP COLUMN IF EXISTS temperature,
        DROP COLUMN IF EXISTS max_tokens,
        DROP COLUMN IF EXISTS top_p,
        DROP COLUMN IF EXISTS top_k,
        DROP COLUMN IF EXISTS context_window
    """)
    
    await conn.execute("""
        DELETE FROM global_settings
        WHERE key IN (
            'temperature_global',
            'top_p_global',
            'top_k_global',
            'max_tokens_global',
            'context_window_global'
        )
    """)


async def main():
    """Run migration."""
    url = "postgresql://postgres:postgres@localhost:5432/postgres"
    if "DATABASE_URL" in __import__("os").environ:
        url = __import__("os").environ["DATABASE_URL"]
    
    conn = await asyncpg.connect(url)
    try:
        await migrate(conn)
        print("Migration completed successfully")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
