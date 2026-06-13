#!/usr/bin/env bash
# Verify that PUT /api/chats/{id}/sources correctly persists source_ids with
# their position ordinals (A2 fix: position was missing from the INSERT).
set -euo pipefail

API="${HLH_API_URL:-http://localhost:9600}"
PASS=0
FAIL=0

pass() { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

# ── Auth ──────────────────────────────────────────────────────────────────────
# Log in and capture the session cookie.
LOGIN=$(curl -sf -c /tmp/hlh_verify_cookie.txt -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"'"${HLH_USER:-admin}"'","password":"'"${HLH_PASS:-admin}"'"}' 2>&1) || true
COOKIE_ARGS="-b /tmp/hlh_verify_cookie.txt"

# ── Setup: create a workspace ─────────────────────────────────────────────────
WS=$(curl -sf $COOKIE_ARGS -X POST "$API/api/workspaces" \
  -H "Content-Type: application/json" \
  -d '{"name":"verify-source-selection-tmp"}')
WS_ID=$(echo "$WS" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Workspace: $WS_ID"

# Create two sources (upload minimal text files)
S1=$(curl -sf $COOKIE_ARGS -X POST "$API/api/workspaces/$WS_ID/sources" \
  -F "file=@/dev/stdin;filename=test1.txt" <<< "Test source one")
SID1=$(echo "$S1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

S2=$(curl -sf $COOKIE_ARGS -X POST "$API/api/workspaces/$WS_ID/sources" \
  -F "file=@/dev/stdin;filename=test2.txt" <<< "Test source two")
SID2=$(echo "$S2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Sources: $SID1  $SID2"

# Create a chat in the workspace
CHAT=$(curl -sf $COOKIE_ARGS -X POST "$API/api/workspaces/$WS_ID/chats" \
  -H "Content-Type: application/json" \
  -d '{"title":"verify-source-selection"}')
CHAT_ID=$(echo "$CHAT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Chat: $CHAT_ID"

# ── PUT /api/chats/{id}/sources ───────────────────────────────────────────────
PUT_RESP=$(curl -sf $COOKIE_ARGS -X PUT "$API/api/chats/$CHAT_ID/sources" \
  -H "Content-Type: application/json" \
  -d "{\"source_ids\":[\"$SID1\",\"$SID2\"]}")
echo "PUT response: $PUT_RESP"

# Assert 200 and source_ids present (non-empty response)
if echo "$PUT_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = d.get('source_ids', [])
assert '$SID1' in ids, f'SID1 missing from {ids}'
assert '$SID2' in ids, f'SID2 missing from {ids}'
"; then
  pass "PUT returns both source IDs"
else
  fail "PUT response missing expected source IDs"
fi

# GET and verify both are present
GET_RESP=$(curl -sf $COOKIE_ARGS "$API/api/chats/$CHAT_ID/sources")
if echo "$GET_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = [s['id'] for s in d.get('items', d if isinstance(d, list) else [])]
assert '$SID1' in ids, f'SID1 missing from GET {ids}'
assert '$SID2' in ids, f'SID2 missing from GET {ids}'
"; then
  pass "GET confirms both sources attached"
else
  fail "GET does not confirm both sources"
fi

# ── Teardown ──────────────────────────────────────────────────────────────────
curl -sf $COOKIE_ARGS -X DELETE "$API/api/workspaces/$WS_ID" > /dev/null || true
rm -f /tmp/hlh_verify_cookie.txt

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
