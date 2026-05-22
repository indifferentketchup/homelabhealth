# Threat Model

## Overview

homelabhealth is a single-user, self-hosted RAG chat application for personal medical records.
It runs as a Docker Compose stack on a homelab host, accessible through an operator-owned reverse
proxy. The operator and the sole user are the same person.

This project is MIT-licensed. It is not formally threat-modeled by a third party. It is not a
HIPAA covered entity. HIPAA, HITRUST, and SOC 2 certification are explicitly out of scope — this
is a personal tool, not a healthcare product. This document is a self-assessment by the
maintainer; it reflects the state of the stack as of 2026-05-22 and is revised at every
minor-version tag.

Last reviewed: 2026-05-22.

---

## Trust boundaries

Three boundaries define the security perimeter.

**Boundary 1 — Browser to reverse proxy.** The operator's reverse proxy (Authelia,
oauth2-proxy, nginx basic auth, or equivalent) is responsible for authenticating the user before
any request reaches `hlh_api`. The application trusts `Remote-User` from upstream without
further validation. This boundary is operator-owned and operator-configured. The application
documents this expectation but does not enforce it.

**Boundary 2 — Reverse proxy to hlh_api.** Traffic from the reverse proxy to `hlh_api`
traverses the operator's Tailscale mesh or LAN. This boundary's security properties are
operator-configured. `hlh_api` does not terminate TLS directly.

**Boundary 3 — hlh_api to bundled sidecars.** Two internal networks carry sidecar traffic.
The `hlh_inference` network (`internal: true`) connects `hlh_api` to `hlh_chat` and
`hlh_infer`; no host ports are bound on these two containers. Docker's `internal: true`
prevents the network from routing to the host's external interfaces — containers on this
network can only communicate with each other and with other containers that are also on it.
The `hlh_default` network connects `hlh_api` to `hlh_search` and `hlh_db`. `hlh_infer` is
dual-homed — it joins both networks to allow HuggingFace weight downloads while staying
isolated from host-port exposure. This dual-homing is a deliberate trade-off: the alternative
is a manual weight-pull procedure on every model update.

---

## What this defends

### Operator auth perimeter

The API is designed to run behind an operator-owned reverse proxy that handles authentication.
`backend/deps.py` returns the seeded owner row from `users` for every request — it does not
perform authentication itself. This posture is documented in `README.md` (Auth section) and
is the explicit design choice for a single-user tool. The application trusts `Remote-User`
from upstream without further validation; the operator is responsible for ensuring the proxy
enforces it.

### Container hardening

`hlh_chat` and `hlh_infer` run with `read_only: true`, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, and no host ports bound. Both are isolated on the
`hlh_inference` internal network (`internal: true`). `hlh_infer` is dual-homed for HuggingFace
egress — this is a conscious trade-off documented in the compose file.
Image tags are pinned: `ghcr.io/ggml-org/llama.cpp:server-b9282` and
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
when the env var is unset — see "PROVIDER_KEY_ENCRYPTION_KEY cleartext fallback" below for
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

`python -m hlh.doctor` (also `GET /api/system/doctor`) runs 11 checks at first launch and on
demand: DB pool, schema version, sidecar reachability, safeguard version import, disk free,
encryption key presence, and HF token. The doctor exits 0 if all checks are green, 1 if any
check is red. Surfaced in the UI at Settings → System → Pre-flight. Shipped in v0.8.0.

---

## What this does NOT defend

### A7 — search egress

`hlh_search` (SearXNG) is default-on. Operator queries reach Google, Brave, Mojeek, Startpage,
arxiv, and pubmed (current defaults seeded in the `searxng_config` table). SearXNG
anonymizes transport — no cookies, no user-agent leaks, no persistent session state are sent
to upstream engines — but query content is visible to whichever engine processes it. PHI in
search queries is user-discipline-bound, not technically enforced. No content scanner runs
against outbound search queries today. The operator bears this risk entirely; the application
provides no guardrail. No mitigation is planned for v0.9.0; the risk is documented here so the
operator understands the boundary. The A7 threat-model entry was deferred to C0 per the
note in `docs/roadmap.md` (A7, v0.7.0).

### C5 first-real-ingest gate — open

`source_chunks` (pgvector) is empty at this writing. The embedding sidecar (`hlh_infer`, A2)
shipped in v0.7.0 ahead of the de-identification pipeline (C5, planned v0.17.0). The operator
must keep `source_chunks` empty until C5 ships. If any record is ingested before C5 lands,
`TRUNCATE source_chunks` and re-run ingest after C5 is deployed. Embedding vectors are
partially invertible; raw PHI captured in vectors is forever-PHI. This risk is borne entirely
by the operator until v0.17.0. The second correction in the A1 section of `docs/roadmap.md`
documents how this gate was originally worded and why it was retained despite A2 shipping
first.

### PROVIDER_KEY_ENCRYPTION_KEY cleartext fallback

If `PROVIDER_KEY_ENCRYPTION_KEY` is unset, `providers.api_key` and the HF token are stored as
cleartext in the database. This fallback is intentional — it matches the posture documented
in the Phase 2.A spec §10 — but it is fragile: anyone with database access can read provider
secrets directly. The doctor check warns yellow when the key is unset, and reds when the key
is present but malformed. Operators with real provider keys should set this variable.

### Audit logging not yet implemented

There is no `audit_log` table, no hash chain, and no insert-only Postgres role. Post-incident
forensics relies on Postgres logs and container stdout, both of which are unstructured and
subject to host-level access controls (or absence thereof). If the host is compromised, those
logs may be tampered with or absent. The operator bears the forensic-capability gap until C4
(v0.12.0) lands. Until then, the breach response playbook in `docs/breach-response.md`
documents what evidence to capture at incident time using the tools that are available.

### B0 safeguards are defeatable

The tiered-refusal preamble lives in the system prompt only. A determined operator — the only
user — can craft prompts that subvert it. This is a structural limitation of prompt-only
controls: the model sees the preamble as text, not as a kernel-level enforcement boundary.
The output-scanner sidecar (`hlh_guard`, llm-guard) that will provide a second enforcement
layer lands in B1 / C7 (v0.15.0). Until then, treat B0 as best-effort behavioral guidance,
not a security control. The operator bears full responsibility for any misuse of the model
before v0.15.0 ships.

### Multi-user auth not in scope

The app assumes a single user. Multi-user access is delegated entirely to the operator's
reverse proxy (Authelia, oauth2-proxy, nginx basic auth). There is no `user` table beyond the
seeded owner row, no session table, and no RBAC layer. `Remote-User` is trusted from upstream
without further validation. Do not expose this app to untrusted users through a proxy that
does not enforce authentication.

### Backups and disk-at-rest encryption

Both are operator responsibility. The database holds personal medical records; if disk-at-rest
encryption is absent and the host is stolen or decommissioned, that data is accessible to
whoever holds the disk. The recommended stack is LUKS for disk encryption and backrest for
backup management — these are documented in `docs/breach-response.md` but are not provisioned
or enforced by the application. The operator bears both risks in full until C1 (v0.10.0) ships.
C1 will add doctor checks confirming LUKS and backrest presence on the host, but will not
provision them automatically.

### No third-party threat model

This document is a self-assessment by the maintainer. It is written honestly but cannot
substitute for independent review. Public-release readiness (v1.0.0) requires a second pair
of eyes as stated in the ship-to-friend gate in `docs/roadmap.md`. Until that review occurs,
treat every claim in this document as preliminary.

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
gate. Owner: Sam. Last reviewed: 2026-05-22.
