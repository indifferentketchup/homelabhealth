# HomeLabHealth — Master Roadmap

Canonical roadmap covering built-in AI, security, and medical safeguards.
Supersedes `docs/builtin-ai/roadmap.md` (built-in AI only) and
`docs/security/SECURITY_PLAN.md` (security only) — both fold in here.
Phase numbering renumbers slightly so AI / Security / Safeguards each get
their own track but interleave on a single dependency graph.

Owner: Sam
Last updated: 2026-05-22 (reconciliation pass)

-----

## Posture

- **Single user (Sam) today.** No third user, no public release yet.
- **Friend is the next user.** Nothing ships to her until the entire
  roadmap is complete — including safeguards, hardening, and security.
  No early access. No “we’ll add safeguards later.”
- **Timeline: open-ended.** Build it right. No hard deadline driving
  shortcuts.
- **Public release: deferred, but documented as if it’s coming.**
  Every commit, every doc, every defaulted env var is written for a
  stranger reading the repo. README is honest about state. `.env.example`
  lists every variable.
- **License: AGPL-3.0 leading.** Locks in if anyone else ships from this.

-----

## Tracks and dependency graph

Three tracks. Phases interleave by dependency, not by track. The friend
sees zero of this until **everything** is at “shipped” status.

```
Track A — Built-in AI
  A0 ✓ shipped on main
  A1 ✓ shipped on main (f2c5039, v0.1.0-phase-1)
  A1.5  partial — is_bundled delete guard shipped (dcb1413);
                  hardening + pinning + network split remaining
  A1.6 ✓ shipped on main — workspace auto-bind + settings lockdown
  A1.7  pre-flight + first-launch ack (remaining)
  A2 ✓ shipped on main (994c7e7) — ahead of C5 gate, no data ingested
  A7 ✓ shipped on main — bundled search (hlh_search), off-roadmap addition
  A3 ─▶ A4 ─▶ A5? ─▶ A6

Track B — Safeguards
  B0 ✓ shipped on main (adba194)
  B1                          (output scanner — gates non-Sam access)
  B2                          (UI disclaimers + crisis card)
  B3                          (audit-logged refusals + retry-with-warning)
  B4                          (red-team eval, ongoing)

Track C — Security
  C0  docs                    (independent, do anytime)
  C1  disk/backup hygiene     (independent, do anytime)
  C2  docker hardening        (folds into A1.5 — still pending)
  C3  synthetic data + logs   (must land before any non-Sam data)
  C4  audit logging           (must land before B3)
  C5  de-id pipeline          (must land before first real-record
                               ingest into A2 pgvector)
  C6  column encryption       (must land before friend gets the URL)
  C7  LLM I/O guardrails      (overlaps with B1 — same llm-guard sidecar)
  C8  supply chain + ops      (independent, do anytime)
  C9  right-to-erasure        (must land before friend gets the URL)
```

**Ship-to-friend gate** = every phase above shipped + tagged.
Trunk-merge gates documented in earlier roadmap revisions are
**retired**. Gates now apply to non-Sam access only.

-----

## Track A — Built-in AI

### A0 — Hardware detect + tier picker — **shipped on main** (`d173e1f`)

`system_profile` table, `GET /api/sysinfo`, `PUT /api/system/profile`,
setup-complete gate, `SystemTab.jsx` with tier cards. Not re-documented
here. Every later AI phase keys off `system_profile.tier`.

### A1 — Chat sidecar — **shipped on main** (`f2c5039`, tagged `v0.1.0-phase-1`)

9 commits + merge. 393 assertions across 13 verify scripts.
Implementation contract documented in commit messages and
`docs/phase-1-design.md`. The pre-B0 main tip is tagged
`pre-safeguards-baseline` so the safeguards-free state is recoverable
if a regression needs comparison.

Summary:

- New table `bundled_models` (role/tier/model/status/progress/license).
- `services/model_puller.py` — httpx streaming pulls from HF, single
  asyncio.Lock, `.partial` → fsync → rename, gated-repo 401 surfacing.
- `services/bundled_providers.py` — idempotent upsert of
  `bundled-chat` provider, no-ops on `external` tier or
  `setup_complete=false`.
- `routers/models.py` — 5 admin endpoints (list/get/pull/pull-for-
  tier/cancel).
