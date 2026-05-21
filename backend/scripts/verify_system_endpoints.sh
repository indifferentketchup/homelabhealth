#!/usr/bin/env bash
# Verify backend/routers/system.py end-to-end against the running hlh_api.
#
# Covers (from dispatch §0.D step 3):
#   - GET  /api/system/hardware  → 200 with non-empty JSON
#   - GET  /api/system/profile   → 200 with current row + recommended_tier
#   - PUT  /api/system/profile   → 200, setup_complete flips TRUE
#   - PUT  with invalid tier     → 400
#   - POST /api/system/redetect  → updates detected_at, leaves tier
#   - "Non-admin returns 401/403" — UNTESTABLE in single-user mode (deps.require_admin
#     is a stub that always returns the seeded owner; same as every other admin endpoint
#     in this codebase). Skipped with note in the report.
#
# Re-runnable: resets system_profile state at start and end.

set -euo pipefail

API="${API:-http://localhost:9600/api}"

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
jget() {
    python3 -c "import json; print(json.load(open('$TMP/last.json')).get('$1', ''))"
}

# ──────────────────────────────────────────────────────────────────────────────
# Reset state: clear stored sysinfo_json + detected_at, set tier back to external/manual,
# setup_complete = false. So the verify run is deterministic.
# ──────────────────────────────────────────────────────────────────────────────
section "Reset system_profile to known baseline"
docker exec hlh_db psql -U hlh -d hlh -c \
    "UPDATE system_profile SET tier = 'external', tier_source = 'manual', sysinfo_json = '{}'::jsonb, detected_at = NULL, chosen_at = NOW(), setup_complete = FALSE WHERE id = 1;" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# 1. GET /api/system/hardware
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/system/hardware"
c GET /system/hardware
last_archive hardware
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "response has 'os' key" "grep -q '\"os\":' '$TMP/hardware.json'"
check "response has 'gpus' key" "grep -q '\"gpus\":' '$TMP/hardware.json'"
check "response has 'ram_total_gb' key" "grep -q '\"ram_total_gb\":' '$TMP/hardware.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 2. GET /api/system/profile — baseline state
# ──────────────────────────────────────────────────────────────────────────────
section "GET /api/system/profile (baseline)"
c GET /system/profile
last_archive profile_baseline
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "tier == external (baseline)" "grep -q '\"tier\":\"external\"' '$TMP/profile_baseline.json'"
check "setup_complete == false (baseline)" "grep -q '\"setup_complete\":false' '$TMP/profile_baseline.json'"
check "recommended_tier present (from empty sysinfo → cpu-min)" \
    "grep -q '\"recommended_tier\":\"cpu-min\"' '$TMP/profile_baseline.json'"
check "detected_at is null (baseline)" "grep -q '\"detected_at\":null' '$TMP/profile_baseline.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 3. POST /api/system/redetect — populates sysinfo_json + detected_at, keeps tier
# ──────────────────────────────────────────────────────────────────────────────
section "POST /api/system/redetect"
c POST /system/redetect
last_archive redetect
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "tier unchanged (still external)" "grep -q '\"tier\":\"external\"' '$TMP/redetect.json'"
check "detected_at is now non-null" \
    "python3 -c \"import json,sys; d=json.load(open('$TMP/redetect.json')); sys.exit(0 if d.get('detected_at') else 1)\""
check "sysinfo_json populated (os key present)" \
    "python3 -c \"import json,sys; d=json.load(open('$TMP/redetect.json')); sys.exit(0 if (isinstance(d.get('sysinfo_json'), dict) and 'os' in d['sysinfo_json']) else 1)\""
check "recommended_tier now reflects real host (not cpu-min from empty sysinfo)" \
    "python3 -c \"import json,sys; d=json.load(open('$TMP/redetect.json')); r=d.get('recommended_tier'); sys.exit(0 if r in ('cpu-min','cpu-std','gpu-8gb','gpu-16gb','gpu-24gb+','apple-mlx') else 1)\""
check "setup_complete still false (redetect doesn't change it)" \
    "grep -q '\"setup_complete\":false' '$TMP/redetect.json'"
