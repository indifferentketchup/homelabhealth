# Design: Rename BooLab heritage → HomeLab Health

**Date:** 2026-05-08
**Status:** Draft for review
**Scope:** One-PR rename of `boolab/booops/808notes/boocode` and `daws` legacy across code, schema, infra, and docs. Single ~10-min outage.

## Goal

Strip every visible legacy from BooLab/BooOps/808notes/BooCode and the audio-workstation (DAW) vocabulary it carried, leaving a codebase that reads as a healthcare RAG app. User-agnostic: a future fork should be able to clone, run `docker compose up`, and see no relics. Simple: one PR, one migration script, one coordinated deploy. Hard Rule #2 (no `schema.sql` modifications) is explicitly waived for this pass — that's the whole point.

## Non-goals

- Renaming the on-disk `/data/branding/` volume path (used by `routers/profile.py` for user profile icons — orthogonal concept).
- Renaming the repo dir `/opt/homelabhealth`.
- Multi-mode infrastructure preserved for future use — single mode forever.
- Per-workspace branding theming — already stripped in earlier passes; this design assumes that prior state.
- Backward compatibility with any external API consumer (single-user app, no public API contract).

## Final state

### Naming convention

| Concept | Before | After |
|---|---|---|
| App slug (env var prefix, postgres user/db/password, container DNS upstream) | `boolab` / `BOOLAB_*` | `hlh` / `HLH_*` |
| Display name (UI literals) | mixed | `HomeLab Health` (already done in `identity.js` + `index.html`) |
| Container service names | `hlh_api`, `hlh_db`, `hlh_ui` (already current) | unchanged |
| localStorage key prefix | mixed (`homelabhealth-*`, `bb-*`) | `hlh-*` (normalized) |

### Database schema (post-migration target)

| Object | Before | After |
|---|---|---|
| Top table | `daws` | `workspaces` |
| Child table | `daw_instructions` | `workspace_instructions` |
| Child table | `daw_context_files` | `workspace_context_files` |
| Child table | `daw_memory` | `workspace_memory` |
| FK column (in 8 tables: `chats`, `sources`, `notes`, `source_groups`, `note_groups`, `workspace_context_files`, `workspace_instructions`, `workspace_memory`) | `daw_id` | `workspace_id` |
| FK indexes (4) | `chats_daw_id_idx`, `sources_daw_id_idx`, `notes_daw_id_idx`, `daw_memory_daw_id_idx` | `chats_workspace_id_idx`, `sources_workspace_id_idx`, `notes_workspace_id_idx`, `workspace_memory_workspace_id_idx` |
| Workspace pin flag | `pinned_808notes` | `pinned` |
| Personas default flag | `is_default_808notes` | `is_default` |
| Personas singleton index | `personas_one_default_808notes_idx` | `personas_one_default_idx` |
| `mode` columns + CHECK constraints (4 tables: daws, chats, memory_entries, searxng_config) | present | **dropped** |
| `is_default_booops`, `is_default_boocode` (personas) | present | **dropped** |
| `pinned_booops` (daws) | present | **dropped** |
| `custom_instructions.scope` column + UNIQUE constraint | `scope TEXT NOT NULL CHECK IN ('global','booops','808notes')` | **dropped**; singleton via `CREATE UNIQUE INDEX custom_instructions_singleton_idx ON custom_instructions ((1))` |
| `global_settings` KV keys | `default_model_808notes`, `ollama_hidden_models_808notes` | `default_model`, `ollama_hidden_models` |
| `branding_config` table | present (dormant) | **dropped** |

### Code-side dropped constants

- `backend/deps.py`: `_SCHEMA_MODE_VALUE = "808notes"` constant removed; every `WHERE mode = $1` filter removed.
- `frontend/vite.config.js`: mode-switch (`'booops'|'808notes'|'boolab'|'boocode' → display title`) removed entirely; identity is static in `identity.js`.

## Migration mechanics

### Migration file (plain SQL, one transaction)

**Path:** `backend/migrations/002_rename_to_homelabhealth.sql`

