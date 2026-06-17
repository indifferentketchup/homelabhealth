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

## [v1.3.2] — 2026-06-17

Production-readiness audit remediation (2026-06-15).

### AI

- **Combined inference front-door `hlh_swap`** (openspec change
  `boofinity-inference-frontdoor`, 2026-06-16). A single container whose
  entrypoint is llama-swap (v226) becomes the only bundled inference endpoint
  (`hlh_swap:9620`, internal `hlh_inference` network). Its config forks
  `llama-server` (chat / tasks / mmproj: `medgemma`, `qwen-chat`, `gemma-tasks`)
  and `boofinity` (embed / rerank / VL: `qwen3-embed`, `qwen3-reranker`,
  `qwen3-vl-embed`, `qwen3-vl-rerank`) as child PROCESSES, arbitrated by a
  swap-exclusive `vram_constrained` group so the two GPU-competing children are
  never both VRAM-resident. No Docker socket, no sibling-container lifecycle.
  Replaces the standalone `hlh_chat` and `hlh_infer` services. The boofinity
  child's API path is set with the CLI flag `--url-prefix /v1` (no `INFINITY_*`
  env var). `hlh_chat/models.ini` drops the embed / reranker presets (now served
  by boofinity); chat/tasks/mmproj presets stay. The provider rebind from
  `hlh_chat:9610` to `hlh_swap:9620` is folder C and must deploy together with
  this change.
- **boofinity model pulls + front-door rebind** (openspec change
  `boofinity-model-pulls-rebind`, folder C, 2026-06-16). The bundled text embed +
  rerank are now served by the boofinity child from HF safetensors repos, not
  flat llama.cpp GGUFs. `model_puller` gains a `kind="snapshot"` ModelSpec
  variant and a `huggingface_hub.snapshot_download` path that writes the standard
  HF hub cache layout into the `hlh_infer_cache` volume (`/cache/hub`, read by
  boofinity via `HF_HOME=/cache`); `_EMBED_SPEC` / `_RERANK_SPEC` flip to
  `Qwen/Qwen3-Embedding-0.6B` / `Qwen/Qwen3-Reranker-0.6B` (seed_registry prunes
  the retired GGUF rows). All three bundled providers (chat / embed / rerank)
  rebind from `hlh_chat:9610` to the front-door `hlh_swap:9620`. The
  GGUF->safetensors switch makes stored vectors non-comparable, so a one-shot
  idempotent reingest fires on the first boot where the embed backend probes
  ready (`services/embed_cutover.py`, guarded by a `global_settings` sentinel),
  with a "retrieval is rebuilding after a model change" banner surfaced via
  `/api/system/profile` and cleared by an ingest completion hook. `bootstrap.py`
  gains `ensure_infer_cache_ownership()`; `hlh_api` mounts `hlh_infer_cache:/cache`;
  doctor gains `_check_infer_cache_writable`. Deploy with or after folder B.
- **Tier-aware resource policy** (`services/resource_policy.py`, new): pure data
  encoding per-tier child coexistence and Gemma degradation under VRAM pressure
  (`gpu-4gb` -> unavailable; `cpu-*` / `apple-mlx` / `gpu-8gb` / `gpu-16gb` ->
  offload-CPU; `gpu-24gb+` -> resident, non-exclusive). `pipeline_status.py`
  gains a `swapping` stage and an `infer_backend_state()` helper that maps the
  front-door `/v1/models` status to loaded / swapping / unavailable.

### Tooling

- **`HLH_INFER_DTYPE` default is `float32`** (Pascal-safe), seeded by
  `image_config.write_tier_env` on every tier. Known limitation: float32 doubles
  VRAM versus bf16 on GPUs that support bf16, so Ampere+ operators should set
  `HLH_INFER_DTYPE=bfloat16` in `.env`. `image_config.py` collapses the old
  `HLH_CHAT_IMAGE` / `HLH_INFER_IMAGE` pair into the single combined
  `HLH_SWAP_IMAGE`, adds tier-scaled `HLH_INFER_MEM`, and the `TierImages`
  `chat_image` / `infer_image` fields collapse into `swap_image` + `infer_mem`.
- **`doctor.py` swap checks**: `hlh_swap` reachability, a boofinity-child
  `/v1/health` probe through the front-door, `HLH_SWAP_IMAGE` tier match, a
  swap-group-policy comparison, and a rebind-consistency ERROR when a bundled
  embed/rerank provider still points at `hlh_chat:9610` after `models.ini` drops
  the matching section. `verify_a1_5_hardening.sh` rewritten for the single
  `hlh_swap` service with a tier-scaled mem assertion and a no-docker-socket
  check.

### Infrastructure

- **Embedding/rerank image moved to the `boofinity` fork** (openspec change
  `boofinity-image-pipeline`, 2026-06-16). `services/image_config.py` now pins
  `BOOFINITY_VERSION = "0.1.0"` and rewrites every `TIER_IMAGE_MAP` `infer_image`
  from the upstream `michaelf34/infinity` image to
  `ghcr.io/indifferentketchup/boofinity:0.1.0-{cpu,cuda}` (cpu/apple-mlx/external
  tiers take `-cpu`; all `gpu-*` tiers take `-cuda`). `INFINITY_VERSION` is removed.
  The boofinity fork carries the VL / `causal_lm` model classes and the
  `/v1/mm_embeddings` and `/v1/mm_rerank` routes the bundled GPU stack will use.
  The publish workflow and GHCR push live in the separate
  `indifferentketchup/boofinity` repo and are an operator step.
- **llama.cpp pin bumped `b9628` -> `b9660`** (continues `9b5655b`). The
  `{LLAMA_CPP_VERSION}` interpolation in `image_config.py` flows the bump into both
  `chat_image` tags; `.env.example` (`HLH_CHAT_IMAGE` / `HLH_INFER_IMAGE` comments)
  and `hlh_orchestra/bootstrap.py` (`CHAT_IMAGE_CPU` / `CHAT_IMAGE_GPU` defaults,
  `server-b9660` / `server-cuda-b9660`) updated to match. `pull_image` keeps its
  always-pull behavior.
- **`LLAMA_SWAP_VERSION = "v226"` added** to `image_config.py` as a module constant
  for downstream folders to import; no service wiring is added in this change.
- **Stale `vision` compose-profile token dropped** from `TIER_IMAGE_MAP['gpu-24gb+']`
  (`bundled-gpu,vision` -> `bundled-gpu`). No `vision`-profile service exists in
  `docker-compose.yml` (MedGemma vision is the chat model + mmproj, not a service).
  The `write_tier_env` "preserve operator-added `vision`" branch is left intact and
  no-ops once the seed drops the token.