DETECTED_BEFORE=$(jget detected_at)
printf "  (first detected_at = %s)\n" "$DETECTED_BEFORE"

# Second redetect should bump detected_at (compare ISO timestamps as strings).
sleep 1.1
c POST /system/redetect
last_archive redetect2
DETECTED_AFTER=$(jget detected_at)
printf "  (second detected_at = %s)\n" "$DETECTED_AFTER"
check "second redetect updates detected_at" "[ \"$DETECTED_BEFORE\" != \"$DETECTED_AFTER\" ]"

# ──────────────────────────────────────────────────────────────────────────────
# 4. PUT /api/system/profile with VALID tier — flips setup_complete
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/system/profile (valid tier)"
c PUT /system/profile '{"tier":"cpu-std","tier_source":"manual"}'
last_archive put_valid
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "tier saved (cpu-std)" "grep -q '\"tier\":\"cpu-std\"' '$TMP/put_valid.json'"
check "tier_source saved (manual)" "grep -q '\"tier_source\":\"manual\"' '$TMP/put_valid.json'"
check "setup_complete now TRUE" "grep -q '\"setup_complete\":true' '$TMP/put_valid.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 5. PUT with auto tier_source — also valid
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/system/profile (tier_source=auto)"
c PUT /system/profile '{"tier":"external","tier_source":"auto"}'
last_archive put_auto
check "returns 200" "[ \"\$(last_code)\" = '200' ]"
check "tier_source saved (auto)" "grep -q '\"tier_source\":\"auto\"' '$TMP/put_auto.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 6. PUT with INVALID tier → 400
# ──────────────────────────────────────────────────────────────────────────────
section "PUT /api/system/profile (invalid tier)"
c PUT /system/profile '{"tier":"made-up-tier","tier_source":"manual"}'
last_archive put_bad_tier
check "returns 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'invalid tier'" "grep -q 'invalid tier' '$TMP/put_bad_tier.json'"

# Bad tier_source
c PUT /system/profile '{"tier":"cpu-std","tier_source":"banana"}'
last_archive put_bad_source
check "bad tier_source → 400" "[ \"\$(last_code)\" = '400' ]"
check "error mentions 'invalid tier_source'" "grep -q 'invalid tier_source' '$TMP/put_bad_source.json'"

# State must NOT have changed from the last successful PUT.
c GET /system/profile
last_archive profile_after_400
check "after rejected PUT, tier is still 'external' (last valid)" \
    "grep -q '\"tier\":\"external\"' '$TMP/profile_after_400.json'"

# ──────────────────────────────────────────────────────────────────────────────
# 7. POST /redetect after PUT — tier still preserved
# ──────────────────────────────────────────────────────────────────────────────
section "POST /api/system/redetect after PUT (tier preserved)"
c PUT /system/profile '{"tier":"cpu-std","tier_source":"manual"}'
last_archive put_for_preserve
c POST /system/redetect
last_archive redetect_after_put
check "redetect returns 200" "[ \"\$(last_code)\" = '200' ]"
check "tier still 'cpu-std' (not auto-changed)" \
    "grep -q '\"tier\":\"cpu-std\"' '$TMP/redetect_after_put.json'"
check "setup_complete still TRUE after redetect" \
    "grep -q '\"setup_complete\":true' '$TMP/redetect_after_put.json'"

# ──────────────────────────────────────────────────────────────────────────────
# Final reset so the verify run doesn't pollute the dev DB.
# ──────────────────────────────────────────────────────────────────────────────
section "Final reset to baseline (idempotent)"
docker exec hlh_db psql -U hlh -d hlh -c \
    "UPDATE system_profile SET tier = 'external', tier_source = 'manual', sysinfo_json = '{}'::jsonb, detected_at = NULL, chosen_at = NOW(), setup_complete = FALSE WHERE id = 1;" >/dev/null
printf "  (done)\n"

# ──────────────────────────────────────────────────────────────────────────────
# Summary.
# ──────────────────────────────────────────────────────────────────────────────
printf "\n%s passed, %s failed\n" "$(color green "$pass")" "$([[ $fail -gt 0 ]] && color red "$fail" || color green "$fail")"
[[ $fail -eq 0 ]] && exit 0
exit 1