```sql
BEGIN;

-- 1. Drop dormant branding_config table.
DROP TABLE IF EXISTS branding_config;

-- 2. Drop mode/scope columns + their CHECK constraints (5 tables).
ALTER TABLE daws DROP CONSTRAINT IF EXISTS daws_mode_check;
ALTER TABLE daws DROP COLUMN IF EXISTS mode;
ALTER TABLE chats DROP CONSTRAINT IF EXISTS chats_mode_check;
ALTER TABLE chats DROP COLUMN IF EXISTS mode;
ALTER TABLE memory_entries DROP CONSTRAINT IF EXISTS memory_entries_mode_check;
ALTER TABLE memory_entries DROP COLUMN IF EXISTS mode;
ALTER TABLE searxng_config DROP CONSTRAINT IF EXISTS searxng_config_mode_check;
ALTER TABLE searxng_config DROP COLUMN IF EXISTS mode;

-- custom_instructions: collapse to singleton (keep 'global' row if present, else the first row).
DELETE FROM custom_instructions
WHERE id NOT IN (
    SELECT id FROM custom_instructions
    ORDER BY (scope = 'global') DESC, created_at ASC NULLS LAST
    LIMIT 1
);
ALTER TABLE custom_instructions DROP CONSTRAINT IF EXISTS custom_instructions_scope_check;
ALTER TABLE custom_instructions DROP COLUMN IF EXISTS scope;
CREATE UNIQUE INDEX IF NOT EXISTS custom_instructions_singleton_idx
    ON custom_instructions ((1));

-- 3. Drop vestigial multi-mode personas columns + their unique indexes.
DROP INDEX IF EXISTS personas_one_default_booops_idx;
DROP INDEX IF EXISTS personas_one_default_boocode_idx;
ALTER TABLE personas DROP COLUMN IF EXISTS is_default_booops;
ALTER TABLE personas DROP COLUMN IF EXISTS is_default_boocode;
ALTER TABLE daws DROP COLUMN IF EXISTS pinned_booops;

-- 4. Rename the surviving suffixed columns + index.
ALTER TABLE personas RENAME COLUMN is_default_808notes TO is_default;
ALTER INDEX IF EXISTS personas_one_default_808notes_idx
    RENAME TO personas_one_default_idx;
ALTER TABLE daws RENAME COLUMN pinned_808notes TO pinned;

-- 5. Update global_settings KV keys.
UPDATE global_settings SET key = 'default_model'
    WHERE key = 'default_model_808notes';
UPDATE global_settings SET key = 'ollama_hidden_models'
    WHERE key = 'ollama_hidden_models_808notes';

-- 6. Rename the top table + its three child tables.
ALTER TABLE daws RENAME TO workspaces;
ALTER TABLE daw_instructions RENAME TO workspace_instructions;
ALTER TABLE daw_context_files RENAME TO workspace_context_files;
ALTER TABLE daw_memory RENAME TO workspace_memory;

-- 7. Rename daw_id columns -> workspace_id across every dependent table (8 total).
ALTER TABLE workspace_instructions RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE workspace_context_files RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE workspace_memory RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE source_groups RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE note_groups RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE chats RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE sources RENAME COLUMN daw_id TO workspace_id;
ALTER TABLE notes RENAME COLUMN daw_id TO workspace_id;

-- 8. Rename indexes whose names contained `daw_id` (Postgres does not auto-rename
--    indexes when their columns are renamed; UNIQUE constraints on (daw_id, name)
--    in source_groups/note_groups DO follow the column automatically).
ALTER INDEX IF EXISTS chats_daw_id_idx RENAME TO chats_workspace_id_idx;
ALTER INDEX IF EXISTS sources_daw_id_idx RENAME TO sources_workspace_id_idx;
ALTER INDEX IF EXISTS notes_daw_id_idx RENAME TO notes_workspace_id_idx;
ALTER INDEX IF EXISTS daw_memory_daw_id_idx RENAME TO workspace_memory_workspace_id_idx;

COMMIT;
```

**Atomicity:** `BEGIN`/`COMMIT` wrap the whole thing. Any failure rolls back to pre-migration state. Postgres permits DDL inside transactions; foreign-key constraints survive renames (they reference table OIDs, not names).

### Postgres role + database rename (separate, runs as superuser)

```sql
-- Run via: docker exec -it hlh_db psql -U postgres
ALTER USER boolab WITH PASSWORD '<new_strong_password>';
ALTER USER boolab RENAME TO hlh;
ALTER DATABASE boolab RENAME TO hlh;
```

