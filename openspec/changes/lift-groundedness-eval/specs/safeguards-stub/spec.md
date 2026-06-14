# Delta spec: safeguards-stub

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: ResponseAnalysisBatch.process() SHALL return was_followed=None not True

`ResponseAnalysisBatch.process()` SHALL set `"was_followed": None` in the
`metadata` dict of every returned `GuidelineMatch`.

`backend/services/safeguards_engine.py` `ResponseAnalysisBatch.process()` at
lines 685-696 SHALL be modified so that the `metadata` dict in every returned
`GuidelineMatch` contains `"was_followed": None` instead of `"was_followed": True`.

The unconditional `True` value is a false-safety signal that would report full
compliance for every response if the class were wired into a call site. Setting
`None` makes the absence of real analysis explicit.

The method signature `def process(self) -> BatchResult:` SHALL remain unchanged.

#### Scenario: process() no longer returns unconditional was_followed=True

- **WHEN** `grep -n "was_followed.*True" backend/services/safeguards_engine.py` is run
- **THEN** the command SHALL produce no output

#### Scenario: py_compile passes after stub modification

- **WHEN** `python3 -m py_compile backend/services/safeguards_engine.py` is run
- **THEN** exit code SHALL be 0

## ADDED Requirements

### Requirement: ResponseAnalysisBatch constructor SHALL accept user_query and assistant_response

`ResponseAnalysisBatch.__init__` SHALL be extended to accept
`user_query: str = ""` and `assistant_response: str = ""` as keyword arguments
with defaults, stored as `self._user_query` and `self._assistant_response`.

(JD-002 correction: `PROMPT_TEMPLATE` at lines 661-676 uses `{user_query}`,
`{assistant_response}`, and `{guidelines_text}`. The old constructor only takes
`guideline_matches`. Without this extension, `process_async` cannot build the
prompt and will raise `KeyError`.)

#### Scenario: Constructor accepts user_query and assistant_response

- **WHEN** `ResponseAnalysisBatch(matches, user_query="q", assistant_response="r")` is called
- **THEN** the instance SHALL be created without error
- **AND** `self._user_query` SHALL equal `"q"` and `self._assistant_response` SHALL equal `"r"`

#### Scenario: Constructor backward-compatible with positional guideline_matches only

- **WHEN** `ResponseAnalysisBatch(matches)` is called without the new keyword args
- **THEN** the instance SHALL be created with `self._user_query == ""` and
  `self._assistant_response == ""`

### Requirement: ResponseAnalysisBatch SHALL expose an async process_async method

`backend/services/safeguards_engine.py` SHALL add `async def process_async(self) -> BatchResult`
to `ResponseAnalysisBatch`. This method SHALL call `call_llm_as_judge` from
`services.eval_judge` using `self._user_query`, `self._assistant_response`, and
`self._guideline_matches` to build the prompt from `PROMPT_TEMPLATE`. If no judge
provider is available, it SHALL return matches with `was_followed=None`.

The method SHALL NOT be wired into any call site in this change.

Zero call sites for both `process` and `process_async` SHALL be confirmed outside
`safeguards_engine.py` after the change.

#### Scenario: process_async exists as an async coroutine

- **WHEN** `grep -n "async def process_async" backend/services/safeguards_engine.py`
  is run
- **THEN** the output SHALL contain at least one matching line

#### Scenario: process_async calls call_llm_as_judge when provider is available

- **WHEN** `process_async` is called on an instance with non-empty `_user_query`
  and `_assistant_response`, and a judge provider is available
- **THEN** `call_llm_as_judge` SHALL be invoked with a prompt built from
  `PROMPT_TEMPLATE.format(user_query=..., assistant_response=..., guidelines_text=...)`
- **AND** the returned `BatchResult` SHALL contain `was_followed=None` in metadata
  (structured per-guideline parse is a follow-up TODO)

#### Scenario: No new call sites for ResponseAnalysisBatch introduced

- **WHEN** `grep -rn "ResponseAnalysisBatch" backend/ | grep -v "safeguards_engine.py"`
  is run
- **THEN** the command SHALL produce no output

#### Scenario: py_compile passes with process_async added

- **WHEN** `python3 -m py_compile backend/services/safeguards_engine.py` is run
  after both modifications
- **THEN** exit code SHALL be 0
