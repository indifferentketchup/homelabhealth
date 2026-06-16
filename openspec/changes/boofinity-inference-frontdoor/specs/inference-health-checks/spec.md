# Delta spec: inference-health-checks (B6, B7)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: doctor SHALL check hlh_swap reachability

`backend/hlh/doctor.py` `run_checks` SHALL include a sidecar check for
`hlh_swap` probing `http://hlh_swap:9620/v1/models`. A connection refusal SHALL
be ERROR; a non-200 SHALL be WARN (still booting); a 200 SHALL be OK.

#### Scenario: unreachable front-door is an error

- **GIVEN** `hlh_swap` is not reachable
- **WHEN** `run_checks` runs
- **THEN** the result SHALL include a check named `hlh_swap_reachable` with status ERROR

#### Scenario: healthy front-door is ok

- **GIVEN** `hlh_swap` returns 200 on `/v1/models`
- **WHEN** `run_checks` runs
- **THEN** the `hlh_swap_reachable` check SHALL have status OK

### Requirement: doctor SHALL check the boofinity child /health through the front-door

`backend/hlh/doctor.py` `run_checks` SHALL include a check that probes the
boofinity child's readiness through the front-door (`http://hlh_swap:9620/v1/health`
or llama-swap's `/upstream` passthrough to a boofinity alias). Because boofinity
runs as a child process of `hlh_swap` with no separate container, there is no
standalone `hlh_infer:7997` endpoint to probe. Connection refusal SHALL be ERROR;
non-200 SHALL be WARN; 200 SHALL be OK.

#### Scenario: unreachable boofinity child is flagged

- **GIVEN** the boofinity child is not reachable through `hlh_swap`
- **WHEN** `run_checks` runs
- **THEN** the result SHALL include a boofinity-child health check with status ERROR

#### Scenario: the check targets the front-door, not a standalone container

- **GIVEN** `backend/hlh/doctor.py`
- **WHEN** the boofinity-child check target is read
- **THEN** it SHALL probe through `hlh_swap:9620`
- **AND** it SHALL NOT probe a standalone `hlh_infer:7997` container endpoint

### Requirement: doctor SHALL flag the un-rebound embed/rerank intermediate state

`backend/hlh/doctor.py` `run_checks` SHALL include a check that detects the B/C
out-of-order deploy state: `models.ini` no longer serves `[qwen3-embed]` /
`[qwen3-reranker]` (folder B removed them) while a bundled embed or rerank
provider row still has `base_url = http://hlh_chat:9610` (folder C's rebind has
not landed). In that state embed/rerank silently 404. The check SHALL report
ERROR with a remedy pointing at folder C's provider rebind, so the
un-rebound state is a boot-time error rather than a silent retrieval failure.

#### Scenario: bundled provider still on hlh_chat after models.ini removal is an error

- **GIVEN** `models.ini` no longer contains `[qwen3-embed]` or `[qwen3-reranker]`
- **AND** a bundled embed or rerank provider row still has `base_url = 'http://hlh_chat:9610'`
- **WHEN** `run_checks` runs
- **THEN** the result SHALL include a check reporting status ERROR
- **AND** its detail SHALL reference repointing the provider to the front-door

#### Scenario: rebound providers pass the consistency check

- **GIVEN** the bundled embed and rerank providers have `base_url = 'http://hlh_swap:9620'`
- **WHEN** `run_checks` runs
- **THEN** the consistency check SHALL have status OK

### Requirement: image_tier_match SHALL compare the combined swap image

`backend/hlh/doctor.py:_check_image_tier_match` SHALL compare `HLH_SWAP_IMAGE`
against the expected combined-image tag for the tier (`hlh-swap:<ver>-cpu` on CPU
tiers, `...-cuda` on GPU tiers), reporting a stale `.env` as WARN when it
diverges. The former separate `HLH_CHAT_IMAGE` / `HLH_INFER_IMAGE` comparison is
collapsed into this single combined-image comparison.

#### Scenario: stale swap pin is flagged

- **GIVEN** `HLH_SWAP_IMAGE` is set to a tag other than the expected pin
- **WHEN** `_check_image_tier_match` runs for a known tier
- **THEN** the check SHALL report status WARN with a `swap:` mismatch detail

#### Scenario: matching pin passes

- **GIVEN** `HLH_SWAP_IMAGE` matches the expected combined-image tag for the tier
- **WHEN** `_check_image_tier_match` runs
- **THEN** the check SHALL have status OK

## MODIFIED Requirements

### Requirement: hardening verify SHALL cover the combined hlh_swap service

`backend/scripts/verify_a1_5_hardening.sh` SHALL assert that `hlh_swap`'s
`mem_limit` is a positive tier-scaled value rather than a hardcoded 4g, matching
the `HLH_INFER_MEM` written by `image_config.write_tier_env`. `hlh_swap` SHALL be
in the hardened-services list (it is `read_only: true`), its network membership
and no-host-ports assertions SHALL be present, and the script SHALL assert that
no service mounts `/var/run/docker.sock`.

#### Scenario: hlh_swap memory assertion is tier-scaled

- **GIVEN** `backend/scripts/verify_a1_5_hardening.sh`
- **WHEN** the `hlh_swap` memory assertion is read
- **THEN** it SHALL accept any positive value (tier-scaled) and SHALL NOT require exactly `4294967296`

#### Scenario: hlh_swap hardening assertions present and no socket is mounted

- **GIVEN** the verify script
- **WHEN** its container-hardening loop is read
- **THEN** `hlh_swap` SHALL be in the hardened-services list
- **AND** the no-host-ports assertion for `hlh_swap` SHALL be present
- **AND** the script SHALL assert no service mounts `/var/run/docker.sock`