- New sidecar `hlh_chat` (`ghcr.io/ggml-org/llama.cpp:server`, port
  9610, compose profile `chat`).
- Shared `hlh_models` volume (rw on `hlh_api`, ro on `hlh_chat`).
- `SystemTab.jsx` — `ModelsPanel`, MedGemma tier labels, external
  hidden behind `<details>`.

**Known gaps** (all close out in A1.5):

1. No internal network — `hlh_chat` on `hlh_default`.
1. No container hardening — no read_only, cap_drop, mem_limit,
   non-root user, tmpfs.
1. `:server` tag unpinned.
1. No sha256 in `MODEL_REGISTRY` entries.
1. No disk pre-flight before multi-GB pulls.
1. MedGemma `filename` entries are unverified placeholders.
1. No delete guard on `bundled-chat` provider row.

**Safeguards posture (post-merge correction):** A1 shipped to `main`
ahead of B0/B1 — against the intent of this roadmap. The current
trunk serves chat freely. B0 lands ASAP as a short-lived branch off
`main` to close that gap before any external exposure. Procedural
lesson, locked going forward: every AI phase bundles its safeguards
on the same feature branch. A2+ follow this rule without exception.

**Second correction (A2):** A2 shipped on `994c7e7` ahead of its
stated C5 gate. Reconciled by fact that no chunks exist in
`source_chunks` at ship time. The C5 gate is retained but reworded:
C5 must land before first real-record ingest, not before A2 merge.

**Third correction (off-roadmap shipments):** A7 (bundled search)
and the workspace auto-bind / settings lockdown (A1.6) were shipped
without prior roadmap entries. They are now documented in-place
rather than reverted.

**Net posture:** trunk-merge gates from the original roadmap are
retired. All gates apply to **non-Sam access** going forward.

### Phase 2.A (2026-05-22) — bundled-system takes everything

Accelerated from the original Phase 2 plan. Spec: `docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md`.

**Shipped:**
- `hlh_infer` sidecar (infinity-emb on `michaelf34/infinity:0.0.77-cpu`) serves embeddings (`BAAI/bge-m3`, 1024-dim) AND rerank (`BAAI/bge-reranker-v2-m3`) from one process.
- Three immutable bundled provider rows (`is_bundled=TRUE`, `bundle_group='homelab-health-ai'`, roles `chat`/`embed`/`rerank`) — server-side 403 on PATCH/DELETE.
- `apply_bundled_bindings(conn, tier)` helper rewrites global embed/rerank + every bundled-chat-bound workspace on lifespan boot AND tier-save. Override-on-bundled is reset on tier change (intentional — see spec §4 boundary cases).
- HF token DB-stored via new `hf_token_config` singleton + `services/hf_token.py` + `routers/system.py` endpoints; UI field in Settings → System.
- UI surgery: embedding/reranker tabs read-only when tier ≠ external; Settings → Providers groups bundled rows under one "HomeLab Health AI" expandable card; WorkspaceDetailPage hides the chat picker behind an advanced disclosure.
- Dark mode toggle (Settings → Sidebar) activates the existing `.dark` palette in globals.css via Zustand + localStorage + matchMedia.

**Phase 2.B follow-ups:**
- Extend `model_puller.MODEL_REGISTRY` for `embed` + `rerank` so the Models panel tracks bge-m3 + bge-reranker download progress (currently infinity pulls them itself, opaque to the UI).
- Optionally pin `michaelf34/infinity` to a specific newer tag if 0.0.77-cpu becomes unsuitable.

**Known limitations** (documented in spec §10):
- Encryption falls back to cleartext if `PROVIDER_KEY_ENCRYPTION_KEY` env unset — same posture as `providers.api_key`.
- Single embedding model across all tiers (bge-m3 is the only 1024-dim option supported by the schema).
- Apple MLX tier treated as external (Phase 6 deferred — no bundled MLX inference yet).

### A1.5 — Hardening + pinning — **partial**

Status: `is_bundled` delete guard shipped on main (`dcb1413`).
Remaining work below is unshipped. Absorbs **C2 (docker hardening)**.

**Shipped so far (`dcb1413`):**

- Additive `is_bundled BOOLEAN DEFAULT false` on `providers` (plus
  `role` and `bundle_group` columns added in the same wave).
