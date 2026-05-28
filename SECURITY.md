# Security

## Status

homelabhealth is a single-maintainer personal project, MIT-licensed. There is no security team, no SLA, and no private disclosure channel. The maintainer has no legal capacity to make safe-harbor or coordinated-disclosure commitments and does not do so.

## Reporting

Email **sam@indifferentketchup.com** with subject line `[HLH SECURITY]`.

Include: a description of the issue, affected version (git SHA or tag), reproduction steps if
available, and whether you have disclosed elsewhere.

The maintainer will acknowledge receipt within 5 business days. Confirmation or refutation
within 14 days. Fix or workaround within 30 days for high-severity issues.

## In scope

- The `main` branch of this repository.
- The latest tagged release.
- The bundled sidecars as configured by the default `docker-compose.yml`: `hlh_api`, `hlh_chat`, `hlh_vision_embed`, `hlh_orchestra`, `hlh_search`, `hlh_ui`, `hlh_db`.

## Out of scope

- Third-party services reached by the app: HuggingFace, SearXNG upstream engines, external LLM providers.
- Optional operator reverse proxy layered in front. Not required; built-in auth ships in-app (v0.19.0).
- Self-hosted dependencies outside compose: host OS, Docker daemon.
- Denial-of-service against bundled inference. Resource exhaustion is an operator capacity-planning concern, not a vulnerability.
- Social engineering of the maintainer.

## What this project is not

- Not a HIPAA covered entity.
- Not compliance-certified. HIPAA, HITRUST, and SOC 2 are explicitly out of scope.
- Not formally threat-modeled by a third party. `THREATMODEL.md` is a self-assessment by the maintainer.

## Related documents

- [`THREATMODEL.md`](./THREATMODEL.md): what the app defends, what it does not, and the trust boundaries.
- [`docs/safe-harbor.md`](./docs/safe-harbor.md): disclaimer covering security research. The maintainer makes no commitments.
- [`docs/breach-response.md`](./docs/breach-response.md): operator playbook for suspected exposure.

Last reviewed: 2026-05-28.
