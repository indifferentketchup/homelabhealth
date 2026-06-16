#!/usr/bin/env bash
# Verify A1.5 hardening on the bundled stack.
# Spec: docs/superpowers/specs/2026-05-22-a1.5-a1.7-bundled-tail-design.md §5
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "  ✓ $*"; }

echo "=== 1. Container hardening ==="
for svc in hlh_db hlh_api hlh_ui hlh_swap hlh_search; do
  echo "[$svc]"
  ro=$(docker inspect "$svc" --format '{{.HostConfig.ReadonlyRootfs}}')
  [[ "$ro" == "true" ]] && ok "ReadonlyRootfs=true" || fail "$svc ReadonlyRootfs=$ro"
  caps=$(docker inspect "$svc" --format '{{json .HostConfig.CapDrop}}')
  echo "$caps" | grep -q '"ALL"' && ok "CapDrop contains ALL" || fail "$svc CapDrop=$caps"
  sopts=$(docker inspect "$svc" --format '{{json .HostConfig.SecurityOpt}}')
  echo "$sopts" | grep -q 'no-new-privileges:true' && ok "no-new-privileges:true" || fail "$svc SecurityOpt=$sopts"
done

echo
echo "=== 2. mem_limit tier-scaled (HLH_INFER_MEM) ==="
swap_mem=$(docker inspect hlh_swap --format '{{.HostConfig.Memory}}')
[[ "$swap_mem" -ge 1073741824 ]] && ok "hlh_swap Memory $swap_mem >= 1g (tier-scaled)" || fail "hlh_swap Memory=$swap_mem (expected positive, tier-scaled)"

echo
echo "=== 3. Network membership ==="
declare -A EXPECT=(
  [hlh_db]='[hlh_default]'
  [hlh_api]='[hlh_default hlh_inference]'
  [hlh_ui]='[hlh_default]'
  [hlh_swap]='[hlh_inference]'
  [hlh_search]='[hlh_default]'
)
for svc in "${!EXPECT[@]}"; do
  nets=$(docker inspect "$svc" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' | xargs -n1 | sort | tr '\n' ' ')
  formatted="[$(echo $nets | xargs)]"
  if [[ "$formatted" == "${EXPECT[$svc]}" ]]; then
    ok "$svc networks = ${EXPECT[$svc]}"
  else
    fail "$svc networks = $formatted (expected ${EXPECT[$svc]})"
  fi
done

echo
echo "=== 4. hlh_inference is internal ==="
internal=$(docker network inspect hlh_inference --format '{{.Internal}}')
[[ "$internal" == "true" ]] && ok "hlh_inference Internal=true" || fail "hlh_inference Internal=$internal"

echo
echo "=== 5. No host ports on hlh_swap ==="
swap_ports=$(docker ps --filter name=hlh_swap --format '{{.Ports}}' | tr -d '[:space:]')
[[ -z "$swap_ports" ]] && ok "hlh_swap has no host ports" || fail "hlh_swap Ports=$swap_ports"

echo
echo "=== 5b. No service mounts the Docker socket ==="
sock_mounts=$(docker ps -q | xargs -r docker inspect --format '{{.Name}} {{json .Mounts}}' | grep '/var/run/docker.sock' || true)
[[ -z "$sock_mounts" ]] && ok "no container mounts /var/run/docker.sock" || fail "docker.sock mounted by: $sock_mounts"

echo
echo "=== 6. Disk pre-flight rejects oversize pull ==="
# Pick the cpu-min chat row (smallest, safest to manipulate)
PID=$(docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT id FROM bundled_models WHERE role='chat' AND tier='cpu-min';" | tr -d '[:space:]')
[[ -n "$PID" ]] || fail "no cpu-min chat row found"

# Save existing state to restore later
ORIG_STATUS=$(docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT status FROM bundled_models WHERE id='$PID';" | tr -d '[:space:]')
ORIG_BYTES=$(docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT COALESCE(expected_bytes::text, 'NULL') FROM bundled_models WHERE id='$PID';" | tr -d '[:space:]')

# Force disk-exceed
docker exec hlh_db psql -U hlh -d hlh -c "UPDATE bundled_models SET status='pending', error_message=NULL, expected_bytes=999999999999999 WHERE id='$PID';" >/dev/null
curl -sS -o /dev/null -X POST "http://localhost:9600/api/models/$PID/pull"
sleep 3
RESULT=$(docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT status||'|'||COALESCE(error_message,'') FROM bundled_models WHERE id='$PID';")
echo "$RESULT" | grep -q 'failed|insufficient disk' && ok "pull rejected with insufficient-disk" || fail "expected 'failed|insufficient disk', got: $RESULT"

# Restore
if [[ "$ORIG_BYTES" == "NULL" ]]; then
  docker exec hlh_db psql -U hlh -d hlh -c "UPDATE bundled_models SET status='$ORIG_STATUS', error_message=NULL, expected_bytes=NULL WHERE id='$PID';" >/dev/null
else
  docker exec hlh_db psql -U hlh -d hlh -c "UPDATE bundled_models SET status='$ORIG_STATUS', error_message=NULL, expected_bytes=$ORIG_BYTES WHERE id='$PID';" >/dev/null
fi

# TODO: once MODEL_REGISTRY entries carry sha256 pins, add a corruption-rejection test here.

echo
echo "=== ALL CHECKS PASSED ==="
