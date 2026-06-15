# Threat Model

## Overview

homelabhealth is a single-user, self-hosted RAG chat application for personal medical records.
It runs as a Docker Compose stack. **Built-in username/password auth** (v0.19.0) validates
`hlh_session` cookies on every API request. An operator may optionally layer a reverse proxy
in front for defense in depth. Not required for default deploy.

This project is MIT-licensed. It is not formally threat-modeled by a third party. It is not a
HIPAA covered entity. HIPAA, HITRUST, and SOC 2 certification are explicitly out of scope. This
is a personal tool, not a healthcare product. This document is a self-assessment by the
maintainer; it reflects the state of the stack as of 2026-05-28 and is revised at every
minor-version tag.

Last reviewed: 2026-05-28.

---

## Trust boundaries

Three boundaries define the security perimeter.

**Boundary 1. Browser to hlh_api.** The UI (`hlh_ui`, port 9604) and API (`hlh_api`, port 9600)
communicate over HTTP(S) as configured by the operator. Authentication is enforced by
`backend/deps.py`: every protected route requires a valid `hlh_session` cookie (argon2-backed
password auth, v0.19.0). Unauthenticated requests receive 401. An optional reverse proxy may sit in front; that layer is operator-owned and adds
defense in depth but is not required.

**Boundary 2. hlh_api to host network.** Traffic from the browser reaches `hlh_api` on the
operator's LAN or VPN. TLS termination is operator-configured (reverse proxy or direct). `hlh_api` binds `0.0.0.0:9600` by default.

**Boundary 3. hlh_api to bundled sidecars.** Two internal networks carry sidecar traffic.
The `hlh_inference` network (`internal: true`) connects `hlh_api` to `hlh_chat`; no host
ports are bound on `hlh_chat`. Docker's `internal: true` prevents the network from routing
to the host's external interfaces. The `hlh_default` network connects `hlh_api` to
`hlh_search`, `hlh_db`, and `hlh_orchestra`.

---

## What this defends

### Built-in authentication (v0.19.0)

`backend/deps.py` validates the `hlh_session` cookie on every protected request via
`services/auth.py` (argon2 password hashing, server-side session rows). Setup wizard
(`POST /api/auth/setup`) creates the owner account on first launch. There is no anonymous
access to PHI endpoints. Session cookies are not yet `Secure`-flagged when HTTPS is absent
(see `routers/auth.py`. operator should terminate TLS at a reverse proxy for production).

### Container hardening

`hlh_chat` and `hlh_orchestra` run with `read_only: true`,
`cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`. `hlh_chat` has no host ports
and is isolated on `hlh_inference` (`internal: true`).
Image tags are pinned: `ghcr.io/ggml-org/llama.cpp:server-b9628` and
`searxng/searxng:2026.5.22-c57f772ad`. Hardening is verified by
`backend/scripts/verify_a1_5_hardening.sh`. Shipped in v0.8.0.

### Bundled provider immutability

Bundled provider rows (`is_bundled=TRUE`) reject `PATCH` and `DELETE` with HTTP 403 from the
API, regardless of UI state. This prevents an operator from accidentally removing the chat,
embed, or rerank sidecars via the settings UI. The enforcement lives in `routers/providers.py`.
Verified by `backend/scripts/verify_bundled_immutability.sh`. Shipped in v0.7.0.

### Provider secret encryption at rest

`providers.api_key` and the singleton HF token are Fernet-encrypted via the
`PROVIDER_KEY_ENCRYPTION_KEY` environment variable (`services/crypto.py`). Fernet uses
AES-128-CBC with HMAC-SHA256 for authentication. Both values fall back to cleartext storage
when the env var is unset. see "PROVIDER_KEY_ENCRYPTION_KEY cleartext fallback" below for
the risk profile of that fallback. The encryption key itself must be kept outside the database;
the recommended location is the `.env` file, which must not be committed to version control.

### B0 safeguard preamble

