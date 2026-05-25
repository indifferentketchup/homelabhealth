# Design: Wipe-and-Reinit Rename — Final BooLab Cleanup

**Date:** 2026-05-08
**Status:** Approved for plan generation
**Scope:** Final cleanup of residual `boolab`/`daws`/`daw_id`/`BOOLAB_*` legacy in code and infra. DB is wiped (volume removed) rather than migrated, since DB contains only seeded defaults.

## Context

This is the closer for a multi-pass strip. Earlier passes on the now-merged `strip-initial` branch (commits `bcd67f3` through `0a54f4a`) deleted dormant features (skills, branding, theme, file viewer), swept the frontend, renamed `is_default_808notes` → `is_default` in JS, stripped Python mode references, baked in HomeLab Health identity, and updated `seed_assets.py` to use the new column names. What remains is the schema rename (`daws` → `workspaces`, `daw_id` → `workspace_id`, child table renames, mode column drops, branding_config drop), the matching backend code follow-through in the routers that query `daws`, and infra renames (postgres user, env var prefixes).

Replaces the larger `2026-05-08-boolab-rename-design.md` spec which assumed live production data and proposed a `pg_dump`-based migration. With an empty DB the migration is unnecessary; this spec keeps the same end state via volume wipe.

## Goal

Zero `boolab`/`daws`/`daw_id`/`BOOLAB_*` references in code, schema, or infra. End state: codebase reads as a single-user healthcare RAG app with no audio-workstation vocabulary or multi-brand vestiges.

## Non-goals