- **Additive dual-space VL retrieval** (openspec change `dual-space-vl-retrieval`,
  folder D, 2026-06-16). `gpu-24gb+` only; every lesser tier is unchanged.
  A new `source_image_embeddings vector(1024)` table (separate from `source_chunks`;
  text/VL spaces are not cosine-comparable, see ADR 0003) stores native image vectors
  from `Qwen3-VL-Embedding-2B`. At ingest, `sources.py` runs a second VL pass after
  the text path commits: `vision.py:embed_image_vl` POSTs to boofinity
  `/v1/mm_embeddings` (`qwen3-vl-embed`, 1024 matryoshka prefix), inserting one row
  per image or PDF page; failure-isolated so a VL failure never flips
  `embedding_status` to error. At query time, `rag.py:_maybe_dual_space_rerank`
  embeds the query into the VL space, ANN-searches `source_image_embeddings`, fuses
  image + text candidates with RRF (k=60), then orders the union with the Qwen3-VL
  reranker (`/v1/mm_rerank`); on VL-rerank failure falls back to RRF order; on any
  gate failure falls back to the text-only path unchanged. Provider rows `embed-vl`
  / `rerank-vl` seeded by `bundled_providers.ensure_bundled_providers` on `gpu-24gb+`
  only; `model_puller.MODEL_REGISTRY` carries `Qwen3-VL-Embedding-2B` /
  `Qwen3-VL-Reranker-2B` as `kind="snapshot"` specs gated to `gpu-24gb+`. FK
  `ON DELETE CASCADE` keeps VL vectors reachable and deletable only via the source
  row (same PHI scoping as `source_chunks`). `verify_dual_space_retrieval.sh` SKIPs
  automatically on non-gpu-24gb+ hosts.

### Safeguards

- **`services/safeguards_engine.py` trimmed 1129 → 257 lines** (openspec change
  `trim-safeguards-engine`). The ported generic guideline framework (CRUD
  `GuidelineStore`, `RelationshipStore`, five batch classes, `Matcher`, and the
  iterative `Resolver` with its 100-step convergence loop) is replaced by a flat list
  of the five fixed rules plus one `_resolve()` function. Behavior is held identical:
  a new `scripts/verify_safeguards_engine_equiv.py` pins matched rules, the
  full-prompt-vs-directive output, and approval-gating across eight probe queries
  against a pre-change baseline. No change to `safeguards.py`, the prompt text, or
  `SAFEGUARD_VERSION` (the rewrite is output-identical, so a version bump would falsely
  signal a behavior change). Removed code paths confirmed dead first: four of five
  batch classes never fired, the relationship graph and `GuidelineStore` CRUD had no
  callers after seeding, and the ENTAILS edge was inert under the resolver ordering.
  This supersedes the earlier `[Unreleased]` note about the response-analysis
  `was_followed` limitation, whose `ResponseAnalysisBatch` no longer exists.

- **Retrieval and web-search degradation now warn the user** (committee review
  2026-06-15). `rag.retrieve_context` and `searx_search_sources` return an explicit
  `degraded` flag distinguishing a hard failure (query-embed error, vector-query
  exception, SearXNG outage) from a legitimate empty result. `chats.py` emits a
  non-fatal `{"type": "warning"}` SSE event on degradation, and the frontend now
  renders it: `useStream.js` gained an `onWarning` callback (previously absent, so
  even the existing model-warm-up warning was silently dropped),
  `useStreamOrchestrator.js` collects warnings, and `ChatView.jsx` shows an inline
  notice. Previously an embedding/retrieval/search failure produced an ungrounded
  answer with no signal to the user.
- **`model_is_loaded` probe failures are now logged** (`services/pipeline_status.py`).
  Transport/HTTP errors to `hlh_chat` are caught distinctly and logged instead of
  silently swallowed, so a down or hung inference router is diagnosable rather than
  surfacing only as a "model not loaded" warmup retry.
- **`pipeline_status` estimate-update failures now log with `exc_info`** for
  traceable diagnosis instead of a bare one-line warning.
- **Source-ingest error-status write failures are now logged** (`routers/sources.py`
  ingest failure handler): the inner `except Exception: pass` after the
  `UPDATE sources SET embedding_status = 'error'` write now emits
  `logger.error(...)` naming `source_id` and noting the row may be stuck in
  `'processing'`. The outer ingest `logger.exception` still records the primary
  failure; the new log surfaces stranded rows that would otherwise stay
  `'processing'` forever (committee review 2026-06-15).
- **Stored-file delete failures are now logged at warning** (`routers/sources.py`
  `_try_delete_file`): the `except OSError: pass` that swallowed real
  `unlink()` failures (permission denied, I/O error, busy) is replaced with
  `logger.warning(...)` naming the path. `missing_ok=True` still suppresses
  `FileNotFoundError`; a missing file stays silent. The function remains
  non-raising so the 200-response delete path is unchanged (committee review
  2026-06-15).
- **Startup sweep recovers stale `'processing'` sources** (`main.py` `lifespan`):
  mirrors the existing stale-`streaming` messages sweep. On every process
  start, sources stuck in `embedding_status = 'processing'` with
  `updated_at < NOW() - INTERVAL '5 minutes'` are flipped to `'error'` with
  `error_message = 'ingest interrupted: source left in processing across restart'`,
  so the user can re-ingest via the existing reingest path. Idempotent and
  startup-only (sweep_conn is the existing `async with pool.acquire()` block
  from the messages sweep, so no new connection) (committee review 2026-06-15).

### Fixes

- **Fixed an `UnboundLocalError` on the complex-query streaming path**
  (`routers/chats.py`). `_hook_start` was bound only in the non-complex `else` branch,
  but the `post_tool_execution` timing read after the block ran unconditionally; every
  successful supervisor-worker (complex) stream raised `UnboundLocalError` after the
  assistant text was already persisted, aborting the SSE stream server-side. Now bound
  before the complexity split (openspec change `trim-safeguards-engine`).
- **Removed a duplicate workspace pin control** (`WorkspaceDetailPage.jsx`). The
  "Details" section carried a draft pin toggle saved via `updateWorkspace` while a
  separate "Pin settings" section toggled the same field live via `pinWorkspace`; the
  two desynced silently. The draft toggle (and its `pinnedFlag` state) is removed,
  leaving the live "Pin settings" control as the single source of truth.

### Tooling

- **Pinned `pydantic` and `numpy` as direct dependencies** in
  `backend/requirements.txt` (previously present only transitively via
  fastapi / flashrank).
- **Repo-wide `aislop fix --safe` sweep**: removed unused imports and
  narrative/trivial comments across 67 backend + frontend files
  (comment/import removals only; verified by full `py_compile`, frontend
  `npm run build`, and an AST check that no removed import was still referenced).
