# Delta spec: deep-research (B1 + B2)

## Why

homelabhealth answers from a single retrieve-and-rerank pass. Questions that need
multiple angles (compare a lab trend against current guidance, cross-check a
symptom across sources) get one shallow pass. An iterative research loop over the
already-bundled SearXNG (generate query, search, summarize, reflect on gaps,
follow up, synthesize with citations) adds real depth without new infrastructure
or any cloud dependency.

## ADDED Requirements

### Requirement: deep_research_max_loops setting SHALL bound the research loop

The maximum number of search-and-reflect cycles per request SHALL be read from
the `global_settings` key `deep_research_max_loops`, seeded idempotently to `3`,
with a safe in-code default when the key is absent.

#### Scenario: setting is seeded on schema apply

- **WHEN** the schema is applied on startup
- **THEN** `global_settings` contains key `deep_research_max_loops` with value `3`
- **AND** re-applying the schema does not change or duplicate the row

#### Scenario: missing or unparseable setting falls back to a default

- **WHEN** the loop loader reads `deep_research_max_loops` and the key is absent or non-numeric
- **THEN** the loader returns the in-code default instead of raising

### Requirement: an iterative research service SHALL loop over SearXNG with safe fallbacks

A new `services/deep_research.py` SHALL expose an async generator
`run_deep_research(query, workspace_id, chat_id)` that performs up to
`deep_research_max_loops` cycles of generate-query, SearXNG search, summarize,
reflect-on-gaps, follow-up, and final synthesis with citations, without using
LangGraph and without spawning concurrent inference against the single
llama-server slot.

#### Scenario: SearXNG results are adapted from the tuple return shape

- **WHEN** the loop calls `searx_search_sources(query)`
- **THEN** it destructures the returned `(sources_list, markdown_block)` tuple
- **AND** it never treats the return value as a dict

#### Scenario: reflection JSON parse failure falls back safely

- **WHEN** the reflection step requests a JSON object from the model and the response is not valid JSON
- **THEN** the loop continues with the original query rather than raising
- **AND** no unhandled exception reaches the caller

#### Scenario: no configured provider yields a wire-contract error event

- **WHEN** `run_deep_research` cannot resolve a provider for the workspace
- **THEN** it yields a `dr_error` event whose message is the verbatim string `No provider configured for this workspace. Open Settings -> Workspace to pick one.`

### Requirement: a deep_research endpoint SHALL stream the loop over SSE

`POST /api/chats/{chat_id}/deep_research` SHALL authenticate the caller, validate
the query, and stream the loop's events as Server-Sent Events with nginx
buffering disabled.

#### Scenario: empty or oversized query is rejected

- **WHEN** the endpoint receives an empty query or a query longer than 2000 characters
- **THEN** it responds `400` before starting any inference

#### Scenario: the streaming response disables proxy buffering

- **WHEN** the endpoint returns its `StreamingResponse`
- **THEN** the response sets `X-Accel-Buffering: no` so progress events are flushed incrementally rather than buffered by nginx for the full run

### Requirement: the compaction summary prompt SHALL preserve structured health context

The `compaction.py` `SUMMARY_SYSTEM_PROMPT` SHALL instruct the summarizer to
preserve, in priority order, unresolved questions, lab values and vitals with
dates, current medications and dosages, decisions with reasoning, and action
items, without removing the existing PRESERVED FACTS reference added by
lift-context-pruning.

#### Scenario: priority ordering is present and PRESERVED FACTS reference retained

- **WHEN** the compaction summary prompt is assembled
- **THEN** it lists the five priority categories
- **AND** it still references the PRESERVED FACTS block as authoritative ground truth
