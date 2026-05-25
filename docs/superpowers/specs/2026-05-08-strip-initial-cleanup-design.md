# Strip-initial cleanup — design

Status: approved 2026-05-08
Branch: `strip-initial`

## Summary

Complete the strip-initial fork-cleanup by deleting three inert UI features, sweeping mechanical dead code, simplifying ops/renames, and dropping unused schema. End state: a leaner single-user RAG app with no legacy multi-brand baggage, no personal config baked in, and a schema that matches what the code actually uses.

Three PRs, sequenced lowest-to-highest irreversibility.

## Context

The audit (read-only sweep, 2026-05-07) found ~2,000 LoC of dead/inert code across backend, frontend, schema, and config. The "safe to delete immediately" file-level items (27 files) were already removed. This spec covers the remaining "needs review" items, organized into three implementation PRs by review-batch convenience and risk.

Cross-cutting principles set by the user during brainstorming:
- **MVP**: drop, don't refactor for purity. Working code stays untouched unless deletion is justified by zero-references or product-decision.
- **User-agnostic**: no personal model names, endpoints, IPs, or services baked in. LLM/AI integration must be env-driven (already largely is).
- **Branding fixed**: app colors, fonts, and brand assets are hardcoded in CSS. No user-customizable theme. Layout knobs (sidebar/chat width, font sizes) stay user-adjustable.

Hard constraints from CLAUDE.md respected throughout:
- `frontend/src/hooks/useStream.js` is never modified (fragile streaming bug).
- `frontend/src/components/ui/` primitives are checked before import.
- Schema changes are explicitly reasoned and idempotent.

## Decisions

### B-1 — Delete the file-source cluster
Stub backend, never wired. ~600 LoC.
- Files: `frontend/src/components/chat/FileBrowserPanel.jsx`, `frontend/src/components/FileBrowserPanel.jsx` (wrapper), `frontend/src/components/chat/FileViewerPanel.jsx`.
- ChatInput: `@`-mention machinery (state + UI), "Browse files" plus-menu item.
- WorkspaceView: panel mounts and `homelabhealth:attach-chat-file` event dispatch.
- Drop `shiki` runtime dep if no remaining consumer (verify at impl time).
- **Stays**: ChatInput drag/drop attach + queue (independent path, uploads via `sources.js`/`workspace_context_files.py`).

### B-2 — Delete the entire Skills feature
Per-chat session-skill toggle never finished wiring; SkillsLibraryPage exists but the in-chat modal cannot populate. Single-user homelab does not need this.
- Backend: `routers/skills.py`, `chats.py:171-197` skill-loading (`session_skill_set`, workspace-skill prompt assembly), any skill-related imports.
- Frontend: `pages/SkillsLibraryPage.jsx`, `api/skills.js`, `/skills` route in `AppRoutes.jsx`, ChatInput plus-menu Skills item, ChatInput skills modal (~120L).
- Sidebar: any nav entry for `/skills`.
- Schema-side drops happen in PR 3.

### B-3 — Delete the user-theme system
Colors, fonts, and brand assets are hardcoded in CSS. No user-customizable theme.
- Files: `UserProfileMenu.jsx`, `hooks/useTheme.js`, `lib/theme.js`, `src/config/` (verify theme-only at impl time before deleting), entire `api/branding.js`.
- `main.jsx`: drop theme import.
- `store/index.js`: drop `setUserProfile` and any branding-related state.
- `store/layoutStore.js`: drop color defaults (`accentColor`, `accentCyan`, `accentPurple`, `bgColor`, `bgPanel`, `bgCard`, `textColor`, `textDim`, `borderColor`), `fontFamily`, `fontBody`, `fontMono`, and the corresponding setters.
- **Stays**: `saveLayout()` mutation path, sidebar/chat width state, font-size state (`fsNav`, `fsChat`, `fsInput`, `fsHeading`, `fsCode`).
- `pages/workspace/SettingsPage.jsx`: drop Theme/Typography tab. Keep Layout tab.
- Backend `routers/settings.py` `_DEFAULT_UI_LAYOUT`: shrink to layout-only keys (drop color/font keys).

### A — Mechanical sweep
Every item below has zero references, confirmed by Grep across the repo.

