#careful

# HLH Bundled-AI — Phase 0: Hardware Detection + Tier Picker

Branch off `v1.10.0`: `feat/phase-0-hardware-detect`.

Repo: `/opt/homelabhealth` on ubuntu-homelab.
Live ports: API `9600`, UI `9604`. DB user/db both `hlh`.
Deploy: `docker compose up --build -d`. Never `git pull` or commit on my behalf.

## Hard rules

1. **No commits, no staging.** I commit manually.
2. **No deploy** unless I say so. Build locally to confirm clean, then stop.
3. **No edits outside the file list at the end of this prompt.** If you need to touch something not listed, stop and report.
4. **Backup before any destructive edit:** `cp file file.bak-phase0-$(date +%Y%m%d)`. No exceptions.
5. **Run `ls frontend/src/components/ui/` before importing primitives.** Import only what exists. If a needed primitive is missing, stop and report.
6. **Never modify `frontend/src/hooks/useStream.js`.**
7. **Schema changes must be idempotent** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, guarded constraints).
8. **Stop and report** on any ambiguity, any unexpected pre-existing state, any test failure, any tool result that doesn't match the spec.

## Scope (this phase only)

Add hardware detection + tier picker UI. Persist operator's chosen tier. No inference containers. No model pulling. No changes to the existing external-provider flow.

## Design source of truth

`/tmp/hlh_phase0_design.md` (I will place this file before you start). Read it first. If anything in this prompt conflicts with the design doc, the design doc wins — stop and report the conflict.

## Plan (subphases, gate between each)

### Subphase 0.A — Inventory (read-only)

1. `git status` confirm working tree clean and on `feat/phase-0-hardware-detect` branched off `v1.10.0`.
2. `grep -rn 'system_profile\|sysinfo\|recommend_tier' backend/ frontend/ 2>/dev/null | grep -v node_modules | grep -v __pycache__` — confirm zero pre-existing references.
3. Confirm `psutil` is in `backend/requirements.txt`. If not, note it (it will be added in 0.C).
4. Confirm `backend/routers/` and `backend/services/` directories exist with the expected layout per existing routers.

Stop. Report findings. Wait for "continue."

### Subphase 0.B — Schema

1. Append the `system_profile` table to `backend/schema.sql` exactly as in the design doc §Schema. Guarded `INSERT ... ON CONFLICT DO NOTHING` for the singleton row.
2. Apply the schema against `hlh_db`:
   ```
   docker exec -i hlh_db psql -U hlh -d hlh < backend/schema.sql
   ```
   Expected: no errors, idempotent re-apply.
3. Verify the row exists:
   ```
   docker exec hlh_db psql -U hlh -d hlh -c "SELECT id, tier, tier_source, setup_complete FROM system_profile;"
   ```
   Expected: `1 | external | manual | f`.

Stop. Report schema diff + verify output. Wait for "continue."

### Subphase 0.C — Backend: sysinfo service

1. Create `backend/services/sysinfo.py` with:
   - `collect() -> dict`: returns sysinfo dict per design doc §Sysinfo collection table.
   - `recommend_tier(sysinfo: dict) -> str`: pure function per the tier table.
   - All subprocess calls wrapped: 2s timeout, log on failure, return null for that field. Detection failure never raises.
2. Add `psutil>=5.9.0` to `backend/requirements.txt` if not present.
3. Create `backend/scripts/verify_sysinfo.py` (Python, no curl): exercises `collect()` and `recommend_tier()` with synthetic inputs covering each tier row. Prints PASS/FAIL per assertion.

Stop. Report file diffs + `python3 backend/scripts/verify_sysinfo.py` output. Wait for "continue."

### Subphase 0.D — Backend: system router

1. Create `backend/routers/system.py` with the four endpoints in design doc §API endpoints. All admin-only via the existing auth dependency used in `backend/routers/providers.py`.
2. Mount in `backend/main.py`: add `system` to the `from routers import (...)` block, add `api.include_router(system.router, prefix="/system", tags=["system"])`. Match the existing pattern from the providers mount.
3. Create `backend/scripts/verify_system_endpoints.sh` covering:
   - GET `/api/system/hardware` returns 200 with non-empty JSON.
   - GET `/api/system/profile` returns 200 with current row + `recommended_tier` field.
   - PUT `/api/system/profile` with valid tier returns 200, sets `setup_complete = TRUE`.
   - PUT with invalid tier returns 400.
   - POST `/api/system/redetect` updates `detected_at`, leaves `tier` unchanged.
   - Non-admin requests return 401/403.

