# Delta spec: eval-service

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: eval_judge.py SHALL expose call_llm_as_judge as a public function

`backend/services/eval_judge.py` SHALL be created and SHALL expose:
- `call_llm_as_judge(provider, model, system_prompt, user_prompt) -> dict`
  with the same logic as the existing `_call_llm_as_judge` in `eval.py:301-383`
  (error-tolerant, returns `{"score": None, ...}` on any failure)
- `_parse_eval_response(raw: str) -> dict` (verbatim copy from `eval.py:240-268`)
- `_normalize_score(raw: Any) -> float | None` (verbatim copy from `eval.py:271-279`)
- `_build_eval_response(data: dict) -> dict` (verbatim copy from `eval.py:282-298`)
- `GROUNDEDNESS_SYSTEM_PROMPT` and `GROUNDEDNESS_USER_PROMPT` (verbatim copy;
  SHALL retain `{context}` and `{response}` slots -- NOT `{outputs}`)
- `resolve_judge_provider(workspace_id: uuid.UUID | None) -> tuple | None`
  (see Requirement below)

The file SHALL NOT import `openevals`, `langchain`, or `langsmith`.

#### Scenario: eval_judge imports resolve at module level

- **WHEN** `python3 -m py_compile backend/services/eval_judge.py` is run
- **THEN** exit code SHALL be 0 with no circular import error

#### Scenario: call_llm_as_judge returns score=None on provider error

- **WHEN** `call_llm_as_judge` is called with a provider whose `base_url`
  points to an unreachable host
- **THEN** the returned dict SHALL have `score` equal to `None`
- **AND** the function SHALL NOT raise an exception

### Requirement: resolve_judge_provider SHALL route through the workspace provider

`resolve_judge_provider(workspace_id)` in `backend/services/eval_judge.py` SHALL
call `resolve_provider_for_workspace(workspace_id)` when `workspace_id` is not
None and return its result. The function SHALL return `None` when
`workspace_id` is None or provider resolution raises or fails.

The function SHALL NOT raise. Any exception from provider resolution SHALL be
caught and result in returning `None`.

#### Scenario: Workspace provider is used when workspace_id is provided

- **WHEN** `resolve_judge_provider(workspace_id)` is called with a valid
  configured workspace UUID
- **THEN** the returned tuple SHALL come from `resolve_provider_for_workspace`

#### Scenario: Returns None when no provider is resolvable

- **WHEN** `workspace_id` is None or `resolve_provider_for_workspace` fails
- **THEN** `resolve_judge_provider` SHALL return `None` without raising

## MODIFIED Requirements

### Requirement: eval.py SHALL import helpers from services.eval_judge

`backend/routers/eval.py` SHALL be updated to import `call_llm_as_judge`,
`_parse_eval_response`, `_normalize_score`, `_build_eval_response` from
`services.eval_judge` rather than defining them inline.

The existing endpoint behavior (`eval_groundedness`, `eval_helpfulness`,
`eval_retrieval_relevance`) SHALL be unchanged after the refactor.

#### Scenario: eval.py compiles after helper removal

- **WHEN** the inline helper definitions are removed from `eval.py` and
  replaced with imports from `services.eval_judge`
- **THEN** `python3 -m py_compile backend/routers/eval.py` SHALL exit 0

#### Scenario: eval endpoints behave identically after refactor

- **WHEN** an admin calls `POST /api/eval/groundedness` before and after
  the extraction refactor with the same inputs
- **THEN** the response shape (`score`, `explanation`, `violations`) SHALL
  be identical