A tiered-refusal system prompt is prepended to every assistant turn by `services/safeguards.py`
(constants: `SAFEGUARD_VERSION`, function: `prepend_safeguard()`). The preamble is locked in
by `routers/chats.py:_assembled_system_prompt`. Workspace system prompts append after it; they
cannot replace it. Each outbound message records the active safeguard version in
`messages.safeguard_version`, making policy drift auditable across forks and conversation
histories. Verified by `backend/scripts/verify_safeguards_assembler.py` (chokepoint
enforcement) and `backend/scripts/verify_safeguards_persistence.py` (DB write). Shipped in
v0.6.0.

### Operator pre-flight

`python -m hlh.doctor` (also `GET /api/system/doctor`) runs health checks at container start
and on demand: DB pool, schema, sidecars, vision mmproj, safeguard version, disk free,
encryption keys, audit chain integrity, guard scanners, de-id pipeline, column encryption,
and more. Advanced host checks (LUKS, backrest) run in CLI only. hidden from the Settings UI.
The doctor exits 0 if all checks are green/yellow, 1 if any check is red. Shipped in v0.8.0;
expanded through v0.25.0.

### Audit logging (C4, v0.11.0)

Hash-chained `audit_log` table with insert-only Postgres role (`hlh_audit_writer`). Guard
refusals (B3, v0.23.0) write `safeguard.refuse.input` and `safeguard.flag.output` rows.
Verified by `backend/scripts/verify_audit_log.sh`.

### De-identification pipeline (C5, v0.16.0)

Regex-based PHI redaction (`services/deid.py`) with configurable policy levels. Pre-write
redactor on ingest. Gates first real-record ingest. do not disable for non-operator deployments.

### Column encryption (C6, v0.17.0)

AES-256-GCM on sensitive columns via HKDF-derived DEKs from `HLH_MASTER_KEY`. Embedding
vectors remain plaintext (cosine search requirement). documented honestly.

### I/O guard scanner (B1 + C7, v0.14.0)

In-process input/output scanning (`services/guard.py`): prompt injection, PII, medical advice,
crisis content, hallucinated identifiers. Not a separate sidecar. runs inside `hlh_api`.

---

## What this does NOT defend

### A7. search egress

`hlh_search` (SearXNG) is default-on. Operator queries reach Google, Brave, Mojeek, Startpage,
arxiv, and pubmed (current defaults seeded in the `searxng_config` table). SearXNG
anonymizes transport. no cookies, no user-agent leaks, no persistent session state are sent
to upstream engines. but query content is visible to whichever engine processes it. PHI in
search queries is user-discipline-bound, not technically enforced. No content scanner runs
against outbound search queries today. The operator bears this risk entirely; the application
provides no guardrail. Documented in C0 (v0.9.0).

### Embedding vector invertibility

De-identification (C5) runs before chunking, but embedding vectors in `source_chunks` are
partially invertible. Source chunk text may be column-encrypted (C6); vectors stay plaintext
for cosine search. Re-embed after policy changes if vectors may contain pre-redaction content.

### PROVIDER_KEY_ENCRYPTION_KEY cleartext fallback

If `PROVIDER_KEY_ENCRYPTION_KEY` is unset, `providers.api_key` and the HF token are stored as
cleartext in the database. This fallback is intentional. it matches the posture documented
in the Phase 2.A spec §10. but it is fragile: anyone with database access can read provider
secrets directly. The doctor check warns yellow when the key is unset, and reds when the key
is present but malformed. Operators with real provider keys should set this variable.

### B0 + guard are not cryptographic enforcement

The tiered-refusal preamble and in-process guard scanner are best-effort behavioral controls.
A determined operator can craft prompts that subvert prompt-only layers. Treat safeguards as
risk reduction, not a kernel boundary.

### Single-user scope

The app supports one owner account (setup wizard). No multi-user RBAC. Do not expose to
untrusted users without additional perimeter controls.

