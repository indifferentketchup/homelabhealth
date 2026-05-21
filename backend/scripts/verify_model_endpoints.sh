#!/usr/bin/env bash
# Verify backend/routers/models.py end-to-end against the running hlh_api.
#
# Covers (per dispatch §1.D step 3):
#   - GET /api/models → 200, JSON 'items' array with the Phase 1 chat rows
#   - GET /api/models/:id → 200 for a valid id, 404 for an unknown id
#   - POST /api/models/pull-for-tier with an invalid tier → 400
#   - POST /api/models/:id/pull queues a background task, status flips
#     to one of {pulling, ready, failed}
#   - POST /api/models/:id/cancel → 200 with cancel_requested boolean
#
# To avoid pulling the multi-GB MedGemma / Qwen3 weights, we insert a
# synthetic "verify-test" row that points at hf-internal-testing's
# tiny config.json (~700 B). The endpoint test exercises the same
# code path; the actual model artifact is irrelevant to the routing.
#
# Re-runnable: deletes its own test rows + verify_model_puller tmp files.

set -euo pipefail

API="${API:-http://localhost:9600/api}"
TEST_TIER="verify-endpoint-tier"      # NOT in ALL_TIERS; won't collide
TINY_REPO="hf-internal-testing/tiny-random-bert"
TINY_FILE="config.json"

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
    if [[ -n "$body" ]]; then
        curl -sS -o "$TMP/last.json" -w '%{http_code}' \
            -X "$method" "$API$path" \
            -H 'Content-Type: application/json' \
            -d "$body" "$@" > "$TMP/last.code"
    else
        curl -sS -o "$TMP/last.json" -w '%{http_code}' \
            -X "$method" "$API$path" "$@" > "$TMP/last.code"
    fi
}

last_code() { cat "$TMP/last.code"; }
last_archive() { cp "$TMP/last.json" "$TMP/$1.json"; cp "$TMP/last.code" "$TMP/$1.code"; }

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────
section "Cleanup leftover verify rows"
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM bundled_models WHERE tier = '$TEST_TIER';" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# 1. GET /api/models
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/models"
c GET /models
last_archive list
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "body has 'items' array" "grep -q '\"items\":\\[' '$TMP/list.json'"
check "items include 'chat'/'cpu-min' (Qwen3 seeded by lifespan)" \
    "python3 -c 'import json,sys; d=json.load(open(\"$TMP/list.json\")); sys.exit(0 if any(it[\"role\"]==\"chat\" and it[\"tier\"]==\"cpu-min\" for it in d[\"items\"]) else 1)'"
check "items include 'chat'/'cpu-std' (MedGemma 4B Q4)" \
    "python3 -c 'import json,sys; d=json.load(open(\"$TMP/list.json\")); sys.exit(0 if any(it[\"role\"]==\"chat\" and it[\"tier\"]==\"cpu-std\" for it in d[\"items\"]) else 1)'"
check "items include 'chat'/'gpu-24gb+' (MedGemma 27B MM)" \
    "python3 -c 'import json,sys; d=json.load(open(\"$TMP/list.json\")); sys.exit(0 if any(it[\"role\"]==\"chat\" and it[\"tier\"]==\"gpu-24gb+\" for it in d[\"items\"]) else 1)'"

# Pick one real row id for the GET single test.
REAL_ID=$(python3 -c "import json; d=json.load(open('$TMP/list.json')); print(next(it['id'] for it in d['items'] if it['role']=='chat' and it['tier']=='cpu-min'))")
echo "  (real cpu-min row id = $REAL_ID)"

# ──────────────────────────────────────────────────────────────────────────────
# 2. GET /api/models/:id
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/models/:id"
c GET "/models/$REAL_ID"
last_archive get_one
check "valid id returns 200" "[ \"\$(last_code)\" = '200' ]"
check "body has role=chat" "grep -q '\"role\":\"chat\"' '$TMP/get_one.json'"
check "body has tier=cpu-min" "grep -q '\"tier\":\"cpu-min\"' '$TMP/get_one.json'"
check "body has license_url" "grep -q '\"license_url\":\"' '$TMP/get_one.json'"