**Backend:**
- `deps.py`: `principal_can_access_chat`, `persona_row_visible`, `workspace_row_visible`, `fetch_workspace_if_visible`, `assert_persona_mutable`, `assert_workspace_mutable` (5 always-True/no-caller helpers).
- `db.py`: `_COLLECTION_RE` regex + `import re`.
- `chats.py`: `_site_default_model`, unused `request: Request` param on `export_chat`, `chat_mode = _SCHEMA_MODE_VALUE` reassign on L1245, `should_retrieve` import on L28.
- `routers/history.py`: 2 unused `request: Request` params + `Request` import.
- `routers/sources.py`: unused `require_admin` import, duplicate `workspace_exists` check at L191-193.
- `routers/settings.py`: `_GLOBAL_SETTING_KEYS`, `GlobalSettingsBody`, `_global_settings_from_map`, `_fetch_global_settings_payload`, `GET /global`, `PATCH /global`. **Paired** with frontend `api/settings.js` removal — must ship together.
- `services/pruning.py`: `import json`, `max_context_tokens` parameter + `over_tokens` branch + `_estimate_tokens_from_messages` helper.
- `services/rag.py`: `invalidate_rag_settings_cache`, `should_retrieve`, `_DEFAULTS` keys `rag_intent_gate_enabled` and `rag_min_words_for_intent`.
- `requirements.txt`: `tree-sitter`, `tree-sitter-languages`, `passlib[bcrypt]` (both pinned lines), `python-jose`, `bcrypt`.
- `Dockerfile`: `apt-get install ... tmux ...` lines.

