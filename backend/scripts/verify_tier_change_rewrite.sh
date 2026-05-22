#!/usr/bin/env bash
# Verify that apply_bundled_bindings rewrites workspaces.model on tier change,
# blowing away any override on bundled-chat-bound workspaces. External-bound
# workspaces remain untouched (apply_bundled_bindings is a no-op for tier=external).
# Spec: docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md §4
set -euo pipefail

API="${API:-http://localhost:9600}"

# Save pre-state to restore at end
PRE_TIER=$(docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT tier FROM system_profile WHERE id=1;" | tr -d '[:space:]')
echo "Starting tier: $PRE_TIER"

# Get the bundled chat provider UUID for assertions
BUNDLED_CHAT_ID=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT id FROM providers WHERE is_bundled=TRUE AND role='chat';" | tr -d '[:space:]')
echo "bundled chat id: $BUNDLED_CHAT_ID"

echo "=== 1. Create a test workspace (auto-bound to bundled chat) ==="
WS=$(curl -sSL -X POST "$API/api/workspaces/" \
  -H 'content-type: application/json' -d '{"name":"tier-rewrite-test","color":"#8FAE92"}')
WS_ID=$(echo "$WS" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  workspace id: $WS_ID"
echo "  initial model: $(echo "$WS" | python3 -c "import sys,json; print(json.load(sys.stdin)['model'])")"

# Cleanup trap — runs on script exit (pass or fail)
cleanup() {
  echo "=== Cleanup ==="
  docker exec hlh_db psql -U hlh -d hlh -c "DELETE FROM chats WHERE workspace_id='$WS_ID';" >/dev/null 2>&1 || true
  docker exec hlh_db psql -U hlh -d hlh -c "DELETE FROM workspaces WHERE id='$WS_ID';" >/dev/null 2>&1 || true
  # Restore tier
  if [[ -n "$PRE_TIER" && "$PRE_TIER" != "None" ]]; then
    curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
      -H 'content-type: application/json' -d "{\"tier\":\"$PRE_TIER\",\"tier_source\":\"manual\"}"
    echo "  Restored tier to $PRE_TIER"
  fi
}
trap cleanup EXIT

echo "=== 2. Switch tier to cpu-min — workspace model should update ==="
curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
  -H 'content-type: application/json' -d '{"tier":"cpu-min","tier_source":"manual"}'
MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model after cpu-min: $MODEL"
[[ "$MODEL" == "Qwen3.5-0.8B-Q8_0.gguf" ]] && echo "  OK" || { echo "  FAIL: expected Qwen3.5-0.8B-Q8_0.gguf, got $MODEL"; exit 1; }

echo "=== 3. Switch tier to cpu-std — workspace model should update again ==="
curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
  -H 'content-type: application/json' -d '{"tier":"cpu-std","tier_source":"manual"}'
MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model after cpu-std: $MODEL"
[[ "$MODEL" == "medgemma-1.5-4b-it-Q4_K_M.gguf" ]] && echo "  OK" || { echo "  FAIL: expected medgemma-1.5-4b-it-Q4_K_M.gguf, got $MODEL"; exit 1; }

echo "=== 4. Override blown away on tier change ==="
# Manually PATCH a custom model while staying on bundled chat
curl -sS -o /dev/null -X PATCH "$API/api/workspaces/$WS_ID" \
  -H 'content-type: application/json' -d '{"model":"my-custom-override.gguf"}'
MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model after override: $MODEL"
[[ "$MODEL" == "my-custom-override.gguf" ]] && echo "  OK override stuck" || { echo "  FAIL: override not stored, got $MODEL"; exit 1; }

# Now change tier — override should be blown away
curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
  -H 'content-type: application/json' -d '{"tier":"cpu-min","tier_source":"manual"}'
MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model after tier switch (override should be gone): $MODEL"
[[ "$MODEL" == "Qwen3.5-0.8B-Q8_0.gguf" ]] && echo "  OK override reset" || { echo "  FAIL: override not reset, got $MODEL"; exit 1; }

echo "=== 5. External tier is a no-op; switching back rebinds ==="
# Switch to external — apply_bundled_bindings no-ops, workspace model stays as-is
MODEL_BEFORE_EXTERNAL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
  -H 'content-type: application/json' -d '{"tier":"external","tier_source":"manual"}'
MODEL_AFTER_EXTERNAL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model unchanged after tier=external: $MODEL_AFTER_EXTERNAL (was $MODEL_BEFORE_EXTERNAL)"
[[ "$MODEL_AFTER_EXTERNAL" == "$MODEL_BEFORE_EXTERNAL" ]] && echo "  OK: external no-op confirmed" || { echo "  FAIL: model changed unexpectedly on tier=external"; exit 1; }

# Switch back to cpu-std — workspace should rebind to cpu-std model
curl -sS -o /dev/null -X PUT "$API/api/system/profile" \
  -H 'content-type: application/json' -d '{"tier":"cpu-std","tier_source":"manual"}'
MODEL=$(docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT model FROM workspaces WHERE id='$WS_ID';" | tr -d '[:space:]')
echo "  model after restore to cpu-std: $MODEL"
[[ "$MODEL" == "medgemma-1.5-4b-it-Q4_K_M.gguf" ]] && echo "  OK" || { echo "  FAIL: tier restore didn't rebind, got $MODEL"; exit 1; }

echo "=== ALL CHECKS PASSED ==="
