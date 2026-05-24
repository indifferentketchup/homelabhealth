#!/usr/bin/env bash
# migrate_column_encryption.sh — encrypt existing plaintext PHI columns.
#
# Encrypts messages.content, notes.content, and custom_instructions.content
# using the HLH_MASTER_KEY set in the hlh_api container environment.
#
# Idempotent: rows already prefixed with "cenc:v1:" are skipped.
# Resumable:  each row is updated in a separate transaction.
# Pre-flight: aborts if HLH_MASTER_KEY is not set.
#
# Usage: bash backend/scripts/migrate_column_encryption.sh
# Requires: hlh_api container to be running with HLH_MASTER_KEY in its env.
set -euo pipefail

echo "=== Column encryption migration ==="
echo "Encrypts existing plaintext content in messages, notes, and custom_instructions."
echo "Requires HLH_MASTER_KEY to be set in the hlh_api container environment."
echo ""

# Pre-flight: verify HLH_MASTER_KEY is set inside the container.
docker exec hlh_api python -c "
import os, sys
key = os.environ.get('HLH_MASTER_KEY', '').strip()
if not key:
    print('ERROR: HLH_MASTER_KEY not set in hlh_api environment')
    sys.exit(1)
print('OK: HLH_MASTER_KEY is configured')
" || { echo "Aborting: pre-flight check failed."; exit 1; }

echo ""
echo "Running migration..."
echo ""

# Stream the migration script into the container via stdin.
# (hlh_api is read_only: true; docker cp is rejected by the daemon.)
docker exec -i hlh_api python - <<'PYEOF'
import asyncio
import os
import sys

sys.path.insert(0, '/app')

from db import init_pool, get_pool, close_pool
from services.crypto import encrypt_column

COL_PREFIX = 'cenc:v1:'


async def migrate() -> None:
    await init_pool()
    pool = await get_pool()

    tables = [
        ('messages', 'id', 'content'),
        ('notes', 'id', 'content'),
        ('custom_instructions', 'id', 'content'),
    ]

    for table, pk, col in tables:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f'SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL'
            )
        encrypted = 0
        skipped = 0
        errors = 0
        for row in rows:
            val = row[col]
            if not val:
                skipped += 1
                continue
            if val.startswith(COL_PREFIX):
                skipped += 1
                continue
            try:
                enc = encrypt_column(val, str(row[pk]))
                async with pool.acquire() as conn:
                    await conn.execute(
                        f'UPDATE {table} SET {col} = $1 WHERE {pk} = $2',
                        enc,
                        row[pk],
                    )
                encrypted += 1
            except Exception as exc:
                print(
                    f'  ERROR: {table} pk={row[pk]}: {exc}',
                    file=sys.stderr,
                )
                errors += 1

        status = f'{table}: encrypted={encrypted}, skipped={skipped}'
        if errors:
            status += f', errors={errors}'
        print(status)

    await close_pool()
    print('')
    print('Migration complete.')


asyncio.run(migrate())
PYEOF

echo ""
echo "=== Done ==="
