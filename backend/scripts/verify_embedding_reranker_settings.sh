#!/usr/bin/env bash
# Verify backend/routers/settings.py endpoints added in step 5:
#   - GET/PUT /api/settings/embedding  (with /v1/embeddings probe)
#   - GET/PUT /api/settings/reranker   (validation only, no probe)
#
# Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §5, §9
#
# Re-runnable. Cleans up step5-* providers and embedding/reranker
# global_settings rows on entry. Stands up a small Python mock embedding
# server on the host tailnet IP to exercise the dim-mismatch path.

set -euo pipefail

API="${API:-http://localhost:9600/api}"
HOST_TAILNET_IP="${HOST_TAILNET_IP:-100.114.205.53}"
MOCK_PORT="${MOCK_PORT:-9611}"

LLAMA_SWAP_URL="http://100.101.41.16:8401"
INFINITY_EMB_URL="http://100.90.172.55:7997"
INFINITY_RERANK_URL="http://100.90.172.55:7996"

TMP=$(mktemp -d)
MOCK_PID=""
cleanup() {
    if [[ -n "$MOCK_PID" ]]; then
        kill "$MOCK_PID" 2>/dev/null || true
        wait "$MOCK_PID" 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT

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
last_body() { cat "$TMP/last.json"; }
last_archive() { cp "$TMP/last.json" "$TMP/$1.json"; cp "$TMP/last.code" "$TMP/$1.code"; }
jget() {
    python3 -c "import json; print(json.load(open('$TMP/last.json')).get('$1', ''))"
}

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup leftover state.
# ──────────────────────────────────────────────────────────────────────────────
section "Cleanup (idempotent)"
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM global_settings WHERE key IN ('embedding_provider_id','embedding_model','reranker_provider_id','reranker_model');" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM providers WHERE name LIKE 'step5-%';" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# Stand up providers we'll point at.
# ──────────────────────────────────────────────────────────────────────────────
section "Create test providers"
c POST /providers "{\"name\":\"step5-emb\",\"base_url\":\"$INFINITY_EMB_URL\"}"
PID_EMB=$(jget id)
printf "  step5-emb id=%s\n" "$PID_EMB"

c POST /providers "{\"name\":\"step5-rrk\",\"base_url\":\"$INFINITY_RERANK_URL\"}"
PID_RRK=$(jget id)
printf "  step5-rrk id=%s\n" "$PID_RRK"

# Inline mock embedding server: returns a 768-dim vector for any input.
# Bound to the host tailnet IP so the hlh_api container can reach it.
cat > "$TMP/mock_emb.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

host, port = sys.argv[1], int(sys.argv[2])

class H(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(n)
        body = {"data": [{"embedding": [0.0] * 768, "index": 0, "object": "embedding"}]}
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

HTTPServer((host, port), H).serve_forever()
PY
python3 "$TMP/mock_emb.py" "$HOST_TAILNET_IP" "$MOCK_PORT" >/dev/null 2>&1 &
MOCK_PID=$!

# Give it a moment to bind.
sleep 0.5

c POST /providers "{\"name\":\"step5-mock-768\",\"base_url\":\"http://$HOST_TAILNET_IP:$MOCK_PORT\"}"
PID_MOCK=$(jget id)
printf "  step5-mock-768 id=%s  (768-dim mock at http://%s:%s)\n" "$PID_MOCK" "$HOST_TAILNET_IP" "$MOCK_PORT"

# Unreachable provider for the probe-network-failure path. We can't use a
# wrong model name to trigger this: infinity-emb is lenient and silently
# substitutes its loaded model, so a bogus name still returns a 1024-dim
# vector (verified live). A non-routable URL reliably yields httpx.HTTPError
# → 502 from the handler.
c POST /providers "{\"name\":\"step5-unreachable\",\"base_url\":\"http://does-not-exist.invalid:9999\"}"
PID_UNREACH=$(jget id)
printf "  step5-unreachable id=%s\n" "$PID_UNREACH"

# ──────────────────────────────────────────────────────────────────────────────
# 1. GET /api/settings/embedding → defaults (both null, dimension 1024)
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/settings/embedding (initial state)"
c GET /settings/embedding
last_archive get_emb_initial
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "provider_id null" "grep -q '\"provider_id\":null' '$TMP/get_emb_initial.json'"
check "model null" "grep -q '\"model\":null' '$TMP/get_emb_initial.json'"
check "dimension is 1024" "grep -q '\"dimension\":1024' '$TMP/get_emb_initial.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 2. PUT /api/settings/embedding validation: one-null → 400
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/embedding validation (one null)"
c PUT /settings/embedding "{\"provider_id\":\"$PID_EMB\",\"model\":null}"
last_archive emb_pid_only
check "provider_id without model → 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'must both be set or both null'" "grep -q 'must both be set or both null' '$TMP/emb_pid_only.json'"

c PUT /settings/embedding "{\"provider_id\":null,\"model\":\"harrier\"}"
last_archive emb_model_only
check "model without provider_id → 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'must both be set or both null'" "grep -q 'must both be set or both null' '$TMP/emb_model_only.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 3. PUT /api/settings/embedding happy path (probe succeeds, 1024 dim)
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/embedding happy path (infinity-emb harrier, 1024)"
c PUT /settings/embedding "{\"provider_id\":\"$PID_EMB\",\"model\":\"harrier\"}"
last_archive emb_set_ok
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "response provider_id matches" "grep -q '\"provider_id\":\"$PID_EMB\"' '$TMP/emb_set_ok.json'"
check "response model is harrier" "grep -q '\"model\":\"harrier\"' '$TMP/emb_set_ok.json'"
check "dimension still 1024" "grep -q '\"dimension\":1024' '$TMP/emb_set_ok.json'"

# DB state.
rows=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT COUNT(*) FROM global_settings WHERE key IN ('embedding_provider_id','embedding_model');")
check "2 global_settings rows persisted" "[ \"$rows\" = '2' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 4. PUT /api/settings/embedding dim mismatch → 400 with EXACT spec string
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/embedding dim mismatch (mock returns 768)"
c PUT /settings/embedding "{\"provider_id\":\"$PID_MOCK\",\"model\":\"anything\"}"
last_archive emb_dim_mismatch
check "returns 400" "[ \"\$(last_code)\" = '400' ]"
check "body contains EXACT spec string 'embedding dimension mismatch: expected 1024, got 768'" \
    "grep -qF 'embedding dimension mismatch: expected 1024, got 768' '$TMP/emb_dim_mismatch.json'"

# DB state must NOT have changed (the probe runs before the write).
still_harrier=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT value FROM global_settings WHERE key = 'embedding_model';")
check "DB still has previous binding (harrier) — rejected probe didn't overwrite" \
    "[ \"$still_harrier\" = 'harrier' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 5. PUT /api/settings/embedding unreachable provider → probe network error
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/embedding unreachable URL (probe network error)"
c PUT /settings/embedding "{\"provider_id\":\"$PID_UNREACH\",\"model\":\"anything\"}"
last_archive emb_unreachable
check "returns 502 (probe failed)" "[ \"\$(last_code)\" = '502' ]"
check "body contains 'embedding probe failed'" "grep -q 'embedding probe failed' '$TMP/emb_unreachable.json'"
check "body does NOT mention dim mismatch" \
    "! grep -q 'dimension mismatch' '$TMP/emb_unreachable.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 6. PUT /api/settings/embedding clear (both null) → 200, rows deleted
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/embedding clear"
c PUT /settings/embedding '{"provider_id":null,"model":null}'
last_archive emb_clear
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "provider_id null" "grep -q '\"provider_id\":null' '$TMP/emb_clear.json'"
check "model null" "grep -q '\"model\":null' '$TMP/emb_clear.json'"
rows=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT COUNT(*) FROM global_settings WHERE key IN ('embedding_provider_id','embedding_model');")
check "global_settings rows deleted" "[ \"$rows\" = '0' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 7. GET /api/settings/reranker → defaults
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/settings/reranker (initial state)"
c GET /settings/reranker
last_archive get_rrk_initial
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "provider_id null" "grep -q '\"provider_id\":null' '$TMP/get_rrk_initial.json'"
check "model null" "grep -q '\"model\":null' '$TMP/get_rrk_initial.json'"
# Reranker GET response intentionally has no 'dimension' field.
check "response has no 'dimension' field" \
    "! grep -q '\"dimension\"' '$TMP/get_rrk_initial.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 8. PUT /api/settings/reranker validation (one null)
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/reranker validation (one null)"
c PUT /settings/reranker "{\"provider_id\":\"$PID_RRK\",\"model\":null}"
last_archive rrk_pid_only
check "provider_id without model → 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'must both be set or both null'" "grep -q 'must both be set or both null' '$TMP/rrk_pid_only.json'"

c PUT /settings/reranker "{\"provider_id\":null,\"model\":\"qwen3-rerank\"}"
last_archive rrk_model_only
check "model without provider_id → 400" "[ \"\$(last_code)\" = '400' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 9. PUT /api/settings/reranker set + clear (validation only — no probe)
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/settings/reranker set (no probe)"
c PUT /settings/reranker "{\"provider_id\":\"$PID_RRK\",\"model\":\"qwen3-rerank\"}"
last_archive rrk_set
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "response provider_id matches" "grep -q '\"provider_id\":\"$PID_RRK\"' '$TMP/rrk_set.json'"
check "response model is qwen3-rerank" "grep -q '\"model\":\"qwen3-rerank\"' '$TMP/rrk_set.json'"

# Reranker set should accept a deliberately-fake model name too — no probe!
# This is the validation-only contract: tests what the endpoint actually does.
c PUT /settings/reranker "{\"provider_id\":\"$PID_RRK\",\"model\":\"deliberately-fake-model-name\"}"
last_archive rrk_set_fake_name
check "reranker accepts a not-yet-existent model name (no probe)" \
    "[ \"\$(last_code)\" = '200' ]"
check "response model matches what we sent" \
    "grep -q '\"model\":\"deliberately-fake-model-name\"' '$TMP/rrk_set_fake_name.json'"

section "PUT /api/settings/reranker clear"
c PUT /settings/reranker '{"provider_id":null,"model":null}'
last_archive rrk_clear
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
rows=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT COUNT(*) FROM global_settings WHERE key IN ('reranker_provider_id','reranker_model');")
check "global_settings reranker rows deleted" "[ \"$rows\" = '0' ]"

# ──────────────────────────────────────────────────────────────────────────────
# Final cleanup.
# ──────────────────────────────────────────────────────────────────────────────
section "Final cleanup"
for pid in "$PID_EMB" "$PID_RRK" "$PID_MOCK" "$PID_UNREACH"; do
    c DELETE "/providers/$pid?force=true"
    check "DELETE provider $pid returns 204" "[ \"\$(last_code)\" = '204' ]"
done

# ──────────────────────────────────────────────────────────────────────────────
# Summary.
# ──────────────────────────────────────────────────────────────────────────────
printf "\n%s passed, %s failed\n" "$(color green "$pass")" "$([[ $fail -gt 0 ]] && color red "$fail" || color green "$fail")"
[[ $fail -eq 0 ]] && exit 0
exit 1
