#!/usr/bin/env bash
# verify_dynamic_images.sh — Dynamic Docker image selection checks.
set -euo pipefail

PASS=0; FAIL=0; WARN=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠ $1"; WARN=$((WARN+1)); }

COMPOSE_DIR=/opt/homelabhealth

echo "=== 1. .env contains image vars ==="
if grep -q 'HLH_CHAT_IMAGE\|COMPOSE_PROFILES' "$COMPOSE_DIR/.env" 2>/dev/null; then
  ok ".env has HLH_CHAT_IMAGE or COMPOSE_PROFILES"
else
  fail ".env missing image vars"
fi

echo ""
echo "=== 2. compose resolves for bundled ==="
if cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled docker compose config --services >/dev/null 2>&1; then
  ok "COMPOSE_PROFILES=bundled resolves"
else
  fail "COMPOSE_PROFILES=bundled fails"
fi

echo ""
echo "=== 3. compose resolves for bundled-gpu ==="
if cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled-gpu docker compose config --services >/dev/null 2>&1; then
  ok "COMPOSE_PROFILES=bundled-gpu resolves"
else
  fail "COMPOSE_PROFILES=bundled-gpu fails"
fi

echo ""
echo "=== 4. compose resolves for bundled-gpu,vision ==="
if cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled-gpu,vision docker compose config --services >/dev/null 2>&1; then
  ok "COMPOSE_PROFILES=bundled-gpu,vision resolves"
else
  fail "COMPOSE_PROFILES=bundled-gpu,vision fails"
fi

echo ""
echo "=== 5. TIER_IMAGE_MAP covers all tiers ==="
RESULT=$(docker exec hlh_api python -c "
from services.image_config import TIER_IMAGE_MAP
from services.sysinfo import ALL_TIERS
missing = ALL_TIERS - set(TIER_IMAGE_MAP.keys())
if missing:
    print(f'MISSING: {missing}')
else:
    print('OK')
" 2>/dev/null)
if [[ "$RESULT" == "OK" ]]; then
  ok "TIER_IMAGE_MAP covers all tiers"
else
  fail "TIER_IMAGE_MAP $RESULT"
fi

echo ""
echo "=== 6. write_tier_env round-trip ==="
TMPENV=$(mktemp)
cp "$COMPOSE_DIR/.env" "$TMPENV.orig"
RESULT=$(cd "$COMPOSE_DIR/backend" && HLH_ENV_PATH="$TMPENV" python3 -c "
import shutil
shutil.copy('$COMPOSE_DIR/.env', '$TMPENV')
import services.image_config as ic
ic.ENV_PATH = '$TMPENV'
ok = ic.write_tier_env('cpu-std')
with open('$TMPENV') as f:
    content = f.read()
has_chat = 'HLH_CHAT_IMAGE=' in content
has_profiles = 'COMPOSE_PROFILES=' in content
print('OK' if (ok and has_chat and has_profiles) else f'FAIL ok={ok} chat={has_chat} profiles={has_profiles}')
" 2>&1)
rm -f "$TMPENV" "$TMPENV.orig" "${TMPENV}.bak-"* 2>/dev/null
if [[ "$RESULT" == "OK" ]]; then
  ok "write_tier_env round-trip"
else
  fail "write_tier_env: $RESULT"
fi

echo ""
echo "=== 7. Doctor image_tier_match check ==="
RESULT=$(docker exec hlh_api python -c "
import asyncio
from hlh.doctor import _check_image_tier_match
from services.key_manager import ensure_keys
ensure_keys()
async def go():
    from db import init_pool, close_pool
    await init_pool()
    try:
        r = await _check_image_tier_match()
        print(r['status'], r['detail'])
    finally:
        await close_pool()
asyncio.run(go())
" 2>/dev/null)
if echo "$RESULT" | grep -q '^ok'; then
  ok "image_tier_match: $RESULT"
else
  warn "image_tier_match: $RESULT"
fi

echo ""
echo "=== 8. No duplicate container_name conflicts ==="
for profile in bundled bundled-gpu "bundled-gpu,vision"; do
  NAMES=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES="$profile" docker compose config 2>/dev/null | grep 'container_name:' | sort)
  DUPES=$(echo "$NAMES" | sort | uniq -d)
  if [[ -z "$DUPES" ]]; then
    ok "profile=$profile: no duplicate container_name"
  else
    fail "profile=$profile: duplicate container_name: $DUPES"
  fi
done

echo ""
echo "=== 9. CPU profile starts without NVIDIA ==="
CPU_SERVICES=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled docker compose config --services 2>/dev/null | sort)
if echo "$CPU_SERVICES" | grep -q 'hlh_chat_cpu'; then
  ok "bundled profile includes hlh_chat_cpu (no GPU required)"
else
  fail "bundled profile missing hlh_chat_cpu"
fi
if echo "$CPU_SERVICES" | grep -q 'hlh_chat_gpu'; then
  fail "bundled profile includes hlh_chat_gpu (should not)"
else
  ok "bundled profile excludes hlh_chat_gpu"
fi

echo ""
echo "=== 10. Compose defaults are CPU (safe fresh-clone) ==="
CHAT_DEFAULT=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled docker compose config 2>/dev/null | grep -A100 'hlh_chat_cpu:' | grep '^\s*image:' | head -1 | awk '{print $2}')
if echo "$CHAT_DEFAULT" | grep -q 'server-b9603' && ! echo "$CHAT_DEFAULT" | grep -q 'cuda'; then
  ok "hlh_chat_cpu default image is CPU: $CHAT_DEFAULT"
