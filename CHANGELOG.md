# Changelog

Canonical record of releases for **homelabhealth**. Most recent on top.

**Convention:** new work accrues under `## [Unreleased]`. When a tag is
cut, rename `[Unreleased]` to `## [<tag>] — YYYY-MM-DD` and start a
fresh empty `[Unreleased]` section. Group entries by track (AI /
Safeguards / Security / UX / Tooling / Docs) when there are >5 items.

**Versioning:** Semver from `v0.1.0`. The `1.x` tags that appear in
older `git log` output were inherited from boolab and have been
retagged (see `v0.2.0` / `v0.3.0` notes). Reference-only snapshots
live under the `snapshot/` namespace.

---

## [Unreleased]

---

## [v1.2.9] — 2026-05-30

### Fixes
- **SearXNG no longer crash-loops under the bootstrap deploy path.**
  `bootstrap.py:create_search` started SearXNG with an empty, root-owned
  `tmpfs /etc/searxng` while the process runs as uid 1000, so SearXNG's
  entrypoint couldn't create `settings.yml` ("Permission denied") and the
  container restart-looped (observed 1144 restarts on one host). The old
  `stage_searxng_config` injected the file via `docker exec` *after* start,
  which always lost the race and failed with `409 (container restarting)`.
  Replaced with an entrypoint shim that copies the staged template into a
  writable (`mode=1777`) tmpfs before handing off to the real entrypoint;
  removed the post-start injection. (The `docker compose` path was already
  correct — it bind-mounts `settings.yml` directly.)

### AI
- **Vision sidecar can now be created by the bootstrap path.** `/vision/start`
  in `hlh_orchestra` only ever `.start()`s an existing `hlh_vision_embed`
  container; the bootstrap never created one, so vision was permanently
  unavailable on bootstrap deploys. Added `create_vision_embed` (mirrors the
  compose `vision` profile), created stopped and started on demand by the
  orchestra. Opt-in via `HLH_ENABLE_VISION=1`.

### UX
- **Model-load tracker is always visible.** It was hidden by default behind a
  per-browser `localStorage` toggle, which made it inconsistent across devices.
  Removed the toggle; `ModelStateSidebar` now always renders in the workspace
  rail. (`WorkspaceView.jsx`)

---

## [v1.2.8] — 2026-05-30

### Fixes
- **RAG now searches the whole workspace, not just attached sources.** Previously,
  once any file was "sent to chat" (`chat_source_selections`), retrieval switched
  to an *exclusive* filter — only attached sources were searchable, so asking the
  model to read any other workspace file returned "I can't see it." Retrieval now
  always searches every embedded source in the workspace; attached sources are
  *prioritized* (ordered first in the injected context and bypass the rerank-min
  gate) rather than being the sole pool. Attached sources are also fetched in a
  separate top-K query so their chunks can't be crowded out of the global top-40.
  (`services/rag.py` `retrieve_context` gains `priority_source_ids`; `routers/chats.py`.)

---

## [v1.2.7] — 2026-05-30

### Fixes
- **Durable-streaming response duplication.** At stream-end, when the assistant
  row flipped to `status='complete'`, the next poll wrote the complete row into
  the React Query cache and React re-rendered *before* the cleanup effect
  cleared `streamText` — so for one frame the real DB row (no longer excluded by
  the `status==='streaming'` filter) and the synthetic `__stream__` tail both
  rendered, showing the answer twice. `ChatView.jsx` now filters the durable
  assistant row by **id** (`durable.streamingMessageId`), not just status,
  keeping it suppressed until the effect clears the id.

---

## [v1.2.6] — 2026-05-30

### AI
- **Safeguard prompt rewritten (b0 → b1): interpret + context, and stop the
  model narrating it.** The old safeguard was a 127-line checklist that (a)
  forbade interpreting results — "just restate the value and range" — so the
  assistant was useless ("22 mg/dL, within range" with no meaning), and (b) a
  reasoning model (medgemma) worked through every rule step-by-step *each turn*,
  generating long internal "Plan: 1…13" reasoning that was slow and leaked into
  responses (the `<THINKING>` dumps + multi-minute waits). Rewrote it as concise,
  permissive guidance: interpret results like a knowledgeable friend
  (in/out of range, what it means, context), keep the real limits (no definitive
  diagnosis, no prescribing, crisis + urgency handling), and explicitly tell the
  model to answer directly without narrating its reasoning or restating rules.
  Operator-chosen policy level: "interpret + context."

## [v1.2.5] — 2026-05-30

### UX
- **Model tracker is now opt-in.** The inference model-load tracker in the
  workspace right rail is hidden by default; a CPU-icon toggle in the rail
  header shows/hides it, and the preference persists (localStorage). It also
  stops blanking now that the DB pool is pre-warmed (v1.2.4).


---

## [v1.2.4] — 2026-05-30

### Fixes
- **Undersized DB pool → cascading failures under model-load spikes.** The
  asyncpg pool used `min_size=1`, so concurrent UI polls (`inference/state`,
  `models`, `profile`, `settings/layout`) plus a chat send forced new
  connections to be opened on demand. When that coincided with a 16.5 GB
  model load saturating the host, the connect timed out — surfacing as
  `internal_error` on send, the model/vision checker blanking, and even the
  font-size flickering (layout poll failing → CSS default, then re-applying the
  saved size). Pre-warm the pool: `min_size=4`, `max_size=20`,
  `command_timeout=120`, so connections already exist before the spike.

---

## [v1.2.3] — 2026-05-30

### UX
- **Default text size 21→18px, default chat width 1200→900px.** Updated in all
  three places that define the layout defaults (backend `_DEFAULT_UI_LAYOUT`,
  frontend store `DEFAULTS`, and the `globals.css` `:root` tokens). Affects the
  base font and chat-message text (`fontSize`/`fsChat`) and the chat column
  width; nav/heading/code sizes unchanged. Operators who already saved a custom
  layout keep theirs (server value overrides the default).

---

## [v1.2.2] — 2026-05-30

### Performance
- **Chat felt slow between messages — model thrashing, not slow inference.**
  Generation was already healthy (~60 tok/s for medgemma-27b on a 5090), but
  bootstrap hardcoded `--models-max 2` while a single RAG turn loads three
  models in sequence (embed → rerank → chat). With only 2 slots the 16.5 GB
  chat model got evicted and **reloaded from disk on the next message**, adding
  multi-second time-to-first-token. Now gpu-aware: `--models-max 4` on GPU
  (CPU stays 2; `HLH_MODELS_MAX` still overrides), and `sleep-idle-seconds`
  raised 300 → 1800 so warm models don't unload mid-session. GPU tiers have the
  VRAM headroom for the full bundled set (~19 GB of 32).

---

## [v1.2.1] — 2026-05-30

### Fixes
- **Duplicate Search / Relevance rows in the Models panel** — v1.1.4 gave
  embed/rerank real download rows, but the older "sidecar-managed" synthetic
  provider rows for those roles stuck around, so each appeared twice. The
  synthetic rows now drop any role that already has a download row, leaving
  only `vision_embed` (medsiglip — a real separate sidecar with no download
  row). One row per model.

---

## [v1.2.0] — 2026-05-30

### Observability
- **Access-log noise filter** — the UI polls a handful of endpoints every ~2s,
  burying real errors under `GET /api/models 200 OK` floods. `startup_report`
  now drops *successful* polls of those endpoints from the uvicorn access log
  (non-2xx always passes through) and quiets httpx's per-request INFO chatter
  (the vision/status poll). `docker logs hlh_api` is readable again.
- **Startup banner** — one greppable block at boot: version, tier, chat model,
  detected GPU, on-disk GGUF count/size, the active-chat symlink target, and
  bundled_models status counts (+ seeded/orphaned). "Is this healthy?" at a
  glance. `HLH_VERSION` is now passed to `hlh_api` (compose + bootstrap).