- `ensure_bundled_*` sets `is_bundled=true` on insert.
- `DELETE /api/providers/{id}` returns 403 on bundled rows (spec
  said 409; implementation chose 403 — see commit).
- Frontend hides Save + Delete on bundled provider rows.

**Remaining:**

Docker:

- New `hlh_inference` network with `internal: true`. `hlh_api` joins
  both `hlh_default` and `hlh_inference`. `hlh_chat` moves to
  `hlh_inference` only.
- `hlh_chat` additions: `user: "1000:1000"`, `read_only: true`,
  `tmpfs: [/tmp]`, `cap_drop: [ALL]`,
  `security_opt: [no-new-privileges:true]`, `mem_limit` per tier
  (cpu-min 3g → gpu-24gb+ 22g).
- Same hardening posture applied to `hlh_api` and `hlh_ui` as part
  of the C2 scope.
- Pin `ghcr.io/ggml-org/llama.cpp:server-<digest>` to a specific
  build. Document upgrade procedure.
- Confirm no service binds `0.0.0.0`. All binds to
  `100.114.205.53`.

`MODEL_REGISTRY` pinning:

- For every chat tier shipped in A1: confirm filename resolves
  against current HF artifact, pin `revision`, compute and pin
  `sha256` after clean pull, verify `expected_bytes`.

Puller hardening:

- Disk pre-flight: refuse pull if free space minus `expected_bytes`
  would leave <5 GB. Status=`failed`, error_message=“insufficient
  disk”.
- sha256 mismatch path already coded — pinning lands here so the
  path is actually exercised.

Provider delete guard:

- Additive `is_bundled BOOLEAN DEFAULT false` on `providers`.
  `ensure_bundled_*` sets true on insert.
- `DELETE /api/providers/{id}` returns 409 on bundled rows.
- Frontend hides delete button (or disables with tooltip).

Acceptance: existing 393 assertions still green, plus
`verify_phase_1_5_hardening.sh` (docker inspect checks, internal
network check, no host ports, sha256 corrupt test, disk pre-flight
synthetic test).

### A1.6 — Workspace auto-bind + Settings lockdown — **shipped on main** (`994c7e7`)

Policy reversal from the original roadmap's "NOT doing" list.

- On workspace create AND on every tier-save / lifespan boot:
  workspace `provider_id` and `model` auto-bind to the bundled chat
  provider via `apply_bundled_bindings(conn, tier)`. Override on a
  bundled-bound workspace is reset on tier change (intentional —
  spec §4 boundary case).
- Embedding + reranker continue to bind at global level (unchanged).
- Settings → Providers / Embedding / Reranker tabs locked down for
  bundled rows: read-only display, no edit, no delete. Tabs other
  than System and Search were removed entirely from the nav in a
  follow-up commit.
- Workspace-level override deferred (the lockdown direction is
  "sensible defaults, no foot-guns").

**Rationale:** the original "operator picks explicitly" stance
assumed an operator who wanted control. The friend deployment is the
opposite case — she wants it to just work. The lockdown removes
configuration surface area, which removes ways to break it.

**Reversibility:** revert is a frontend-only change (re-enable the
tabs and the workspace picker). The backend `apply_bundled_bindings`
helper can stay; it's idempotent and harmless if the UI lets
operators override.

### A1.7 — Operator pre-flight + first-launch ack

Single highest-leverage thing for the non-technical-friend
deployment. Catches operator-error misconfiguration before any PHI
is entered.

- `make doctor` (or `python -m hlh.doctor`) — pre-flight script.
  Checks:
  - LUKS on the host root partition.
  - Backrest reachable, repo passphrase set, last successful
    snapshot within N days.
  - `HLH_MASTER_KEY` set and not the example placeholder.
  - Authelia reachable (if configured).
  - Active safeguard prompt version matches the version pinned in
    code (catches accidental override).
  - Sidecar healthchecks green.
- Output: green/yellow/red per check + actionable remediation line.
  No PHI in output.
- Runs on every container start (logged) and on demand via
  `docker exec hlh_api make doctor`.
- First-launch modal (folded in from B2): one-time acknowledgement
  on the "Done" screen of setup — "what HLH is and isn't, not for
  clinical use, you understand." Tick to dismiss, cannot be re-shown
  via UI (resets on `setup_complete=false`).

