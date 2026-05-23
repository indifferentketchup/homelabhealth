#!/usr/bin/env bash
# Verify audit_log schema + hash chain insert + chain integrity detection.
# Spec: docs/superpowers/specs/2026-05-23-v0.11.0-c4-audit-logging-design.md
#
# Drives insert_audit_event() and verify_chain() from services/audit.py via
# the hlh_api container. Since hlh_api is read_only:true, docker cp is blocked;
# we stream Python code over stdin instead (printf | docker exec -i).
#
# Crash-safety: the insert step writes each row id to /tmp/verify_audit_log_ids.txt
# (on the host) as it completes, so the trap can clean up partial inserts.
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "  OK: $*"; }

AUDIT_PY_PATH="/opt/homelabhealth-v0.11.0/backend/services/audit.py"
IDS_FILE="/tmp/verify_audit_log_ids.txt"

# Reset the IDs file at start so prior aborted runs don't leak ids in.
: > "$IDS_FILE"

# ─── Pre-state capture ────────────────────────────────────────────────────────
PRE_COUNT=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT COUNT(*) FROM audit_log;" | tr -d '[:space:]')
PRE_CHAIN_HASH=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT encode(last_hash, 'hex') FROM audit_log_chain_head WHERE id = 1;" | tr -d '[:space:]')
echo "Pre-state: row_count=$PRE_COUNT  chain_head=$PRE_CHAIN_HASH"

MIDDLE_ID=""
MIDDLE_ORIG_TARGET=""

# ─── Cleanup trap ─────────────────────────────────────────────────────────────
# Reads inserted ids from the temp file (populated incrementally by the insert
# step) so a mid-stream crash still results in clean DB state.
cleanup() {
  echo "=== Cleanup ==="
  local ids_csv=""
  if [[ -s "$IDS_FILE" ]]; then
    ids_csv=$(tr '\n' ',' < "$IDS_FILE" | sed 's/,$//')
  fi
  if [[ -n "$ids_csv" ]]; then
    docker exec hlh_db psql -U hlh -d hlh -c \
      "DELETE FROM audit_log WHERE id IN ($ids_csv);" >/dev/null 2>&1 || true
    echo "  Deleted test rows: $ids_csv"
  else
    echo "  No inserted ids to delete"
  fi
  # Always restore chain head to pre-test state (hlh role can UPDATE directly).
  docker exec hlh_db psql -U hlh -d hlh -c \
    "UPDATE audit_log_chain_head SET last_hash = decode('${PRE_CHAIN_HASH}', 'hex') WHERE id = 1;" \
    >/dev/null 2>&1 || true
  echo "  Restored chain head to $PRE_CHAIN_HASH"
  rm -f "$IDS_FILE"
}
trap cleanup EXIT

# ─── Step 1: Insert 3 known audit records via hlh_api python (stdin stream) ───
echo
echo "=== 1. Insert 3 audit records ==="

# Load the audit module source from the worktree; stream it into hlh_api via
# stdin together with the driver code, split by a sentinel string.
# The driver writes each inserted id to stdout immediately after the insert
# returns, AND prints the comma-joined list on the last line. Bash captures
# only the final line via tail -1; the trap reads partial ids from the host
# temp file populated by the bash side as we parse stdout.
AUDIT_SRC=$(cat "$AUDIT_PY_PATH")

# Insert driver: prints "INSERTED:<id>" per row, then "IDS:<csv>" at the end.
INSERT_STDOUT=$(printf '%s\n<<<DRIVER>>>\n' "$AUDIT_SRC" | docker exec -i hlh_api python3 -c "
import sys, types, asyncio, os, hashlib, uuid

src = sys.stdin.read()
parts = src.split('<<<DRIVER>>>')

# Register module under its real name before exec so @dataclass can resolve __module__
_audit_mod = types.ModuleType('services.audit')
_audit_mod.__name__ = 'services.audit'
_audit_mod.__package__ = 'services'
sys.modules['services.audit'] = _audit_mod
exec(compile(parts[0], 'services/audit.py', 'exec'), _audit_mod.__dict__)

insert_audit_event = _audit_mod.insert_audit_event
AuditRecord = _audit_mod.AuditRecord

import asyncpg

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://hlh:hlh@hlh_db:5432/hlh')
DATABASE_URL = DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')

records = [
    AuditRecord(
        request_id=uuid.UUID('aaaaaaaa-0000-0000-0000-000000000001'),
        actor='verify-script',
        action='chat.send',
        target_type='chat',
        target_id='test-chat-1',
        status_code=200,
        payload_hash=hashlib.sha256(b'payload-a').digest(),
    ),
    AuditRecord(
        request_id=uuid.UUID('aaaaaaaa-0000-0000-0000-000000000002'),
        actor='verify-script',
        action='source.read',
        target_type='source',
        target_id='test-source-1',
        status_code=200,
        payload_hash=hashlib.sha256(b'payload-b').digest(),
    ),
    AuditRecord(
        request_id=uuid.UUID('aaaaaaaa-0000-0000-0000-000000000003'),
        actor='verify-script',
        action='note.create',
        target_type='note',
        target_id='test-note-1',
        status_code=201,
        payload_hash=hashlib.sha256(b'payload-c').digest(),
    ),
]

async def run():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        ids = []
        for rec in records:
            row_id = await insert_audit_event(conn, rec)
            ids.append(row_id)
            # Emit per-row immediately so bash can persist partial progress.
            print(f'INSERTED:{row_id}', flush=True)
        print('IDS:' + ','.join(str(i) for i in ids), flush=True)
    finally:
        await conn.close()

asyncio.run(run())
")

# Persist every INSERTED:<id> line to the trap-readable file as we parse it.
while IFS= read -r line; do
  case "$line" in
    INSERTED:*)
      echo "${line#INSERTED:}" >> "$IDS_FILE"
      ;;
  esac