Run **after** the schema migration succeeds. `.env` then updates `DATABASE_URL` to `postgresql+asyncpg://hlh:<new_password>@hlh_db:5432/hlh`. Compose `POSTGRES_USER/PASSWORD/DB` flip to `hlh` (these env vars only take effect on first-init for a fresh volume; for the existing volume the SQL above is the actual change).

### `schema.sql` rewrite

`backend/schema.sql` becomes the post-migration target shape:

- `CREATE TABLE IF NOT EXISTS workspaces (...)` (was `daws`); no `mode` column; `pinned BOOLEAN DEFAULT FALSE`.
- `CREATE TABLE IF NOT EXISTS personas (...)`: `is_default BOOLEAN DEFAULT FALSE`; no `is_default_booops`/`is_default_boocode`/`is_default_808notes`.
- `CREATE TABLE IF NOT EXISTS workspace_instructions (...)` (was `daw_instructions`).
- `CREATE TABLE IF NOT EXISTS workspace_context_files (...)` (was `daw_context_files`).
- `CREATE TABLE IF NOT EXISTS workspace_memory (...)` (was `daw_memory`).
- Every FK column declared `workspace_id UUID REFERENCES workspaces(id)`.
- Indexes renamed: `chats_workspace_id_idx`, `sources_workspace_id_idx`, `notes_workspace_id_idx`, `workspace_memory_workspace_id_idx`.
- No `branding_config` table block.
- No mode/scope CHECK constraints or the `$boocode_mode_chk$` DO-block.
- Header comment: `-- HomeLab Health — full schema. Table order respects foreign keys.`
- All trailing idempotent `ALTER TABLE daws ADD COLUMN IF NOT EXISTS ...` rewritten to `ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS ...`.

After the migration runs once, `apply_schema()` on subsequent API startups is a no-op (every `IF NOT EXISTS`/`IF EXISTS` is satisfied). Fresh installs (no DB) get the new shape directly from `CREATE TABLE`.

## Code changes by layer

### Layer A — infra & build (config-only, ~12 files)

**Pattern:** `boolab` → `hlh` in infra contexts; `BOOLAB_*` env vars → `HLH_*`; mode-suffix tokens → drop the suffix.

| File | Change |
|---|---|
| `.env`, `.env.example` | `BOOLAB_PUBLIC_HOST`→`HLH_PUBLIC_HOST`; `BOOLAB_API_UPSTREAM`→`HLH_API_UPSTREAM`; `BOOLAB_PORT_API`→`HLH_PORT_API`; `BOOLAB_PORT_808NOTES`→`HLH_PORT_UI`; `BOOLAB_VITE_API_PROXY`→`HLH_VITE_API_PROXY`; `VITE_PUBLIC_808NOTES_URL`→`VITE_PUBLIC_URL`; `DATABASE_URL` user/db/password all → `hlh`. |
| `docker-compose.yml`, `docker-compose.core.yml`, `docker-compose.ui.yml`, `docker-compose.ui.join.yml` | `POSTGRES_USER/PASSWORD/DB: boolab` → `hlh`; `pg_isready -U boolab -d boolab` → `-U hlh -d hlh`; all `BOOLAB_*` env passthrough → `HLH_*`; `VITE_PUBLIC_808NOTES_URL` → `VITE_PUBLIC_URL`. |
| `frontend/nginx.conf` | `proxy_pass http://boolab_api:8000/api/;` → `http://hlh_api:8000/api/;` |
| `frontend/default.conf.template` | `BOOLAB_API_UPSTREAM`→`HLH_API_UPSTREAM`; `$boolab_upstream`→`$hlh_upstream`; remove dead `# BooCode terminals (Phase 5)` comment block. |
| `frontend/t.template` | **Delete.** Already-orphaned duplicate of `default.conf.template`. |
| `frontend/vite.config.js` | Delete the mode-switch (lines 13-31). Identity is static in `identity.js`; the file collapses to the Vite config object. |
| `backend/main.py:42` | `os.environ.get("BOOLAB_PUBLIC_HOST")` → `os.environ.get("HLH_PUBLIC_HOST")`. |
| `backend/services/history.py` | `HISTORY_ENV = "BOOLAB_HISTORY_DIR"` → `"HLH_HISTORY_DIR"`; update docstring. |