- **Loud startup-failure summary** — if lifespan throws (e.g. the v1.1.4
  CheckViolationError), a `STARTUP FAILED — cause: …` block is logged at
  CRITICAL before the traceback, so the root cause isn't buried in the
  restart-loop spam.
- **Doctor model-layer checks** — `python -m hlh.doctor` / `/api/system/doctor`
  now also check: `/models` volume writable by uid-1000 (the EACCES gotcha,
  with the chown fix in the detail), and failed/stuck/pending model pulls.
- **`hlh-status.sh`** — one host command (curl|bash) summarizing per-container
  state + health, the API startup banner, and recent error lines across the
  whole stack.

---

## [v1.1.8] — 2026-05-30

### Fixes
- **Interrupted model pulls wedged forever in 'pulling'** — pull tasks are
  process-local asyncio tasks; a restart/crash mid-download orphaned the row
  (status stuck at `pulling`, no live task), and the UI then couldn't recover
  it: `pull_one` returns 409 "already pulling" and cancel is a no-op. After the
  crash-loop churn this stranded the chat/vision rows. Added
  `reset_orphaned_pulls()` at boot — flips any `pulling` row back to `pending`
  so it's retryable.

---

## [v1.1.7] — 2026-05-30

### Fixes
- **Flat-path model pulls failed with EACCES on the models volume** — embed /
  rerank / tasks (and, post-v1.1.5, chat) download to flat `/models/<file>`
  paths, but Docker only chowns a *fresh empty* named volume to the mounting
  uid; once `hlh_models` was populated, its root stayed root-owned and the
  read_only uid-1000 `hlh_api` got `PermissionError: [Errno 13]` writing
  `*.gguf.partial`. (Chat/vision subdirs worked because they were already
  1000-owned.) Bootstrap now runs `ensure_models_ownership()` — a throwaway
  root container that `chown -R 1000:1000 /models` — after volume creation,
  so re-running the installer self-heals existing volumes too.

---

## [v1.1.6] — 2026-05-30

### Fixes
- **API crash-loop on boot (regression from v1.1.4)** — v1.1.4 added the
  `tasks` role to `MODEL_REGISTRY`, but `bundled_models.role`'s CHECK
  constraint didn't allow it. `seed_registry` then raised
  `CheckViolationError` on every startup → lifespan aborted → `hlh_api`
  crash-looped → nothing worked, including login. Added `tasks` to the CHECK
  (inline for fresh DBs) plus an idempotent drop+re-add `ALTER` for existing
  DBs (mirrors the `providers_role_check` migration). Affected v1.1.4 and
  v1.1.5; this is the hotfix.

---

## [v1.1.5] — 2026-05-30

### AI
- **Tier-aware chat model loading (GPU tiers now work end-to-end)** —
  `models.ini` previously pinned `[medgemma]` to the cpu-std 4B GGUF with
  `n-gpu-layers=0`, so GPU tiers (16/24 GB) downloaded the 27B model but the
  bundled router still loaded the wrong file on CPU. Two changes:
  - Chat GGUFs now live at flat `/models/<filename>.gguf` paths
    (`_FLAT_DEST_ROLES` += `chat`).
  - New `bundled_providers.link_active_chat(tier)` symlinks
    `/models/active-medgemma.gguf` (or `active-qwen.gguf` on `cpu-min`) at
    the tier's downloaded GGUF, mirroring `link_active_mmproj`. Runs from
    `apply_bundled_bindings` (tier save) and from the puller's success
    handler (chat-pull finish). `models.ini` now points the chat aliases at
    the symlinks, so one static config serves every tier.
  - `n-gpu-layers = auto` everywhere — CPU build no-ops it, CUDA build
    offloads as many layers as fit in VRAM.
  - Best-effort `migrate_legacy_chat_paths()` runs at boot to move any
    `/models/chat/<tier>/<file>.gguf` from v1.1.4 to the new flat path
    (drops duplicates, never re-downloads).

---

## [v1.1.4] — 2026-05-30

### AI
- **Bundled embedder / reranker / tasks models now download** — `embed`
  (bge-m3), `rerank` (bge-reranker-v2-m3), and `tasks` (gemma-3-270m) were
  `None` placeholders (`# Phase 2`) in `model_puller.MODEL_REGISTRY`, so
  `seed_registry` never created rows, nothing was pullable, and the bundled
  router had no weights — `/v1/embeddings` returned 500 and RAG/search could
  not work. Added pull specs (public gpustack / unsloth GGUF mirrors;
  filenames match `models.ini`) for all six router tiers, plus a flat
  `/models/<file>` dest-path for these tier-independent roles so they land
  exactly where `models.ini` points. The Models tab now lists Embed / Relevance
  / Tasks rows you can pull.
  - **Known remaining gap:** GPU tiers' chat model (medgemma-27b) downloads to
    `/models/chat/<tier>/` but `models.ini` only wires the cpu-std path and
    pins `n-gpu-layers=0`. GPU chat needs a tier-aware `models.ini` (separate
    change). Embed/rerank/tasks above are tier-independent and unaffected.

### UX
- **"Enable GPU acceleration" card** — when no GPU is detected, the System tab
  now shows a prompt with the one-command host installer
  (`enable-gpu.sh`), a **Copy** button, an inline **View script** (fetches the
  exact file the command runs, so users can audit it before piping to `sudo
  bash`), and a **View on GitHub** link. The install runs on the host — the
  app's container can't reconfigure the host's Docker.

---

## [v1.1.3] — 2026-05-29

### Fixes
- **Tier selection 500 on bootstrap installs** — `write_tier_env()` writes
  `/data/.env`, which only exists (bind-mounted) in the compose deployment. In
  bootstrap installs `hlh_api` runs `read_only` with no `.env`, so the write
  raised `OSError` and the first-time tier-picker `PUT /api/system/profile`
  returned `internal_error` — blocking setup entirely. The `.env` sync is a
  compose-only concern, so it now logs and skips on `OSError` instead of
  failing the request.

---

## [v1.1.2] — 2026-05-29

### Infrastructure
- **Robust GPU detection in bootstrap** — `detect_gpu()` previously only
  returned true when the Docker daemon advertised a runtime named `nvidia`.
  Docker Desktop (common on WSL) exposes GPUs via device requests without that
  runtime, so a working card (e.g. RTX 5090) went undetected and the stack
  came up CPU-only. Added a probe fallback that actually launches `nvidia-smi
  -L` in a GPU container.
- **hlh_api gets GPU access when present** — bootstrap now passes
  `device_requests` to `hlh_api` (gated on `gpu=True`), so in-container
  `nvidia-smi` detection populates the hardware card / tier-picker VRAM
  recommendation. Previously only `hlh_chat` got the GPU, so the card always
  showed no GPU.

### Tooling
- **One-command `install.sh`** — `curl … | bash` wrapper around the orchestra
  bootstrap so end users don't type the socket mount / `HLH_BOOTSTRAP` flags.
  TTY flags are gated on `[ -t 0 ] && [ -t 1 ]` so it works both piped and
  interactive.

### UX
- **Hardware card CPU-model row** — long CPU model strings no longer float to
  the far right of the card; the value now stacks under its label.

---

## [v1.1.1] — 2026-05-29

### Fixes
- **Workspace blank screen (TDZ crash)** — `ChatView.jsx` read `durableEnabled`
  / `durable` in its durable-stream resume effect ~40 lines before those
  `const`s were declared. Dependency arrays evaluate during render, so every
  `ChatView` mount threw `ReferenceError: Cannot access 'durableEnabled' before
  initialization`, blanking every workspace (no error boundary). Moved the
  declarations above the effect. Bug introduced in `c16dacb` (v1.0.0).

