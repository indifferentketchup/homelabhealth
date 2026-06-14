# Delta spec: context-handoff (E4)

**Date:** 2026-06-13

## Why

`WaveScheduler.run` passes the raw `results` dict (all step outputs) to
subsequent waves or callers without any size guard. For long multi-wave runs the
concatenated text grows unboundedly and can exceed token limits. An extractive
compression step using the first and last wave outputs (no LLM required) bounds
the context size.

Validation source: E.md item 5 (confirmed, extractive fallback needs no LLM).

## ADDED Requirements

### Requirement: backend/services/context_handoff.py SHALL expose extractive_summary and format_as_input

`backend/services/context_handoff.py` SHALL be a new module with:

- `_TRUNCATE_CHARS = 500` module constant
- `extractive_summary(outputs: list[str], truncate: int = _TRUNCATE_CHARS) -> str`:
  returns the first and last strings from `outputs` (truncated to `truncate`
  chars each), joined by `"\n\n"`. Returns `"Empty conversation."` for empty input.
  If `len(outputs) == 1`, returns only the first string truncated.
- `format_as_input(source_id: str, summary: str, turn_count: int) -> str`:
  renders a header block: `--- CONTEXT FROM: {source_id} ({turn_count} turns) ---`
  followed by the summary.

No imports outside stdlib. No `NodeConversation` dependency.

#### Scenario: extractive_summary returns first and last truncated strings

- **WHEN** `extractive_summary` is called with a list of 3 strings each > 500 chars
- **THEN** the returned string SHALL contain the first 500 chars of the first string
- **AND** SHALL contain the first 500 chars of the last string
- **AND** total length SHALL be at most 1002 chars (500 + 2 + 500)

#### Scenario: empty list returns sentinel string

- **WHEN** `extractive_summary` is called with `[]`
- **THEN** the return value SHALL be `"Empty conversation."`
- **AND** no exception SHALL be raised

#### Scenario: single-item list returns one truncated string

- **WHEN** `extractive_summary` is called with a list of exactly one string > 500 chars
- **THEN** the return value SHALL be the first 500 chars of that string

#### Scenario: format_as_input includes header with source_id and turn_count

- **WHEN** `format_as_input` is called with `source_id="wave-1"`, `summary="test"`,
  `turn_count=3`
- **THEN** the return value SHALL contain `"CONTEXT FROM: wave-1"`
- **AND** SHALL contain `"3 turns"`

### Requirement: WaveScheduler.run SHALL accept compress_context parameter

`WaveScheduler.run` SHALL accept a keyword parameter `compress_context: bool = False`.
When `True` and total `results` character count exceeds 4000 after a wave
completes, it SHALL call `extractive_summary` on the list of step outputs and
replace the `results` dict with a single `_context_summary` key.
Default is `False` so all existing callers are unaffected.

#### Scenario: compression fires when threshold exceeded and compress_context is True

- **WHEN** `WaveScheduler.run` is called with `compress_context=True`
- **AND** total `results` value character count exceeds 4000 after a wave
- **THEN** `results` SHALL contain a `_context_summary` key with the extractive summary
- **AND** the original step-id keys SHALL be replaced

#### Scenario: compression does not fire when compress_context is False (default)

- **WHEN** `WaveScheduler.run` is called without specifying `compress_context`
- **THEN** `results` dict SHALL contain the unmodified step-id keys regardless of size

#### Scenario: compression does not fire when output is below threshold

- **WHEN** total `results` character count is below 4000
- **AND** `compress_context=True`
- **THEN** `results` SHALL NOT be replaced with `_context_summary`