- **Removed the stale `hlh_vision_embed` container** (the MedSigLIP service
  dropped in v1.2.11).

---

## [v1.3.1] — 2026-06-15

### Tooling

- **llama.cpp pin bumped b9603 → b9628** (2026-06-15). GitHub release b9637 exists
  but its GHCR `server-`/`server-cuda-` images are not published; b9628 is the
  newest build with both variants on GHCR. Updated `docker-compose.yml`,
  `.env.example`, `backend/services/image_config.py` (`LLAMA_CPP_VERSION`, which
  drives the tier-save `.env` writer), `hlh_orchestra/bootstrap.py` (CPU/GPU
  chat-image defaults), `backend/scripts/verify_dynamic_images.sh`, and
  THREATMODEL.md. Requires `hlh_api` + `hlh_orchestra` image rebuilds (both bake
  the pin) so fresh installs and the tier-save path pull b9628.

---

## [v1.3.0] — 2026-06-14

### Docs

- **Memory-store ownership map added (2026-06-14).** Wrote a read/write matrix as the module docstring of `backend/services/memory/__init__.py` documenting all four memory stores (SQLite CoreTier, pgvector `memory_entries`, `workspace_memory`, `workspace_patient_profile`): who writes each (file:line), who reads each, which are read at inference time, and the authoritative-for-X rule. Confirmed via grep that `services/memory_tools.search_memory()` is unreachable from any live inference or route path (the tool spec dicts are defined but not bound). No code or data changed.

### Refactor

- **Shared summarization module extracted (2026-06-14).** Created `backend/services/summarization.py` owning `SUMMARY_SYSTEM_PROMPT` (the richer priority-ordered prose prompt), `extract_medical_facts(text) -> list[str]` (public; was private `_extract_medical_facts` in compaction.py), `build_preserved_facts_block(facts) -> str`, and `summarize_transcript(provider, model, transcript, existing_summary=None, ...) -> str`. Both `compaction.py` and `pruning.py` now import from `services.summarization` and no longer define their own prompt, regex patterns, or facts-block construction. The fragile cross-module private import `from services.compaction import _extract_medical_facts` in `pruning.py` is removed. Trigger logic (token-percent vs. message-count), provider resolution (bundled vs. workspace), and disposal (soft `compacted_at` SET vs. hard `DELETE`) are unchanged in each module.

- **chats.py god-router decomposed (2026-06-14).** Moved groundedness background-eval helpers (`_run_groundedness_eval`, `_maybe_fire_groundedness_eval`, `_BG_EVAL_TASKS`) into `backend/services/eval_judge.py` (renamed public entry point to `maybe_fire_groundedness_eval`). Extracted all 12 pure chat-CRUD endpoints (create/list/get/patch/delete chat, web-search toggle, source-selection CRUD, export, list messages, fork) into new `backend/routers/chats_crud.py`, mounted at the same `/api/chats` prefix and `tags=["chats"]`. Streaming/inference core (`append_message`, `gen()`, `stop`, `approval-response`, `discard-stale`, `deep_research`) untouched in `chats.py`. Route set byte-identical before and after -- 17 routes total across both modules.
- **SystemTab decomposition.** Extracted 9 inline sub-components from `frontend/src/components/settings/SystemTab.jsx` (1299 lines) into a `settings/system/` subdirectory: `tierData.js` (shared TIERS array, `VISIBLE_TIERS`, `formatGpu`, `rationaleFor`), `RoleCell.jsx`, `GpuEnableCard.jsx`, `HardwareCard.jsx`, `RecommendedBadge.jsx`, `TierRadio.jsx`, `ModelsPanel.jsx` (~430 lines, the largest panel), and `PreFlightCard.jsx`. `SystemTab.jsx` reduced to 283 lines. Behavior, props, and rendering output unchanged. `useStreamOrchestrator.js` left untouched — the state machine, 11 `useState` calls, and durable/SSE interleaving make any extraction non-trivially risky; deferred.

### Tooling

- **Dead-code cleanup + C2 concurrency fix.** Deleted orphan `.pyc` files `services/__pycache__/process_pool.cpython-312.pyc` and `services/__pycache__/terminal_sweep.cpython-312.pyc` (source `.py` files removed in a prior wave). In `services/inference_job.py`: the `asyncio.create_task(schedule_extraction(...))` call now stores its task in `_background_tasks` and registers a `discard` done-callback, preventing silent GC of the wrapper coroutine under memory pressure; removed unused imports `datetime`, `timezone` (stdlib) and `build_headers` (provider_client). Removed dead `DisambiguationBatch` class from `services/safeguards_engine.py` -- zero instantiation sites inside or outside the file, no `__all__` export. `ResponseAnalysisBatch` intentionally kept (has a functional `process_async` path, intended future use).

### Security

- **PHI de-identification gate for deep research (T1-1/T1-2).** `backend/services/deep_research.py` now fetches `is_bundled` for the resolved provider immediately after workspace resolution. When external, the original query is redacted via `redact_text` before both the SearXNG web-search call (highest-risk PHI leak: query sent to Google/Bing) and all LLM helper calls (`_summarize`, `_reflect`, `_synthesize`). Reflect-generated follow-up queries are also redacted before being used as the next search query. Bundled providers are unchanged.
- **PHI de-identification gate for memory extraction (T1-1).** `backend/services/memory_extraction.py::extract_from_exchange` gains a `provider_is_bundled: bool = True` keyword parameter. When `False` and `deid_enabled()`, both `user_text` and `assistant_text` are redacted before the LLM conversation string is assembled. The `provider_is_bundled` flag is threaded from `inference_job.py` through `schedule_extraction` and `run_background_extraction` in `memory_hooks.py`.
- **Conflict-resolution skip for external providers (T1-1).** `run_background_extraction` in `backend/services/memory_hooks.py` now guards `resolve_conflicts` behind `provider_is_bundled`. When the provider is external and conflict resolution is enabled, the LLM call is skipped and `to_add, to_remove = new_facts, []` is used instead (append-only fallback). Avoids sending raw patient facts (names, diagnoses, meds, doses) to a third-party LLM. Logs at INFO when the skip fires.
- **Assembled prompt preview demoted to DEBUG (T1-3).** `_assembled_system_prompt` in `backend/routers/chats.py` now logs the ~2000-char preview at `logger.debug` instead of `logger.info`. The preview includes the patient profile injection (name, diagnoses, meds) and must not appear in default INFO-level logs.
- **Pruning summarization input now decrypts message content (T1-5).** `backend/services/pruning.py` was building the summarization transcript from raw `r['content']` (ciphertext when `HLH_MASTER_KEY` is set); only the fact-extraction path used `decrypt_column`. The main `transcript` variable now calls `decrypt_column(r['content'], str(r['id']))` so the summarizer LLM receives real text. The separate `decrypted_transcript` variable used only for fact extraction is removed; `_extract_medical_facts` now receives the already-decrypted `transcript`.
- **Memory extract endpoint decrypts message content (T1-6).** `backend/routers/memory.py::extract_memory` was appending raw encrypted `r['content']` to the LLM prompt. `decrypt_column` is now called per row before building the prompt lines. The SQL query is extended to include `id` in the outer `SELECT` (previously only `role, content`) so the row ID is available for the decrypt call.