**Frontend:**
- `routes/paths.js`: `getPublicHref`, `isHttpUrl`.
- `lib/workspaceLayout.js`: `writeWorkspaceLayout` export.
- `api/settings.js`: `getGlobalSettings`, `patchGlobalSettings` (paired with backend).
- `store/index.js`: `messages`/`setMessages`, `defaultModel`/`setDefaultModel`, `setPersonaIconUrl`, `setPersonaEmoji`, `settingsOpen`/`setSettingsOpen`. Un-export `defaultPersona` and `personaFieldsFromRecord`. Inline `personaToUi` (one-line forwarder).
- `store/layoutStore.js`: any per-field setters not already removed by B-3 (`setSidebarWidth`, `setChatMaxWidth`, `setFsNav`, `setFsChat`, `setFsInput`, `setFsHeading`, `setFsCode`).
- `components/ui/`: drop unused exports — `alert.jsx` (`AlertTitle`, `AlertAction`), `badge.jsx` (`badgeVariants`), `button.jsx` (`buttonVariants`), `card.jsx` (`CardAction`), `dialog.jsx` (`DialogClose`, `DialogPortal`, `DialogOverlay`), `scroll-area.jsx` (`ScrollBar`).
- `components/chat/ChatView.jsx`: drop props `compactEmptyState`, `modelBarProps`, `hidePersonaInChatInput`, `hideDesktopModelBar` (no caller passes them) and the conditionals they gate.
- `components/chat/ModelSelectorBar.jsx`: drop props `hidePersona`, `_hideWorkspace`; drop dead constants `showModelPicker`, `showPersonaPicker`.
- `components/layout/Sidebar.jsx`: drop `activeWorkspaceId` prop on `ChatRow`; drop `adminUi`/`showAi` constants and the impossible `if (!showAi && !showSettings) return null` branch.
- `pages/workspace/WorkspaceApp.css`: drop `.workspace-landing__banner*`, `.workspace-landing-banner-grid`, `.home-view*`, `.page*` rules.
- `package.json`: drop `fuse.js`, `html-react-parser`, `cmdk`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-popover`. Align `@types/react`/`@types/react-dom` to React 18 majors.
- `vite.config.js`: drop `coerceAppMode`, `displayNameFromAppMode`, `htmlDisplayNameFromAppModePlugin`, `htmlOgImageFromShellPlugin`, `htmlOgTitleDescriptionFromShellPlugin` plugins (placeholders no longer exist in `index.html`).

### F — Ops decisions
- F-1: Delete `docker-compose.core.yml`, `docker-compose.ui.yml`, `docker-compose.ui.join.yml`. Single-stack only.
- F-2: Revert hardcoded Tailscale IP `100.114.205.53` in `docker-compose.yml` L37, L58 to plain port binding.
- F-3: `git rm backups/boolab_20260418_044136.sql.gz`. Add `backups/` to `.gitignore`. (History-purge with BFG/filter-repo deferred — separate decision.)
- F-4: Rename `scripts/reembed_harrier.py` → `scripts/reembed_chunks.py`. Fix docstring container reference (`boolab_api` → `hlh_api`). Drive model name from `EMBEDDING_MODEL` env (no hardcoded model).
- F-5: `.gitignore` `*.bak-*` → `*.bak*` to catch `*.bak.<date>` patterns.

### C — Renames
- C-1: `BOOLAB_*` env-var prefix → `HLH_*` in `docker-compose.yml`, `.env.example`, `frontend/Dockerfile`, `frontend/default.conf.template`, `frontend/vite.config.js`, `frontend/.env.development`, `frontend/.env.production`, `backend/main.py`. Specific renames: `BOOLAB_PUBLIC_HOST` → `HLH_PUBLIC_HOST`; `BOOLAB_PORT_API` → `HLH_PORT_API`; `BOOLAB_PORT_808NOTES` → `HLH_PORT_UI` (drop the legacy brand name from this var since there is only one UI port now); `BOOLAB_VITE_API_PROXY` → `HLH_VITE_API_PROXY`; `BOOLAB_API_UPSTREAM` → `HLH_API_UPSTREAM`. Drop `BOOLAB_PUBLIC_BOOLAB_URL`, `BOOLAB_PUBLIC_BOOOPS_URL`, `BOOLAB_PUBLIC_808NOTES_URL`, `BOOLAB_PUBLIC_BOOCODE_URL` build args entirely (multi-brand split is gone with B).
- C-2: `is_default_808notes` column rename → `is_default BOOLEAN`. Coupled with PR 3 (schema). JS readers in `paths.js`, `store/index.js`, `pages/workspace/AISettings.jsx`, `components/chat/ModelSelectorBar.jsx` all update.
- C-3: `bb-sidebar-pinned-open`, `bb-sidebar-recent-open` localStorage keys in `Sidebar.jsx` → `hlh-sidebar-pinned-open`, `hlh-sidebar-recent-open`.
- C-4: Drop "Harrier" mention in `services/embeddings.py:91` comment. Generic phrasing.
- C-5: **Keep** `boolab` Postgres user/db names. Buried in `.env`, no codebase surface, not worth a downtime window.

### D — Schema cleanup
All operations idempotent (`DROP ... IF EXISTS`, `ALTER TABLE ... DROP COLUMN IF EXISTS`). Schema is applied on every startup; existing deploys converge automatically. Every drop has zero readers/writers confirmed by Grep.

**DROP TABLE:**
- `branding_config`
- `terminal_machines`, `terminal_sessions`, `terminal_audit`
- `repo_files`, `repo_chunks`
- `message_tokens`
- `skills`, `workspace_skills` (verify exact names at impl time)

**ALTER TABLE DROP COLUMN:**
- `messages`: `status`, `last_seq`, `error`, `started_at`, `finished_at`
- `daws`: `dubdrive_sync_folder`, `dubdrive_sync_enabled`, `dubdrive_last_synced_at`, `repo_path`, `repo_branch`, `repo_auto_sync`, `repo_sync_status`, `repo_last_synced_at`, `repo_file_count`, `repo_chunk_count`, `pinned_booops`, `mode`
- `personas`: `is_default_booops`, `is_default_boocode`, `default_model`, `mode`
- `chats`: `mode`
- `memory_entries`: `mode`
- `users`: `password_hash`
- Any other `mode` columns repo-wide.

**ALTER TABLE ADD COLUMN:**
- `personas`: `is_default BOOLEAN NOT NULL DEFAULT FALSE` (replaces multi-flag siblings).

**DROP INDEX:**
- All persona unique indexes for `is_default_booops`, `is_default_boocode`.
- Add single uniqueness index on `personas.is_default` (partial index `WHERE is_default IS TRUE` to allow multiple FALSE rows).

**DROP CONSTRAINT:**
- All `*_mode_check` CHECK constraints (`daws_mode_check`, persona/chat/memory mode CHECKs).

**Seed cleanup:**
- `DELETE FROM global_settings WHERE key IN ('rag_intent_gate_enabled', 'rag_min_words_for_intent')`.
- Remove theme-related keys from `_DEFAULT_UI_LAYOUT` seed (already covered by B-3 in code; ensure seed payload matches).
- Terminal-machine seed rows fall out with the table drop.

**Migration safety:**
- `is_default_808notes` → `is_default`: backfill in the same migration (`UPDATE personas SET is_default = COALESCE(is_default_808notes, FALSE)`), then drop the old column. Both columns coexist briefly within the migration.

**`schema.sql` cleanup:**
- Update header comment to drop "boolab" project name.
- Drop the `_SCHEMA_MODE_VALUE` constant in `deps.py` if unreferenced after mode column removal.

### E — Refactor
- `routers/workspaces.py`: extract repeated 14-column `SELECT … FROM daws d LEFT JOIN personas p …` (7× duplicated) into a module-level constant. ~15 lines saved.
- All other refactors deemed overengineering for MVP and skipped: `chats.py append_message` split, `chats.py _assembled_system_prompt` split, `_inference_base`/`_openai_headers`/`_sse` cross-file consolidation, `_extract_text`/`parse_source_bytes` merge.

## PR sequence

### PR 1 — Feature deletions (B)
- B-1 file-source cluster
- B-2 Skills feature (code only; schema in PR 3)
- B-3 theme system

Estimated diff: ~1,500 LoC removed across ~15 files. Three logical commits within the PR for fine-grained rollback.

### PR 2 — Code cleanup bundle (A + F + C + E)
- A mechanical sweep (backend + frontend, F↔B `/global` pair ships here)
- F ops decisions (compose simplification, IP revert, backups gitignore, script rename, gitignore broadening)
- C renames (BOOLAB_* → HLH_*, bb-* → hlh-*, Harrier comment, except C-2 which couples to PR 3)
- E daws SELECT consolidation

Estimated diff: ~600 LoC removed + renames across most config files. Single review pass; no semantic changes beyond the F↔B pair.

### PR 3 — Schema cleanup + coupled JS rename (D + C-2)
- D schema drops/adds/renames (idempotent)
- C-2 JS column rename `is_default_808notes` → `is_default`
- All JS `mode` references removed (column dropped repo-wide)

Estimated diff: ~100 LoC schema + small JS. Irreversible; requires `pg_dump` before merge.

## Verification

CLAUDE.md confirms no test runner. Verification is manual.

**Per PR (all three):**
- `python -m py_compile $(find backend -name '*.py')` — backend compiles.
- `cd frontend && npm run build` — frontend builds without errors.
- `docker compose up --build -d` — full stack starts; API container healthy; UI loads.

**PR 1 specific (feature deletions):**
- Chat works end-to-end: send message, stream response, persist on reload.
- Sources tab: upload PDF, verify ingest + embedding.
- Drag-drop file attach in ChatInput still works.
- No broken `/skills` link in sidebar nav.
- No theme toggle UI; sidebar profile button still navigates to `/profile`.
- SettingsPage Layout tab still adjusts sidebar width / chat max width / font sizes.
- No console errors on initial load.

**PR 2 specific (code cleanup):**
- All API endpoints respond correctly (manual smoke: `curl http://localhost:9400/api/workspaces`, `/chats`, etc.).
- Sidebar localStorage migration: existing `bb-sidebar-*` values are abandoned (acceptable for single-user; new keys default to expanded). Document in PR description.
- `HLH_*` env vars resolve correctly in compose; `docker compose config` validates.
- `npm run build` shows no unused-dep warnings beyond expected.

