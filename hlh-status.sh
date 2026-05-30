#!/usr/bin/env bash
#
# homelabhealth status — one-glance health of the whole stack. Run on the host:
#
#   curl -fsSL https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/hlh-status.sh | bash
#   # or, if you have the repo:  bash hlh-status.sh
#
# Shows per-container state + health, recent ERROR/WARN/CRITICAL lines, and the
# API's startup banner — so you don't have to grep each container by hand.
#
set -uo pipefail

CONTAINERS=(hlh_db hlh_api hlh_chat hlh_ui hlh_search hlh_orchestra)
ERR_RE='error|exception|traceback|critical|failed|denied|startup failed'

command -v docker >/dev/null 2>&1 || { echo "error: docker not found" >&2; exit 1; }

bar() { printf '%s\n' "────────────────────────────────────────────────────────────"; }

bar
echo "  homelabhealth stack status"
bar
printf '%-18s %-22s %s\n' "CONTAINER" "STATE" "HEALTH"
for c in "${CONTAINERS[@]}"; do
  if ! docker inspect "$c" >/dev/null 2>&1; then
    printf '%-18s %-22s %s\n' "$c" "absent" "—"
    continue
  fi
  state=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}—{{end}}' "$c" 2>/dev/null)
  restarts=$(docker inspect -f '{{.RestartCount}}' "$c" 2>/dev/null)
  [ "${restarts:-0}" -gt 3 ] 2>/dev/null && state="$state (restarts=$restarts)"
  printf '%-18s %-22s %s\n' "$c" "$state" "$health"
done

echo
bar
echo "  API startup banner (last boot)"
bar
docker logs hlh_api 2>&1 | grep -E 'homelabhealth API ready|tier=|bundled_models:|/models:|STARTUP FAILED' | tail -8 \
  || echo "  (no banner found — API may not have started)"

echo
bar
echo "  recent problems (last 200 lines per container)"
bar
found=0
for c in "${CONTAINERS[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || continue
  hits=$(docker logs --tail 200 "$c" 2>&1 | grep -iE "$ERR_RE" | grep -ivE 'GET /|POST /api/models' | tail -5)
  if [ -n "$hits" ]; then
    found=1
    echo "── $c ──"
    echo "$hits"
    echo
  fi
done
[ "$found" -eq 0 ] && echo "  none in recent logs ✓"

echo
echo "Tip: full doctor report → open Settings → System, or:"
echo "  docker exec hlh_api python -m hlh.doctor"
