#!/usr/bin/env bash
# Step-3 happy-path: exercise POST /providers/{id}/test and
# GET /providers/{id}/models against the GPU-host backends documented in
# /opt/boolab/.env.example. Also exercise a deliberately-broken URL for
# the failure path.
#
# Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §3, §8 step 3
#
# Re-runnable: cleans up step-3-test-* providers on entry.

set -euo pipefail

API="${API:-http://localhost:9600/api}"

# GPU-host backends (tailnet-internal, no API key required).
LLAMA_SWAP_URL="http://100.101.41.16:8401"
INFINITY_EMB_URL="http://100.90.172.55:7997"
INFINITY_RERANK_URL="http://100.90.172.55:7996"
BROKEN_URL="http://does-not-exist.invalid:9999"

# Expected model ids on each backend.
EXPECTED_CHAT_MODEL="qwen3.6-35b-a3b-mxfp4"
EXPECTED_EMB_MODEL="harrier"
EXPECTED_RRK_MODEL="qwen3-rerank"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

color() {
    case "$1" in
        green) printf "\033[32m%s\033[0m" "$2" ;;
        red)   printf "\033[31m%s\033[0m" "$2" ;;
        *)     printf "%s" "$2" ;;
    esac
}

check() {
    local label="$1"; shift
    if eval "$@" >/dev/null 2>&1; then
        printf "  %s  %s\n" "$(color green PASS)" "$label"
        pass=$((pass + 1))
    else
        printf "  %s  %s\n" "$(color red FAIL)" "$label"
        fail=$((fail + 1))
    fi
}

section() { printf "\n— %s —\n" "$1"; }