### Backups and disk-at-rest encryption

Both are operator responsibility. The database holds personal medical records; if disk-at-rest
encryption is absent and the host is stolen or decommissioned, that data is accessible to
whoever holds the disk. The recommended stack is LUKS for disk encryption and backrest for
backup management. documented under `docs/operator/advanced/` but not provisioned by the app.
Doctor checks for LUKS/backrest are advanced/optional (v0.10.1 demotion). The operator bears
both risks unless configured on the host.

### No third-party threat model

This document is a self-assessment by the maintainer. It is written honestly but cannot
substitute for independent review. Public-release readiness (v1.0.0) requires a second pair
of eyes as stated in the ship-to-friend gate in `docs/roadmap.md`. Until that review occurs,
treat every claim in this document as preliminary.

---

## Adversary classes

- **External attacker (unauthenticated).** Can reach the login page if HLH is internet-exposed. Cannot reach PHI without valid credentials. If HLH is behind a VPN or proxy with its own auth, the attacker cannot reach the login page at all.
- **Attacker on operator's LAN.** Can reach any port the operator binds to LAN interfaces. Cannot bypass built-in auth. Defense is operator network configuration.
- **Authenticated operator.** Full app access. Trusted. Threat model assumes the operator does not exfiltrate their own data.
- **Compromised model.** Bundled AI models receive PHI inputs. No defense beyond not exposing the chat sidecar to external networks (already on `internal: true`).
- **Compromised dependency.** HF hub, PyPI, npm. Defense today: pinned image tags and pinned package versions. Supply chain hardening (C8) addresses this in a later release.

---

## Risk register

- **R-001 SearXNG PHI exfiltration.** Operator types PHI into search. SearXNG forwards to third-party engines. Severity: high. Defense: operator discipline + pending UI disclaimers (B2). Status: documented, not mitigated.
- **R-002 Model output PHI memorization.** Bundled models trained on public corpora. Risk of regurgitating other users' data is low but non-zero. Defense: no fine-tuning on user data. Status: structural.
- **R-003 Docker socket compromise via hlh_orchestra.** If hlh_orchestra is compromised, attacker has Docker daemon access on the host. Defenses: minimal code surface (<200 lines), hardcoded container allowlist, token auth, read_only rootfs, cap_drop ALL, no-new-privileges. Residual: yes. Status: documented, accepted, minimized.
- **R-004 Backup compromise.** Backrest repo on operator's chosen storage. If that storage is compromised, PHI is exposed. Defense: per-operator passphrase generated at install. Status: deferred to operator's choice of repo backend.
- **R-005 No TLS enforcement.** HLH does not require TLS. An operator who exposes HLH on `0.0.0.0` without TLS ships credentials and PHI in cleartext. Defense: README warns; doctor check pending. Status: operator discipline.
- **R-006 Embedding vector invertibility.** Vectors in `source_chunks` are partially invertible. Source text may be column-encrypted (C6); vectors stay plaintext for cosine search. Status: documented, accepted for single-operator stage.

---

## Out of scope

The following are out of scope by design. These items will not be addressed:

- HIPAA covered-entity status: out of scope. This is a personal tool.
- HITRUST / SOC 2 certification: out of scope.
- Differential privacy, homomorphic encryption, TEE / SGX / SEV / TDX, federated learning:
  out of scope. See `docs/roadmap.md` "What we deliberately are NOT doing".
- HSM-signed external audit log: out of scope. Postgres hash chain (C4) is the planned
  ceiling; `immudb` is documented in `docs/roadmap.md` as an upgrade path.
- Fine-tuning, LoRA hot-swap, multi-host inference, BYOM file upload: out of scope.
- User override of safeguard refusals: out of scope by design.

---

## Review cadence

This document is reviewed at every minor-version tag and whenever the following change:
hardening posture, network topology, encrypted columns, safeguard pipeline, or the C5 ingest
gate. Owner: Sam. Last reviewed: 2026-05-28.
