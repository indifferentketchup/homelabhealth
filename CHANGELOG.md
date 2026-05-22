# Changelog

Canonical record of releases for **homelabhealth**. Most recent on top.

**Convention:** new work accrues under `## [Unreleased]`. When a tag is
cut, rename `[Unreleased]` to `## [<tag>] — YYYY-MM-DD` and start a
fresh empty `[Unreleased]` section. Group entries by track (AI /
Safeguards / Security / UX / Tooling / Docs) when there are >5 items.

---

## [Unreleased]

Work since `pre-personas-removal` (2026-05-22). Roadmap tracks: A1.5,
A1.6, A1.7, A2, A7, B0, C2 all shipped to `main`.

### AI / bundled inference
- **Phase 1 follow-up — bundled chat sidecar lands on main** via
  `f2c5039` (was already shipped as `v0.1.0-phase-1` but unmerged at
  that tag; merge completed in this window).
- **Phase 2.A — "bundled-system takes everything"** (`994c7e7`). Three
  immutable bundled provider rows (chat / embed / rerank), grouped
  under `bundle_group='homelab-health-ai'`. `apply_bundled_bindings`
  helper rewrites global embed/rerank + bundled-chat-bound workspaces
  on every lifespan boot AND tier-save. New `hlh_infer` sidecar
  (`michaelf34/infinity:0.0.77-cpu`) serves `/v1/embeddings` (bge-m3,
  1024-dim) and `/v1/rerank` (bge-reranker-v2-m3) from one process via
  `INFINITY_URL_PREFIX=/v1`. HF token moved from `.env` to a DB-backed
  encrypted singleton with UI input + show-me-how guide.
- **A1.6 — workspace auto-bind + Settings lockdown**: reversed the
  original roadmap's "operator picks explicitly" stance. Settings →
  Providers / Embedding / Reranker tabs removed entirely;
  WorkspaceDetailPage chat-provider override removed. Sensible
  defaults, no foot-guns.
- **A1.5 — hardening + pinning** (partial → shipped via the
  bundled-tail branch). Pinned image tags
  (`ghcr.io/ggml-org/llama.cpp:server-b9282`,
  `searxng/searxng:2026.5.22-c57f772ad`). Container hardening across
  all 6 services (`read_only`, `cap_drop:[ALL]`, `no-new-privileges`,
  `tmpfs`, per-service `mem_limit`). New `hlh_inference` network with
  `internal:true` — chat moves to inference-only; infer stays on both
  for HF egress. Disk pre-flight in `model_puller` rejects pulls that
  would leave <5 GB headroom. `bundled_models.revision` column +
  `ModelSpec.revision` plumbed through `_hf_url` (sha256 + expected
  bytes population deferred to Phase 2 follow-up).
- **A1.7 — operator pre-flight + first-launch ack**: new `python -m
  hlh.doctor` CLI runs 11 health checks (DB pool, schema, sidecars,
  safeguard version, disk free, encryption key, HF token); CLI exits 0
  green / 1 red. `GET /api/system/doctor` JSON endpoint. SystemTab
  gains a Pre-flight expandable section. First-launch acknowledgement
  modal mounted globally — required "I understand" checkbox stamps
  `system_profile.acknowledged_at`. Optional-search bullet renders
  only when `hlh_search` reports healthy.
- **A7 — bundled search**: `hlh_search` sidecar (SearXNG) added to the
  `bundled` compose profile. `searxng/settings.yml` bind-mounted with
  JSON format enabled. `SEARXNG_URL=http://hlh_search:8080` overrides
  `.env` from compose. Internal port 8080; host port 9612 bound to
  `0.0.0.0` (user-agnostic). `searxng_config` table seeded with
  `wikipedia, brave, mojeek, startpage, arxiv, pubmed` defaults.
- **Phase 2.B — embed + rerank visibility**: Models panel now shows 3
  rows (chat + embed + rerank). Embed/rerank synthesized client-side
  from bundled providers; status derived from
  `providers.last_verified_status`. Polling cap 60×5s = 5 min before
  flipping to error. No Pull button on synthetic rows (sidecar-managed).
