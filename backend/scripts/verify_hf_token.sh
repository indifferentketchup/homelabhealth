#!/usr/bin/env bash
# Verify HF token storage, masking, validation, and end-to-end CRUD.
# Spec: docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md §5
set -euo pipefail

API="${API:-http://localhost:9600}"

echo "=== 1. Capture pre-state (so we can restore at the end) ==="
PRE=$(curl -sS "$API/api/system/hf-token")
echo "$PRE" | python3 -m json.tool
PRE_CONFIGURED=$(echo "$PRE" | python3 -c "import sys, json; print(json.load(sys.stdin)['configured'])")

# Clear before testing to ensure a known baseline
curl -sS -o /dev/null -X DELETE "$API/api/system/hf-token"

echo "=== 2. Initial state (unset) ==="
STATE=$(curl -sS "$API/api/system/hf-token")
echo "$STATE" | python3 -m json.tool
echo "$STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert not d['configured'], 'not unset after clear'" || { echo "FAIL"; exit 1; }
echo "OK"

echo "=== 3. PUT garbage → 4xx ==="
code=$(curl -sS -o /tmp/r -w '%{http_code}' -X PUT "$API/api/system/hf-token" \
  -H 'content-type: application/json' -d '{"token":"garbage"}')
[[ "$code" =~ ^4[0-9][0-9]$ ]] && echo "OK: $code" || { echo "FAIL: expected 4xx, got $code"; cat /tmp/r; exit 1; }

echo "=== 4. PUT valid → 204 ==="
code=$(curl -sS -o /tmp/r -w '%{http_code}' -X PUT "$API/api/system/hf-token" \
  -H 'content-type: application/json' -d '{"token":"hf_abcdefghijklmnopqrstuvwxyz"}')
[[ "$code" == "204" ]] && echo "OK: 204" || { echo "FAIL: got $code"; cat /tmp/r; exit 1; }

echo "=== 5. GET shows masked + timestamp ==="
STATE=$(curl -sS "$API/api/system/hf-token")
echo "$STATE" | python3 -m json.tool
echo "$STATE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['configured'] == True, 'not configured'
assert d.get('masked', '') and 'wxyz' in d['masked'], f'masked missing or wrong: {d.get(\"masked\")}'
assert d.get('updated_at', '').startswith('20'), f'updated_at missing: {d.get(\"updated_at\")}'
print('masked:', d['masked'])
" || { echo "FAIL"; exit 1; }
echo "OK"

echo "=== 6. PUT fine-grained token (with underscores) ==="
code=$(curl -sS -o /tmp/r -w '%{http_code}' -X PUT "$API/api/system/hf-token" \
  -H 'content-type: application/json' -d '{"token":"hf_aBcDe_FgHiJ_KlMnO_PqRsT"}')
[[ "$code" == "204" ]] && echo "OK: 204" || { echo "FAIL: fine-grained rejected ($code)"; cat /tmp/r; exit 1; }

echo "=== 7. DELETE → 204 ==="
code=$(curl -sS -o /tmp/r -w '%{http_code}' -X DELETE "$API/api/system/hf-token")
[[ "$code" == "204" ]] && echo "OK: 204" || { echo "FAIL: got $code"; cat /tmp/r; exit 1; }

echo "=== 8. Confirm cleared ==="
STATE=$(curl -sS "$API/api/system/hf-token")
echo "$STATE" | python3 -m json.tool
echo "$STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert not d['configured'], 'still configured'" || { echo "FAIL"; exit 1; }
echo "OK"

if [[ "$PRE_CONFIGURED" == "True" ]]; then
  echo "=== Pre-state was configured — restoring is not possible (we never saw the cleartext)."
  echo "    Operator must re-paste their HF token via the UI if needed."
fi

echo "=== ALL CHECKS PASSED ==="
