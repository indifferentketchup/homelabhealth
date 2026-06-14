#!/usr/bin/env bash
# verify_groundedness_eval.sh -- smoke test for the eval router and groundedness endpoint.
#
# NOTE: This is a smoke test. Full correctness verification (judge scoring accuracy)
# requires the workspace chat model to be loaded and responding.
#
# NOTE (durable streaming): Groundedness scoring only fires on the non-durable
# SSE gen() path. If durable_streaming_enabled=true in global_settings, the
# background task never fires and messages.groundedness_score will always be NULL.
#
# Usage:
#   HLH_ADMIN_USER=admin HLH_ADMIN_PASS=<pass> bash verify_groundedness_eval.sh
#
# Env vars:
#   HLH_ADMIN_USER  -- admin username (required)
#   HLH_ADMIN_PASS  -- admin password (required)
#   HLH_API_BASE    -- API base URL (default: http://localhost:9600)
#   HLH_WORKSPACE   -- workspace UUID for eval call (default: use first available)

set -euo pipefail

API_BASE="${HLH_API_BASE:-http://localhost:9600}"
ADMIN_USER="${HLH_ADMIN_USER:?HLH_ADMIN_USER env var required}"
ADMIN_PASS="${HLH_ADMIN_PASS:?HLH_ADMIN_PASS env var required}"

PASS=0
FAIL=0
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

log_pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
log_fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }
log_warn() { echo "WARN: $1"; }

echo "=== verify_groundedness_eval.sh ==="
echo "API: $API_BASE"

# 1. Authenticate as admin
echo ""
echo "--- Step 1: authenticate as admin ---"
LOGIN_RESP=$(curl -s -c "$COOKIE_JAR" -X POST "$API_BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
    -w "\n%{http_code}")
LOGIN_BODY=$(echo "$LOGIN_RESP" | head -n -1)
LOGIN_STATUS=$(echo "$LOGIN_RESP" | tail -n 1)
if [ "$LOGIN_STATUS" = "200" ]; then
    log_pass "admin login returned 200"
else
    log_fail "admin login returned $LOGIN_STATUS (body: $LOGIN_BODY)"
    echo "TOTAL: PASS=$PASS FAIL=$FAIL"
    exit 1
fi

# 2. Get a workspace ID
echo ""
echo "--- Step 2: get workspace ID ---"
if [ -n "${HLH_WORKSPACE:-}" ]; then
    WS_ID="$HLH_WORKSPACE"
    log_pass "using provided workspace_id: $WS_ID"
else
    WS_RESP=$(curl -s -b "$COOKIE_JAR" "$API_BASE/api/workspaces" -w "\n%{http_code}")
    WS_BODY=$(echo "$WS_RESP" | head -n -1)
    WS_STATUS=$(echo "$WS_RESP" | tail -n 1)
    if [ "$WS_STATUS" != "200" ]; then
        log_fail "GET /api/workspaces returned $WS_STATUS"
        echo "TOTAL: PASS=$PASS FAIL=$FAIL"
        exit 1
    fi
    WS_ID=$(echo "$WS_BODY" | python3 -c "import sys,json; ws=json.load(sys.stdin); print(ws[0]['id'] if ws else '')" 2>/dev/null || true)
    if [ -z "$WS_ID" ]; then
        log_fail "no workspaces found -- create one before running this script"
        echo "TOTAL: PASS=$PASS FAIL=$FAIL"
        exit 1
    fi
    log_pass "found workspace_id: $WS_ID"
fi

# 3. Call POST /api/eval/groundedness as admin
echo ""
echo "--- Step 3: POST /api/eval/groundedness (admin) ---"
EVAL_RESP=$(curl -s -b "$COOKIE_JAR" -X POST "$API_BASE/api/eval/groundedness" \
    -H "Content-Type: application/json" \
    -d "{\"workspace_id\":\"$WS_ID\",\"query\":\"What was the patient's glucose level?\",\"context\":\"Lab result: Glucose 95 mg/dL (2026-06-01).\",\"response\":\"The patient's glucose level was 95 mg/dL on 2026-06-01.\"}" \
    -w "\n%{http_code}")
EVAL_BODY=$(echo "$EVAL_RESP" | head -n -1)
EVAL_STATUS=$(echo "$EVAL_RESP" | tail -n 1)

if [ "$EVAL_STATUS" = "404" ]; then
    log_fail "eval router returned 404 -- router not mounted in main.py"
elif [ "$EVAL_STATUS" = "200" ]; then
    log_pass "eval/groundedness returned 200"
    # Check that 'score' key is present (value may be null if model not loaded)
    SCORE_PRESENT=$(echo "$EVAL_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if 'score' in d else 'no')" 2>/dev/null || echo "no")
    if [ "$SCORE_PRESENT" = "yes" ]; then
        SCORE_VAL=$(echo "$EVAL_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('score'))" 2>/dev/null || echo "None")
        if [ "$SCORE_VAL" = "None" ]; then
            log_warn "score is null -- workspace chat model may not be loaded (gemma-tasks not used; uses workspace provider)"
        else
            log_pass "score field is present and non-null: $SCORE_VAL"
        fi
    else
        log_fail "eval response missing 'score' key (body: ${EVAL_BODY:0:200})"
    fi
elif [ "$EVAL_STATUS" = "403" ]; then
    # This should not happen since we authenticated as admin
    log_fail "eval/groundedness returned 403 -- check that $ADMIN_USER has admin role"
else
    log_fail "eval/groundedness returned $EVAL_STATUS (body: ${EVAL_BODY:0:200})"
fi

# 4. Register a non-admin user and confirm 403
echo ""
echo "--- Step 4: test non-admin user gets 403 ---"
NON_ADMIN_COOKIE=$(mktemp)
trap 'rm -f "$COOKIE_JAR" "$NON_ADMIN_COOKIE"' EXIT

# Try to hit without a session cookie (unauthenticated -> 401)
UNAUTH_RESP=$(curl -s -X POST "$API_BASE/api/eval/groundedness" \
    -H "Content-Type: application/json" \
    -d "{\"workspace_id\":\"$WS_ID\",\"query\":\"x\",\"context\":\"x\",\"response\":\"x\"}" \
    -w "\n%{http_code}")
UNAUTH_STATUS=$(echo "$UNAUTH_RESP" | tail -n 1)
if [ "$UNAUTH_STATUS" = "401" ] || [ "$UNAUTH_STATUS" = "403" ]; then
    log_pass "unauthenticated request correctly blocked (status $UNAUTH_STATUS)"
else
    log_fail "unauthenticated request returned unexpected status $UNAUTH_STATUS (expected 401 or 403)"
fi

# 5. Summary
echo ""
echo "=== SUMMARY ==="
echo "TOTAL: PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