- **Model choices locked**: cpu-min →
  `unsloth/Qwen3.5-0.8B-MTP-GGUF / Qwen3.5-0.8B-Q8_0.gguf`
  (Apache-2.0, no token needed, ~0.85 GB). cpu-std + gpu-8gb →
  `unsloth/medgemma-1.5-4b-it-GGUF`. gpu-16gb + gpu-24gb+ →
  `unsloth/medgemma-27b-it-GGUF`. License clicks at
  huggingface.co/google/medgemma-* still required for gated pulls.

### Safeguards
- **B0 baseline** (`adba194`). System-prompt tiered-refusal prepended
  to every assistant turn; `messages.safeguard_version` records which
  version was active on send so policy drift is auditable.
  B1/B2/B3/B4 still open.

### Security
- **C2 — docker hardening** absorbed into A1.5 (above). All other
  C-track items (C0–C9) still open.
- **bundled provider immutability** (server-side defense in depth):
  bundled rows reject PATCH/DELETE with HTTP 403 and the mandated
  spec-string detail. UI hides controls; backend enforces.

### UX
- **Dark mode toggle** in sidebar (sun / system / moon segmented
  pill). Existing `.dark` CSS palette (locked tokens from 2026-05-03)
  now actually activates — Zustand `themeSlice` writes the class on
  `<html>` on boot + on change; `prefers-color-scheme` reactive in
  `system` mode.
- **Typography settings actually apply**. `applyWorkspaceLayoutToDom`
  rewritten to read from the layoutStore (not the deprecated
  always-cleared localStorage key) and write the
  `--font-size-base / --fs-nav / --fs-chat / --fs-input / --fs-heading
  / --fs-code` CSS vars. Defaults bumped to 21 / 20 / 21 / 20 / 24 /
  19. Clamp ceiling lifted 24 → 32 so headings can grow.
- **Hardcoded color audit**: replaced literal hex fallbacks with
  CSS-var token classes where they bypassed dark mode.
- **Personas removed** (`3a5b760`). System-prompt assembly simplified;
  personas table dropped; UI surfaces gone.

### Tooling / Verify scripts
- `verify_a1_5_hardening.sh` — docker inspect + jq assertions for
  hardening / network membership / mem limits / disk pre-flight
  rejection.
- `verify_a1_7_doctor.sh` — doctor JSON shape, CLI exit code, ack
  endpoint round-trip.
- `verify_hf_token.sh`, `verify_bundled_immutability.sh`,
  `verify_tier_change_rewrite.sh` — existing scripts from Phase 2.A,
  brought current with model-filename changes during this window.

### Docs
- `docs/roadmap.md` — three reconciliation passes against shipped
  reality. Trunk-merge gates retired; all remaining gates apply to
  non-Sam access only. Ship-to-friend checkboxes ticked for A1, A1.5,
  A1.6, A1.7, A2, A7, B0, C2.
- README gains "First boot" note + `make doctor` usage.
- Spec docs (under `docs/superpowers/specs/`, gitignored) for the
  bundled-system reshape + bundled-tail kept local-only.

---

## [pre-personas-removal] — 2026-05-22

Reference tag taken right before personas were removed. Last commit:
`docs: unify AI/safeguards/security roadmap; restructure docs/`. Use
for forensic comparison if personas-removal needs to be revisited.

---

## [pre-safeguards-baseline] — 2026-05-22

Reference tag: A1 (chat sidecar) shipped to `main` ahead of B0
safeguards. Tag exists as the recoverable "no-safeguards" baseline so
any future safeguards-regression can compare against it.

---

## [v0.1.0-phase-1] — 2026-05-22

**Phase 1: bundled chat sidecar + model puller.** First bundled-AI
release.

- New `hlh_chat` sidecar (`ghcr.io/ggml-org/llama.cpp:server`, port
  9610) reads model weights from the shared `hlh_models` volume.
- `services/model_puller.py` — httpx streaming pulls from HF with
  single asyncio lock, `.partial → fsync → rename`, gated-repo 401
  surfacing.
- `bundled_models` table tracks role / tier / model / status / progress
  / license.
- `services/bundled_providers.py` — idempotent upsert of the
  `bundled-chat` provider row; no-op on `external` tier or
  `setup_complete=false`.
- `routers/models.py` — five admin endpoints
  (list / get / pull / pull-for-tier / cancel).
- SystemTab gains the Models sub-panel, MedGemma tier labels, and the
  external-tier advanced toggle.