else
  fail "hlh_chat_cpu default image: $CHAT_DEFAULT"
fi

echo ""
echo "=== 11. hlh_chat_cpu and hlh_chat_gpu share container_name ==="
CPU_CN=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled docker compose config 2>/dev/null | grep -A30 'hlh_chat_cpu:' | grep '^\s*container_name:' | head -1 | awk '{print $2}')
GPU_CN=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled-gpu docker compose config 2>/dev/null | grep -A30 'hlh_chat_gpu:' | grep '^\s*container_name:' | head -1 | awk '{print $2}')
if [[ "$CPU_CN" == "hlh_chat" && "$GPU_CN" == "hlh_chat" ]]; then
  ok "both share container_name=hlh_chat"
else
  fail "container_names: cpu=$CPU_CN gpu=$GPU_CN"
fi

echo ""
echo "=== 12. Only one hlh_chat variant at a time ==="
BUNDLED_CHAT=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled docker compose config --services 2>/dev/null | grep hlh_chat)
GPU_CHAT=$(cd "$COMPOSE_DIR" && COMPOSE_PROFILES=bundled-gpu docker compose config --services 2>/dev/null | grep hlh_chat)
if [[ "$BUNDLED_CHAT" == "hlh_chat_cpu" && "$GPU_CHAT" == "hlh_chat_gpu" ]]; then
  ok "bundled → cpu only, bundled-gpu → gpu only"
else
  fail "bundled chat=$BUNDLED_CHAT, bundled-gpu chat=$GPU_CHAT"
fi

echo ""
echo "=== 13. vision profile preserved on tier change ==="
TMPENV=$(mktemp)
echo "COMPOSE_PROFILES=bundled,vision" > "$TMPENV"
echo "HLH_CHAT_IMAGE=old" >> "$TMPENV"
RESULT=$(cd "$COMPOSE_DIR/backend" && python3 -c "
import services.image_config as ic
ic.ENV_PATH = '$TMPENV'
ic.write_tier_env('cpu-std')
with open('$TMPENV') as f:
    for line in f:
        if line.startswith('COMPOSE_PROFILES='):
            profiles = set(line.strip().split('=',1)[1].split(','))
            print('OK' if 'vision' in profiles and 'bundled' in profiles else f'FAIL: {profiles}')
            break
" 2>&1)
rm -f "$TMPENV" "${TMPENV}.bak-"* 2>/dev/null
if [[ "$RESULT" == "OK" ]]; then
  ok "vision preserved after tier change to cpu-std"
else
  fail "vision not preserved: $RESULT"
fi

echo ""
echo "════════════════════════════════════════"
echo "  PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
echo "════════════════════════════════════════"
exit $FAIL
