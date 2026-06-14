# Delta spec: models-ini-tuning (A1)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: [medgemma] section SHALL include V-cache quantization and flash-attn

`hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini` SHALL include
`cache-type-v = q4_0` and `flash-attn = on` in the `[medgemma]` section. The
V-cache SHALL be quantized to q4_0 to match the existing `cache-type-k = q4_0`
set globally in `[*]`, reducing VRAM usage without requiring `GGML_CUDA_FA_ALL_QUANTS`.

#### Scenario: V-cache and flash-attn lines present in [medgemma]

- **GIVEN** `hlh_chat/models.ini`
- **WHEN** the `[medgemma]` section is read
- **THEN** it SHALL contain `cache-type-v = q4_0`
- **AND** it SHALL contain `flash-attn = on`
- **AND** the same lines SHALL be present in `hlh_orchestra/templates/models.ini`

#### Scenario: No flash-attn error on GPU-tier startup

- **WHEN** `docker compose restart hlh_chat` is run on a GPU tier
- **THEN** `docker logs hlh_chat 2>&1 | grep -i flash` SHALL show no error lines
- **AND** the container SHALL remain running and not crash-loop

### Requirement: [medgemma] section SHALL include spec-ngram-mod-n-max tuning

`hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini` SHALL include
`spec-ngram-mod-n-max = 96` in the `[medgemma]` section, overriding the global
default of 64 to allow longer candidate drafts for the larger MedGemma models.

#### Scenario: spec-ngram-mod-n-max present in [medgemma]

- **GIVEN** `hlh_chat/models.ini`
- **WHEN** the `[medgemma]` section is read
- **THEN** it SHALL contain `spec-ngram-mod-n-max = 96`
- **AND** the same line SHALL be present in `hlh_orchestra/templates/models.ini`

### Requirement: [qwen-chat] section SHALL include V-cache quantization, flash-attn, and draft-mtp

`hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini` SHALL include
`cache-type-v = q4_0`, `flash-attn = on`, and `spec-type = draft-mtp` in the
`[qwen-chat]` section. The `spec-type = draft-mtp` SHALL override the global
`spec-type = ngram-mod`, enabling MTP speculative decoding using the MTP heads
embedded in the main model GGUF with no separate draft model required.

#### Scenario: V-cache, flash-attn, and draft-mtp lines present in [qwen-chat]

- **GIVEN** `hlh_chat/models.ini`
- **WHEN** the `[qwen-chat]` section is read
- **THEN** it SHALL contain `cache-type-v = q4_0`
- **AND** it SHALL contain `flash-attn = on`
- **AND** it SHALL contain `spec-type = draft-mtp`
- **AND** the same lines SHALL be present in `hlh_orchestra/templates/models.ini`

#### Scenario: Both models.ini copies are identical for chat sections

- **GIVEN** `hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini`
- **WHEN** the `[medgemma]` and `[qwen-chat]` sections are compared
- **THEN** those sections SHALL be line-for-line identical between the two files

### Requirement: spec-ngram-mod-thsh SHALL be audited against the running binary

SHALL verify `spec-ngram-mod-thsh = 2` in `hlh_chat/models.ini` `[*]` against
the b9603 binary by running
`docker exec hlh_chat /app/llama-server --help 2>&1 | grep -i ngram`.
If the parameter is absent from the output it SHALL be removed from
`hlh_chat/models.ini` before the change ships.

#### Scenario: Unrecognized parameter is removed before shipping

- **WHEN** `llama-server --help` output does not list `spec-ngram-mod-thsh`
- **THEN** the line `spec-ngram-mod-thsh = 2` SHALL be absent from
  `hlh_chat/models.ini` when the change is shipped

#### Scenario: Recognized parameter is kept with a comment

- **WHEN** `llama-server --help` output lists `spec-ngram-mod-thsh`
- **THEN** the line SHALL be retained and annotated with a comment
  explaining the parameter's effect