### Layer B — schema follow-through (~14 backend files + 4 frontend)

**Pattern:** `daws`→`workspaces`, `daw_id`→`workspace_id`, `is_default_808notes`→`is_default`, `pinned_808notes`→`pinned`, `default_model_808notes`→`default_model`, `ollama_hidden_models_808notes`→`ollama_hidden_models`. Drop every `WHERE mode = $1` filter and the `_SCHEMA_MODE_VALUE` argument it referenced.

| File | One-line summary |
|---|---|
| `backend/schema.sql` | Full rewrite to post-migration shape. |
| `backend/migrations/002_rename_to_homelabhealth.sql` | **New file.** Migration described above. |
| `backend/migrations/remove_sampling_params.py` | Rename file to `001_remove_sampling_params.py` for ordering; content unchanged (historical artifact). |
| `backend/deps.py` | Drop `_SCHEMA_MODE_VALUE` constant; update callers. |
| `backend/routers/workspaces.py` | `daws`→`workspaces`; `pinned_808notes`→`pinned`; drop `mode` insert/update/select; drop `_SCHEMA_MODE_VALUE` arg. ~30 SQL strings touched. |
| `backend/routers/personas.py` | `is_default_808notes`→`is_default` (19 hits). |
| `backend/routers/chats.py` | `is_default_808notes`→`is_default`; `default_model_808notes`→`default_model`; `daws`→`workspaces`; drop mode WHERE clauses. |
| `backend/routers/inference.py` | `default_model_808notes`→`default_model`; `ollama_hidden_models_808notes`→`ollama_hidden_models`; drop the mode-dispatch helper function. |
| `backend/routers/notes.py`, `sources.py`, `memory.py`, `workspace_context_files.py`, `workspace_memory.py`, `skills.py`, `custom_instructions.py`, `history.py` | `daw_id`→`workspace_id`; `daws`→`workspaces` in JOINs; drop scope/mode filters where present. |
| `backend/seed_assets.py` | `is_default_808notes`→`is_default`. |
| `frontend/src/store/index.js` | `x.is_default_808notes`→`x.is_default` (in `defaultPersona`). |
| `frontend/src/components/chat/ModelSelectorBar.jsx` | `p.is_default_808notes`→`p.is_default`. |
| `frontend/src/pages/workspace/AISettings.jsx` | `currentDefaultKey = 'is_default_808notes'` → `'is_default'`. |
| `frontend/src/pages/SkillsLibraryPage.jsx` | `daw_id` → `workspace_id` if/where referenced. |
| `frontend/src/routes/paths.js` | Spot-check + minor rename. |

### Layer C — strays + docs (~5 files)