c() {
    local method="$1"; shift
    local path="$1"; shift
    local body="${1:-}"; [[ $# -gt 0 ]] && shift || true
    local out="$TMP/last.json"
    local code_file="$TMP/last.code"
    if [[ -n "$body" ]]; then
        curl -sS -o "$out" -w '%{http_code}' \
            -X "$method" "$API$path" \
            -H 'Content-Type: application/json' \
            -d "$body" "$@" > "$code_file"
    else
        curl -sS -o "$out" -w '%{http_code}' \
            -X "$method" "$API$path" "$@" > "$code_file"
    fi
}

last_code() { cat "$TMP/last.code"; }
last_archive() { cp "$TMP/last.json" "$TMP/$1.json"; cp "$TMP/last.code" "$TMP/$1.code"; }
jget() {
    python3 -c "import json; print(json.load(open('$TMP/last.json')).get('$1', ''))"
}

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup leftover step-3 rows from prior runs.
# ──────────────────────────────────────────────────────────────────────────────
section "Cleanup (idempotent)"
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM providers WHERE name LIKE 'step3-%';" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# 1. Chat provider — llama-swap.
# ──────────────────────────────────────────────────────────────────────────────
section "Create chat provider (llama-swap)"
c POST /providers "{\"name\":\"step3-chat\",\"base_url\":\"$LLAMA_SWAP_URL\"}"
last_archive create_chat
check "POST returns 201" "[ \"\$(last_code)\" = '201' ]"
PID_CHAT=$(jget id)
printf "  id = %s\n" "$PID_CHAT"

c POST "/providers/$PID_CHAT/test"
last_archive test_chat
check "POST /test returns 200" "[ \"\$(last_code)\" = '200' ]"
check "test ok:true" "grep -q '\"ok\":true' '$TMP/test_chat.json'"
check "test status:\"ok\"" "grep -q '\"status\":\"ok\"' '$TMP/test_chat.json'"
check "test models contains $EXPECTED_CHAT_MODEL" "grep -q '\"$EXPECTED_CHAT_MODEL\"' '$TMP/test_chat.json'"

# last_verified_at + last_verified_status updated.
verified=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT (last_verified_at IS NOT NULL) AND last_verified_status = 'ok' FROM providers WHERE id = '$PID_CHAT'::uuid;")
check "DB last_verified_at set, last_verified_status='ok'" "[ \"$verified\" = 't' ]"

c GET "/providers/$PID_CHAT/models"
last_archive models_chat
check "GET /models returns 200" "[ \"\$(last_code)\" = '200' ]"
check "GET /models body has \"data\"" "grep -q '\"data\"' '$TMP/models_chat.json'"
check "GET /models contains $EXPECTED_CHAT_MODEL" "grep -q '\"id\":\"$EXPECTED_CHAT_MODEL\"' '$TMP/models_chat.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 2. Embedding provider — infinity-emb.
# ──────────────────────────────────────────────────────────────────────────────
section "Create embedding provider (infinity-emb)"
c POST /providers "{\"name\":\"step3-emb\",\"base_url\":\"$INFINITY_EMB_URL\"}"
last_archive create_emb
check "POST returns 201" "[ \"\$(last_code)\" = '201' ]"
PID_EMB=$(jget id)

c POST "/providers/$PID_EMB/test"
last_archive test_emb
check "POST /test ok:true" "grep -q '\"ok\":true' '$TMP/test_emb.json'"
check "test contains $EXPECTED_EMB_MODEL" "grep -q '\"$EXPECTED_EMB_MODEL\"' '$TMP/test_emb.json'"

c GET "/providers/$PID_EMB/models"
last_archive models_emb
check "GET /models returns 200" "[ \"\$(last_code)\" = '200' ]"
check "GET /models contains $EXPECTED_EMB_MODEL" "grep -q '\"id\":\"$EXPECTED_EMB_MODEL\"' '$TMP/models_emb.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 3. Reranker provider — infinity-rerank.
# ──────────────────────────────────────────────────────────────────────────────
section "Create reranker provider (infinity-rerank)"
c POST /providers "{\"name\":\"step3-rrk\",\"base_url\":\"$INFINITY_RERANK_URL\"}"
last_archive create_rrk
check "POST returns 201" "[ \"\$(last_code)\" = '201' ]"
PID_RRK=$(jget id)

c POST "/providers/$PID_RRK/test"
last_archive test_rrk
check "POST /test ok:true" "grep -q '\"ok\":true' '$TMP/test_rrk.json'"
check "test contains $EXPECTED_RRK_MODEL" "grep -q '\"$EXPECTED_RRK_MODEL\"' '$TMP/test_rrk.json'"

c GET "/providers/$PID_RRK/models"
last_archive models_rrk
check "GET /models returns 200" "[ \"\$(last_code)\" = '200' ]"
check "GET /models contains $EXPECTED_RRK_MODEL" "grep -q '\"id\":\"$EXPECTED_RRK_MODEL\"' '$TMP/models_rrk.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Broken provider — bad URL.
# ──────────────────────────────────────────────────────────────────────────────
section "Create broken provider (bad URL)"
c POST /providers "{\"name\":\"step3-broken\",\"base_url\":\"$BROKEN_URL\"}"
last_archive create_broken
check "POST returns 201 (provider rows are not validated at create-time)" "[ \"\$(last_code)\" = '201' ]"
PID_BROKEN=$(jget id)

c POST "/providers/$PID_BROKEN/test"
last_archive test_broken
check "POST /test returns 200 (probe result, not request failure)" "[ \"\$(last_code)\" = '200' ]"
check "test ok:false" "grep -q '\"ok\":false' '$TMP/test_broken.json'"
check "test status starts with 'error:'" "grep -q '\"status\":\"error:' '$TMP/test_broken.json'"

c GET "/providers/$PID_BROKEN/models"
last_archive models_broken
check "GET /models returns 502 (upstream failure)" "[ \"\$(last_code)\" = '502' ]"
check "502 body mentions 'upstream models fetch failed'" "grep -q 'upstream models fetch failed' '$TMP/models_broken.json'"

# DB write on test failure.
verified=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT (last_verified_at IS NOT NULL) AND (last_verified_status LIKE 'error:%') FROM providers WHERE id = '$PID_BROKEN'::uuid;")
check "DB last_verified_status starts with 'error:'" "[ \"$verified\" = 't' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 5. Final cleanup — delete all step3-* providers (none are referenced).
# ──────────────────────────────────────────────────────────────────────────────
section "Final cleanup"
for pid in "$PID_CHAT" "$PID_EMB" "$PID_RRK" "$PID_BROKEN"; do
    c DELETE "/providers/$pid"
    check "DELETE $pid returns 204" "[ \"\$(last_code)\" = '204' ]"
done

# ──────────────────────────────────────────────────────────────────────────────
# Summary.
# ──────────────────────────────────────────────────────────────────────────────
printf "\n%s passed, %s failed\n" "$(color green "$pass")" "$([[ $fail -gt 0 ]] && color red "$fail" || color green "$fail")"
[[ $fail -eq 0 ]] && exit 0
exit 1