Deploy: `docker compose up --build -d`. Tail logs until ready.

Stop. Report file diffs, build output, verify script results. Wait for "continue."

### Subphase 0.E — Frontend: Settings → System tab

1. Create `frontend/src/api/system.js`: wrappers for the four endpoints, following the shape of `frontend/src/api/providers.js`.
2. Create `frontend/src/components/settings/SystemTab.jsx`:
   - Detected-hardware card (CPU, RAM, GPU(s), disk free) + "Re-detect" button.
   - Recommended-tier badge with one-line rationale.
   - Tier selector (radio group) with per-tier details: chat model, embed model, rerank model, vision/STT availability, approx footprint.
   - Save button calls `PUT /api/system/profile`.
   - `Save` disabled until selection differs from current OR `setup_complete = false`.
3. Wire the tab into `frontend/src/pages/workspace/SettingsPage.jsx` following the existing tab-mount pattern from Providers/Embedding/Reranker tabs.
4. **First-boot gate**: in the SettingsPage (or a top-level layout component — pick whichever is least invasive and report your choice), if `setup_complete === false`, redirect any post-login navigation to `Settings → System` until the operator saves. Use the existing routing helpers; do not invent new ones.
5. `ls frontend/src/components/ui/` first. If you need a primitive that isn't present, stop and report instead of adding a shadcn import.

Deploy: `docker compose up --build -d`.

Stop. Report file diffs, Vite build output, no console errors on `http://<host>:9604/settings`. Wait for "continue."

### Subphase 0.F — E2E verification

1. Create `backend/scripts/verify_system_ui.py` (Playwright, headless Chromium, follows the pattern from `verify_providers_ui.py`):
   - Log in.
   - Navigate to `/settings`, confirm Settings → System tab is present and pre-selected when `setup_complete = false`.
   - Confirm Detected Hardware card renders non-empty values.
   - Click "Re-detect", confirm a new timestamp appears.
   - Change tier selection, click Save, expect 200.
   - Reload, confirm `setup_complete = true` and saved tier persists.
   - Confirm no redirect-to-System occurs after save.
2. Run all prior verify scripts as regression:
   - `verify_providers_crud.sh`
   - `verify_providers_live.sh`
   - `verify_embedding_reranker_settings.sh`
   - `verify_providers_ui.py`
   - `verify_embedding_reranker_ui.py`
   - `verify_workspace_provider_picker.py`
   - `verify_sysinfo.py`
   - `verify_system_endpoints.sh`
   - `verify_system_ui.py`

Stop. Report:
- Full pass/fail count per verify script.
- Diff stat across the phase.
- List of files touched (must match the file list below).
- Screenshots from `verify_system_ui.py` to `/tmp/phase0-evidence/`.
- Anything noticed and skipped (per scope discipline).

Wait for my "go" to commit + tag.

## File list (everything this phase may touch)

NEW:
- `backend/services/sysinfo.py`
- `backend/routers/system.py`
- `backend/scripts/verify_sysinfo.py`
- `backend/scripts/verify_system_endpoints.sh`
- `backend/scripts/verify_system_ui.py`
- `frontend/src/api/system.js`
- `frontend/src/components/settings/SystemTab.jsx`

MODIFIED:
- `backend/schema.sql` (append `system_profile` table)
- `backend/main.py` (router mount only, follow the providers pattern; do NOT touch the deprecated-env-vars block)
- `backend/requirements.txt` (psutil, only if not present)
- `frontend/src/pages/workspace/SettingsPage.jsx` (one tab entry + one render branch + first-boot redirect)

If you need to touch anything else, stop and report.

## Out of scope (do not do)

- Pulling models / starting inference containers / docker-compose changes.
- Changing existing external-provider flow.
- Changing embedding dim (locked at 1024 — already documented).
- Touching `AISettings.jsx` or `ModelSelectorBar.jsx` (broken-but-degraded; separate cleanup).
- Modifying `useStream.js`.
- Any commits or tags.

## Report format

End each subphase with:
1. **Diff stat (this subphase only).**
2. **Files touched** (must match expected set).
3. **Build/verify output** (full pass count).
4. **Skipped (per scope discipline)** — things you noticed but didn't fix.
5. **Open question / blocker** (if any).
6. **Next-step preview** (one-line: what subphase X.Y will do when I say continue).