**Placement:** between A1.5 and A2. Biggest UX gate for the friend
deployment. Folds in B2's first-launch modal — both are "what the
operator sees first."

### A2 — Embed + Rerank — **shipped on main** (`994c7e7`)

**As shipped:** a single combined sidecar `hlh_infer` (not the two
separate sidecars in the original plan), running
`michaelf34/infinity:0.0.77-cpu` with `INFINITY_MODEL_ID` listing
both models. Embed engine `optimum` (ONNX) for bge-m3; rerank engine
`torch` for bge-reranker-v2-m3 (no ONNX exports exist). Both served
under `/v1/*` prefix to match existing call-site paths.

**Network posture deferred:** sidecar currently on `hlh_default`
pending the A1.5 `hlh_inference` split. Move when A1.5 finishes.

**Models as shipped:**

| Role | Repo | File |
|---|---|---|
| embed | `BAAI/bge-m3` (loaded by infinity from HF) | n/a (multi-file HF) |
| rerank | `BAAI/bge-reranker-v2-m3` (same) | n/a |

Both auto-bind to `global_settings.embedding_provider_id` and
`global_settings.reranker_provider_id` on lifespan boot via
`apply_bundled_bindings`.

**A2 shipped ahead of its C5 gate.** Reconciled by fact: zero
chunks in `source_chunks` at ship time. The gate now reads as:
**C5 must land before first real-record ingest.** Until C5, do not
ingest any record. If a record is ingested before C5, treat the
vectors as compromised and re-embed after redaction (operationally:
`TRUNCATE source_chunks` and re-run ingest post-C5).

**Constraint:** embed dim hard-locked at 1024 (schema). Migration
plan required before any model swap to a different dim.

**Two-sidecar variant retained as fallback** in spec §10: if
infinity multi-model proves unreliable, split into `hlh_embed` +
`hlh_rerank`. Not needed today.

### A3 — Vision (VLM) + MedSigLIP

Sidecar `hlh_vlm` running llama.cpp with `--mmproj`. Qwen2.5-VL-3B Q4
(8gb tier) / Qwen2.5-VL-7B Q4 (16gb+).

MedSigLIP for medical-image embeddings. License is HAI-DEF — review at
impl. If redistribution is forbidden, surface a manual-download flow.

**MTP + mmproj gotcha (locked):** cannot combine — fatal n_embd
mismatch at load. VLM model configs must NOT use MTP variants. Bake
this into `MODEL_REGISTRY` validation.

### A4 — STT (whisper.cpp)

Sidecar `hlh_stt` on port 9640. Tier-keyed defaults (whisper-tiny.en →
whisper-large-v3-turbo).

**Not a `providers` row.** Single internal endpoint. New
`POST /api/transcribe`, mic button on chat input + record-notes
editor.

Decision deferred: webm/opus transcode in browser vs in `hlh_api`.

### A5 — OCR (conditional)

Run only if A3 VLM eval on 5+ real medical document photos shows
insufficient readability. Otherwise skip. If needed: Tesseract 5 or
PaddleOCR. Custom HTTP shape.

### A6 — Apple MLX backend variant

Deferred indefinitely. Detection in A0 flags `apple-mlx`; falls back
to `cpu-std` at runtime on darwin/arm64. Friend's hardware
determines priority. As shipped: `apply_bundled_bindings` treats
`apple-mlx` as a no-op (same as `external`) so partial-bind state
can't occur on Apple Silicon hosts.

### A7 — Bundled search (`hlh_search`) — **shipped on main** (`994c7e7`)

Off-roadmap addition. SearXNG meta-search sidecar bundled so chat can
ground responses against current web results without operator setup.

| Service | Image | Port | Network | Default |
|---|---|---|---|---|
| `hlh_search` | `searxng/searxng:latest` | 9612 (host) / 8080 (container) | host egress required | profile-gated |

**As shipped:**

- Compose profile `bundled` (same profile as `hlh_chat` + `hlh_infer`).
- Internal access via `http://hlh_search:8080` on `hlh_default`;
  `SEARXNG_URL` env in `hlh_api` overrides any operator `.env` value.
- Host port `9612` exposed on `0.0.0.0` so the SearXNG UI is
  reachable at `http://localhost:9612/`. Bind is user-agnostic — not
  Tailscale-scoped (the bundled stack is meant to deploy on arbitrary
  hosts; see `feedback-user-agnostic` memory).