### UX
- **Removed orphaned model selector** — the chat header's model dropdown
  (`ModelSelectorBar`) was a leftover from the multi-provider era and called the
  now admin-only, `provider_id`-scoped `/api/inference/models`, returning `422`.
  The chat model is fixed by hardware tier (users can't pick), so the selector
  is gone; replaced with a read-only `WorkspaceTitle` showing the workspace
  name. Sends fall back to the workspace's bound model. Removed dead
  `fetchModels()` wrapper.

---

## [v1.1.0] — 2026-05-28

### Infrastructure
- **Smart bootstrap (single `docker run`)** — `hlh_orchestra` now doubles as a
  bootstrap entrypoint when started with `HLH_BOOTSTRAP=1`. It creates
  networks, volumes, generates `HLH_MASTER_KEY` and `ORCHESTRA_TOKEN`, pulls
  every image, and starts the stack in dependency order. Auto-detects GPU.
  Eliminates the clone + `.env` + compose flow for end users — one command
  on a fresh host brings the whole stack up. Compose workflow remains
  available for contributors and existing installs.
  New modules: `hlh_orchestra/bootstrap.py`, `hlh_orchestra/templates/`
  (baked-in `models.ini` and `searxng_settings.yml`), `hlh_orchestra/entrypoint.sh`.

### Demo
- **Demo data overhauled** — replaced two FHIR JSON bundles framed as a
  doctor's patient list (Jane Doe, John Smith) with twelve individual
  scanned-report-style text files for one synthetic person (Alex Taylor):
  CBC, CMP, TSH, lipid panel, A1c, complement panel, tryptase, MRI brain,
  CTA head, abdominal US. Each file looks like what a real upload from a
  patient portal would contain.
- Demo loader (`routers/demo.py`) now handles `.txt` files in addition to
  FHIR JSON.

### Docs
- `architecture.md` updated: `hlh_vision_embed` + `hlh_orchestra` rows added
  to the container topology, `hlh_config` + `hlh_vision_cache` volumes
  documented, smart-bootstrap note added.
- `CLAUDE.md` Conventions section gained eight entries from session learnings
  (reasoning strip fallback, durable-stream resume, vision_embed upsert,
  GHCR token gotcha, etc.).
- New design doc: `docs/superpowers/specs/2026-05-28-smart-orchestra-bootstrap-design.md`.

---

## [v1.0.0] — 2026-05-28

### UX
- **Inference tracker friendly names** — model IDs (`bge-m3`, `medsiglip`,
  etc.) replaced with role-based labels (Search, Vision, Chat, etc.) with
  hover tooltips showing the plain-English description and technical ID.
- **Models table friendly roles** — Role column in Settings → System uses
  the same friendly labels with tooltips. MedSigLIP row grayed out with
  "Not available on this tier" when the current tier can't support it.
- **Top bar shows workspace name** — model selector demoted to small
  muted text; workspace name is the primary header.
- **Model name on assistant messages** — "AI-generated" badge replaced
  with "MedGemma AI" or "Qwen AI" based on the model that generated the
  response.
- **Crisis resources in sidebar** — always visible in the nav panel with
  clickable phone numbers (988, Poison Control, 911). Collapses to a
  phone icon when sidebar is collapsed.
- **Live reasoning box** — thinking content streams in real time in an
  open collapsible block with a pulsing "Reasoning…" indicator. Collapses
  to "Show reasoning" after completion. Answer streams below.
- **STT removed from tier cards** — whisper not implemented; removed
  aspirational references.
- **Vision Search in tier cards** — MedSigLIP availability shown per tier
  (gpu-8gb+ only).

### AI
- **Reasoning strip rewrite** — replaced brittle hardcoded answer-start
  patterns with paragraph-level heuristic that detects when thinking ends
  and the user-facing answer begins. Falls back to showing raw text
  instead of discarding the response.
- **Streaming thinking filter** — `ThinkingStreamFilter` now emits
  `<THINKING>` immediately on detection and streams content live, instead
  of buffering silently. `</THINKING>` emitted on answer transition.
- **Tier-filtered inference tracker** — sidebar only shows the chat model
  for the active tier (no more duplicate "Chat" entries).

### Infrastructure
- **Thin-client resume** — refreshing the page or opening on another
  device automatically reconnects to an in-progress durable stream.
  `useDurableChat.resume()` detects `status: 'streaming'` messages on
  mount and starts polling.
- **Duplicate message fix** — optimistic user message dedup now checks
  all messages, not just the last one. Streaming assistant placeholders
  filtered from display during active inference.
- **Blank response fix** — empty assistant bubble no longer renders
  during durable streaming; server-side `status: 'streaming'` rows
  filtered from `displayMessages` while busy.
- **Vision embed provider lifecycle** — always seeded on boot regardless
  of sidecar reachability; no more deletion/re-creation race.

### Docs
- README final pass — real clone URL, removed AGENTS.md reference,
  version bumped to v1.0.0.
- THREATMODEL.md review date updated, typo fixed.
- Roadmap v1.0.0 checklist completed.

---

## [v0.27.0] — 2026-05-26

### AI
- **Durable streaming inference (Phase A)** — inference runs as a
  background task detached from the HTTP connection; partial content
  flushed to Postgres every 500ms with chained writes; mobile Safari
  backgrounding no longer loses the assistant response. Feature-flagged
  (`durable_streaming_enabled` in `global_settings`; default off).
  New endpoints: `POST /stop`, `POST /discard-stale`.
  New modules: `services/chat_jobs.py`, `services/inference_job.py`.
  Frontend: `useDurableChat` polling hook with adaptive intervals
  (1s/2s/5s) and visibility-change refetch.
- **`hlh_chat --reasoning on --reasoning-format deepseek`** plus API-layer
  **`reasoning_strip`** — MedGemma 1.5 ``thought`` blocks are dropped from
  SSE and saved assistant rows (llama.cpp b9282 still mixes peg-native
  thinking into ``content``; strip is the effective fix).
- **cpu-std context window lowered to 8K** (8192 tokens) — matches
  `cpu-min` footprint; reduces KV-cache RAM pressure on CPU-only hosts.
  GPU tiers unchanged. `TIER_CHAT_CTX` in `services/sysinfo.py`; env
  `HLH_CHAT_CTX` still overrides.
- **Chat role normalization** before inference — merge consecutive
  user/assistant turns so MedGemma's jinja template accepts retries
  after failed completions.
- **Stream status UX** — phase events over SSE (`preparing`, `search`,
  `rag`, `inference`), elapsed-time status bar, stale-stream banner
  (60s), and `retry_last` on message POST to re-run inference without
  duplicating the user row.
- **Lifespan sweeper** — 60s background loop marks streaming messages
  older than 5 minutes as failed (orphan cleanup).

### UX
- **Mobile sources panel:** header FileStack opens the sources drawer (with
  Send to Chat) instead of the legacy `/sources` checkbox page; drawer rows
  stack the button on narrow widths; long-press context menu adds Send to Chat.
- `StreamStatusBar` + `StaleStreamBanner` in chat (pattern from BooCode
  v1.12.3).
- Fix blank page: restore missing `ModelSelectorBar` import in `ChatView.jsx`.
- Map Safari **Load failed** to a actionable retry message; emit SSE errors
  when inference returns empty; start SSE stream before RAG so mobile
  clients get bytes immediately.

### Tooling
- `verify_durable_streaming.py` — end-to-end verification for Phase A
  (202 send, poll-to-complete, stop, 409 double-send).

---

## [v0.26.0] — 2026-05-25

### Docs
- **`docs/architecture.md`:** system design — container topology, chat/ingest SSE flows,
  data model, security layers, release map (verified against git history through v0.25.0).
- **`AGENTS.md` + `docs/CONTEXT.md`:** committed agent entry points and session bootstrap.
- **Committed `docs/superpowers/specs/`** (design docs); plans remain local.
- **Stale doc pass:** THREATMODEL auth updated for built-in sessions (v0.19.0); roadmap A3
  two-pass → v0.25.0; shipped superpowers specs marked historical; frontend api comment,
  `SECURITY.md` auth scope, docker-compose OG description (removed legacy DAW copy).

### Tooling
- **`.gitignore`:** `CLAUDE.md`, `.cursor/`, `.cursorignore` stay local-only.

---

## [v0.25.0] — 2026-05-25

### AI
- **Two-pass vision extraction** for standalone images: pass 1 extracts
  visible text (labels, overlays, report text); pass 2 interprets medical
  image content (modality, region, findings, impression). Output merged as
  `[TEXT FROM IMAGE]` + `[IMAGE INTERPRETATION]`. PDFs keep a single
  document-extraction pass per page.
- **Vision inference timeouts:** `hlh_chat` `--timeout 300` (configurable
  via `HLH_CHAT_TIMEOUT`); `services/vision.py` client timeout raised to
  300 s to match.

### UX
- **Pre-flight UI:** LUKS, backrest, and master-key doctor checks tagged
  `advanced=True` and hidden from Settings → System → Pre-flight. CLI
  `python -m hlh.doctor` still shows them.

### Docs
- **A4 STT deferred** with operator consent — ship-to-friend gate closed
  without whisper.cpp sidecar. Revisit if voice input is requested.
- README rewritten for bundled-AI posture (v0.22–v0.24 features).
- Roadmap synced through v0.24.0; ship-to-friend gate updated.
- CHANGELOG backfill for `v0.23.1` (per-tier context windows).

---

## [v0.24.0] — 2026-05-25

### AI
- **Token tracking:** capture `prompt_tokens` and `completion_tokens` from
  llama.cpp responses. Stored per message; `ctx_max` stored per chat from
  `HLH_CHAT_CTX` env.
- **Auto-compaction:** when prompt tokens reach 85% of `ctx_max`, older
  messages are summarized via the LLM and marked `compacted_at`. The
  summary replaces them in future inference while originals remain visible
  (collapsed) in the UI. Uses anchored rolling summarization — new
  summaries merge with prior summary context.

### UX
- **Context indicator** (opt-in): small token usage pill under the chat
  input showing "X / Y tokens" with color-coded dot (gray → amber →
  orange → red). Enable in Settings → Layout → "Context usage indicator".
- Compacted messages shown as collapsed group ("N earlier messages
  summarized") with expand to view originals at reduced opacity.
  Conversation summary displayed as a blue system bubble.

### API
- `prompt_tokens`, `completion_tokens`, `compacted_at` added to messages
  API response.
- `ctx_max` added to chat detail response.
- `GET/PUT /api/settings/context-bar` for the opt-in toggle.

---

## [v0.23.1] — 2026-05-25

### AI
- **Per-tier context windows:** `HLH_CHAT_CTX` passed to `hlh_chat`
  `--ctx-size` (default 32K; was llama.cpp's 512-token default).
  Tier defaults: cpu-min 8K; cpu-std / gpu-4gb / gpu-8gb / gpu-16gb 32K;
  gpu-24gb+ 64K. Context size shown in tier card footprints.

---

## [v0.23.0] — 2026-05-25

### Safeguards
- **B3 Audit-logged refusals:** every guard refusal (input block or output
  flag) writes a hash-chained `audit_log` row with action
  `safeguard.refuse.input` or `safeguard.flag.output`.
- Retry-with-warning UX: input blocks show an amber inline warning with
  category-specific guidance ("rephrase as an educational question").
  Draft is preserved for easy editing. No bypass button.
- Output guard flags displayed as expandable amber badge on flagged
  assistant messages.

### UX
- **Safety Log** settings panel: paginated view of all safeguard events
  (input blocks + output flags) from the audit log.

### API
- `GET /api/audit/refusals` — paginated audit_log rows filtered to
  `safeguard.*` actions.
- `guard_flags` field now included in messages list API response.

---

## [v0.22.0] — 2026-05-25

### AI
- **A3 Vision (MedGemma mmproj):** enable MedGemma's built-in multimodal
  capabilities via `--mmproj` on `hlh_chat`. PDFs and images are rendered
  as page images and sent to the vision model for structured text extraction
  during ingest. Falls back to pdfplumber/Tesseract when vision is unavailable.
- New `gpu-4gb` tier for 4–5 GB VRAM cards (MedGemma 4B Q4_K_M with partial
  GPU offload).
- Vision MODEL_REGISTRY entries (mmproj-F16.gguf) for cpu-std through gpu-24gb+.
- `services/vision.py` — async vision extraction via `/v1/chat/completions`
  with base64 image_url.
- `pdf2image` + `poppler-utils` added for PDF→PNG page rendering.
- Doctor check: `vision_available` — verifies mmproj file present for the
  active tier.

### UX
- Tier picker: cpu-min accuracy warning, gpu-4gb partial offload info,
  <4 GB VRAM GPU→CPU fallback explanation.
- Updated vision fields in all tier cards to show MedGemma mmproj availability.

### Tooling
- `hlh_chat` compose command switched to shell entrypoint with conditional
  `--mmproj` injection via `/models/vision/active-mmproj.gguf` symlink.
- `link_active_mmproj()` in `bundled_providers.py` manages the symlink
  atomically on every tier save and lifespan boot.

---

## [v0.21.0] — 2026-05-25

Sources pipeline polish: reingest, source injection into chat, and bugfixes.

### AI
- `POST /api/sources/reingest-all` re-parses and re-embeds from stored
  files without re-uploading (`6d8dbac`).
- Backend source injection — sources attached to a message are injected
  into the system prompt with clickable viewer (`473a7ed`).
- Structured lab table parser now correctly separates value from
  reference range (`29f0fa2`).

### Safeguards
- De-id: only redact birthdate patterns, not all dates (`37cf78a`).
- De-id applied to "Send to Chat" content endpoint (`f83cf3f`).

### UX
- Per-file upload progress with status indicators (`c308f1e`).
- Source dedup check scoped to current workspace (`636acd8`).
- Tighter workspace card footer buttons (`55cc090`).
- Auto-title logging + timeout bumped to 30 s (`e69c2af`).

### Fixes
- Pass `sourceIds` to `runStream` — was undefined in closure scope (`e82afad`).
- Add `'image'` to `sources.source_type` CHECK constraint (`5d61967`).
- Delete stored files on source/workspace deletion (`a7e3a91`).

### Docs
- `CLAUDE.md` — updated auth section (built-in auth, not single-user stub),
  expanded layout with security services, added pdfplumber/tesseract/argon2
  to stack.

---

## [v0.20.0] — 2026-05-25

Sources overhaul: file storage, PDF/OCR parsing, multi-file upload, and
safeguards hardening.

### AI
- File storage — uploaded files stored on disk; "Send to Chat" reads full
  document content (`39a6e4d`).
- Switch to pdfplumber + structured lab table parser (`1b25590`).
- Tesseract OCR for image uploads (PNG, JPG, TIFF, BMP) (`9faad18`).
- Multi-file upload support (`9e41fed`).
- Tighten system prompt to prevent hallucination over source data (`8a49ffa`).
- Remove raw-text fallback for auto-title (`3cf5c3f`).

### Safeguards
- Structured record-interpretation rules + banned verbs (`c6cb018`).
- Prevent speculative alarmism from lab values (`b2dd8ab`).

### UX
- Sources: right-click context menu, auto-title from LLM (`c06fc9b`).
- Sources: hover tooltip, inline rename, resizable panel (`a49d519`).
- Sources: attachment chips, collapsible notes, tighter layout (`4744e6b`).
- Sources: replace checkboxes with "Send to Chat" button (`8229fa1`).
- Tighter panel headers + collapsible notes list (`410ddb3`).
- Bump small font sizes for readability (`fb8d383`).
- Move pre-flight checks to bottom of system page (`ddbf352`).

### Fixes
- Fix audit stream-consumed error on multipart uploads (`531db04`).
- Fix auth redirect loop on login/setup pages (`59a5f6e`).
- Add `--no-model-warmup` to hlh_infer — warmup crashed process (`e9e3f8a`).
- Add v2 subcommand for infinity-emb 0.0.77 + bump mem to 6g (`39527df`).

### Tooling
- Drop HF token from UI, API, doctor, and compose (`b63d5e3`).

---

## [v0.19.0] — 2026-05-24

Built-in authentication. Username/password login with session cookies.
No reverse-proxy auth assumed — the app handles its own auth out of
the box. First-launch setup wizard creates the admin account.

### Code
- `backend/services/auth.py` — PBKDF2-SHA256 password hashing (600k
  iterations), session token management (SHA-256 hashed in DB, raw in
  HttpOnly cookie), `create_user`, `set_password`, `needs_setup`.
- `backend/routers/auth.py` — `POST /login`, `POST /logout`,
  `GET /me`, `GET /needs-setup`, `POST /setup` (first-launch account
  creation).
- `backend/deps.py` — replaced always-owner stub with session-based
  auth. `get_principal()` reads session cookie, validates against DB,
  returns 401 if invalid.
- `backend/main.py` — `_AuthMiddleware` enforces auth on all `/api/*`
  requests except login/setup/health endpoints. Auth router mounted
  at `/api/auth`.
- `backend/schema.sql` — `users.password_hash TEXT`, `sessions` table
  with token_hash + expiry.

### Frontend
- `LoginPage.jsx` — username/password form with error handling.
- `SetupPage.jsx` — first-launch account creation (username + password
  + confirm). Auto-login after setup.
- `AppRoutes.jsx` — `AuthGuard` wrapper checks setup status then
  session on mount. Redirects to `/setup` or `/login` as needed.
- `api/index.js` — global 401 handler redirects to `/login` on
  session expiry.

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.19.0]`.
- `docs/roadmap.md` — `v0.19.0` moved from Planned to Shipped;
  active-work pointer retargeted to `v0.20.0` / B3.

---

## [v0.18.0] — 2026-05-24

Key auto-generation + HF token cleanup. Zero-friction first launch:
encryption keys auto-generate and persist to `/data/keys/.hlh_keys`.
No `.env` editing required for a default deployment.

### Code
- `backend/services/key_manager.py` — `ensure_keys()` reads env → file
  → auto-generates. Sets `os.environ` so existing crypto code works
  unchanged. Persists to `/data/keys/.hlh_keys` with `0600` permissions.
- `backend/main.py` — `ensure_keys()` called first in lifespan.
- `backend/hlh/doctor.py` — `hf_token` check changed from WARN to OK
  when unset ("optional — bundled models are on ungated repos"). Doctor
  CLI also calls `ensure_keys()` for consistency.
  `provider_key` and `master_key` WARN messages updated to reference
  auto-generation.
- `docker-compose.yml` — `hlh_keys` named volume for key persistence.
- `backend/Dockerfile` — pre-creates `/data/keys` with correct ownership.

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.18.0]`.
- `docs/roadmap.md` — `v0.18.0` moved from Planned to Shipped;
  active-work pointer retargeted to `v0.19.0` (built-in auth).

---

## [v0.17.0] — 2026-05-24

C6 column encryption. AES-256-GCM envelope encryption on PHI columns
using per-record HKDF-derived DEKs from `HLH_MASTER_KEY`. Opt-in —
app works without the key (plaintext passthrough). This is the FINAL
MVP item — all ship-to-friend prerequisites are now met.

### Code
- `backend/services/crypto.py` — column encryption primitives:
  `encrypt_column()` / `decrypt_column()` with `cenc:v1:` prefix,
  HKDF key derivation from `HLH_MASTER_KEY` + record UUID,
  AES-256-GCM. Passthrough when key unset.
- `backend/routers/chats.py` — encrypt `messages.content` on write
  (user + assistant + fork paths), decrypt on read (list, detail,
  export, api_messages for inference).
- `backend/routers/notes.py` — encrypt/decrypt `notes.content`.
- `backend/routers/custom_instructions.py` — encrypt/decrypt
  `custom_instructions.content`.
- `backend/scripts/migrate_column_encryption.sh` — idempotent
  migration encrypting existing plaintext rows. Pre-flight guard
  for `HLH_MASTER_KEY`.
- `backend/hlh/doctor.py` — `column_encryption` check (OK when
  key configured, WARN when unset). 18 checks total.

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.17.0]`.
- `docs/roadmap.md` — `v0.17.0` moved from Planned to Shipped;
  ship-to-friend C6 checkbox ticked. **All MVP checkboxes now [x].**

---

## [v0.16.0] — 2026-05-24

C5 de-identification pipeline. Regex-based PHI redaction gates first
real-record ingest — source document chunks and embeddings now store
redacted text by default. External inference messages are also redacted
before leaving the operator's network.

### Architecture deviation
The roadmap specified a Microsoft Presidio sidecar with NER models.
This release implements regex-based de-identification in-process —
no new container, no model downloads. Covers SSN, phone, email, MRN,
dates, ZIP, and title+name patterns across three policy levels
(strict/standard/permissive). NER-based scanning can be added as a
future enhancement.

### Code
- `backend/services/deid.py` — `redact_text()` and `redact_chunks()`
  with three policy levels. 7 pattern categories in strict mode.
  `DeidResult` with typed placeholders (`[SSN]`, `[PHONE]`, etc.).
  Env: `HLH_DEID_ENABLED` (default true), `HLH_REDACTION_POLICY`
  (default strict).
- `backend/routers/sources.py` — chunks redacted before embedding
  in the ingest pipeline. Stored text and vectors encode redacted form.
- `backend/routers/chats.py` — user messages redacted before
  external (non-bundled) inference. Bundled local inference skipped
  (data stays on operator's machine).
- `backend/hlh/doctor.py` — `deid_pipeline` check (OK when enabled
  with policy + pattern count, WARN when disabled). 17 checks total.

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.16.0]`.
- `docs/roadmap.md` — `v0.16.0` moved from Planned to Shipped;
  ship-to-friend C5 checkbox ticked; active-work pointer retargeted
  to `v0.17.0` / C6.

---

## [v0.14.0] — 2026-05-23

B1 + C7 I/O guard scanner. In-process regex-based input and output
scanning on every chat inference request. No separate Docker container
— same security coverage via `services/guard.py` for a single-user
LAN deployment.

### Architecture deviation
The roadmap specified a separate `hlh_guard` Docker sidecar running
llm-guard (Protect AI). This release implements the same functional
coverage as an in-process regex scanner — no new container, no new
pip dep. The sidecar architecture can be revisited if the threat model
changes (public release, multi-user, untrusted operators).

### Code
- `backend/services/guard.py` — `scan_input()` (9 prompt-injection
  patterns + 6 banned substrings) and `scan_output()` (4 PII patterns,
  7 medical-advice patterns, 1 crisis pattern, 2 hallucinated-ID
  patterns). 29 patterns total. Crisis flags pass through (flag, don't
  block). All other categories block.
- `backend/routers/chats.py` — input scan before inference (returns
  422 `input_blocked` on hit). Output scan after response completion
  (stores `guard_flags` JSONB on flagged messages, emits `guard_alert`
  SSE event before `[DONE]`).
- `backend/schema.sql` — `guard_flags JSONB` column on `messages`.
- `backend/hlh/doctor.py` — `guard_scanners` check (OK when module
  loads, reports pattern count). 16 checks total.

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.14.0]`.
- `docs/roadmap.md` — `v0.14.0` moved from Planned to Shipped;
  ship-to-friend B1 + C7 checkboxes ticked; active-work pointer
  retargeted to `v0.15.0` / B3.

---

## [v0.13.0] — 2026-05-23

B2 UI disclaimers + crisis card. Visible safety chrome so the user
is never confused about whether the AI's output is medical advice.

### Code
- `backend/schema.sql` — `ai_generated BOOLEAN` column on `messages`
  (default FALSE; set TRUE on assistant inserts, FALSE on user inserts,
  propagated on fork).
- `backend/routers/chats.py` — three INSERT sites updated to include
  `ai_generated`.

### Frontend
- `DisclaimerBanner.jsx` — persistent "Educational only. Not medical
  advice." banner at the top of every active chat view.
- `CrisisCard.jsx` — visually distinct card with 988, Poison Control,
  and 911 hotline numbers. Appears below any assistant message whose
  content matches crisis keywords (suicide, self-harm, overdose, etc.).
  US defaults hardcoded; locale configurability deferred.
- `MessageBubble.jsx` — "AI-generated" badge on assistant messages,
  "Not medical advice" footnote at the bottom of every assistant bubble.
- `ChatView.jsx` — integrates `DisclaimerBanner`.
- `MessageList.jsx` — integrates `CrisisCard` via Virtuoso's
  `itemContent` callback (conditional on `detectCrisis()`).

### Docs
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.13.0]`.
- `docs/roadmap.md` — `v0.13.0` moved from Planned to Shipped;
  ship-to-friend B2 checkbox ticked; active-work pointer retargeted
  to `v0.14.0` / B1+C7.

