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

_No entries yet._

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