- Auto-seed of the bundled-chat provider on tier confirm.
- 393 assertions across 13 verify scripts (including the E2E chat
  round-trip).

Known gaps recorded for A1.5 follow-up (now shipped — see Unreleased):
no internal network, no container hardening, unpinned `:server` tag,
no sha256 in MODEL_REGISTRY, no disk pre-flight, MedGemma filename
placeholders, no delete guard on bundled-chat.

---

## [v1.11.0] — 2026-05-21

**Phase 0: bundled-AI hardware detection + tier picker.**

- `system_profile` table (singleton).
- `services/sysinfo.py` — hardware detection + tier recommendation
  (cpu-min / cpu-std / gpu-8gb / gpu-16gb / gpu-24gb+ / apple-mlx /
  external).
- `routers/system.py` — `GET /hardware`, `GET/PUT /profile`,
  `POST /redetect`.
- SystemTab UI with tier cards and the setup-complete gate that locks
  the rest of the app until a tier is confirmed.
- E2E + regression precondition tests for gated routes.

Every later AI phase keys off `system_profile.tier`.

---

## [v1.10.0] — 2026-05-21

**Providers and API keys.** First multi-provider release.

- New `providers` table (shared list of OpenAI-compatible endpoints).
  Optional encrypted `api_key` via new `services/crypto.py` (Fernet
  with `PROVIDER_KEY_ENCRYPTION_KEY`; cleartext fallback when unset).
- `routers/providers.py` — CRUD + connection-test + 409 on in-use
  delete with force-delete cascade.
- `workspaces.provider_id` per-workspace binding.
- `global_settings.embedding_provider_id / embedding_model` and
  `reranker_provider_id / reranker_model` for the two global pickers.
- Shared `provider_client.py` resolver collapses six previously
  env-var-driven inference call sites into one auth-aware path. The
  five env vars (`OPENAI_API_KEY`, `INFERENCE_URL`, `EMBEDDING_URL`,
  `RERANKER_URL`, `DEFAULT_MODEL`) become deprecated; startup warns if
  any are still set.
- Frontend: Providers CRUD tab, Embedding + Reranker picker tabs,
  per-workspace provider+model picker.
- Pre-merge: env var rename `BOOLAB_*` → `HLH_*`; postgres user/db
  rename `boolab` → `hlh`; schema rewrite to post-rename shape;
  pgvector extension creation order fixed for fresh-init.

---

## [pass-4-lite] — 2026-05-02

Isolated `docker-compose.yml` from the legacy boolab project (separate
network, separate container names, separate volume namespace). One
follow-up to remove a phantom chromadb dep + stale comment.

---

## [pass-3-complete] — 2026-05-02

**Big strip pass: fork from boolab → homelabhealth identity.** Single
commit that removed auth, removed multi-mode UI, renamed
`daws → workspaces`, hardcoded the HomeLab Health branding +
healthcare palette, rewrote `schema.sql` to the post-rename shape,
and rewrote the docs.

---

## [pre-strip-snapshot] — 2026-04-27

Snapshot taken right before the strip pass. One late addition before
the tag: `schema: add generation status/seq + message_tokens for
persistent streaming`.

---

## [pre-phase-4-merge] — 2026-04-22

Pre-existing tag from the boocode/boolab era. Captures the boolab
state before the phase-4 merge that eventually became homelabhealth.
Earliest tagged history of this repo.

---

## Pre-tag history (chronological)

Before the first tag (`pre-phase-4-merge`, 2026-04-22), the repo
evolved as boolab → boocode → homelabhealth. Highlights from the
pre-tag commits:

- `62063e7` Phase 0 — initial skeleton, docker, schema, mode detection.
- `bc561ed` Phase 1 — BooOps core chat, streaming, model switcher.
- `8efc758` feat: auth + user tiers (later stripped in pass-3).
- `22034c8` feat: global personas + drop mode column (later removed
  in the personas-removal pass — see Unreleased).
- `8673cf2` feat: branding asset seeding.
- A long tail of boocode terminal fixes (xterm, PTY width, scroll
  containment, glyph rendering) before the strip-down to
  homelabhealth.

These commits remain reachable via `git log` but are not part of any
shipped homelabhealth release per se.
