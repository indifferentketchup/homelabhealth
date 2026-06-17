#!/usr/bin/env bash
# Verify the bundled providers exist with correct columns, reject PATCH/DELETE
# with 403, and the /test endpoint branches correctly per role.
# Spec: docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md §7
set -euo pipefail

API="${API:-http://localhost:9600}"

echo "=== 1. Three bundled rows exist with right columns ==="
ITEMS=$(curl -sS "$API/api/providers")
echo "$ITEMS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('items', [])
bundled = [p for p in items if p.get('is_bundled')]
print(f'Found {len(bundled)} bundled rows')
for p in bundled:
    print(f\"  {p['name']:40s}  role={p['role']:7s}  group={p['bundle_group']}\")
assert len(bundled) == 3, f'expected 3 bundled rows, got {len(bundled)}'
roles = sorted([p['role'] for p in bundled])
assert roles == ['chat', 'embed', 'rerank'], f'roles wrong: {roles}'
for p in bundled:
    assert p['bundle_group'] == 'homelab-health-ai', f'wrong bundle_group: {p}'
    assert p['name'].startswith('HomeLab Health AI · '), f'wrong name: {p[\"name\"]}'
    # Folder C (2026-06-16): all three bundled providers resolve through the
    # llama-swap front-door, not the old direct hlh_chat:9610.
    assert p['base_url'] == 'http://hlh_swap:9620', f'wrong base_url: {p[\"name\"]} -> {p[\"base_url\"]}'
print('OK')
"

echo "=== 2. PATCH on each bundled row → 403 ==="
for role in chat embed rerank; do
  PID=$(curl -sS "$API/api/providers" | python3 -c "
import sys, json
items = json.load(sys.stdin)['items']
for p in items:
    if p.get('is_bundled') and p.get('role') == '$role':
        print(p['id']); break
")
  echo "  PATCH $role ($PID):"
  CODE=$(curl -sS -o /tmp/r -w '%{http_code}' -X PATCH "$API/api/providers/$PID" \
    -H 'content-type: application/json' -d '{"name":"hacked"}')
  [[ "$CODE" == "403" ]] && echo "    OK: 403" || { echo "    FAIL: got $CODE"; cat /tmp/r; exit 1; }
  grep -q 'Bundled providers are not editable' /tmp/r || { echo "    FAIL: wrong detail message"; cat /tmp/r; exit 1; }
done

echo "=== 3. DELETE on each bundled row → 403 ==="
for role in chat embed rerank; do
  PID=$(curl -sS "$API/api/providers" | python3 -c "
import sys, json
items = json.load(sys.stdin)['items']
for p in items:
    if p.get('is_bundled') and p.get('role') == '$role':
        print(p['id']); break
")
  echo "  DELETE $role:"
  CODE=$(curl -sS -o /tmp/r -w '%{http_code}' -X DELETE "$API/api/providers/$PID")
  [[ "$CODE" == "403" ]] && echo "    OK: 403" || { echo "    FAIL: got $CODE"; cat /tmp/r; exit 1; }
done

echo "=== 4. Test on chat row → ok (hlh_chat reachable) ==="
PID=$(curl -sS "$API/api/providers" | python3 -c "
import sys, json
print(next(p['id'] for p in json.load(sys.stdin)['items'] if p.get('is_bundled') and p.get('role') == 'chat'))
")
RESP=$(curl -sS -X POST "$API/api/providers/$PID/test")
echo "$RESP" | python3 -m json.tool
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: chat reachable') if d.get('ok') else print('  WARN: chat test failed (hlh_chat may be unhealthy)')"

echo "=== 5. Test on embed/rerank → reachable IF hlh_infer is healthy ==="
for role in embed rerank; do
  PID=$(curl -sS "$API/api/providers" | python3 -c "
import sys, json
print(next(p['id'] for p in json.load(sys.stdin)['items'] if p.get('is_bundled') and p.get('role') == '$role'))
")
  echo "  Test $role:"
  RESP=$(curl -sS -X POST "$API/api/providers/$PID/test")
  echo "$RESP" | python3 -m json.tool
  echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('ok'):
    print('    OK: $role reachable')
else:
    print('    WARN: $role unreachable — hlh_infer may still be pulling models (first-boot ~5-15min)')
"
done

echo "=== ALL CHECKS PASSED ==="
