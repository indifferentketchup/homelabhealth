# Delta spec: stall-detection (E3)

**Date:** 2026-06-13

## Why

`_answer_sub_question` and `WaveScheduler._run_step` have no guard against a
worker that repeatedly returns semantically identical low-information responses
or repeatedly invokes the same tool with identical arguments. Both conditions
waste tokens and block wave progress indefinitely until the timeout fires.

The hive `stall_detector.py` provides two pure functions with no class
dependencies that can be dropped in directly.

Validation source: E.md item 4 (confirmed drop-in, pure functions).

## ADDED Requirements

### Requirement: backend/services/stall_detector.py SHALL expose is_stalled and is_tool_doom_loop

`backend/services/stall_detector.py` SHALL be a new module containing four
functions copied verbatim from the reference source:
`ngram_similarity`, `is_stalled`, `fingerprint_tool_calls`, `is_tool_doom_loop`.

The module SHALL have no imports beyond `from __future__ import annotations`
and `import json`.

#### Scenario: is_stalled returns True for identical consecutive responses

- **WHEN** `is_stalled` is called with `["the sky is blue", "the sky is blue", "the sky is blue"]`,
  `threshold=3`, `similarity_threshold=0.85`
- **THEN** the return value SHALL be `True`

#### Scenario: is_stalled returns False for diverse responses

- **WHEN** `is_stalled` is called with `["alpha response", "beta response", "gamma response"]`,
  `threshold=3`, `similarity_threshold=0.85`
- **THEN** the return value SHALL be `False`

#### Scenario: is_tool_doom_loop returns True for identical fingerprint sequences

- **WHEN** `is_tool_doom_loop` is called with three identical fingerprint lists
  `[[("search", '{"q": "test"}')], [("search", '{"q": "test"}')], [("search", '{"q": "test"}')]]`
  and `threshold=3`
- **THEN** the first element of the returned tuple SHALL be `True`

#### Scenario: module has no side effects on import

- **WHEN** `stall_detector` is imported
- **THEN** no global state is modified and no I/O occurs

### Requirement: _answer_sub_question SHALL check for stall after each LLM response

`_answer_sub_question` in `backend/services/supervisor_worker.py` SHALL import
`is_stalled` from `services.stall_detector` and accumulate LLM responses in a
per-call list. After each response is appended, it SHALL call `is_stalled` with
`_STALL_THRESHOLD=3` and `_STALL_SIMILARITY=0.85`. If `True`, it SHALL log a
WARNING and return a `WorkerAnswer` with `error='stall_detected'`.

Note: the function currently makes one `_llm_call`. The stall list will have
length 1 in production today; the check is a no-op infrastructure hook.

#### Scenario: stall detection fires on repeated single-turn workers (future)

- **WHEN** `_answer_sub_question` makes 3 or more LLM calls with similar responses
- **AND** `is_stalled` returns `True`
- **THEN** a WARNING SHALL be logged
- **AND** the function SHALL return a `WorkerAnswer` with `error='stall_detected'`
- **AND** no further `_llm_call` invocations SHALL occur

#### Scenario: normal single-response worker is unaffected

- **WHEN** `_answer_sub_question` makes one `_llm_call` and returns
- **THEN** `is_stalled` returns `False` (list too short)
- **AND** the function returns the answer normally

### Requirement: WaveScheduler.run SHALL check for wave-level stall

`WaveScheduler.run` in `backend/services/conductor.py` SHALL accumulate per-wave
output strings in a sliding window. After each wave completes, if the window has
`_WAVE_STALL_THRESHOLD=3` or more entries, it SHALL call `is_stalled` with the
joined wave outputs and `_WAVE_STALL_SIMILARITY=0.90`. If stalled, it SHALL raise
`RuntimeError` with a message including the current `wave_index`.

#### Scenario: wave stall raises RuntimeError

- **WHEN** three consecutive waves produce outputs with Jaccard n-gram similarity >= 0.90
- **AND** `is_stalled` returns `True`
- **THEN** `WaveScheduler.run` SHALL raise `RuntimeError` naming the wave index

#### Scenario: diverse wave outputs do not trigger stall

- **WHEN** three consecutive waves produce clearly different text
- **THEN** `is_stalled` returns `False` and execution continues normally
