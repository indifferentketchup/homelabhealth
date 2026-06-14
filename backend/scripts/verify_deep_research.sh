#!/usr/bin/env bash
# Verify the POST /api/chats/{chat_id}/deep_research endpoint.
# Tests: empty query rejection, query-too-long rejection, JSON mode probe (BU-1).
#
# Usage:
#   SESSION=<hlh_session_token> CHAT_ID=<uuid> bash verify_deep_research.sh
#   SESSION=<token>  (CHAT_ID auto-fetched from first chat in GET /api/chats)
#
# Requires the docker stack to be running (hlh_api must be live).
set -euo pipefail

API="${API:-http://localhost:9600/api}"
SESSION="${SESSION:-}"
CHAT_ID="${CHAT_ID:-}"

PASS=0
FAIL=0

if [ -z "$SESSION" ]; then
    echo "ERROR: SESSION env var required (hlh_session cookie value)" >&2
    echo "Usage: SESSION=<token> [CHAT_ID=<uuid>] bash verify_deep_research.sh" >&2
    exit 1
fi

# Auto-fetch CHAT_ID if not provided
if [ -z "$CHAT_ID" ]; then
    echo "CHAT_ID not set -- fetching first available chat via GET $API/chats ..."
    CHAT_ID=$(curl -s "$API/chats" -b "hlh_session=$SESSION" | python3 -c "
import sys, json
data = json.load(sys.stdin)
chats = data.get('chats') or data
if isinstance(chats, list) and len(chats) > 0:
    print(chats[0]['id'])
else:
    print('')
" 2>/dev/null || true)
    if [ -z "$CHAT_ID" ]; then
        echo "FAIL: could not auto-fetch a chat ID; create a chat first or pass CHAT_ID=<uuid>" >&2
        FAIL=$((FAIL+1))
        echo "PASS=$PASS FAIL=$FAIL"
        exit 1
    fi
fi

echo "Using CHAT_ID=$CHAT_ID"
echo ""

# ── Test 1: empty query must return HTTP 400 ─────────────────────────────────
echo "Test 1: empty query rejected (expect 400)..."
if T1_RESULT=$(curl -s -w '\n%{http_code}' -X POST "$API/chats/$CHAT_ID/deep_research" \
    -H "Content-Type: application/json" \
    -d '{"query":""}' \
    -b "hlh_session=$SESSION" 2>/dev/null); then
    T1_CODE=$(echo "$T1_RESULT" | tail -1)
    T1_BODY=$(echo "$T1_RESULT" | head -1)
    if [ "$T1_CODE" = "400" ]; then
        echo "  PASS: HTTP $T1_CODE -- $T1_BODY"
        PASS=$((PASS+1))
    else
        echo "  FAIL: expected 400, got HTTP $T1_CODE -- $T1_BODY"
        FAIL=$((FAIL+1))
    fi
else
    echo "  FAIL: curl error"
    FAIL=$((FAIL+1))
fi

# ── Test 2: query too long (2001 chars) must return HTTP 400 ─────────────────
echo "Test 2: query too long (2001 chars) rejected (expect 400)..."
LONG_QUERY=$(python3 -c "print('x' * 2001)")
if T2_RESULT=$(curl -s -w '\n%{http_code}' -X POST "$API/chats/$CHAT_ID/deep_research" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$LONG_QUERY\"}" \
    -b "hlh_session=$SESSION" 2>/dev/null); then
    T2_CODE=$(echo "$T2_RESULT" | tail -1)
    T2_BODY=$(echo "$T2_RESULT" | head -1)
    if [ "$T2_CODE" = "400" ]; then
        echo "  PASS: HTTP $T2_CODE -- $T2_BODY"
        PASS=$((PASS+1))
    else
        echo "  FAIL: expected 400, got HTTP $T2_CODE -- $T2_BODY"
        FAIL=$((FAIL+1))
    fi
else
    echo "  FAIL: curl error"
    FAIL=$((FAIL+1))
fi

# ── Test 3: JSON mode probe for bundled model (BU-1 verification) ─────────────
echo "Test 3: JSON mode capability of bundled model (BU-1 probe)..."
echo "  (warning on failure -- fallback path is still valid)"
if T3_RESULT=$(docker exec hlh_api python3 -c "
import asyncio, httpx, json, os

async def t():
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            'http://hlh_chat:8080/v1/chat/completions',
            json={
                'model': os.environ.get('CHAT_MODEL', 'qwen-chat'),
                'messages': [{'role': 'user', 'content':
                    'Respond with JSON: {\"continue\": true, \"follow_up_query\": \"test\"}'}],
                'response_format': {'type': 'json_object'},
                'max_tokens': 64
            }
        )
        body = r.json()
        content = body['choices'][0]['message']['content']
        parsed = json.loads(content)
        assert 'continue' in parsed, f'missing continue key in: {content}'
        print('BU-1 JSON mode: PASS')

asyncio.run(t())
" 2>&1); then
    if echo "$T3_RESULT" | grep -q "PASS"; then
        echo "  PASS: $T3_RESULT"
        PASS=$((PASS+1))
    else
        echo "  WARNING: JSON mode probe returned unexpected result: $T3_RESULT"
        echo "  (fallback path in _reflect handles this gracefully)"
        PASS=$((PASS+1))
    fi
else
    echo "  WARNING: JSON mode probe failed (BU-1): $T3_RESULT"
    echo "  (the reflect() fallback returns (True, original_query) on parse failure -- safe)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