---

## [v0.12.0] — 2026-05-23

C3 synthetic data + log scrubbing. Defense-in-depth PHI redaction on
all Python log output, sanitized exception responses, browser cache
prevention on API responses, frontend route audit, and Synthea test
fixtures.

### Code
- `backend/services/log_redactor.py` — `PHIRedactorFilter(logging.Filter)`
  scrubbing SSN, phone, email, MRN, DOB, and credit card patterns from
  log records. Installed on root logger at startup via `install_redactor()`.
  Known gap: `record.exc_info` tracebacks are not scrubbed (defense-in-depth,
  not perfection — no current handlers embed PHI in exception messages).
- `backend/main.py` — global `@app.exception_handler(Exception)` returns
  `{"error": "internal_error", "request_id": <uuid>}` to client; scrubbed
  trace to server log only. `_NoCacheAPIMiddleware` sets `Cache-Control:
  no-store` on all `/api/*` responses.

### Docs
- `frontend/src/routes/paths.js` — one-line route audit comment confirming
  all paths are UUID-keyed (no PHI in URLs). Verified 2026-05-23.
- `tests/fixtures/synthea/` — two synthetic FHIR R4 Patient bundles
  (`patient_jane_doe.json`, `patient_john_smith.json`) for future C5
  de-id pipeline verification.
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.12.0]`; fresh empty
  `[Unreleased]` section restored.
- `docs/roadmap.md` — `v0.12.0` moved from Planned to Shipped;
  ship-to-friend C3 checkbox ticked; active-work pointer retargeted
  to `v0.13.0` / B2.

---

## [v0.11.0] — 2026-05-23

C4 audit logging. Append-only hash-chained `audit_log` table recording
every PHI-touching API request. Insert-only Postgres role, write-ahead
dependency on every PHI endpoint, hash-chain tamper detection, retention
CLI, and a doctor check for chain integrity.

### Code
- `backend/schema.sql` — `audit_log` table (BIGSERIAL PK, hash chain
  with `prev_hash` / `row_hash`), `audit_log_chain_head` singleton
  (chain head + post-prune anchor), `hlh_audit_writer` insert-only role.
- `backend/services/audit.py` — `AuditRecord` dataclass, chain-hash
  primitives (`_canonicalize`, `_compute_row_hash`), `insert_audit_event`
  (serialized via `SELECT ... FOR UPDATE` on chain head, `SET LOCAL ROLE
  hlh_audit_writer`), `verify_chain` (anchor-aware, backwards compatible),
  `AuditEventHandle` FastAPI dependency, `audit_event` yield-based
  dependency with fault-tolerant post-yield commit.
- `backend/main.py` — `_RequestIDMiddleware` generates UUID per request,
  surfaces `X-Request-ID` header, captures response status code for
  audit commit.
- `backend/routers/audit.py` — `GET /api/audit/recent` (paginated,
  excludes hash columns, self-auditing).
- `backend/routers/*` — 18 routers wrapped with `Depends(audit_event)` +
  `audit.targeting(...)` on every PHI-touching endpoint. Streaming
  endpoints use direct attribute assignment.
- `backend/hlh/doctor.py` — new `_check_audit_log_chain` (ERROR on chain
  break; reads `first_anchor_hash` for post-prune correctness). 15 checks
  total.
- `backend/hlh/audit_retention.py` — CLI (`python -m hlh.audit_retention`)
  with `--dry-run`, positive-integer validation, distinct error messages,
  atomic prune + anchor advance.
- `backend/scripts/verify_audit_log.sh` — insert/tamper/restore/verify
  roundtrip against the live stack.

### Docs
- `docs/operator/advanced/audit-retention.md` — opt-in retention setup,
  cron example, post-prune chain anchor explanation, recovery cross-ref.
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.11.0]`; fresh empty
  `[Unreleased]` section restored.
- `docs/roadmap.md` — `v0.11.0` moved from Planned to Shipped;
  ship-to-friend C4 checkbox ticked; active-work pointer retargeted
  to `v0.12.0` / C3.

---

## [v0.10.1] — 2026-05-23

C1 demoted to advanced/optional per MVP-scope review. Friend deployment
is on LAN behind Authelia — disk encryption and backup discipline are
operator-prudence, not friend-deployment blockers. No code path
behavior changes for operators who didn't set the env vars; doctor now
WARNs (not ERRORs) on missing LUKS / backrest / master-key state.

### Code
- `backend/hlh/doctor.py` — three checks (`luks_status`, `backrest_repo`,
  `master_key`) downgraded to never return ERROR. All previous ERROR
  paths are now WARN. Doctor message paths updated to point at the new
  `docs/operator/advanced/` location.

### Docs
- `docs/operator/key-custody.md` → `docs/operator/advanced/key-custody.md`
- `docs/operator/restore-drill.md` → `docs/operator/advanced/restore-drill.md`
- `docs/operator/luks-setup.md` → `docs/operator/advanced/luks-setup.md`
- Internal cross-references updated to the new paths.
- `.gitignore` — extended `docs/operator/*` + `!docs/operator/*.md` pattern
  one level deeper for `docs/operator/advanced/*.md`.
- `docs/roadmap.md` — C1 deep section updated: removed "pending v0.10.1
  demotion" annotation (now shipped). Latest release callout retargeted
  to v0.10.1.

---

## [v0.10.0] — 2026-05-22

C1 disk + backup hygiene foundation. Three new pre-flight checks plus
three operator docs. No schema, no compose, no UI changes.

### Code
- `backend/hlh/doctor.py` — three additive checks registered in
  `run_checks()`:
  - `luks_status` — best-effort LUKS detection on the docker data
    root. From inside the api container subprocess calls usually fall
    through to a WARN "unverifiable" state; the check returns OK or
    "not on LUKS" WARN when host visibility is available.
  - `backrest_repo` — reads `BACKREST_REPO_PASSWORD` env then
    `/run/secrets/backrest_password` as fallback. Placeholder set
    rejection (`changeme`, `example`, etc.) and 16-char length floor.
  - `master_key` — reads `HLH_MASTER_KEY` env. Same placeholder set,
    32-char floor. Returns WARN-on-unset (not ERROR) since C6
    consumes the value at v0.18.0.
  No secret value ever appears in `detail` output (length and
  placeholder match only).

### Docs
- `docs/operator/key-custody.md` — per-host key generation rules and
  copy-pasteable commands for `HLH_MASTER_KEY` and the backrest
  passphrase. Explicit "generate on your host, not the maintainer's"
  guidance per C6 threat model.
- `docs/operator/restore-drill.md` — backrest restore verification
  walkthrough. Verification, not initial setup.
- `docs/operator/luks-setup.md` — one-time LUKS-on-data-volume
  guide. Includes `cryptsetup luksFormat`, `/etc/crypttab`, and
  auto-mount setup.
- `.gitignore` — extended `docs/*` + `!docs/*.md` pattern to also
  permit `docs/operator/*.md`.
- `CHANGELOG.md` — `[Unreleased]` flipped to `[v0.10.0]`; fresh empty
  `[Unreleased]` section restored.
- `docs/roadmap.md` — `v0.10.0` moved from Planned to Shipped;
  ship-to-friend C1 checkbox ticked; phase-track-summary updated;
  active-work pointer retargeted to `v0.11.0` / C8.

---

## [v0.9.0] — 2026-05-22

Security + threat-model docs foundation. No code path changes.

### Docs
- `SECURITY.md` added — posture statement, reporting instructions, in/out-of-scope items,
  and links to related documents.
- `THREATMODEL.md` added — trust boundaries, specific defenses with file and script citations,
  open gaps, and out-of-scope items.
- `docs/safe-harbor.md` added — disclaimer explaining what this project does and does not
  authorize with respect to security research.
- `docs/breach-response.md` added — operator playbook for isolating the host, snapshotting
  evidence, rotating secrets, notifying affected parties, and recovering.
- `README.md` — new `## Security posture` section inserted between `## Stack` and
  `## License`, summarizing defenses, open gaps, and linking to the four new docs.
- `CHANGELOG.md` — `[Unreleased]` stub renamed to `[v0.9.0]`; fresh empty `[Unreleased]`
  section added above it.
- `docs/roadmap.md` — active-work callout retargeted to `v0.10.0`; `v0.9.0` moved from
  planned to shipped; C0 ship-to-friend gate ticked; AGPL-3.0 references on lines 26 and 678
  corrected to MIT.

---

## [v0.8.1] — 2026-05-22

Docs + tooling polish on top of `v0.8.0`. No code path changes.

### Docs
- `CHANGELOG.md` added covering every tag from
  `snapshot/pre-phase-4-merge` (2026-04-22) forward.
- Tag history re-normalized: `1.x` (inherited from boolab) renumbered
  to `v0.2.0` / `v0.3.0`; debugging snapshots moved to `snapshot/`
  namespace; four merges that shipped untagged (B0 safeguards,
  personas removal, Phase 2.A, bundled-tail) now have proper
  `v0.5.0` / `v0.6.0` / `v0.7.0` / `v0.8.0` tags. `snapshot/genesis`
  added at the repo root.
- Convention documented in `CLAUDE.md` (local, gitignored):
  `[Unreleased]` at the top, rename on tag, group by track when
  >5 items.
- Roadmap tag references updated throughout. Three stale spots fixed
  (A2 network posture, C1 doctor checks claim, ship-to-friend A7
  note).

### Tooling
- `verify_tier_change_rewrite.sh` brought current with the new
  cpu-min (`Qwen3.5-0.8B-Q8_0.gguf`) + cpu-std
  (`medgemma-1.5-4b-it-Q4_K_M.gguf`) filenames.

---

## [v0.8.0] — 2026-05-22

**A1.5 hardening + A1.7 operator pre-flight + Phase 2.B embed/rerank
visibility.** Bundled-tail branch merged via `e612da7`.

### AI / bundled inference (A1.5)
- Pinned image tags: `ghcr.io/ggml-org/llama.cpp:server-b9282`,
  `searxng/searxng:2026.5.22-c57f772ad`.
- Container hardening across all six services: `read_only`,
  `cap_drop:[ALL]`, `no-new-privileges`, `tmpfs`, per-service
  `mem_limit` (chat tier-keyed via `HLH_CHAT_MEM`; infer 4g).
  Postgres + nginx + chat needed minimal `cap_add` workarounds
  documented in compose.
- New `hlh_inference` network with `internal: true`. Chat moves to
  inference-only; infer joins both for HF egress (defense-in-depth
  via container hardening).
- `model_puller` gains disk pre-flight (`5 GB headroom` guard) and
  `ModelSpec.revision` plumbed through `_hf_url`.
- `bundled_models.revision` column.

### A1.7 — Operator pre-flight + first-launch ack
- `python -m hlh.doctor` CLI runs 11 health checks (DB, schema,
  sidecars, safeguard-version import, disk free, encryption key,
  HF token). Exits 0 green / 1 red.
- `GET /api/system/doctor` returns the same as JSON.
- SystemTab gains a Pre-flight expandable section with colored
  per-check badges + refresh button.
- First-launch acknowledgement modal mounted globally — required
  "I understand" checkbox stamps `system_profile.acknowledged_at`.
  Optional-search bullet renders only when `hlh_search` reports
  healthy.

### Phase 2.B — Embed + rerank visibility
- Models panel synthesizes 2 extra rows from the bundled
  embed/rerank provider records (no puller rewrite). Status derived
  from `providers.last_verified_status`. Polling cap 60 × 5s = 5 min
  before flipping to error. No Pull button (sidecar-managed).

### Tooling
- `verify_a1_5_hardening.sh` + `verify_a1_7_doctor.sh` — both
  `ALL CHECKS PASSED` on merge.

### Docs
- Roadmap reconciled (3 passes); ship-to-friend checkboxes ticked
  for A1, A1.5, A1.6, A1.7, A2, A7, B0, C2. Trunk-merge gates
  retired; all remaining gates apply to non-Sam access only.
- README gains `make doctor` note.

---

## [v0.7.0] — 2026-05-22

**Phase 2.A: "bundled-system takes everything".** Merged via
`994c7e7`. System tier fully determines chat + embed + rerank — no
user-facing model pickers.

### AI / bundled inference
- Three immutable bundled provider rows (chat / embed / rerank),
  grouped under `bundle_group='homelab-health-ai'`. Server-side 403
  on PATCH/DELETE.
- New `hlh_infer` sidecar (`michaelf34/infinity:0.0.77-cpu`) serves
  both `/v1/embeddings` (`BAAI/bge-m3`, 1024-dim) and `/v1/rerank`
  (`BAAI/bge-reranker-v2-m3`) from one process. Embed engine
  `optimum` (ONNX); rerank engine `torch` (no ONNX exports exist
  for bge-reranker-v2-m3). `INFINITY_URL_PREFIX=/v1` aligns paths
  with existing call sites.
- `apply_bundled_bindings(conn, tier)` helper rewrites global
  embed/rerank + every bundled-chat-bound workspace's `model` on
  every lifespan boot AND tier-save. Override-on-bundled is reset
  on tier change.
- HF token moved from `.env` to a DB-backed encrypted singleton
  (`hf_token_config`). GET/PUT/DELETE `/api/system/hf-token`
  endpoints. Model puller resolves DB token first, falls back to env.

### A1.6 — Workspace auto-bind + Settings lockdown
- Policy reversal from the original roadmap. New workspaces
  auto-bind to bundled chat. Settings → Providers / Embedding /
  Reranker tabs removed entirely. WorkspaceDetailPage chat-provider
  override flow removed. Sensible defaults, no foot-guns.

### A7 — Bundled search
- `hlh_search` sidecar (SearXNG) added to the `bundled` compose
  profile. `searxng/settings.yml` bind-mounted with JSON format
  enabled. `SEARXNG_URL=http://hlh_search:8080` overrides `.env`
  from compose. Internal port 8080; host port 9612 bound to
  `0.0.0.0` (user-agnostic). `searxng_config` table seeded with
  sensible engine defaults.

### UX
- Dark mode toggle (sun / system / moon) in the sidebar. CSS palette
  already locked at 2026-05-03; this activates the runtime toggle
  via Zustand + localStorage + `matchMedia` listener.
- Typography settings actually apply now (`applyWorkspaceLayoutToDom`
  reads the store, not the deprecated localStorage key). Defaults
  bumped to 21 / 20 / 21 / 20 / 24 / 19; clamp ceiling 24 → 32.

### Model choices locked
- cpu-min → `unsloth/Qwen3.5-0.8B-MTP-GGUF` (`Qwen3.5-0.8B-Q8_0.gguf`,
  Apache-2.0, no token needed, ~0.85 GB).
- cpu-std + gpu-8gb → `unsloth/medgemma-1.5-4b-it-GGUF`.
- gpu-16gb + gpu-24gb+ → `unsloth/medgemma-27b-it-GGUF`.

### Tooling
- `verify_hf_token.sh`, `verify_bundled_immutability.sh`,
  `verify_tier_change_rewrite.sh` — three new verify scripts.

### Security
- Provider immutability defense-in-depth: bundled rows reject
  PATCH/DELETE with HTTP 403 + mandated spec-string detail. UI hides
  controls; backend enforces.

---

## [v0.6.0] — 2026-05-22

**B0 safeguards baseline.** Merged via `adba194`. Tiered-refusal
system prompt prepended to every assistant turn.

- `services/safeguards.py` exposes `SAFEGUARD_VERSION` +
  `prepend_safeguard()`. Prompt is locked into `routers/chats.py`
  via `_assembled_system_prompt`; cannot be overridden by workspace
  prompts.
- `messages.safeguard_version` records which version was active at
  send time so policy drift is auditable. Forks copy the version
  verbatim.
- Two verify scripts: `verify_safeguards_assembler.py` (chokepoint
  enforcement) + `verify_safeguards_persistence.py` (DB write).

B1 (output scanner sidecar), B2 (UI disclaimers + crisis card),
B3 (audit-logged refusals), B4 (red-team eval) all still open.

---

## [v0.5.0] — 2026-05-22

**Personas removed.** Merged via `3a5b760`.

- Personas table dropped (one-time destructive migration in
  `schema.sql`, idempotent on re-applies).
- System-prompt assembly simplified — `_assembled_system_prompt`
  no longer touches persona columns.
- Persona UI surfaces removed from workspaces + chats.

---

## [snapshot/pre-personas-removal] — 2026-05-22

Reference tag taken right before personas were removed. Last commit:
`docs: unify AI/safeguards/security roadmap; restructure docs/`. Use
for forensic comparison if personas-removal needs to be revisited.

Was named `pre-personas-removal` before the 2026-05-22 retag pass.

---

## [snapshot/pre-safeguards] — 2026-05-22

Reference tag: A1 (chat sidecar) shipped to `main` ahead of B0
safeguards. Tag exists as the recoverable "no-safeguards" baseline
so any future safeguards-regression can compare against it.

Was named `pre-safeguards-baseline` before the 2026-05-22 retag pass.

---

## [v0.4.0] — 2026-05-22

**Phase 1: bundled chat sidecar + model puller.** First bundled-AI
release. Was originally tagged `v0.1.0-phase-1`; renumbered to
`v0.4.0` to fit the semver track.

- New `hlh_chat` sidecar (`ghcr.io/ggml-org/llama.cpp:server`, port
  9610) reads model weights from the shared `hlh_models` volume.
- `services/model_puller.py` — httpx streaming pulls from HF with
  single asyncio lock, `.partial → fsync → rename`, gated-repo 401
  surfacing.
- `bundled_models` table tracks role / tier / model / status /
  progress / license.
- `services/bundled_providers.py` — idempotent upsert of the
  `bundled-chat` provider row; no-op on `external` tier or
  `setup_complete=false`.
- `routers/models.py` — five admin endpoints
  (list / get / pull / pull-for-tier / cancel).
- SystemTab gains the Models sub-panel, MedGemma tier labels, and
  the external-tier advanced toggle.
- Auto-seed of the bundled-chat provider on tier confirm.
- 393 assertions across 13 verify scripts (including the E2E chat
  round-trip).

Known gaps recorded for A1.5 follow-up (shipped in `v0.8.0`):
no internal network, no container hardening, unpinned `:server`
tag, no sha256 in MODEL_REGISTRY, no disk pre-flight, MedGemma
filename placeholders, no delete guard on bundled-chat.

---

## [v0.3.0] — 2026-05-21

**Phase 0: bundled-AI hardware detection + tier picker.** Was
originally tagged `v1.11.0` (inherited boolab numbering); renumbered
to `v0.3.0`.

- `system_profile` table (singleton).
- `services/sysinfo.py` — hardware detection + tier recommendation
  (cpu-min / cpu-std / gpu-8gb / gpu-16gb / gpu-24gb+ / apple-mlx
  / external).
- `routers/system.py` — `GET /hardware`, `GET/PUT /profile`,
  `POST /redetect`.
- SystemTab UI with tier cards and the setup-complete gate that
  locks the rest of the app until a tier is confirmed.
- E2E + regression precondition tests for gated routes.

Every later AI phase keys off `system_profile.tier`.

---

## [v0.2.0] — 2026-05-21

**Providers and API keys.** First multi-provider release. Was
originally tagged `v1.10.0` (inherited boolab numbering); renumbered
to `v0.2.0`.

- New `providers` table (shared list of OpenAI-compatible
  endpoints). Optional encrypted `api_key` via new
  `services/crypto.py` (Fernet with `PROVIDER_KEY_ENCRYPTION_KEY`;
  cleartext fallback when unset).
- `routers/providers.py` — CRUD + connection-test + 409 on in-use
  delete with force-delete cascade.
- `workspaces.provider_id` per-workspace binding.
- `global_settings.embedding_provider_id / embedding_model` and
  `reranker_provider_id / reranker_model` for the two global
  pickers.
- Shared `provider_client.py` resolver collapses six previously
  env-var-driven inference call sites into one auth-aware path.
  The five env vars (`OPENAI_API_KEY`, `INFERENCE_URL`,
  `EMBEDDING_URL`, `RERANKER_URL`, `DEFAULT_MODEL`) become
  deprecated; startup warns if any are still set.
- Frontend: Providers CRUD tab, Embedding + Reranker picker tabs,
  per-workspace provider+model picker.
- Pre-merge: env var rename `BOOLAB_*` → `HLH_*`; postgres user/db
  rename `boolab` → `hlh`; schema rewrite to post-rename shape;
  pgvector extension creation order fixed for fresh-init.

---

## [v0.1.1] — 2026-05-02

**Compose isolated from boolab.** Was originally tagged
`pass-4-lite`; renumbered to `v0.1.1` to fit the semver track.

- Isolated `docker-compose.yml` from the legacy boolab project
  (separate network, separate container names, separate volume
  namespace).
- Phantom chromadb dep + stale comment removed.

---

## [v0.1.0] — 2026-05-02

**Big strip pass: fork from boolab → homelabhealth identity.** Was
originally tagged `pass-3-complete`; renumbered to `v0.1.0` as the
first proper homelabhealth release.

- Removed auth + multi-mode UI.
- Renamed `daws → workspaces`, `daw_id → workspace_id`.
- Hardcoded the HomeLab Health branding + healthcare palette.
- Rewrote `schema.sql` to the post-rename shape.
- Rewrote the docs.

---

## [snapshot/pre-strip] — 2026-04-27

Snapshot taken right before the strip pass. One late addition before
the tag: `schema: add generation status/seq + message_tokens for
persistent streaming`.

Was named `pre-strip-snapshot` before the 2026-05-22 retag pass.

---

## [snapshot/pre-phase-4-merge] — 2026-04-22

Captures the boolab state before the phase-4 merge that eventually
became homelabhealth.

Was named `pre-phase-4-merge` before the 2026-05-22 retag pass.

---

## [snapshot/genesis] — 2026-03-22

**Root commit of the repo** (`62063e7` — "Phase 0 complete: skeleton,
docker, schema, mode detection"). Marks the boolab/boocode origin
point. Between this and `snapshot/pre-strip` (2026-04-27) is one
month of pre-homelabhealth history — 92 commits in total.

Highlights from that window:

- `62063e7` Phase 0 — initial skeleton, docker, schema, mode
  detection (root).
- `bc561ed` Phase 1 — BooOps core chat, streaming, model switcher
  (same day).
- `8efc758` feat: auth + user tiers (later stripped in `v0.1.0`).
- `22034c8` feat: global personas + drop mode column (later removed
  in `v0.5.0`).
- `8673cf2` feat: branding asset seeding.
- A long tail of boocode terminal fixes (xterm, PTY width, scroll
  containment, glyph rendering) before the strip-down to
  homelabhealth.

These commits remain reachable via `git log` but are not part of
any release. `snapshot/pre-strip` is the other bookend of this
window — the last commit before the strip pass that produced
`v0.1.0`.