- `searxng/settings.yml` bind-mounted into the container with JSON
  format enabled (default SearXNG config has JSON off — that's why
  the prior external-URL wiring would silently fail to parse).
- `searxng_config` table seeded on lifespan with sensible engine
  defaults (`wikipedia, brave, mojeek, startpage, arxiv, pubmed`).

**Posture deviations from the original diff:**

- **Default state: on** (profile `bundled` is the default in
  `.env.example`), not opt-in. The user has explicitly chosen "fuck
  it, they get what we ship" — search is part of what we ship.
- **No UI confirmation modal yet.** Threat-model entry in
  `THREATMODEL.md` at C0 ship will document the PHI-in-query risk;
  the modal proposed in the diff lands then.
- **Friend default deferred.** When the friend-deployment work picks
  up, decide whether to gate search behind the first-launch ack
  modal (A1.7) or keep it on.

**Known posture risk:** operator search queries reach third-party
engines. SearXNG anonymizes (no cookies, no user-agent leaks, no
logs) but the query content itself is visible. PHI risk is
user-discipline-bound, not technically enforced. Documented for C0.

-----

## Track B — Safeguards (medical AI guardrails)

User-facing safety. Not security in the network/crypto sense —
behavioral guardrails on what the model will and won’t say.

### Safeguard philosophy (locked)

**Tiered refusal:**

- Explain symptoms and conditions freely (educational tone).
- Refuse anything actionable: prescriptions, dosages, diagnoses,
  treatment plans, drug-combination opinions.

**No user override.** Refusals are firm. No “I understand, proceed
anyway.” Audit-log every refusal so we can tune over time, but the
firm-refuse stance ships.

**Special-case categories** (must always trigger):

1. Crisis: self-harm, suicidal ideation, overdose intent. Show
   crisis hotline card, do not engage with the underlying request.
1. Drug interactions: refuse to opine on combinations. Direct to
   clinician/pharmacist.
1. Urgency triage: when the model detects symptoms suggesting acute
   medical need, surface “this could be urgent, consider emergency
   services” — never literal “call 911.”

### B0 — System prompt baseline

- Tiered-refusal system prompt locked into every chat request to
  `hlh_chat`. Prepended in `hlh_api` before forward; cannot be
  overridden by workspace prompt config.
- Workspace-level system prompts append; they don’t replace.
- New `safeguard_version` column on `messages` so we can correlate
  refusals to a prompt revision.

**Status:** A1 shipped ahead of B0. B0 now lands as a short-lived
branch off `main` (one-file change in the chat forward path + the
`safeguard_version` migration), merges before any external exposure.
System-prompt-only guardrails are defeatable but provide the baseline.
Pre-B0 main tip tagged `pre-safeguards-baseline`.

### B1 — Output scanner sidecar

- New sidecar `hlh_guard` running `llm-guard` (Protect AI, MIT). On
  `hlh_inference` net.
- Streaming output from `hlh_chat` proxied through `hlh_guard` in
  `hlh_api` before forwarding to the SSE stream.
- Scanner categories:
  - PII regurgitation
  - Refusal categories: prescriptions, dosages, diagnoses
  - Drug-interaction opinions
  - Crisis content
  - Hallucinated identifiers (NPI/SSN/DEA that don’t validate)
  - Toxicity
- On hit: stream is truncated, replaced with the appropriate refusal
  card or crisis resource card.
- Same sidecar serves C7 (LLM I/O guardrails — prompt injection,
  token limit, PII input scanning).

**Gate:** must land before any external exposure (friend deployment
or public release). Same sidecar as C7 — ship once.

### B2 — UI disclaimers + crisis card

- Persistent disclaimer banner per chat session: “Educational only.
  Not medical advice.”
- Crisis card component — large, distinct visual. Lists hotline
  numbers configurable per locale. US default: 988 (Suicide & Crisis
  Lifeline), Poison Control 1-800-222-1222, “consider emergency
  services” for triage hits.
- “Not medical advice” footnote on every assistant message.
- First-launch modal: folded into A1.7 (see Track A) — it belongs
  with the operator pre-flight UX rather than the safeguard chrome.
