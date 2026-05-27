#!/usr/bin/env bash
# verify_a3_sidecar_split.sh — Phase A3: sidecar split + vision embed checks.
# Run from the host (not inside a container).
set -euo pipefail

API="http://localhost:9600"
PASS=0; FAIL=0; WARN=0

ok()   { echo "  ✓ $1"; ((PASS++)); }
fail() { echo "  ✗ $1"; ((FAIL++)); }
warn() { echo "  ⚠ $1"; ((WARN++)); }

# ── Auth: get session cookie ──────────────────────────────────────────────
echo "=== Auth ==="
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT
LOGIN_RESP=$(curl -s -o /dev/null -w '%{http_code}' -c "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -d '{"username":"sam","password":"sam"}' \
  "$API/api/auth/login" 2>/dev/null)
if [[ "$LOGIN_RESP" == "200" ]]; then
  ok "logged in"
else
  fail "login failed (HTTP $LOGIN_RESP) — remaining checks may 401"
fi

authed_curl() {
  curl -s -b "$COOKIE_JAR" "$@"
}

# ── Sidecar split checks ─────────────────────────────────────────────────
echo ""
echo "=== 1. hlh_infer container does NOT exist ==="
if docker ps -a --format '{{.Names}}' | grep -qx hlh_infer; then
  fail "hlh_infer container still exists"
else
  ok "hlh_infer container removed"
fi

echo ""
echo "=== 2. hlh_embed responds on /v1/embeddings ==="
EMBED_RESP=$(docker exec hlh_embed curl -s -o /dev/null -w '%{http_code}' \
  -X POST http://localhost:7997/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-m3","input":["test"]}' 2>/dev/null)
if [[ "$EMBED_RESP" == "200" ]]; then
  ok "hlh_embed /v1/embeddings → 200"
else
  fail "hlh_embed /v1/embeddings → HTTP $EMBED_RESP"
fi

echo ""
echo "=== 3. hlh_rerank responds on /v1/rerank ==="
RERANK_RESP=$(docker exec hlh_rerank curl -s -o /dev/null -w '%{http_code}' \
  -X POST http://localhost:7997/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-reranker-v2-m3","query":"test","documents":["a","b"]}' 2>/dev/null)
if [[ "$RERANK_RESP" == "200" ]]; then
  ok "hlh_rerank /v1/rerank → 200"
else
  fail "hlh_rerank /v1/rerank → HTTP $RERANK_RESP"
fi

echo ""
echo "=== 4. Bundled embed provider base_url contains hlh_embed:7997 ==="
EMBED_URL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT base_url FROM providers WHERE role='embed' AND is_bundled=true")
if echo "$EMBED_URL" | grep -q 'hlh_embed:7997'; then
  ok "embed base_url=$EMBED_URL"
else
  fail "embed base_url=$EMBED_URL (expected hlh_embed:7997)"
fi

echo ""
echo "=== 5. Bundled rerank provider base_url contains hlh_rerank:7997 ==="
RERANK_URL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT base_url FROM providers WHERE role='rerank' AND is_bundled=true")
if echo "$RERANK_URL" | grep -q 'hlh_rerank:7997'; then
  ok "rerank base_url=$RERANK_URL"
else
  fail "rerank base_url=$RERANK_URL (expected hlh_rerank:7997)"
fi

echo ""
echo "=== 6. Embedding end-to-end (1024-dim) ==="
EMBED_DIM=$(docker exec hlh_embed curl -s \
  -X POST http://localhost:7997/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-m3","input":["test embedding"]}' 2>/dev/null \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data'][0]['embedding']))" 2>/dev/null)
if [[ "$EMBED_DIM" == "1024" ]]; then
  ok "embedding dim=1024"
else
  fail "embedding dim=$EMBED_DIM (expected 1024)"
fi

echo ""
echo "=== 7. Rerank end-to-end ==="
RERANK_OK=$(docker exec hlh_rerank curl -s \
  -X POST http://localhost:7997/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"model":"BAAI/bge-reranker-v2-m3","query":"health","documents":["medical record","weather forecast"]}' 2>/dev/null \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print('ok' if isinstance(r.get('results'),list) else 'fail')" 2>/dev/null)
if [[ "$RERANK_OK" == "ok" ]]; then
  ok "rerank returns results"
else
  fail "rerank response malformed"
fi

echo ""
echo "=== 8. No hlh_infer references in backend Python ==="
INFER_REFS=$(grep -rn 'hlh_infer' /opt/homelabhealth/backend/ --include='*.py' | grep -v __pycache__ || true)
if [[ -z "$INFER_REFS" ]]; then
  ok "zero hlh_infer references in *.py"
else
  fail "hlh_infer references remain: $INFER_REFS"
fi

# ── Vision embed checks ──────────────────────────────────────────────────
echo ""
echo "=== 9. providers_role_check includes vision_embed ==="
ROLE_CHECK=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT consrc FROM pg_constraint WHERE conname='providers_role_check'" 2>/dev/null || \
  docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='providers_role_check'")
if echo "$ROLE_CHECK" | grep -q 'vision_embed'; then
  ok "providers_role_check includes vision_embed"
else
  fail "providers_role_check missing vision_embed: $ROLE_CHECK"
fi

echo ""
echo "=== 10. image_chunks table exists with vector(1152) ==="
IC_EXISTS=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name='image_chunks' AND column_name='embedding'" 2>/dev/null)
if echo "$IC_EXISTS" | grep -q 'embedding'; then
  ok "image_chunks.embedding column exists"
else
  fail "image_chunks table or embedding column missing"
fi

echo ""
echo "=== 11. global_settings vision_embed keys ==="
# These are only set when vision sidecar is active; check schema allows them
VE_PID=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT value FROM global_settings WHERE key='vision_embed_provider_id'" 2>/dev/null)
VE_MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT value FROM global_settings WHERE key='vision_embed_model'" 2>/dev/null)
VE_PID=$(echo "$VE_PID" | tr -d '[:space:]')
VE_MODEL=$(echo "$VE_MODEL" | tr -d '[:space:]')
if [[ -n "$VE_PID" && -n "$VE_MODEL" ]]; then
  ok "vision_embed_provider_id=$VE_PID, vision_embed_model=$VE_MODEL"
else
  warn "vision_embed settings not set (expected if vision profile not active)"
fi

echo ""
echo "=== 12. hlh_vision_embed container (if vision profile active) ==="
if docker ps --format '{{.Names}}' | grep -qx hlh_vision_embed; then
  VISION_HEALTH=$(docker exec hlh_vision_embed curl -s -o /dev/null -w '%{http_code}' http://localhost:7997/health 2>/dev/null)
  if [[ "$VISION_HEALTH" == "200" ]]; then
    ok "hlh_vision_embed healthy"
  else
    fail "hlh_vision_embed unhealthy (HTTP $VISION_HEALTH)"
  fi
else
  warn "hlh_vision_embed not running (expected if vision profile not active)"
fi

echo ""
echo "=== 13. Bundled vision_embed provider immutability ==="
VE_ROW=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT id FROM providers WHERE role='vision_embed' AND is_bundled=true" 2>/dev/null | tr -d '[:space:]')
if [[ -n "$VE_ROW" ]]; then
  DEL_RESP=$(authed_curl -o /dev/null -w '%{http_code}' -X DELETE "$API/api/providers/$VE_ROW")
  if [[ "$DEL_RESP" == "403" ]]; then
    ok "DELETE bundled vision_embed → 403"
  else
    fail "DELETE bundled vision_embed → HTTP $DEL_RESP (expected 403)"
  fi
else
  warn "no bundled vision_embed provider row (expected if vision profile not active)"
fi

echo ""
echo "=== 14-15. Vision API endpoints (if vision active) ==="
if [[ -n "$VE_PID" ]]; then
  # 8x8 red PNG base64
  TEST_IMG="iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP8z4AdMOEQH6QSAM1BAQ/oQeJvAAAAAElFTkSuQmCC"

  EMBED_RESP=$(authed_curl -H 'Content-Type: application/json' \
    -d "{\"image\":\"$TEST_IMG\"}" "$API/api/vision/embed")
  EMBED_DIM=$(echo "$EMBED_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dim',0))" 2>/dev/null)
  if [[ "$EMBED_DIM" == "1152" ]]; then
    ok "POST /api/vision/embed → dim=1152"
  else
    fail "POST /api/vision/embed → dim=$EMBED_DIM (expected 1152)"
  fi

  TEXT_RESP=$(authed_curl -H 'Content-Type: application/json' \
    -d '{"text":"chest x-ray"}' "$API/api/vision/embed")
  TEXT_DIM=$(echo "$TEXT_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dim',0))" 2>/dev/null)
  if [[ "$TEXT_DIM" == "1152" ]]; then
    ok "POST /api/vision/embed (text) → dim=1152"
  else
    fail "POST /api/vision/embed (text) → dim=$TEXT_DIM (expected 1152)"
  fi

  CLASSIFY_RESP=$(authed_curl -H 'Content-Type: application/json' \
    -d "{\"image\":\"$TEST_IMG\",\"labels\":[\"normal\",\"pneumonia\",\"fracture\"]}" \
    "$API/api/vision/classify")
  CLASS_COUNT=$(echo "$CLASSIFY_RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('classifications',[])))" 2>/dev/null)
  if [[ "$CLASS_COUNT" == "3" ]]; then
    ok "POST /api/vision/classify → 3 classifications"
  else
    fail "POST /api/vision/classify → $CLASS_COUNT classifications (expected 3)"
  fi
else
  warn "skipping vision API tests (vision not configured)"
fi

echo ""
echo "=== 18. Vision endpoints 503 when not configured ==="
if [[ -z "$VE_PID" ]]; then
  NOCFG_RESP=$(authed_curl -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d '{"text":"test"}' "$API/api/vision/embed")
  if [[ "$NOCFG_RESP" == "503" ]]; then
    ok "POST /api/vision/embed → 503 when not configured"
  else
    fail "POST /api/vision/embed → HTTP $NOCFG_RESP (expected 503)"
  fi
else
  warn "skipping 503 test (vision is configured)"
fi

echo ""
echo "=== 19. Doctor checks ==="
DOCTOR_RESP=$(authed_curl "$API/api/system/doctor")
DOCTOR_ERRORS=$(echo "$DOCTOR_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('error',0))" 2>/dev/null)
echo "  Doctor summary: $(echo "$DOCTOR_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('summary',{}))" 2>/dev/null)"
if [[ "$DOCTOR_ERRORS" == "0" ]]; then
  ok "doctor: 0 errors"
else
  warn "doctor: $DOCTOR_ERRORS errors (may be expected for missing sidecars)"
fi

echo ""
echo "=== 20. INFINITY_ENGINE per sidecar ==="
EMBED_ENGINE=$(docker inspect hlh_embed --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep INFINITY_ENGINE || true)
RERANK_ENGINE=$(docker inspect hlh_rerank --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep INFINITY_ENGINE || true)
if echo "$EMBED_ENGINE" | grep -q 'optimum'; then
  ok "hlh_embed INFINITY_ENGINE=optimum"
else
  fail "hlh_embed engine: $EMBED_ENGINE"
fi
if echo "$RERANK_ENGINE" | grep -q 'torch'; then
  ok "hlh_rerank INFINITY_ENGINE=torch"
else
  fail "hlh_rerank engine: $RERANK_ENGINE"
fi

if docker ps --format '{{.Names}}' | grep -qx hlh_vision_embed; then
  VISION_ENGINE=$(docker inspect hlh_vision_embed --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep INFINITY_ENGINE || true)
  if echo "$VISION_ENGINE" | grep -q 'torch'; then
    ok "hlh_vision_embed INFINITY_ENGINE=torch"
  else
    fail "hlh_vision_embed engine: $VISION_ENGINE"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
echo "════════════════════════════════════════"
exit $FAIL