### AI

- **Attached-source injection ported to durable streaming path (T2-1).** `backend/services/inference_job.py::run_inference_job` gains an `attached_source_ids: list[str] | None = None` parameter. When non-empty, the same attached-document injection block used in the SSE path (`routers/chats.py`) is executed: reads source file bytes, runs PDF/image extraction or plain parse, applies `redact_text` when `deid_enabled()`, and appends `[DOCUMENT: ...]` blocks to `system_blocks`. The call site in `chats.py` now passes `body.attached_source_ids`. Durable streaming and SSE paths are now behaviorally identical for attached sources.

### UX

- **lift-chat-ui (F1-F6): Chat UI lift.** Six frontend improvements shipped together: (F1) `ThinkingBlock` replaced with a shadcn `Collapsible` that auto-opens on stream start and auto-closes ~1 s after reasoning completes, showing "Thought for N s" on the trigger; user manual toggle is respected via `userOverrideRef`. (F2) Streaming RAG pill upgraded from a plain div to a `Badge` with a database icon. (F3) Conversation export: download-as-Markdown button appears in the chat header (inside the `mx-auto` wrapper, before `DisclaimerBanner`) when not streaming; `THINKING` blocks stripped with a global regex. (F4) GFM table renderer added to `makeMdComponents()` so lab tables from PDF/OCR render with borders and zebra rows. (F5) Pipeline step trace panel in `StreamStatusBar`: completed stages shown as a `Collapsible` badge list placed above (not inside) the `role="status"` live region to avoid screen-reader flood. (F6) Client-side regeneration history carousel: up to 2 prior responses navigable via `ChevronLeft`/`ChevronRight` `ButtonGroup`; history is per-mount only (no persistence). Group B (artifact side panel, needs `sheet.jsx`) and Group C (inline citations, needs `sources_used` populated on INSERT) remain deferred.

### AI