- AI-generated messages tagged with `ai_generated=true` and rendered
  with a visible badge (C-track also wants this for provenance —
  same column).

### B3 — Audit-logged refusals + retry-with-warning flow

Depends on C4 (audit logging infrastructure).

- Every refusal writes an `audit_log` row: action=`safeguard.refuse`,
  detail={category, scanner_hit, model, prompt_id}.
- Retry-with-warning UX: user sees “This was refused because
  [category]. You can rephrase as an educational question.” No
  bypass button — just guidance.
- Refusal review panel in settings: user can see their own refusal
  history, helps them learn what the tool is for vs not.

### B4 — Red-team eval (ongoing)

- `garak` (NVIDIA, Apache-2.0) red-team suite run periodically
  against `hlh_chat` + `hlh_guard` end-to-end.
- Custom probes for the three special-case categories: crisis,
  drug interactions, urgency triage.
- Track results over time in `docs/safeguards/eval-history.md`.
- Not a phase that “completes” — a discipline. Run before every
  release tag. Run after every model-default change.

-----

## Track C — Security

The full S0-S9 plan from `SECURITY_PLAN.md` survives. Renumbered C0-C9
for consistency with the master roadmap. Most content is unchanged from
the existing plan; this section captures the **placement** in the
dependency graph and any deltas.

### C0 — Documentation foundation

`SECURITY.md`, `THREATMODEL.md`, `docs/safe-harbor.md`,
`docs/breach-response.md`, README “Security posture” section.

**Placement:** independent. Do anytime. Land before public release is
even mentionable.

### C1 — Disk and backup hygiene

LUKS confirm, backrest passphrase, restore drill doc, key custody
doc. `make doctor` pre-flight is its own phase now — see A1.7.

**Per-host key generation — locked.** `HLH_MASTER_KEY` (C6) and the
backrest repo passphrase MUST be generated on the operator's host,
not on Sam's machine. If Sam generates them, Sam has copies — which
defeats the C6 threat model entirely. The friend's onboarding doc
includes a one-page "generate your keys" step; A1.7's `make doctor`
fails red if either is missing or matches the example placeholder.

**Placement:** independent. Do anytime. Cheap.

### C2 — Docker hardening

Already absorbed into A1.5. C2 ships when A1.5 ships.

### C3 — Synthetic data + log scrubbing

- Synthea fixtures in `tests/fixtures/synthea/`. Replace any
  real-shaped test data.
- Python `logging.Filter` redactor wrapping root logger.
- Global FastAPI exception handler — `{error, request_id}` to client,
  scrubbed trace to server log only.
- Audit all frontend routes — no PHI in URLs, UUIDs only.
- `Cache-Control: no-store` middleware on `/api/records/*`.

**Placement:** must land before any non-Sam data enters the system.
Friend’s deployment requires this.

### C4 — Audit logging

`audit_log` table, hash chain, insert-only Postgres role, write-ahead
inserts, retention env var, FastAPI dependency wrapping PHI endpoints.

**Placement:** B3 depends on this. Friend deployment requires this.

### C5 — De-identification pipeline

Microsoft Presidio sidecar (`hlh_redact`), Layer A (regex+validators
for SSN/NPI/DEA/MRN/dates/ZIP/IP/MAC), Layer B (clinical NER —
`obi/deid_roberta_i2b2` vs `openai/privacy-filter` bake-off), Layer C
(generic PII NER). Policy: `HLH_REDACTION_POLICY=strict|standard| permissive`.

Integration:

- Pre-write redactor (optional, off by default for Sam, **on** by
  default for friend deployment — env-defaulted).
- Pre-inference redactor (off for local llama-swap, on for any
  external provider).
- Log scrubber upgrade: S3’s regex replaced by Presidio pipeline.

**Placement:** A2 (embed+rerank) merge gate. RAG-into-pgvector
without de-id means PHI in vectors forever.

### C6 — Column encryption

KEK/DEK envelope. `HLH_MASTER_KEY` in env. Per-record DEK via HKDF.
AES-256-GCM on `record_text_enc`. Migration script idempotent +
resumable. `pg_dump` to encrypted file pre-migration.

Caveat: embedding vectors are partially invertible. Encrypt source
chunk text column; leave vectors in plaintext (cosine search
requires plaintext). Document this honestly.

