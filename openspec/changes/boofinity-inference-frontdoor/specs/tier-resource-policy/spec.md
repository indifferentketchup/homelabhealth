# Delta spec: tier-resource-policy (B5)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: resource_policy SHALL encode per-tier coresidency rules

`backend/services/resource_policy.py` SHALL exist as a pure policy module (no DB,
no HTTP, no background task) that maps each tier to the set of model roles
allowed VRAM-resident simultaneously and to the swap-group layout (one exclusive
group versus split non-exclusive groups). It SHALL expose `policy_for(tier)` and
`coresident(tier)`.

#### Scenario: constrained tier uses one exclusive swap group

- **GIVEN** `resource_policy.policy_for("gpu-4gb")`
- **WHEN** the returned policy is read
- **THEN** `swap_group_exclusive` SHALL be `True`
- **AND** the coresident role set SHALL NOT permit chat and embed together

#### Scenario: roomy tier allows coresident backends

- **GIVEN** `resource_policy.policy_for("gpu-24gb+")`
- **WHEN** the returned policy is read
- **THEN** `swap_group_exclusive` SHALL be `False`
- **AND** the coresident role set SHALL permit chat and embed together

#### Scenario: module is pure

- **GIVEN** `backend/services/resource_policy.py`
- **WHEN** its imports are read
- **THEN** it SHALL NOT import a database, HTTP client, or asyncio task primitive

### Requirement: resource_policy SHALL decide Gemma degradation under pressure

`resource_policy.py` SHALL expose `gemma_degradation(tier)` returning either
`"offload_cpu"` (Gemma runs on CPU, slow) or `"unavailable"` (Gemma is dropped
with a warning) per the ADR-0002 tier semantics. The smallest GPU tier SHALL
return `"unavailable"`; CPU tiers SHALL return `"offload_cpu"`.

#### Scenario: smallest GPU tier drops Gemma with a warning

- **GIVEN** `resource_policy.gemma_degradation("gpu-4gb")`
- **WHEN** the result is read
- **THEN** it SHALL equal `"unavailable"`

#### Scenario: CPU tier offloads Gemma rather than dropping it

- **GIVEN** `resource_policy.gemma_degradation("cpu-std")`
- **WHEN** the result is read
- **THEN** it SHALL equal `"offload_cpu"`

#### Scenario: every known tier resolves to a valid degradation mode

- **GIVEN** each tier in the policy map
- **WHEN** `gemma_degradation(tier)` is called
- **THEN** the result SHALL be one of `"offload_cpu"` or `"unavailable"`

### Requirement: pipeline_status SHALL surface a model-swapping state

`backend/services/pipeline_status.py` SHALL add a `swapping` stage so the
frontend can render an "embedding / model-swapping" phase while llama-swap loads
a backend. The estimate-key table SHALL include a `swapping` entry, and the
module SHALL expose a helper that maps the front-door's model status to one of
`loaded`, `swapping`, or `unavailable`.

#### Scenario: swapping stage has an estimate key

- **GIVEN** `pipeline_status._estimate_key("swapping")`
- **WHEN** the result is read
- **THEN** it SHALL be a non-empty estimate key string

#### Scenario: front-door status maps to a backend state

- **GIVEN** a helper that reads `hlh_swap`'s `/v1/models` status for a model
- **WHEN** the model is mid-load
- **THEN** the helper SHALL return `swapping`
- **AND** WHEN the model is ready it SHALL return `loaded`
- **AND** WHEN the front-door is unreachable it SHALL return `unavailable`