| File | Change |
|---|---|
| `scripts/reembed_harrier.py` | Docstring: `boolab_api` container ref → `hlh_api`. **Rename the file** to `reembed_workspace.py` (the script's docstring confirms it reembeds workspace source chunks). |
| `.claude/settings.local.json` | `Bash(docker exec boolab_db *)` → `Bash(docker exec hlh_db *)`. Remove the `Bash(git -C /opt/boolab log...)` line (different repo, doesn't belong here). |
| `README.md` | Sweep for "BooLab", "BooOps", "BooCode", "808notes" → "HomeLab Health" or remove if context-dependent. Update setup instructions to use new env-var names. |
| `CLAUDE.md` | Same sweep. Update the "Project" section paragraph. Update env-var references. Add a one-line note that `daws`/`daw_id` historical naming was renamed on 2026-05-08. |
| Misc comment sweep | `schema.sql` header, `default.conf.template` "BooCode terminals (Phase 5)", schema "BooCode Phase 3/4/5" annotations — remove or rephrase to be code-name-free. |

### localStorage migration

Normalize to `hlh-*` prefix:

| Old key | New key |
|---|---|
| `homelabhealth-settings-tab` | `hlh-settings-tab` |
| `homelabhealth-user-profile-v1` | `hlh-user-profile-v1` |
| `bb-sidebar-pinned-open` | `hlh-sidebar-pinned-open` |
| `bb-sidebar-recent-open` | `hlh-sidebar-recent-open` |

**One-time UI-state loss** on existing browsers post-deploy. Lost state: selected settings tab, user profile cache (rehydrates from API on first request), sidebar section open/closed booleans. All recoverable in seconds, no actual data loss.

## Deploy sequence

Single coordinated deploy with ~10-min outage. Sam runs solo.

1. **Pre-flight backup.**
   ```bash
   docker exec hlh_db pg_dump -U boolab -d boolab --clean --if-exists \
       > backup-pre-rename-$(date +%Y%m%d-%H%M%S).sql
   ls -la backup-pre-rename-*.sql && head -5 backup-pre-rename-*.sql
   ```
   Verify file exists, > 0 bytes, starts with `-- PostgreSQL database dump`.

2. **Stop dependents.** DB stays up.
   ```bash
   docker compose stop hlh_api hlh_ui
   ```

3. **Schema migration** (single transaction).
   ```bash
   docker exec -i hlh_db psql -U boolab -d boolab \
       < backend/migrations/002_rename_to_homelabhealth.sql
   ```
   If it errors mid-way, nothing changed; investigate and re-run.

4. **Role + database rename** (as `postgres` superuser).
   ```bash
   docker exec -it hlh_db psql -U postgres -c \
       "ALTER USER boolab WITH PASSWORD '<new>';
        ALTER USER boolab RENAME TO hlh;
        ALTER DATABASE boolab RENAME TO hlh;"
   ```

5. **Apply code changes.** New `.env`, new compose, new `schema.sql`, all code identifier renames — one PR working tree, single commit or thin commit series.

6. **Bring services up.**
   ```bash
   docker compose up -d --build hlh_api hlh_ui
   ```
   New API starts, applies new `schema.sql` (no-op against the just-migrated DB).

7. **Verify** (Verification section below).

## Verification

No automated test suite — manual ladder, each step gates the next.

### Stage 1 — post-schema-migration (DB only)

```bash
docker exec -it hlh_db psql -U boolab -d boolab -c "\dt"
# expect: workspaces, workspace_instructions, workspace_context_files, workspace_memory
# expect-absent: daws, daw_instructions, daw_context_files, daw_memory, branding_config

docker exec -it hlh_db psql -U boolab -d boolab -c "\d workspaces"
# expect: column `pinned` exists; no `pinned_808notes`, `pinned_booops`, `mode`

docker exec -it hlh_db psql -U boolab -d boolab -c "\d personas"
# expect: column `is_default` exists; no is_default_808notes/booops/boocode

docker exec -it hlh_db psql -U boolab -d boolab -c "\d chats"
# expect: column `workspace_id` exists; no `daw_id`, no `mode`

docker exec -it hlh_db psql -U boolab -d boolab -c "\di"
# expect: chats_workspace_id_idx, sources_workspace_id_idx, notes_workspace_id_idx,
#         workspace_memory_workspace_id_idx, personas_one_default_idx,
#         custom_instructions_singleton_idx
# expect-absent: any *_daw_id_idx, personas_one_default_*_idx

docker exec -it hlh_db psql -U boolab -d boolab -c "SELECT COUNT(*) FROM workspaces;"
# expect: same count as pre-migration daws
```

### Stage 2 — post-role-rename

```bash
docker exec -it hlh_db psql -U hlh -d hlh -c "SELECT current_user, current_database();"
# expect: hlh, hlh

docker exec -it hlh_db psql -U boolab -d boolab 2>&1
# expect: role "boolab" does not exist
```

### Stage 3 — post-deploy (API up)

```bash
curl -s http://100.114.205.53:9400/api/health
# expect: {"status":"ok"}

curl -s http://100.114.205.53:9400/api/workspaces/ | jq '.items | length'
# expect: > 0, matches Stage 1 count

curl -s http://100.114.205.53:9400/api/personas/ | jq '.items | length'
# expect: > 0

curl -sI http://100.114.205.53:9402/
# expect: 200

docker logs hlh_api --tail 30 | grep -i error
# expect: empty

docker logs hlh_api --tail 30 | grep "Application startup complete"
# expect: present
```

### Stage 4 — browser smoke (operator-driven)

1. Open `https://homelabhealth.indifferentketchup.com/` → workspace landing loads, Stethoscope glyph + "HomeLab Health" title visible.
2. Click an existing workspace → its sources panel loads, color ribbon renders (Concept B preserved).
3. Pick a chat in the workspace → message history loads (verifies `workspace_id` FK + `is_default` persona lookup).
4. Create a new chat → it attaches to the workspace, persona defaults to the seeded Assistant (verifies `is_default` insert).
5. Open Settings → drag a Layout slider, save → reload page, value persisted (verifies `global_settings` KV path).
6. Avatar menu → light/dark toggle still works (regression check on unrelated path).

If any of 1–6 fails, jump to Rollback.

## Rollback (~5 min)

```bash
docker compose stop hlh_api hlh_ui

# Step 1 — drop the post-migration tables BEFORE restoring. pg_dump --clean only
# knows the pre-migration table names (daws, daw_instructions, etc.) and will not
# touch the renamed tables on restore. Explicit DROP avoids duplicate tables.
docker exec -i hlh_db psql -U hlh -d hlh <<'EOF'
DROP TABLE IF EXISTS workspace_memory CASCADE;
DROP TABLE IF EXISTS workspace_context_files CASCADE;
DROP TABLE IF EXISTS workspace_instructions CASCADE;
DROP TABLE IF EXISTS workspaces CASCADE;
EOF

# Step 2 — reverse the role + database rename (as postgres superuser):
docker exec -i hlh_db psql -U postgres <<'EOF'
ALTER DATABASE hlh RENAME TO boolab;
ALTER USER hlh RENAME TO boolab;
ALTER USER boolab WITH PASSWORD 'boolab';
EOF

# Step 3 — restore from the pre-rename dump. The dump's DROP IF EXISTS statements
# for the original names (daws, daw_instructions, etc.) are no-ops since step 1
# already dropped their renamed successors; CREATE TABLE recreates the originals.
docker exec -i hlh_db psql -U boolab -d boolab < backup-pre-rename-YYYYMMDD-HHMMSS.sql

# Step 4 — revert the code:
git revert HEAD
docker compose up -d --build hlh_api hlh_ui
```

If you skipped Step 1, the DB ends up with BOTH the renamed tables AND the original
ones recreated by the restore (duplicate schema, no data loss). Recovery: stop
services, run Step 1, re-run Step 3.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Migration aborts mid-way due to an unknown FK or column | The `BEGIN`/`COMMIT` wrap ensures atomic rollback; backup taken in step 1 is the safety net. |
| `daw_id` column exists in a table not listed above | Stage 1 verification (`\d <table>`) catches it; rerun the migration with the missing `RENAME COLUMN` line added. |
| New chat/note created after deploy but before Stage-4 discovery of a bug | Operator avoids using the app between step 6 and end of Stage 4; window is < 10 min. |
| Role rename leaves old `boolab` connection strings cached in any backup script | Audit `scripts/` for hardcoded credentials before deploy; none expected after the Layer A sweep. |
| `pg_dump` backup fails silently | Pre-flight check in step 1 (file exists, non-empty, starts with PostgreSQL banner) detects this before proceeding. |

## Out of scope (deferred)

- Renaming `/opt/homelabhealth` to anything else.
- Renaming `/data/branding/` volume path (used by `routers/profile.py:USER_PROFILE_ICONS`).
- Cleanup of dormant cruft unrelated to this rename (e.g., `daws.color` per-workspace badge tint stays as `workspaces.color`; concept B preserved per prior decisions).
- Updating dependencies, frameworks, or runtime versions.
- Adding an automated test suite (operator-driven verification only, per current project convention).

## Implementation notes

- Single PR, single feature branch (e.g., `rename/boolab-to-homelabhealth`).
- Generate the new postgres password before deploy: `openssl rand -base64 32` (or similar). Store in `.env` only; never commit.
- Suggested commit decomposition (optional, makes review easier):
  1. Schema + migration script + `schema.sql` rewrite (`backend/`).
  2. Backend code follow-through (renames + drop mode filters in routers).
  3. Layer A infra (env, compose, nginx, vite).
  4. Frontend code follow-through + localStorage key rename.
  5. Layer C strays (scripts, docs, comment sweep).
- Each commit individually passes `npm run build` and `python3 -m py_compile $(find backend -name '*.py')`, but the deploy is atomic — commits aren't independently deployable.