- **D1: Eval router mounted.** `backend/routers/eval.py` (`POST /api/eval/groundedness`, `/helpfulness`, `/retrieval-relevance`) was defined but not reachable (all endpoints 404'd). Added `from routers.eval import router as eval_router` import and `api.include_router(eval_router, ...)` call in `backend/main.py`. Endpoints now require admin (`Depends(require_admin)`).
- **D2: Groundedness eval service module.** New `backend/services/eval_judge.py` extracts `call_llm_as_judge`, `_parse_eval_response`, `_normalize_score`, `_build_eval_response`, `GROUNDEDNESS_SYSTEM_PROMPT`, `GROUNDEDNESS_USER_PROMPT`, and `resolve_judge_provider` from `routers/eval.py` into a reusable service layer. `eval.py` now imports from this module. `resolve_judge_provider` uses the workspace chat provider (not gemma-tasks) because the GROUNDEDNESS_SYSTEM_PROMPT is ~1,700 chars (~425 tokens), nearly exhausting the gemma-tasks 512-token context window.
- **D3: Groundedness score column.** `ALTER TABLE messages ADD COLUMN IF NOT EXISTS groundedness_score FLOAT` added to `backend/schema.sql`. Two new `global_settings` seeds: `groundedness_eval_enabled=false` (opt-in) and `groundedness_eval_sample_rate=1.0`.
- **D4: Async groundedness background task.** After assistant message INSERT in the non-durable SSE `gen()` path, `_maybe_fire_groundedness_eval` (async, awaited) gates on the feature flag and sample rate, then fires `asyncio.create_task(_run_groundedness_eval(...))`. Task references held in module-level `_BG_EVAL_TASKS` set with done-callback to prevent GC mid-flight. Soft-fails on any error (never raises into streaming response). Durable streaming path excluded by design (deferred). `_assembled_system_prompt` return signature extended from 2-tuple to 3-tuple `(assembled, sse_rag_meta, rag_block)` -- all call sites updated: `chats.py`, `services/inference_job.py`, `scripts/verify_safeguards_assembler.py`.
- **D5: ResponseAnalysisBatch stub fixed.** `safeguards_engine.py` `ResponseAnalysisBatch.process()` previously returned `was_followed=True` unconditionally (false-safety signal). Now returns `was_followed=None`. New `process_async()` method makes a real LLM judge call via `eval_judge.call_llm_as_judge`. Constructor extended to accept `user_query` and `assistant_response` kwargs (required by `PROMPT_TEMPLATE`). Class has zero call sites; not wired in this change.

- **C1: Structured patient profile store.** New `workspace_patient_profile` table (UUID PK, JSONB, `ON DELETE CASCADE`) added to `schema.sql` with idempotent `CREATE TABLE IF NOT EXISTS` and a backfill `INSERT ... ON CONFLICT DO NOTHING` for existing workspaces. New `backend/services/patient_profile.py` module exports `get_profile`, `upsert_profile`, `apply_fact_updates`, `resolve_conflicts`, and `format_profile_for_injection`. Profile is injected unconditionally into every chat system prompt (after `workspace_memory`, before the RAG `retrieve_memory_facts` block) via a new try/except block in `_assembled_system_prompt` in `routers/chats.py`. Two new schema seeds: `memory_conflict_resolution_enabled=false` and `memory_injection_token_budget=1500`. REST endpoints `GET /api/workspaces/{id}/patient-profile` and `PUT /api/workspaces/{id}/patient-profile` added to `routers/workspaces.py`.
- **C2: LLM conflict-resolution pass.** `resolve_conflicts` in `patient_profile.py` performs a vanilla LLM + JSON call (no trustcall) to supersede contradictory facts before profile upsert. Gated by `memory_conflict_resolution_enabled` global setting (default `false`). Hallucinatedction IDs in `factsToRemove` are validated against existing profile fact IDs and discarded. Falls back to append-only on any LLM/parse failure.
- **C3: asyncio debounce/dedup for background extraction.** `backend/services/memory_hooks.py` gains a module-level `_pending_extraction` dict, `schedule_extraction` (with `signal_type` keyword param -- V2 fix), and pure-Python regex functions `_detect_correction` / `_detect_reinforcement`. `run_background_extraction` gains optional `workspace_id`, `pool`, `signal_type` kwargs and writes extracted facts to `workspace_patient_profile` after `extract_from_exchange` returns (dual-write: SQLite CoreTier via `eng.manage()` in `memory_extraction.py` is unchanged). `inference_job.py` extraction block replaced with `schedule_extraction` call including signal detection. Identity-check done_callback prevents GC race on debounce replacement.
- **C4: Token-budgeted ranked injection formatter.** `format_profile_for_injection` in `patient_profile.py` renders structured fields first, then facts sorted by confidence DESC then `created_at` DESC, with a `len(text)//4` char/4 token estimator and hard truncation at budget. Returns `""` for empty or all-null profiles.
- **B1: Deep research mode.** Iterative multi-loop SearXNG research with chain-of-thought reflection and cited synthesis. New `backend/services/deep_research.py` runs up to `deep_research_max_loops` (default 3, configurable via `global_settings`) iterations of: search -> summarize -> compress (if >3000 chars) -> reflect (JSON mode with safe fallback on parse failure) -> follow-up query. Final synthesis produces an answer with inline `[Source Title]` citations. New endpoint `POST /api/chats/{id}/deep_research` (SSE, `get_principal` auth, `X-Accel-Buffering: no`). New `global_settings` seed `deep_research_max_loops=3`. Verify script: `backend/scripts/verify_deep_research.sh`.

### UX

- **B2: Compaction summary prompt upgraded.** `SUMMARY_SYSTEM_PROMPT` in `backend/services/compaction.py` now preserves content in explicit priority order: (1) unresolved questions and open issues, (2) lab values/vital signs/test results with dates, (3) medications and dosages currently active or recently changed, (4) decisions with reasoning, (5) action items and follow-up plans. "Plain prose, not bullets" constraint added. Existing PRESERVED FACTS block reference retained from G.1.

### Fixes

- **Tier-0 bug fixes (2026-06-14):** Eight precise bugs corrected. (T0-1) `_parse_eval_response` in `services/eval_judge.py` called `m.group(1)` on the bare-braces `\{.*\}` regex pattern which has no capture group; replaced with `m.group(1) if m.lastindex else m.group(0)` to avoid `IndexError` and null scores on model responses with preambles. (T0-2) asyncpg cursor read (`SELECT orchestration_cursor`) in `supervisor_worker.py` and cursor writes in both `supervisor_worker.py` and `conductor.py` used `WHERE id = $N` without `::uuid`; added `::uuid` cast to all three, preventing silent 0-row updates when `message_id` is a string. (T0-3) `_streaming_sweeper` in `main.py` had a TOCTOU: the three UPDATE statements (`to_increment`, `to_fail`, `to_exhaust`) had no `AND status = 'streaming'` guard, allowing a job that completed between the SELECT and UPDATE to have its terminal `'complete'` status overwritten with `'failed'`; added the guard to all three. (T0-4) `post_deep_research` in `routers/chats.py` was the only comparable PHI-reading endpoint without an audit event; added `audit: AuditEventHandle = Depends(audit_event)` to the signature and `async with audit.targeting("chat", chat_id): pass` in the body. (T0-5) `run_background_extraction` in `services/memory_hooks.py` held an asyncpg pool connection across the `resolve_conflicts` LLM call (up to 30 s); restructured into three phases: read settings+profile, LLM call outside connection, re-acquire for write. (T0-6) `ResponseAnalysisBatch.process_async` in `services/safeguards_engine.py` always called `resolve_judge_provider(workspace_id=None)`, making it permanently a no-op; added `workspace_id` constructor param (default `None`) and passes `self._workspace_id` to the resolver. (T0-7) `format_profile_for_injection` in `services/patient_profile.py` sorted facts by `created_at ASC` as the confidence tiebreaker; flipped to `DESC` (newest first) using a stable two-pass sort. (T0-8) `StreamStatusBar.jsx` had the completed-stages `Collapsible` outside the `role="status" aria-live="polite"` region, so screen readers no longer announced completed steps; wrapped both the Collapsible and the active-status row in a single outer `<div role="status" aria-live="polite">` and removed the duplicate role/aria-live from the inner div. Badge keys changed from `key={i}` to `key={e.phase + '-' + i}` for stability.

- **G.3: Pruning no longer re-summarizes compacted messages.** `backend/services/pruning.py` COUNT and SELECT queries now filter `AND compacted_at IS NULL`. This prevents pruning.py from including soft-deleted (compaction-processed) messages in its transcript or threshold count, which previously caused it to overwrite the compaction summary with double-counted content on any turn where both triggers fired.

### AI

- **E1: Liveness-aware retry budget for orphaned streaming rows.** `backend/schema.sql` gains two idempotent `ADD COLUMN IF NOT EXISTS` alterations: `retry_count INT NOT NULL DEFAULT 0` and `max_retries INT NOT NULL DEFAULT 3` on `messages`. The 60-second background sweeper (`_streaming_sweeper`) is now liveness-aware: it fetches stale (`> 5 min`) streaming rows and partitions them via `job_registry.has_active()`. A row whose job is still active and within budget gets `retry_count` incremented and stays `'streaming'` so the frontend auto-resume path (`useStreamOrchestrator.js`) can keep reconnecting; an active row past budget is failed and cancelled; a row with **no active job** (orphaned, the job died or the client left) is failed immediately at the 5-minute mark, matching pre-E1 behavior, instead of lingering for the full retry window. The lifespan startup sweep keeps the simpler two-branch UPDATE (after a restart the in-memory registry is empty, so prior-process rows are correctly treated as orphaned). The `messages_status_check` constraint is unchanged; `'failed'` is used throughout (not `'error'`).
- **E2: Orchestration cursor persistence for supervisor-worker and conductor.** `backend/schema.sql` gains `orchestration_cursor JSONB` (nullable, idempotent `ADD COLUMN IF NOT EXISTS`) on `messages`. `run_supervisor_worker` in `backend/services/supervisor_worker.py` accepts optional `conn`/`message_id` kwargs; writes a `{"type": "supervisor_worker", ...}` cursor after `asyncio.gather` returns (V1 fix: after all workers, not per-worker). Resume reads the cursor on entry and skips sub-questions already in `completed`; if cursor sub-questions diverge from the new decomposition, it silently falls through to a full re-gather (V2 fix: no assertion). `WaveScheduler.run` in `backend/services/conductor.py` accepts the same optional kwargs and writes a `{"type": "wave_scheduler", ...}` cursor after each wave barrier; this is currently a no-op until `run_analysis` is wired through a durable message path (V3 noted in docstring).
- **E3: Stall and doom-loop detection.** New module `backend/services/stall_detector.py` (pure stdlib functions, ported verbatim from hive): `ngram_similarity`, `is_stalled`, `fingerprint_tool_calls`, `is_tool_doom_loop`. `_answer_sub_question` in `supervisor_worker.py` accumulates responses and calls `is_stalled`; currently a no-op with single-call workers (hook in place). `WaveScheduler.run` in `conductor.py` checks `is_stalled` across the last three wave output windows and raises `RuntimeError` on stall.
- **E4: ContextHandoff extractive wave-output summary.** New module `backend/services/context_handoff.py` (pure stdlib): `extractive_summary` (first + last wave output, each truncated to 500 chars) and `format_as_input` (header block). `WaveScheduler.run` gains a `compress_context: bool = False` parameter; when `True` and accumulated results exceed 4000 chars, replaces results with an extractive summary under `"_context_summary"`. Default `False` -- no behavior change for existing callers.

- **G.1: Critical-fact pinning after summarization.** `_extract_medical_facts` helper added to `backend/services/compaction.py` (importable by pruning.py). Regex patterns extract lab values with units (HbA1c, TSH, eGFR, BP, glucose, etc.), ISO/US/written dates, diagnosis lines, and medication dosages. After LLM summarization, a `## PRESERVED FACTS` block of verbatim extracted spans is appended to `pruning_summary` in both compaction.py and pruning.py. Pruning.py decrypts message content before fact extraction so the feature works under column encryption (`HLH_MASTER_KEY`). `SUMMARY_SYSTEM_PROMPT` and the `_openai_summarize` prompt updated to reference the block.
- **G.2: Priority-aware, budget-capped head selection in compaction.** When the decrypted head exceeds `HEAD_SUMMARY_TOKEN_BUDGET` (2500, char/4 estimate, sized for a 4096-ctx summarizer), `_run_compaction` drops the lowest-weight (cheapest, lowest-signal) messages until under budget and summarizes the survivors in **chronological order** (never the last remaining message). Fact pinning (G.1) runs over the FULL head, so dropping a message never loses a lab value, date, or dose. The set of IDs marked `compacted_at = NOW()` is unchanged (the whole head is still compacted; only the summary *input* is trimmed). Prevents the summary-prompt context overflow the prior unbounded head could cause.
- **models.ini tuning (A1).** Both `hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini` updated: `[medgemma]` gains `cache-type-v = q4_0`, `flash-attn = on`, `spec-ngram-mod-n-max = 96`; `[qwen-chat]` gains `cache-type-v = q4_0`, `flash-attn = on`, `spec-type = draft-mtp` (overrides global `ngram-mod`). Removed unrecognized `spec-ngram-mod-thsh = 2` from global `[*]` section (absent from b9603 binary `--help` output). Container restart only for A1; no rebuild required.
- **Embed/rerank latency logging (A2).** `backend/services/embeddings.py:_post()` and `backend/services/rag.py:_rerank_infinity()` now emit `logger.debug` timing lines after each successful HTTP call. Silent at default INFO level; visible with `LOG_LEVEL=DEBUG`. Zero behavioral change.

### Tooling

- **Refactor: dependency inversion for prompt-assembly helpers.** Moved `_assembled_system_prompt`, `_stream_inference`, `_openai_short_chat_title`, `_first_auto_memory_sentence`, `_normalize_messages_for_inference`, and `_clean_auto_title` from `routers/chats.py` into the new service module `backend/services/prompt_assembly.py`. `services/inference_job.py` previously imported these four symbols from the router via a deferred in-function import to dodge a circular dependency (wrong direction: service importing from router); the inversion is eliminated -- `inference_job.py` now imports from the service layer at top level. `routers/chats.py`, `routers/history.py`, and `backend/scripts/verify_safeguards_assembler.py` all updated to import from the new module. `_assembled_system_prompt` retains its 3-tuple return shape and dict/Record duck-typing; `_openai_short_chat_title` gains a `user_message_text` keyword alias for the `history.py` call site. The deferred `from services.patient_profile import ...` inside `_assembled_system_prompt` is kept deferred with an explanatory comment (patient_profile pulls in asyncpg transitively; no actual cycle today but the deferred import is cheap and defensive).
- **Consolidate non-streaming LLM calls under `async_llm_call`.** `backend/services/provider_client.py::async_llm_call` is the single shared helper for all non-streaming OpenAI-compatible chat completions. Signature extended with `extra_body: dict | None = None` (merged into request payload) and docstring updated to note callers must de-identify content before calling. `routers/memory.py::extract_memory` and `routers/chats.py::_openai_short_chat_title` migrated from inline httpx blocks to the shared helper. `routers/memory.py` loses its `import httpx` and `build_headers` import (now unused). `conductor.py`, `supervisor_worker.py`, `compaction.py`, `pruning.py`, `deep_research.py`, `patient_profile.py`, and `memory_extraction.py` were already using the shared helper. Remaining raw `/v1/chat/completions` call sites kept as-is: `eval_judge.py::call_llm_as_judge` (returns structured dict, not str), `_stream_inference` and the model warm-up call in `chats.py` (streaming / fire-and-forget semantics), `routers/inference.py` streaming proxy, and `services/vision.py` (multimodal image_url message structure).

---

## [v1.2.17] — 2026-06-13

### Tooling

- **Dep pruning.** Removed dead and redundant frontend dependencies confirmed by
  grep: `ai` (Vercel SDK, never imported), `next-themes` (never imported),
  `@radix-ui/react-scroll-area`, `@radix-ui/react-tooltip` (both re-exported by
  `radix-ui` umbrella; no direct imports), `@xyflow/react` (ai-elements orphan).
  `huggingface-hub` removed from `backend/requirements.txt` (Python package was
  never imported; downloads use `httpx` directly). `embla-carousel-react` kept
  (active consumer in `components/ui/carousel.jsx`). Frontend build and backend
  startup verified clean post-removal.

### AI

- **Bundled embedder/reranker switched to Qwen3 0.6B.** `bge-m3` →
  `Qwen/Qwen3-Embedding-0.6B-GGUF` (Q8_0, still 1024-dim so the
  `vector(1024)` schema contract holds; `pooling = last` per Qwen's
  llama.cpp usage) and `bge-reranker-v2-m3` →
  `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`. Router aliases renamed
  `bge-m3`/`bge-reranker` → `qwen3-embed`/`qwen3-reranker` across
  models.ini (both copies), `bundled_providers.py`, pipeline-status
  estimate keys (old keys deleted via schema migration), model
  inventory RAM table, and frontend display strings.
  `apply_bundled_bindings` rewrites `embedding_model`/`reranker_model`
  at boot, so existing deploys pick up the new aliases automatically —
  but stored vectors are NOT comparable across embedders: run
  `POST /api/sources/reingest-all` after updating.

### Tooling

- **llama.cpp pin bumped b9282 → b9603** (2026-06-12) across
  `docker-compose.yml`, `.env.example`, `services/image_config.py`,
  `hlh_orchestra/bootstrap.py`, `verify_dynamic_images.sh`, and
  THREATMODEL.md. b9603 is the newest build with both `server-` and
  `server-cuda-` GHCR images published (b9604–b9611 released but
  images not yet on GHCR at pin time).

### Fixes

- **Approval gate now functional (A1).** The safeguard approval path had no DB
  row on `202` return, letting a second `POST /messages` bypass the 409 guard.
  Fixed by inserting an `approval_pending` sentinel row before returning,
  widening the 409 guard to `status IN ('streaming', 'approval_pending')`,
  adding `approval_pending` to the `messages_status_check` constraint
  (idempotent `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`), and adding a
  frontend branch in `useDurableChat.sendMessage` that polls the sentinel row.
- **Source-selection `position` column (A2).** `PUT /api/chats/{id}/sources`
  was failing 100% of the time with a NOT NULL violation. Fixed by enumerating
  `body.source_ids` and passing the ordinal as the `position` parameter.
- **Provider bypass removed from compaction and vision (A3).** `compaction.py`
  and `vision.py` hardcoded `http://hlh_chat:9610`, bypassing the provider
  abstraction layer. Both now call `resolve_bundled_chat_provider()` added to
  `services/provider_client.py`. Returns `None` gracefully on external tier or
  unconfigured state.
- **BM25 partitioned to non-priority sources (A4).** Priority (attached)
  sources were being filtered through the workspace-wide BM25 prefilter,
  silently dropping their chunks from retrieval. `services/rag.py` now
  partitions `source_ids` into priority and non-priority sets; BM25 runs only
  on `non_priority_ids`. The priority query is unconditional with no BM25 gate.
- **Flush failure surfacing + startup sweep (A6).** Persistent DB flush
  failures in `inference_job.py` were silently swallowed. Added a 3-strike
  counter that re-raises on the third consecutive failure, escalating to
  `_mark_failed`. The `except Exception: pass` around `await last_flush_task`
  is now `except Exception: raise`. Lifespan startup sweep in `main.py`
  marks any `status='streaming'` rows older than 10 minutes as `failed` on
  process restart.
- **model_puller cancel event inside lock (C4).** `_CANCEL_EVENTS` assignment
  now happens inside `_PULL_LOCK` to prevent a race where cancel() is called
  before the event is registered.
- **Chat-switch resume no longer resumes the wrong chat (C7).** Added a
  `useEffect` in `useStreamOrchestrator.js` that resets `resumedRef` and stops
  any active stream when `activeChatId` changes.
- **Double-submitted model pull guard (C9).** `pull_model` re-reads the DB row
  inside `_PULL_LOCK` and returns early if `status == 'ready'`, preventing a
  second concurrent pull from re-downloading a completed model.

### Memory

- **Auto-extraction pipeline wired.** `register_memory_hooks()` is called in
  the lifespan on startup, wiring `post_tool_execution` callbacks so
  `manage_memory` tool calls during inference are logged to the memory engine.
  `run_background_extraction()` is now fired as a named background task in
  `inference_job.py` step 10 after each completion, gated by the
  `memory_auto_extract_enabled` key in `global_settings` (default `false`).
  Enable at runtime: set the key to `'true'` via the DB shell.

### Cleanup

- **`process_pool.py` removed.** 701-line file from `fork-lift-wave-1` with
  zero importers. Dead code. (`S4`)
- **`ai-elements/` removed.** 47-file Wave 4 component suite with zero
  consumers in the live frontend. (`S10`)
- **`image_chunks` schema dropped.** Table and HNSW index removed; MedSigLIP
  vision embeddings were removed in v1.2.11 and the schema was never cleaned
  up. (`S8`)

### AI
- **`fork-lift-wave-1` landed on `main` after `v1.2.16`.** Wave 1-4 commits
  added lifecycle hooks, structured model config, type-inject MCP wiring,
  verify-gate, ai-elements surfaces, safeguard engine, 3-tier memory engine,
  audit recovery, memory tools, BM25-prefiltered RAG, eval endpoints, cache
  config, supervisor-worker orchestration, process pool, approval gate,
  conductor scheduling, and token analytics.

### Tooling
- **`@nick-vi/type-inject-mcp`** moved to `devDependencies` so the MCP wiring
  added in Wave 1 resolves correctly in local installs.

### Docs
- Synced README, architecture, context, roadmap, changelog, and active
  `openspec` batches with the current post-`v1.2.16` branch state.

---

## [v1.2.16] — 2026-06-08

### UX
- **Button press feedback** now uses `scale(0.97)` instead of `translate-y-px`.
- **Entry animations** added for messages, status bar, and RAG pill.
- **Assistant bubbles** now use a `bg-muted/30` surface with `rounded-xl`.
- **Sidebar sections** animate open/closed via `grid-template-rows`.
- **Custom easing tokens** (`--ease-out`, `--ease-in-out`) added to `globals.css`.
- **Z-index scale cleanup.** Plus menu moved from `9999` to `50`.
- **Typography polish.** `--fs-nav` reduced from `20px` to `15px` for clearer hierarchy.
- **Light theme background** shifted from `#F8F5F0` to `#F7F6F3`.
- **SVG stethoscope icon** replaces emoji for cross-platform consistency.
- **Medical disclaimer** now renders at full opacity.
- **Compacted summary styling** now uses theme tokens instead of hardcoded blue.
- **Empty chat state** now shows three clickable suggestion chips.
- **Chat input placeholder** changed from `Message…` to `Ask about your health records…`.

---

## [v1.2.15] — 2026-06-08

### UX
- **Tailwind opacity modifiers fixed.** The `bg-primary/10`, `ring-ring/50`,
  etc. utilities now work via `color-mix` instead of silently emitting no CSS.
  Tailwind's `alpha()` helper mapped all shadcn-style color tokens through
  `color-mix(in srgb, var(--x) calc(<alpha> * 100%), transparent)`.
- **Geist Variable + JetBrains Mono Variable fonts** bundled via
  `@fontsource-variable`. Set as the default `sans`/`heading`/`mono` font
  stack in `tailwind.config.js`.
- **Stream orchestrator hook.** Extracted the streaming state machine into
  `useStreamOrchestrator.js`, decoupling it from ChatView. Stripped ~700 lines
  from `ChatView.jsx`.
- **Wire-contract error messages** for missing providers, missing embedding
  model, and dimension mismatch now render as clickable links to the relevant
  settings page.
- **Sidebar redesigned**, login/setup pages polished, new `confirm-dialog` and
  `sonner` UI components, workspace pages consolidated. Removed `useDurableChat`
  and old `useStream` dependency from ChatView.

### Tooling
- **Unified `hlh` CLI.** The individual `hlhstart`/`hlhupdate` scripts are
  replaced by a single `hlh` binary with subcommands:
  `hlh start`, `hlh stop`, `hlh restart`, `hlh update`, `hlh help`.
  The legacy names remain as wrappers delegating to the unified CLI, so
  muscle memory still works.
- **New `hlh stop` and `hlh restart` commands.** Stop tears down app
  containers (`hlh_api`, `hlh_ui`, `hlh_chat`, `hlh_search`, `hlh_orchestra`)
  while preserving `hlh_db` + all volumes.
- **`install.sh`** installs all five commands (`hlh`, `hlhstart`, `hlhstop`,
  `hlhrestart`, `hlhupdate`). README updated to document the new commands.

---

## [v1.2.14] — 2026-06-02

### AI
- **gpu-16gb now runs MedGemma-1.5-4B (Q8_0), not the 27B.** Only the gpu-24gb+
  tier gets the 27B now. Keeps the chat model + its mmproj comfortably resident
  on a 16 GB card (the 27B + projector was tight). Updated the chat + vision
  registry specs, the tier card in Settings, and the models.ini tier notes.

---

## [v1.2.13] — 2026-06-02

### Fixes
- **Vision now reuses the chat model instead of loading a redundant 4b.** v1.2.11
  spun up a separate MedGemma-4b (`vision_base` role + `[medgemma-vision]` preset)
  for ingestion — but MedGemma's chat model is *itself* multimodal, so on a 27b
  tier that meant a second model competing for VRAM (and a confusing extra model
  to pull). Now the `[medgemma]` chat preset loads its matching mmproj and the
  **same instance does chat + image-reading** (`vision.py` requests
  `model="medgemma"`). The projector matches the chat model per tier (4b mmproj on
  4b tiers, 27b on 27b) — i.e. on gpu-16gb/24gb+ it uses the 27b mmproj you
  already pull, no extra download, no second model in VRAM.
- **`seed_registry` prunes orphaned `bundled_models` rows.** Retired specs (the
  short-lived 4b `vision_base`, and the 4b mmproj briefly mapped to the 27b tiers)
  lingered as stale "pending"/"ready" rows in Settings → System. Boot now deletes
  any row the registry no longer defines, so the model list reflects reality.

### Removed
- The `vision_base` role, `[medgemma-vision]` preset, `link_active_vision_base`,
  and the always-4b ingestion-vision plumbing from v1.2.11.

---

## [v1.2.12] — 2026-06-02

### Fixes
- **Bootstrap now actually refreshes `:latest` images (critical update bug).**
  `pull_image` was skip-if-present: it pulled an image once and then *never*
  again, so re-running the bootstrap (incl. via `hlhupdate`) recreated
  containers from the **stale local `:latest`** and silently kept shipping old
  code. Effect: recent releases (v1.2.8 RAG fix, v1.2.9 monitor, v1.2.11
  vision/MedSigLIP removal) never reached already-deployed boxes — e.g.
  `hlh_ui` stayed on the old build and still showed the removed "Vision Search"
  UI. Now always pulls (pinned tags are a cached no-op; floating tags refresh),
  with a local-image fallback if the registry is unreachable.

### Tooling
- **`hlhstart` / `hlhupdate` launchers.** Thin host-side wrappers around the
  bootstrap `docker run` so starting/updating the stack is one word instead of a
  long command. `hlhstart` = start/restart (idempotent); `hlhupdate` = pull
  latest images + recreate (keeps `hlh_db` + the secrets/data volumes).
- **`install.sh` now installs the launchers.** The `curl … install.sh | bash`
  one-shot installer (the de-facto "hlhinstall") drops `hlhstart`/`hlhupdate`
  into `/usr/local/bin` (best-effort: writable dir or passwordless sudo; skipped
  with a hint otherwise) before bootstrapping. README quickstart leads with it.
- **Dropped the vestigial `-e HLH_BOOTSTRAP=1` flag** from `install.sh` and the
  README. Since v1.2.11 the orchestra is bootstrap-only, so its entrypoint always
  bootstraps — the env var is no longer read anywhere. Also corrected the
  quickstart prose (the orchestra now exits after bootstrap; it is not a
  long-running lifecycle manager).

---

## [v1.2.11] — 2026-05-30

Spec: `docs/superpowers/specs/2026-05-30-remove-medsiglip-medgemma-4b-vision-design.md`

### AI
- **MedGemma vision actually reads attached images/PDFs now.** Two bugs meant
  ingestion vision silently fell back to junk OCR text: `vision.py` sent no
  `model` field (the llama-server router 400s without one) and `models.ini` had
  no vision preset with an mmproj. Added a `[medgemma-vision]` router preset
  (loaded on demand, evicted when idle) and made `vision.py` request it.
- **Ingestion vision is pinned to MedGemma-4b, tier-independent.** The 4b model
  (+ its mmproj) stays GPU-resident next to the chat model — even a 27b chat
  tier — instead of forcing a VRAM offload. New `vision_base` role pulls the 4b
  base GGUF on every vision-capable tier; `link_active_vision_base` /
  `link_active_mmproj` aim the preset's symlinks. `is_vision_available()` gates
  on both, so the preset is never requested (can't break chat) until pulled.

### Removed
- **MedSigLIP / the `hlh_vision_embed` sidecar is gone.** It only powered the
  unused `/api/vision/{embed,search,classify}` image-vector endpoints — never
  the ingest or chat path — for a ~5 GB sidecar's worth of cost. Removed the
  backend services/router/lifecycle, the `vision_embed` provider seeding +
  resolution, the doctor check, the `medsiglip` model-registry role, the
  `hlh_vision_embed` compose service + `vision` profile + `hlh_vision_cache`
  volume, and the frontend "Vision Search" UI. (The `vision_embed` /
  `medsiglip` role values stay in the schema CHECKs — harmless, no migration.)
- **`hlh_orchestra` is now bootstrap-only.** With vision lifecycle gone its only
  job is the `install.sh` `docker run` bootstrap; dropped the long-running
  FastAPI server, the `/vision/*` endpoints, `app.py`, and its compose service.

---

## [v1.2.10] — 2026-05-30

### Fixes
- **Vision reachable under the bootstrap deploy path.** v1.2.9 created
  `hlh_vision_embed` but, when the orchestra is launched via the `install.sh`
  `docker run` one-liner, it gets a random name on the default bridge — so
  `hlh_api`'s call to `http://hlh_orchestra:9620` (and the vision lifecycle)
  couldn't resolve. `bootstrap.run()` now self-attaches the orchestra container
  to `hlh_default` with the `hlh_orchestra` network alias. No-op under compose
  (which already names + networks the service). Completes the vision fix for
  pull-from-GHCR + bootstrap deployments.

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