- Preserving any DB content (it's empty — see "What's wiped" below).
- Migrating production data via `pg_dump` (no production data exists).
- Renaming `/data/branding/` volume path (still used by `routers/profile.py` for user profile icons; orthogonal).
- Renaming `scripts/reembed_harrier.py` (low-stakes stray; separate trivial commit if/when wanted).
- Sweeping `README.md` / `CLAUDE.md` (low-stakes; doesn't gate the rename).
- Frontend code changes (already clean from strip-initial work — verified via grep).

## Final state

### Database (post-wipe, post-fresh-init)

Tables created by the new `schema.sql`:

| Table | Notes |
|---|---|
| `workspaces` | (was `daws`); `pinned BOOLEAN` (no `pinned_808notes`/`pinned_booops`); no `mode` column |
| `workspace_instructions` | (was `daw_instructions`); `workspace_id` FK |
| `workspace_context_files` | (was `daw_context_files`); `workspace_id` FK |
| `workspace_memory` | (was `daw_memory`); `workspace_id` FK |
| `chats` | `workspace_id` FK; no `mode` column |
| `sources` | `workspace_id` FK |
| `notes` | `workspace_id` FK |
| `source_groups` | `workspace_id` FK |
| `note_groups` | `workspace_id` FK |
| `memory_entries` | no `mode` column |
| `personas` | `is_default BOOLEAN`; no `is_default_booops`/`is_default_boocode` |
| `custom_instructions` | no `scope` column; singleton enforced via `UNIQUE INDEX ((1))` |
| `searxng_config` | no `mode` column |
| `global_settings` | KV keys `default_model`, `ollama_hidden_models` (no `_808notes` suffix); seeded empty |
| (other unchanged tables) | users, source_chunks, ollama_config, branding_assets — names unchanged |

Tables **removed**:
- `branding_config` — dormant, dropped from schema entirely.

Indexes:
- `chats_workspace_id_idx`, `sources_workspace_id_idx`, `notes_workspace_id_idx`, `workspace_memory_workspace_id_idx` (renamed from `*_daw_id_idx`).
- `personas_one_default_idx` (was `personas_one_default_808notes_idx`); the `_booops` and `_boocode` variants dropped.
- `custom_instructions_singleton_idx` (new — `UNIQUE ((1))` for singleton).

### Infra

| Concept | Before | After |
|---|---|---|
| Postgres user / db / password | `boolab` / `boolab` / `boolab` | `hlh` / `hlh` / `hlh` |
| `DATABASE_URL` | `postgresql+asyncpg://boolab:boolab@hlh_db:5432/boolab` | `postgresql+asyncpg://hlh:hlh@hlh_db:5432/hlh` |
| Env var prefix in `.env` / compose | `BOOLAB_*` (PUBLIC_HOST, API_UPSTREAM, PORT_*, VITE_API_PROXY) | `HLH_*` |
| `BOOLAB_PORT_808NOTES` | (UI port name) | `HLH_PORT_UI` |
| `VITE_PUBLIC_808NOTES_URL` | (build-time SPA URL) | `VITE_PUBLIC_URL` |

### Code-side

- `backend/deps.py`: `_SCHEMA_MODE_VALUE = "808notes"` constant removed; remaining `WHERE mode = $1` filters in the affected routers removed.
- All `daws` / `daw_id` / `daw_instructions` / `daw_context_files` / `daw_memory` references in `backend/routers/*.py` flipped to the renamed names.

## What's preserved (volumes NOT wiped)

- `homelabhealth_hlh_branding` — `/data/branding/user_icons/` (Sam's profile icon, if any).
- `homelabhealth_hlh_uploads` — `/data/uploads/` (any uploaded source files).
- `homelabhealth_hlh_history` — `/data/history/` (chat history files).

## What's wiped (single volume)

- `homelabhealth_hlh_db_data` — postgres data directory. Loses:
  - 1 seeded `personas` row — **auto-recreated** by `seed_assets.py` on next API startup.
  - 1 empty `custom_instructions` row (0 chars content, placeholder) — not auto-recreated; no loss.
  - 0 rows of every other table (verified by direct query before approval).

## Approach: 5-task plan

1. **Rewrite `backend/schema.sql`** to the target shape. No migration script — fresh init creates the post-rename schema directly.
2. **Backend code sweep** — finalize `daws`→`workspaces`, `daw_id`→`workspace_id` in the 7 routers that still query them (`chats.py`, `workspaces.py`, `notes.py`, `sources.py`, `history.py`, `workspace_context_files.py`, `workspace_memory.py`); drop `_SCHEMA_MODE_VALUE` from `deps.py`; drop residual mode WHERE-clauses. `python -m py_compile $(find backend -name '*.py')` returns clean.
3. **Infra rename** — `BOOLAB_*` → `HLH_*` in `.env`, `.env.example`; `boolab` → `hlh` postgres user/db/password in `docker-compose.yml`; `DATABASE_URL` in `.env` and `.env.example`.
4. **Wipe DB volume + rebuild**:
   ```bash
   docker compose stop hlh_api hlh_ui
   docker volume rm homelabhealth_hlh_db_data
   docker compose up -d --build
   ```
5. **Verify** — curl `/api/health` returns 200; curl UI returns 200; `personas` table has 1 row (Assistant); repo-wide grep for `boolab|daws|daw_id|BOOLAB_` in code returns 0 hits (excluding `docs/superpowers/`).

## Deploy

Single coordinated change. Steps 1–3 are code edits committed to `main` (no feature branch — single-user solo-dev pattern). Step 4 is the operator action (volume wipe + rebuild). Step 5 is verification.

Order matters: code must be committed BEFORE the volume wipe — if the volume is wiped first and the API tries to start with the old schema.sql, it'll create the old `daws` table, then code edits flip it to `workspaces` and the API breaks on next startup.

Approximate timing:
- Steps 1–3: ~15 min of focused editing (per-task verification).
- Step 4: ~30 sec (compose build is fast; DB init is sub-second on empty).
- Step 5: ~1 min curl + grep.

Total: ~20 min start-to-finish.

## Rollback

If verification fails:
- `git revert HEAD~N..HEAD` to undo the rename commits.
- `docker compose down hlh_api hlh_ui; docker volume rm homelabhealth_hlh_db_data; docker compose up -d --build` to wipe the (now-bad) new DB and reinit against the reverted code.

The wipe approach makes rollback trivial — there's no migration to reverse and no production data at risk.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| `seed_assets.py` references a column name that conflicts with the new schema | Verified during brainstorming: `seed_assets.py` line 21 already uses `is_default` (the new name). No additional audit needed. Step 5 verification queries `personas` post-wipe to catch any regression. |
| Backend router still has `daws.column_name` Python attribute access that wasn't caught by `daws`/`daw_id` grep | py_compile catches syntax; verification curl on `/api/workspaces/` and `/api/chats/` catches runtime AttributeError |
| Postgres `hlh` user/db creation fails on fresh init due to compose env var typo | First-startup logs from `hlh_db` container show init success/failure; verification step 5 attempts a query as `hlh` |
| Other volumes that depend on schema (e.g., a cached query plan or pg stats) break post-wipe | Postgres regenerates query plans on first query; no concern |

## Out of scope (deferred)

- `scripts/reembed_harrier.py` rename to `scripts/reembed_workspace.py` (low-stakes stray).
- `README.md` and `CLAUDE.md` sweeps for legacy terms (doesn't gate functionality).
- Misc comment sweeps in `schema.sql` and config files (cosmetic).
- Renaming `/opt/homelabhealth` directory (out of scope).
- Renaming `/data/branding/` path (`routers/profile.py` uses it for user_icons — orthogonal).
- Rotating the postgres password to something stronger than `hlh:hlh` (single-user local dev; can be done later via `ALTER USER`).

## Implementation notes

- Single PR on `main` (already on `main`; no feature branch required for this scope per single-user solo-dev pattern).
- Each of steps 1–3 committed separately for review traceability.
- Step 4 (volume wipe) is an operator action and not part of any commit; documented in plan as a deploy-time task.
- No automated test suite — verification via grep + py_compile + curl + manual eyeball, per project convention (CLAUDE.md).