**Placement:** must land before friend gets the URL. The friend
case is the canonical reason this exists.

### C7 — LLM I/O guardrails

`llm-guard` sidecar — same sidecar as B1. Different scanner config.

Input scanners: prompt injection, ban substrings, token limit, PII
(redundant with C5 pre-inference but cheap second layer).

Output scanners: PII regurgitation, refusal categories (overlaps
with B1), hallucinated identifiers.

**Placement:** B1 and C7 are the same deployable. Ship together.

### C8 — Supply chain + ops

`make security` target: trivy + pip-audit + npm audit + syft SBOM.
Renovate or Dependabot. Container image scanning. SOPS + age for
encrypted `.env` files. Pre-commit `.env` check.

**Placement:** independent. Do anytime. Half-day cost.

### C9 — Right-to-erasure

Hard delete by default. Cascade to chunks, embeddings, AI summaries,
audit log content fields (with `tombstoned_at` preserving the
existence record). Document backup conflict honestly. Configurable
retention via `HLH_MAX_RECORD_AGE_DAYS`.

**Placement:** must land before friend gets the URL. Two-day cost,
mostly cascade auditing.

-----

## Ship-to-friend gate

The friend’s deployment URL is not handed over until every box below
is checked.

**Built-in AI:**

- [x] A1 merged to `main`
- [ ] A1.5 merged to `main` (partial — `is_bundled` shipped;
  hardening/pinning/network split remaining)
- [x] A1.6 workspace auto-bind + settings lockdown
- [ ] A1.7 operator pre-flight + first-launch ack
- [x] A2 merged to `main` (no real-record ingest until C5)
- [ ] A3 merged or explicitly deferred with friend’s consent (e.g.,
  she doesn’t need vision)
- [ ] A4 merged or explicitly deferred
- [x] A7 bundled search (default-on; revisit posture for friend
  deployment at A1.7)

**Safeguards:**

- [x] B0 system prompt locked in (post-A1 reconciliation)
- [ ] B1 output scanner sidecar shipped
- [ ] B2 UI disclaimers + crisis card shipped
- [ ] B3 audit-logged refusals shipped (depends on C4)
- [ ] B4 red-team eval pass on current model defaults

**Security:**

- [ ] C0 docs shipped
- [ ] C1 disk + backup hygiene confirmed on friend’s host
- [ ] C2 docker hardening (lands with A1.5 — still pending)
- [ ] C3 synthetic data + log scrubbing shipped
- [ ] C4 audit logging shipped
- [ ] C5 de-id pipeline shipped, pre-write redactor defaulted **on**
  for non-Sam deployments. **Blocks first real-record ingest.**
- [ ] C6 column encryption shipped, friend’s `HLH_MASTER_KEY`
  generated + stored + key custody documented for her
- [ ] C7 LLM I/O guardrails (lands with B1)
- [ ] C8 supply chain hardening shipped
- [ ] C9 right-to-erasure shipped

**Public-release-readiness** (deferred decision, but docs treat it
as coming):

- [ ] All checkboxes above
- [ ] `SECURITY.md` vulnerability disclosure policy active
- [ ] `LICENSE` file (AGPL-3.0) committed
- [ ] README final pass — honest, no weasel words, names non-defenses
- [ ] `THREATMODEL.md` reviewed by a second pair of eyes
- [ ] Tagged `v1.0.0`

-----

## Cross-cutting items

Apply continuously, not as phases:

- No PHI in client-side `console.log`. Pre-commit hook or lint rule.
- No telemetry. No Sentry. No analytics. Opt-in only, if ever.
- HTTPS-only cookies. `__Host-` prefix, `HttpOnly`, `Secure`,
  `SameSite=Strict`.
- Short session timeout (15-30 min idle).
- `autocomplete="off"` on PHI fields.
- `[SECURITY]` commit-message prefix on anything touching auth,
  crypto, redaction, audit, or safeguards.
- Every release tagged. No “release” via `latest` Docker tag.
- Theme toggle, design tokens, and typography baseline shipped
  alongside Phase 1 work. Not a tracked phase; future UX work folds
  into whichever phase touches the affected surface.

-----

## What we deliberately are NOT doing

Out of scope. Listed so future-Sam doesn’t re-litigate.

