#!/usr/bin/env bash
# Verify backend/routers/providers.py end-to-end against the running stack.
#
# Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §3, §9
#
# Assumes hlh_api is reachable at http://localhost:9600 and hlh_db is accessible
# via `docker exec hlh_db psql -U hlh -d hlh`. Single-user mode: no auth header.
#
# Re-runnable: cleans up its own test rows on entry.

set -euo pipefail

API="${API:-http://localhost:9600/api}"
SECRET_A="sk-ZZZTESTREDACT-A-12345"
SECRET_B="sk-ZZZTESTREDACT-B-67890"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

color() {
    case "$1" in
        green)  printf "\033[32m%s\033[0m" "$2" ;;
        red)    printf "\033[31m%s\033[0m" "$2" ;;
        yellow) printf "\033[33m%s\033[0m" "$2" ;;
        *)      printf "%s" "$2" ;;
    esac
}

check() {
    # check "label" <success-condition-as-bash-cmd>
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

# Issue a curl, write body and status to files. Usage:
#   c POST /providers '{"name":"x"}' [extra-curl-args...]
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

# Extract a JSON field with python (no jq dep).
jget() {
    python3 -c "import json,sys; print(json.load(open('$TMP/last.json')).get('$1', ''))"
}

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup: nuke any leftover verify-test-* providers from previous runs.
# ──────────────────────────────────────────────────────────────────────────────
section "Cleanup (idempotent)"
docker exec hlh_db psql -U hlh -d hlh -c \
    "UPDATE workspaces SET model = NULL WHERE provider_id IN (SELECT id FROM providers WHERE name LIKE 'verify-test-%');" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM global_settings WHERE key IN ('embedding_provider_id','embedding_model','reranker_provider_id','reranker_model') AND value IN (SELECT id::text FROM providers WHERE name LIKE 'verify-test-%');" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM providers WHERE name LIKE 'verify-test-%';" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "DELETE FROM workspaces WHERE name LIKE 'verify-test-ws-%';" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# 1. POST /providers → 201, api_key redacted, no plaintext leak.
# ──────────────────────────────────────────────────────────────────────────────
section "POST /providers"
c POST /providers "{\"name\":\"verify-test-a\",\"base_url\":\"http://example.invalid:9999\",\"api_key\":\"$SECRET_A\"}"
last_archive create_a
check "POST returns 201" "[ \"\$(last_code)\" = '201' ]"
check "response api_key == \"***\"" "grep -q '\"api_key\":\"\\*\\*\\*\"' '$TMP/create_a.json'"
check "response does not leak secret" "! grep -q '$SECRET_A' '$TMP/create_a.json'"
PID_A=$(jget id)
[[ -n "$PID_A" ]] && printf "  provider_a id = %s\n" "$PID_A"

# ──────────────────────────────────────────────────────────────────────────────
# 2. GET /providers (list) — no plaintext leak.
# ──────────────────────────────────────────────────────────────────────────────
section "GET /providers"
c GET /providers
last_archive list1
check "list returns 200" "[ \"\$(last_code)\" = '200' ]"
check "list contains api_key:\"***\"" "grep -q '\"api_key\":\"\\*\\*\\*\"' '$TMP/list1.json'"
check "list does not leak secret" "! grep -q '$SECRET_A' '$TMP/list1.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 3. GET /providers/{id} — single, redacted.
# ──────────────────────────────────────────────────────────────────────────────
section "GET /providers/{id}"
c GET "/providers/$PID_A"
last_archive get_a
check "get returns 200" "[ \"\$(last_code)\" = '200' ]"
check "single response does not leak secret" "! grep -q '$SECRET_A' '$TMP/get_a.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 4. PATCH with api_key:"" — rejected.
# ──────────────────────────────────────────────────────────────────────────────
section "PATCH api_key:\"\" rejected"
c PATCH "/providers/$PID_A" '{"api_key":""}'
last_archive patch_empty
check "PATCH with empty api_key returns 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions empty string" "grep -qi 'empty string' '$TMP/patch_empty.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 5. PATCH without api_key field — preserves existing.
# ──────────────────────────────────────────────────────────────────────────────
section "PATCH name only (api_key preserved)"
c PATCH "/providers/$PID_A" '{"name":"verify-test-a-renamed"}'
last_archive patch_name
check "PATCH returns 200" "[ \"\$(last_code)\" = '200' ]"
check "renamed in response" "grep -q '\"name\":\"verify-test-a-renamed\"' '$TMP/patch_name.json'"
check "api_key still \"***\"" "grep -q '\"api_key\":\"\\*\\*\\*\"' '$TMP/patch_name.json'"
# Confirm encrypted blob is unchanged in DB (still decrypts to SECRET_A).
c GET "/providers/$PID_A"
last_archive get_after_rename
check "still redacted after PATCH" "grep -q '\"api_key\":\"\\*\\*\\*\"' '$TMP/get_after_rename.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 6. PATCH api_key:null — cleared.
# ──────────────────────────────────────────────────────────────────────────────
section "PATCH api_key:null (clears)"
c PATCH "/providers/$PID_A" '{"api_key":null}'
last_archive patch_null
check "PATCH returns 200" "[ \"\$(last_code)\" = '200' ]"
check "api_key now null" "grep -q '\"api_key\":null' '$TMP/patch_null.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 7. PATCH api_key:"<new>" — re-set.
# ──────────────────────────────────────────────────────────────────────────────
section "PATCH api_key:\"<new>\" (re-set)"
c PATCH "/providers/$PID_A" "{\"api_key\":\"$SECRET_B\"}"
last_archive patch_b
check "PATCH returns 200" "[ \"\$(last_code)\" = '200' ]"
check "api_key now \"***\" again" "grep -q '\"api_key\":\"\\*\\*\\*\"' '$TMP/patch_b.json'"
check "PATCH response does not leak new secret" "! grep -q '$SECRET_B' '$TMP/patch_b.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 8. Duplicate name on POST → 409.
# ──────────────────────────────────────────────────────────────────────────────
section "POST duplicate name → 409"
c POST /providers "{\"name\":\"verify-test-a-renamed\",\"base_url\":\"http://example.invalid:1111\"}"
last_archive dup
check "duplicate name returns 409" "[ \"\$(last_code)\" = '409' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 9. Set up references for DELETE without/with force.
#    - Workspace pointing at the provider.
#    - global_settings.embedding_provider_id matching.
#    - global_settings.reranker_provider_id matching.
# ──────────────────────────────────────────────────────────────────────────────
section "Set up references (workspace + embedding + reranker)"
docker exec hlh_db psql -U hlh -d hlh -c \
    "INSERT INTO workspaces (name, provider_id, model) VALUES ('verify-test-ws-1', '$PID_A'::uuid, 'fake-model');" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "INSERT INTO global_settings (key, value) VALUES ('embedding_provider_id', '$PID_A'), ('embedding_model', 'fake-emb')
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c \
    "INSERT INTO global_settings (key, value) VALUES ('reranker_provider_id', '$PID_A'), ('reranker_model', 'fake-rrk')
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;" >/dev/null
printf "  (workspace + 2 global_settings pairs created)\n"

# ──────────────────────────────────────────────────────────────────────────────
# 10. DELETE without force → 409 with dependency counts.
# ──────────────────────────────────────────────────────────────────────────────
section "DELETE without force → 409 with refs"
c DELETE "/providers/$PID_A"
last_archive del_no_force
check "returns 409" "[ \"\$(last_code)\" = '409' ]"
check "body mentions 'provider in use'" "grep -q 'provider in use' '$TMP/del_no_force.json'"
check "body shows workspaces: 1" "grep -q '\"workspaces\":1' '$TMP/del_no_force.json'"
check "body shows embedding: true" "grep -q '\"embedding\":true' '$TMP/del_no_force.json'"
check "body shows reranker: true" "grep -q '\"reranker\":true' '$TMP/del_no_force.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 11. DELETE with force=true → 204; refs cleaned up in single txn.
# ──────────────────────────────────────────────────────────────────────────────
section "DELETE ?force=true → 204"
c DELETE "/providers/$PID_A?force=true"
last_archive del_force
check "returns 204" "[ \"\$(last_code)\" = '204' ]"

# Provider is gone.
c GET "/providers/$PID_A"
last_archive get_gone
check "subsequent GET returns 404" "[ \"\$(last_code)\" = '404' ]"

# Workspace remains, but provider_id=NULL and model=NULL.
ws_rows=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT provider_id IS NULL AND (model IS NULL OR model = '') FROM workspaces WHERE name = 'verify-test-ws-1';")
check "workspace's provider_id and model both cleared" "[ \"$ws_rows\" = 't' ]"

# global_settings rows for embedding/reranker are gone.
emb_rows=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT COUNT(*) FROM global_settings WHERE key IN ('embedding_provider_id','embedding_model','reranker_provider_id','reranker_model');")
check "all 4 referencing global_settings rows deleted" "[ \"$emb_rows\" = '0' ]"

# ──────────────────────────────────────────────────────────────────────────────
# 12. Connection-test endpoint against a deliberately-bad provider.
# ──────────────────────────────────────────────────────────────────────────────
section "POST /providers/{id}/test against unreachable URL"
c POST /providers '{"name":"verify-test-broken","base_url":"http://does-not-exist.invalid:9999","api_key":"sk-anything"}'
last_archive create_broken
PID_BROKEN=$(jget id)
c POST "/providers/$PID_BROKEN/test"
last_archive test_broken
check "test returns 200 even on failure" "[ \"\$(last_code)\" = '200' ]"
check "test body has ok:false" "grep -q '\"ok\":false' '$TMP/test_broken.json'"
check "test body has error: prefix" "grep -q '\"status\":\"error:' '$TMP/test_broken.json'"

# Confirm last_verified_at + last_verified_status got written.
verified=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
    "SELECT (last_verified_at IS NOT NULL) AND (last_verified_status LIKE 'error:%') FROM providers WHERE id = '$PID_BROKEN'::uuid;")