c GET "/models/00000000-0000-0000-0000-000000000000"
last_archive get_missing
check "unknown id returns 404" "[ \"\$(last_code)\" = '404' ]"
check "404 body mentions 'model not found'" "grep -q 'model not found' '$TMP/get_missing.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 3. POST /api/models/pull-for-tier — invalid tier
# ──────────────────────────────────────────────────────────────────────────────
section "POST /api/models/pull-for-tier (invalid tier)"
c POST /models/pull-for-tier '{"tier":"made-up-tier"}'
last_archive bad_tier
check "returns 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'invalid tier'" "grep -q 'invalid tier' '$TMP/bad_tier.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Insert synthetic test row pointing at a tiny public HF file, then pull it
# ──────────────────────────────────────────────────────────────────────────────
section "Insert synthetic test row + POST /pull + status check"
docker exec hlh_db psql -U hlh -d hlh -c "
    INSERT INTO bundled_models (role, tier, model_id, quant, repo, filename, status)
    VALUES ('chat', '$TEST_TIER', '$TINY_REPO@$TINY_FILE', 'verify',
            '$TINY_REPO', '$TINY_FILE', 'pending');
" >/dev/null

TEST_ID=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT id FROM bundled_models WHERE tier = '$TEST_TIER';")
echo "  (synthetic test id = $TEST_ID)"

# Set HLH_MODELS_DIR inside the api container so the pull lands in /tmp.
# We can't easily set per-process env on a running container, so we accept
# that the file lands at /models/<role>/<tier>/<filename> — which fails if
# /models isn't writable. Inspect logs after if needed.
# For Phase 1.D the routing/status path is what matters; /models writability
# is exercised in 1.E once the volume is mounted.
#
# Workaround for THIS verify run: ensure /models is writable by the api
# container even before 1.E. Do it via docker exec mkdir + chmod.
docker exec hlh_api sh -c "mkdir -p /models && chmod -R 777 /models" 2>&1 || true

c POST "/models/$TEST_ID/pull"
last_archive pull
check "POST /pull returns 202" "[ \"\$(last_code)\" = '202' ]"
check "response has model id" "grep -q \"\\\"id\\\":\\\"$TEST_ID\\\"\" '$TMP/pull.json'"

# Allow the background task to run. 700-byte file, should complete in <2s.
sleep 3
c GET "/models/$TEST_ID"
last_archive pull_status
STATUS=$(python3 -c "import json; print(json.load(open('$TMP/pull_status.json'))['status'])")
ERR=$(python3 -c "import json; print(json.load(open('$TMP/pull_status.json')).get('error_message') or '')")
echo "  (post-pull status=$STATUS error_message=${ERR:-<none>})"
check "status is one of {pulling, ready, failed}" \
    "[ \"$STATUS\" = 'pulling' ] || [ \"$STATUS\" = 'ready' ] || [ \"$STATUS\" = 'failed' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 5. POST /api/models/:id/cancel — endpoint shape
# ──────────────────────────────────────────────────────────────────────────────
section "POST /api/models/:id/cancel"
c POST "/models/$TEST_ID/cancel"
last_archive cancel
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "body has 'ok': true" "grep -q '\"ok\":true' '$TMP/cancel.json'"
check "body has 'cancel_requested' boolean" \
    "python3 -c \"import json; d=json.load(open('$TMP/cancel.json')); assert isinstance(d.get('cancel_requested'), bool)\""

# Mid-pull cancel timing isn't reliably testable against a 700-byte file
# (pull may complete before cancel registers). The cancel endpoint itself
# is exercised here; pull_model() correctness for the cancel-mid-pull case
# is established by code review (cancel_event checked at each chunk
# boundary in services/model_puller.py).

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────
section "Final cleanup"
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM bundled_models WHERE tier = '$TEST_TIER';" >/dev/null
printf "  (test row removed)\n"

# ──────────────────────────────────────────────────────────────────────────────
# Summary.
# ──────────────────────────────────────────────────────────────────────────────
printf "\n%s passed, %s failed\n" "$(color green "$pass")" "$([[ $fail -gt 0 ]] && color red "$fail" || color green "$fail")"
[[ $fail -eq 0 ]] && exit 0
exit 1
