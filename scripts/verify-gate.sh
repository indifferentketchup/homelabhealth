#!/usr/bin/env bash
# verify-gate.sh — auto-discover and run all verify_*.{sh,py} scripts in backend/scripts/.
#
# Reports PASS/FAIL per script with elapsed time. Writes JSON summary to
# .omo/evidence/verify-gate/verify-gate-report.json. Exits 0 if all pass, 1 otherwise.
#
# Usage:
#   bash scripts/verify-gate.sh               # run all discovered scripts
#   bash scripts/verify-gate.sh --list-only    # just list what would run
#
# Per CLAUDE.md conventions:
#   - Exit codes captured via `if cmd; then ec=0; else ec=$?; fi` (not `; ec=$?`)
#   - Counter increments use POSIX arithmetic (`PASS=$((PASS+1))`), not ((PASS++))
#   - docker exec without -it (non-interactive scripting)

set -u  # only -u; no -e so we can capture exit codes manually

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_SCRIPTS="$PROJECT_ROOT/backend/scripts"
EVIDENCE_DIR="$PROJECT_ROOT/.omo/evidence/verify-gate"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
LIST_ONLY=false

# Parse args
for arg in "$@"; do
  case "$arg" in
    --list-only) LIST_ONLY=true ;;
    *) printf "Unknown arg: %s\n" "$arg" >&2; exit 1 ;;
  esac
done

# ── Prerequisite checks ──────────────────────────────────────────────────────
DOCKER_OK=false
API_OK=false
DB_OK=false

if command -v docker &>/dev/null; then
  DOCKER_OK=true
  # Check if hlh_api container is running (non-TTY — drop -it per CLAUDE.md)
  if docker exec hlh_db pg_isready -U hlh &>/dev/null; then
    DB_OK=true
  fi
  if docker exec hlh_api python3 -c "import httpx; r=httpx.get('http://localhost:9600/api/auth/me'); exit(0) if r.status_code in (200,401) else exit(1)" &>/dev/null; then
    API_OK=true
  fi
fi

# ── Discovery ─────────────────────────────────────────────────────────────────
scripts=()
while IFS= read -r -d '' f; do
  scripts+=("$f")
done < <(find "$BACKEND_SCRIPTS" -maxdepth 1 -type f \( -name 'verify_*.sh' -o -name 'verify_*.py' \) -print0 | sort -z)

total=${#scripts[@]}

if [ "$total" -eq 0 ]; then
  printf "No verify_*.sh or verify_*.py scripts found in %s\n" "$BACKEND_SCRIPTS" >&2
  exit 1
fi

if [ "$LIST_ONLY" = true ]; then
  printf "Discovered %d verify scripts:\n" "$total"
  for script in "${scripts[@]}"; do
    printf "  %s\n" "$(basename "$script")"
  done
  exit 0
fi

# ── Setup ────────────────────────────────────────────────────────────────────
mkdir -p "$EVIDENCE_DIR"

PASS=0
FAIL=0
SKIP=0
results=()

# Color helpers
color_green() { printf "\033[32m%s\033[0m" "$1"; }
color_red()   { printf "\033[31m%s\033[0m" "$1"; }
color_yellow(){ printf "\033[33m%s\033[0m" "$1"; }
color_dim()   { printf "\033[2m%s\033[0m" "$1"; }

section() {
  printf "\n—— %s ——\n" "$1"
}

# ── Precondition summary ─────────────────────────────────────────────────────
section "Preconditions"
printf "  Docker available:      %s\n" "$(if [ "$DOCKER_OK" = true ]; then color_green "yes"; else color_red "no"; fi)"
printf "  hlh_api reachable:     %s\n" "$(if [ "$API_OK" = true ]; then color_green "yes"; else color_red "no"; fi)"
printf "  hlh_db reachable:      %s\n" "$(if [ "$DB_OK" = true ]; then color_green "yes"; else color_red "no"; fi)"
printf "\nDiscovered %s script(s) to run.\n" "$total"

# ── Run each script ──────────────────────────────────────────────────────────
section "Execution"

for script in "${scripts[@]}"; do
  name="$(basename "$script")"
  base="${name%.*}"
  ext="${script##*.}"

  # Determine runner and working directory
  case "$ext" in
    sh)
      runner=("bash" "$script")
      run_dir="$PROJECT_ROOT"
      ;;
    py)
      runner=("python3" "$script")
      run_dir="$PROJECT_ROOT"
      ;;
  esac

  start_epoch=$(date +%s)
  start_fmt=$(date -u +"%H:%M:%S")
  output_file="$EVIDENCE_DIR/${base}.log"

  # Print start line
  printf "  [%s] %s ... " "$start_fmt" "$(color_dim "$name")"

  # Run the script, capturing exit code per CLAUDE.md convention
  if (
    cd "$run_dir" && "${runner[@]}"
  ) > "$output_file" 2>&1; then
    ec=0
  else
    ec=$?
  fi

  end_epoch=$(date +%s)
  elapsed=$((end_epoch - start_epoch))
  elapsed_fmt="${elapsed}s"

  if [ "$ec" -eq 0 ]; then
    PASS=$((PASS + 1))
    printf "%s  %s\n" "$(color_green "PASS")" "$(color_dim "[${elapsed_fmt}]")"
    status="pass"
  else
    FAIL=$((FAIL + 1))
    printf "%s  %s\n" "$(color_red "FAIL")" "$(color_dim "[${elapsed_fmt}]")"
    status="fail"
  fi

  # Collect result for JSON
  result_json="{\"name\":\"${name}\",\"status\":\"${status}\",\"exit_code\":${ec},\"elapsed_sec\":${elapsed}}"
  results+=("$result_json")
done

# ── Summary ──────────────────────────────────────────────────────────────────
section "Summary"

if [ "$FAIL" -eq 0 ]; then
  printf "  %s  " "$(color_green "ALL PASSED")"
else
  printf "  %s  " "$(color_red "SOME FAILED")"
fi
printf "%s passed, %s failed, %s skipped\n" \
  "$(if [ "$PASS" -gt 0 ]; then color_green "$PASS"; else printf "%s" "$PASS"; fi)" \
  "$(if [ "$FAIL" -gt 0 ]; then color_red "$FAIL"; else printf "%s" "$FAIL"; fi)" \
  "$SKIP"

# ── Write JSON report ────────────────────────────────────────────────────────
{
  printf "{\n"
  printf "  \"timestamp\": \"${TIMESTAMP}\",\n"
  printf "  \"total\": %d,\n" "$total"
  printf "  \"passed\": %d,\n" "$PASS"
  printf "  \"failed\": %d,\n" "$FAIL"
  printf "  \"skipped\": %d,\n" "$SKIP"
  printf "  \"preconditions\": {\n"
  printf "    \"docker_ok\": ${DOCKER_OK},\n"
  printf "    \"api_ok\": ${API_OK},\n"
  printf "    \"db_ok\": ${DB_OK}\n"
  printf "  },\n"
  printf "  \"scripts\": [\n"
  sep=""
  for r in "${results[@]}"; do
    printf "  %s\n    %s" "$sep" "$r"
    sep=","
  done
  printf "\n  ]\n"
  printf "}\n"
} > "$EVIDENCE_DIR/verify-gate-report.json"

printf "\nReport written to %s\n" "$EVIDENCE_DIR/verify-gate-report.json"

# ── Exit ─────────────────────────────────────────────────────────────────────
[ "$FAIL" -eq 0 ]