**PR 3 specific (schema):**
- `pg_dump -Fc <db> > pre-pr3.dump` taken and stored.
- Apply `schema.sql` to the live DB; verify with `psql \d` that dropped columns/tables are gone, `is_default` column exists with correct backfill.
- Run the app; confirm chat creation, persona selection, workspace listing all work.
- If anything breaks: `pg_restore -c -d <db> pre-pr3.dump` and revert the merge.

## Risk and rollback

| PR | Reversibility | Mitigation |
|---|---|---|
| 1 | Full revert via `git revert`. Each B-* in its own commit for granular rollback. | Manual smoke test before merge. |
| 2 | Full revert via `git revert`. Pure code reorganization + cosmetic changes. | `npm run build` + `python -m py_compile` + container start. |
| 3 | **Irreversible at the schema level** (column drops lose data). | `pg_dump` before merge. Backfill `is_default` from `is_default_808notes` before dropping. Drops gated by `IF EXISTS`. Every drop has zero readers/writers per audit. |

## Out of scope

Deliberately NOT in this cleanup:
- `frontend/src/hooks/useStream.js` — fragile per CLAUDE.md hard rule #2.
- `chats.py append_message` and `_assembled_system_prompt` splits — work as-is, refactor when next touched.
- `_inference_base`/`_openai_headers`/`_sse` cross-file consolidation — net wash on lines.
- `_extract_text`/`parse_source_bytes` merge — works, edge cases differ.
- Postgres DB rename (`boolab` user/db) — see C-5.
- History-purge of the 4.4 MB `backups/*.sql.gz` blob from git history — separate destructive decision.
- Re-introduction of any deleted feature — file browsing, skills, theme switcher.
- Vector dimension flexibility (currently hardcoded 1024 in `schema.sql`) — schema-bound to BAAI/bge-m3; full multi-model support is feature work, not cleanup.

## Total impact

- ~2,000+ LoC removed
- 27 files already deleted (pre-spec)
- ~5 more files deleted via PRs 1 and 2
- 9 schema tables dropped
- ~25 schema columns dropped (including all `mode` columns)
- 5 npm dependencies removed
- 5 Python dependencies removed
- All "BOOLAB"/"808notes"/"Harrier" naming gone from code (legacy `boolab` Postgres user/db name retained in `.env` only)
