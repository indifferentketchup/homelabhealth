# Security

## Status

homelabhealth is a single-maintainer personal project, MIT-licensed. There is no security team, no SLA, and no private disclosure channel. The maintainer has no legal capacity to make safe-harbor or coordinated-disclosure commitments and does not do so.

## Reporting

If you find a vulnerability, open a public issue on the repository describing it. There is no embargo, no coordinated-disclosure window, no acknowledgement timeline, and no triage process. The maintainer may fix it, may not, and may take any amount of time.

**Do not contact the maintainer privately about vulnerabilities.** Private reports will not be prioritized and may not be answered.

## In scope

- The `main` branch of this repository.
- The latest tagged release.
- The bundled sidecars as configured by the default `docker-compose.yml`: `hlh_api`, `hlh_chat`, `hlh_infer`, `hlh_search`, `hlh_ui`, `hlh_db`.

## Out of scope

- Third-party services reached by the app: HuggingFace, the search engines reached via SearXNG (Google, Brave, Mojeek, Startpage, arxiv, pubmed), and any external LLM provider the operator configures.
- The operator-deployed reverse proxy and auth layer (Authelia, oauth2-proxy, nginx basic auth, etc). This is the operator's responsibility.
- Self-hosted dependencies running on the operator's host: Postgres instances outside compose, the host OS, the Docker daemon.
- Denial-of-service against bundled inference. Resource exhaustion is an operator capacity-planning concern, not a vulnerability.
- Social engineering of the maintainer.

## What this project is not

- Not a HIPAA covered entity.
- Not compliance-certified. HIPAA, HITRUST, and SOC 2 are explicitly out of scope.
- Not formally threat-modeled by a third party. `THREATMODEL.md` is a self-assessment by the maintainer.

## Related documents

- [`THREATMODEL.md`](./THREATMODEL.md) — what the app defends, what it does not, and the trust boundaries.
- [`docs/safe-harbor.md`](./docs/safe-harbor.md) — disclaimer covering security research. The maintainer makes no commitments.
- [`docs/breach-response.md`](./docs/breach-response.md) — operator playbook for suspected exposure.

Last reviewed: 2026-05-22.