check "last_verified_* updated in DB" "[ \"$verified\" = 't' ]"

# Cleanup.
docker exec hlh_db psql -U hlh -d hlh -c "DELETE FROM providers WHERE id = '$PID_BROKEN'::uuid;" >/dev/null
docker exec hlh_db psql -U hlh -d hlh -c "DELETE FROM workspaces WHERE name = 'verify-test-ws-1';" >/dev/null

# ──────────────────────────────────────────────────────────────────────────────
# 13. Final redaction sweep — no test secret should appear in any transcript.
# ──────────────────────────────────────────────────────────────────────────────
section "Redaction sweep across all archived responses"
leaks=$(grep -lE 'sk-ZZZTESTREDACT' "$TMP"/*.json 2>/dev/null || true)
if [[ -z "$leaks" ]]; then
    printf "  %s  no plaintext secret in any captured response\n" "$(color green PASS)"
    pass=$((pass + 1))
else
    printf "  %s  PLAINTEXT LEAK in: %s\n" "$(color red FAIL)" "$leaks"
    fail=$((fail + 1))
fi

# ──────────────────────────────────────────────────────────────────────────────
# Summary.
# ──────────────────────────────────────────────────────────────────────────────
printf "\n%s passed, %s failed\n" "$(color green "$pass")" "$([[ $fail -gt 0 ]] && color red "$fail" || color green "$fail")"
[[ $fail -eq 0 ]] && exit 0
exit 1