done <<<"$INSERT_STDOUT"

INSERTED_IDS=$(echo "$INSERT_STDOUT" | awk -F: '/^IDS:/{print $2}' | tail -1)
echo "  Inserted row ids: $INSERTED_IDS"
[[ -n "$INSERTED_IDS" ]] || fail "No IDs returned from insert step"

# Extract individual IDs
ID1=$(echo "$INSERTED_IDS" | cut -d',' -f1)
ID2=$(echo "$INSERTED_IDS" | cut -d',' -f2)
ID3=$(echo "$INSERTED_IDS" | cut -d',' -f3)
MIDDLE_ID="$ID2"
ok "3 rows inserted: ids=$ID1,$ID2,$ID3"

# Capture original target_id of middle row for restore later
MIDDLE_ORIG_TARGET=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT target_id FROM audit_log WHERE id = $MIDDLE_ID;" | tr -d '[:space:]')
echo "  Middle row original target_id: $MIDDLE_ORIG_TARGET"

# ─── verify_chain helper — fetches ALL rows id ASC, runs verify_chain ─────────
# Pre-state may contain rows; verify_chain assumes the first row in the input
# is the genesis row (prev_hash == 32 zero bytes). The only way to be correct
# on any pre-state is to verify the full chain from id=1.
run_full_verify() {
  printf '%s\n<<<DRIVER>>>\n' "$AUDIT_SRC" | docker exec -i hlh_api python3 -c "
import sys, types, asyncio, os

src = sys.stdin.read()
parts = src.split('<<<DRIVER>>>')
_audit_mod = types.ModuleType('services.audit')
_audit_mod.__name__ = 'services.audit'
_audit_mod.__package__ = 'services'
sys.modules['services.audit'] = _audit_mod
exec(compile(parts[0], 'services/audit.py', 'exec'), _audit_mod.__dict__)
verify_chain = _audit_mod.verify_chain

import asyncpg

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://hlh:hlh@hlh_db:5432/hlh')
DATABASE_URL = DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')

async def run():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            'SELECT id, ts, request_id, actor, action, target_type, target_id, '
            'status_code, payload_hash, prev_hash, row_hash '
            'FROM audit_log ORDER BY id ASC'
        )
        ok, bad_id = verify_chain(rows)
        print(f'ok={ok} bad_id={bad_id}')
    finally:
        await conn.close()

asyncio.run(run())
"
}

# ─── Step 2: Verify chain PASS ────────────────────────────────────────────────
echo
echo "=== 2. Full-chain verification (expect PASS) ==="
VERIFY_RESULT=$(run_full_verify)
echo "  verify_chain result: $VERIFY_RESULT"
echo "$VERIFY_RESULT" | grep -q "ok=True bad_id=None" \
  && ok "Chain intact (PASS)" \
  || fail "Chain verification failed unexpectedly: $VERIFY_RESULT"

# ─── Step 3: Tamper with middle row ───────────────────────────────────────────
echo
echo "=== 3. Tamper: UPDATE middle row target_id ==="
docker exec hlh_db psql -U hlh -d hlh -c \
  "UPDATE audit_log SET target_id = 'tampered' WHERE id = $MIDDLE_ID;" >/dev/null
ok "Tampered row id=$MIDDLE_ID (target_id set to 'tampered')"

# ─── Step 4: Re-verify — expect FAIL at middle row ────────────────────────────
echo
echo "=== 4. Full-chain verification after tamper (expect FAIL at id=$MIDDLE_ID) ==="
TAMPER_RESULT=$(run_full_verify)
echo "  verify_chain result: $TAMPER_RESULT"
echo "$TAMPER_RESULT" | grep -q "ok=False bad_id=$MIDDLE_ID" \
  && ok "Chain break detected at correct row (PASS)" \
  || fail "Tamper not detected correctly: got '$TAMPER_RESULT', expected 'ok=False bad_id=$MIDDLE_ID'"

# ─── Step 5: Restore tampered row ─────────────────────────────────────────────
echo
echo "=== 5. Restore tampered row ==="
docker exec hlh_db psql -U hlh -d hlh -c \
  "UPDATE audit_log SET target_id = '$MIDDLE_ORIG_TARGET' WHERE id = $MIDDLE_ID;" >/dev/null
ok "Restored target_id='$MIDDLE_ORIG_TARGET' on row id=$MIDDLE_ID"

# ─── Step 6: Re-verify after restore — expect PASS ────────────────────────────
echo
echo "=== 6. Full-chain verification after restore (expect PASS) ==="
RESTORE_RESULT=$(run_full_verify)
echo "  verify_chain result: $RESTORE_RESULT"
echo "$RESTORE_RESULT" | grep -q "ok=True bad_id=None" \
  && ok "Chain intact after restore (PASS)" \
  || fail "Chain broken after restore: $RESTORE_RESULT"

echo
echo "VERIFY: audit_log chain integrity — PASS"