- Differential privacy (not training, not aggregate stats).
- Homomorphic encryption (1000× perf hit, theater).
- TEE / SGX / SEV / TDX (same reason).
- Federated learning (single-user).
- Two-person rule (single-user).
- HSM-signed external audit log (Postgres hash chain is enough;
  `immudb` documented as upgrade path).
- Formal compliance certification (HIPAA / HITRUST / SOC 2). HLH is
  not a covered entity. Disclaim explicitly.
- llama-swap front-end (operator can layer via `external` tier).
- Fine-tuning UI.
- LoRA hot-swap.
- Multi-host inference within a single HLH instance.
- BYOM file upload (HF-pull only).
- User override on safeguard refusals.

-----

## Open questions

Resolve at the phase where they become blocking.

- **A2 Q:** infinity-emb vs llama.cpp embedding server. Bake-off at
  A2 kickoff.
- **A3 Q:** MedSigLIP license redistribution terms. If forbidden,
  manual-download flow.
- **A4 Q:** STT input transcode browser-side vs `hlh_api`-side.
- **A5 Q:** dedicated OCR needed at all? End-of-A3 eval decides.
- **A7 Q:** search egress posture for friend deployment. Shipped
  default-on. Revisit if she finds it confusing, if PHI-in-query
  incidents occur, or at A1.7 when first-launch ack lands.
- **B1 Q:** llm-guard scanner threshold tuning. Iterate via B4 eval
  history.
- **B2 Q:** crisis hotline numbers per locale. Friend is US; expand
  list only if other locales come up.
- **C5 Q:** clinical NER bake-off — `obi/deid_roberta_i2b2` vs
  `openai/privacy-filter`. Synthea eval set decides.
- **C6 Q:** encrypt embedding vectors? Practical answer: no (cosine
  search needs plaintext). Document the risk in
  `THREATMODEL.md`.
- **Public release Q:** still deferred. Trigger to revisit: A4
  shipped + friend running it for 30 days incident-free + at least
  one other person asks to self-host.

-----

## Effort estimate (rough)

|Track          |Phases                                                                                                      |Total                    |
|---------------|------------------------------------------------------------------------------------------------------------|-------------------------|
|A — Built-in AI|A1 (done) + A1.5 finish (2d) + A1.6 (done) + A1.7 (1d) + A2 (done) + A3 (5d) + A4 (3d) + A5? + A6 + A7 (done)|~1.5 weeks if A5/A6 skipped|
|B — Safeguards |B0 (done) + B1 (3d) + B2 (2d) + B3 (1d on top of C4) + B4 (ongoing)                                         |~1 week + ongoing        |
|C — Security   |C0 (1d) + C1 (2hr) + C2 (in A1.5) + C3 (2d) + C4 (3d) + C5 (5-7d) + C6 (5d) + C7 (in B1) + C8 (1d) + C9 (2d)|~3-4 weeks               |

**Total to ship-to-friend gate: 5-6 weeks of focused work** (revised
down: A1.6, A2, A7, B0 already shipped). Open-ended timeline means
this is the *floor*; reality is “until done right.”

-----

## Triggers to accelerate or pause

**Accelerate** if:

- Friend asks when she can start using it. Answer is still “when it’s
  done” — but it sharpens prioritization.
- Sam discovers his own clinical use creep (he’s MSW; the tool is
  tempting). Strengthens the no-override safeguard stance.

**Pause** if:

- A model default changes in a way that breaks the safeguard prompt
  (run B4 immediately, don’t ship).
- A C-track CVE drops on a dep (drop A-track work, ship the C patch).
- Friend’s deployment infrastructure changes (rebuild C1 plan for her
  new host).

-----

## File locations

- This file: `docs/roadmap.md` — canonical source of truth for AI,
  safeguards, and security.
- Phase 1 design + dispatch (historical): `docs/phase-1-design.md`,
  `docs/phase-1-dispatch.md`.
- Phase 0 historical: `docs/hlh_phase0_design.md`,
  `docs/hlh_phase0_dispatch.md`.
- Old security plan: `docs/security/SECURITY_PLAN.md` was deleted in
  the commit that landed this roadmap; content folded into Track C.
- Safeguard eval history: `docs/safeguards/eval-history.md` (B4
  creates this).
- Per-phase specs as they kick off:
  `docs/superpowers/specs/YYYY-MM-DD-<phase>-design.md`.
