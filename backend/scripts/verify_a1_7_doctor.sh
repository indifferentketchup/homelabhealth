#!/usr/bin/env bash
# Verify A1.7 doctor + acknowledgement endpoint.
# Spec: docs/superpowers/specs/2026-05-22-a1.5-a1.7-bundled-tail-design.md §5
set -euo pipefail

API="${API:-http://localhost:9600}"
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "  ✓ $*"; }

echo "=== 1. GET /api/system/doctor shape ==="
resp=$(curl -sS "$API/api/system/doctor")
echo "$resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'checks' in d, 'missing checks'
assert isinstance(d['checks'], list), 'checks not list'
assert len(d['checks']) >= 11, f\"only {len(d['checks'])} checks (expected >=11)\"
assert 'summary' in d, 'missing summary'
for k in ('ok','warn','error'):
    assert k in d['summary'], f'summary missing {k}'
for c in d['checks']:
    assert set(c.keys()) >= {'name','status','detail'}, f'check shape wrong: {c}'
    assert c['status'] in ('ok','warn','error'), f\"bad status {c['status']}\"
print('OK: shape valid')
"
ok "doctor JSON shape"

echo
echo "=== 2. CLI mode exits 0/1 appropriately ==="
if docker exec hlh_api python -m hlh.doctor >/dev/null 2>&1; then ec=0; else ec=$?; fi
[[ "$ec" == "0" || "$ec" == "1" ]] && ok "exit code $ec" || fail "unexpected CLI exit $ec"

echo
echo "=== 3. acknowledgement flow ==="
docker exec hlh_db psql -U hlh -d hlh -c "UPDATE system_profile SET acknowledged_at = NULL WHERE id = 1;" >/dev/null
before=$(curl -sS "$API/api/system/profile" | python3 -c "import sys,json; print(json.load(sys.stdin).get('acknowledged_at'))")
[[ "$before" == "None" ]] && ok "before: acknowledged_at is null" || fail "expected null, got $before"

code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API/api/system/acknowledge")
[[ "$code" == "204" ]] && ok "POST returns 204" || fail "POST got $code"

after=$(curl -sS "$API/api/system/profile" | python3 -c "import sys,json; print(json.load(sys.stdin).get('acknowledged_at'))")
[[ "$after" != "None" ]] && ok "after: acknowledged_at = $after" || fail "still null after POST"

echo
echo "=== ALL CHECKS PASSED ==="
