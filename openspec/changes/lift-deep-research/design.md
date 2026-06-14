# Design: lift-deep-research

**Date:** 2026-06-13

---

## Must Have

- Plain Python async, no LangGraph, no LangChain, no new pip dependencies.
- `services/searx.py::searx_search_sources` is the ONLY SearXNG call point.
  Never import or use `SearxSearchWrapper` or any LangChain utility.
- JSON reflection step MUST have a non-JSON fallback (BU-1).
- SSE progress events for every loop phase (BU-3 UX mitigation).
- `global_settings.deep_research_max_loops` read via asyncpg k/v table
  (`SELECT value FROM global_settings WHERE key = 'deep_research_max_loops'`).
- Provider resolution through `services/provider_client.py::resolve_provider_for_workspace`
  (not `resolve_bundled_chat_provider` -- uses the workspace's configured provider).

## Must NOT Have

- LangGraph, LangChain, or any framework import.
- Direct use of `os.environ.get("INFERENCE_URL")` or any deprecated env var.
- Auto-trigger from intent gate or on every web-search-enabled chat send.
- Blocking the main asyncio event loop during LLM calls (all calls are httpx async).
- A new Python package dependency (httpx is already present).

---

## B1: services/deep_research.py

### SearXNG adapter (BU-2)

`searx_search_sources(query)` returns `(sources_list, markdown_block)` where:
- `sources_list: list[dict]` -- each dict has `{"title": str, "url": str}`
- `markdown_block: str` -- pre-formatted text block for LLM injection

The loop uses `markdown_block` as the search snippet body for LLM calls, and
accumulates `sources_list` for citation metadata. No adaptation of dict keys is
needed -- `markdown_block` is already formatted for injection.

### Loop structure

```python
async def run_deep_research(
    query: str,
    workspace_id: str,
    chat_id: str,
    *,
    max_loops: int = 3,
) -> AsyncIterator[dict]:
    """
    Yields SSE-compatible dicts:
      {"type": "dr_phase", "phase": "searching"|"summarizing"|"reflecting"|"compressing"|"done", "loop": N}
      {"type": "dr_sources", "sources": [...], "loop": N}
      {"type": "dr_result", "content": "...", "sources": [...]}
      {"type": "dr_error", "error": "..."}
    """
    provider, model = await resolve_provider_for_workspace(workspace_id)
    max_loops = await _load_max_loops(max_loops)

    all_sources: list[dict] = []
    findings: str = ""
    current_query = query

    for loop_n in range(1, max_loops + 1):
        # Phase: searching
        yield {"type": "dr_phase", "phase": "searching", "loop": loop_n}
        sources_list, markdown_block = await searx_search_sources(current_query)
        if not markdown_block:
            break
        all_sources.extend(sources_list)
        yield {"type": "dr_sources", "sources": sources_list, "loop": loop_n}

        # Phase: summarizing
        yield {"type": "dr_phase", "phase": "summarizing", "loop": loop_n}
        iteration_summary = await _summarize(
            query=query,
            current_query=current_query,
            snippets=markdown_block,
            provider=provider,
            model=model,
        )
        findings = _append_findings(findings, iteration_summary, loop_n)

        # Phase: compressing (if findings growing large)
        if len(findings) > 3000 and loop_n < max_loops:
            yield {"type": "dr_phase", "phase": "compressing", "loop": loop_n}
            findings = await _compress_findings(
                findings=findings,
                provider=provider,
                model=model,
            )

        # Phase: reflecting (skip on last loop)
        if loop_n < max_loops:
            yield {"type": "dr_phase", "phase": "reflecting", "loop": loop_n}
            should_continue, next_query = await _reflect(
                original_query=query,
                findings=findings,
                provider=provider,
                model=model,
            )
            if not should_continue or not next_query:
                break
            current_query = next_query

    # Final synthesis
    yield {"type": "dr_phase", "phase": "done", "loop": loop_n}
    result = await _synthesize(
        original_query=query,
        findings=findings,
        sources=all_sources,
        provider=provider,
        model=model,
    )
    yield {"type": "dr_result", "content": result, "sources": all_sources}
```

### JSON reflection step and fallback (BU-1)

```python
async def _reflect(
    original_query: str,
    findings: str,
    provider,
    model: str,
) -> tuple[bool, str | None]:
    """
    Returns (should_continue, next_query).
    Falls back to (True, original_query) on any JSON parse failure.
    """
    prompt = (
        "You are a research assistant. Given the findings so far, identify "
        "the most important missing information needed to fully answer the "
        "original question. Respond with valid JSON only:\n"
        "{\"continue\": true, \"follow_up_query\": \"<specific search query>\"}\n"
        "If the findings are sufficient, respond:\n"
        "{\"continue\": false, \"follow_up_query\": \"\"}\n"
        "No other text. JSON only."
    )
    user_content = (
        f"Original question: {original_query}\n\n"
        f"Findings so far:\n{findings}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 128,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw)
        cont = bool(parsed.get("continue", False))
        fq = str(parsed.get("follow_up_query") or "").strip()
        return cont, fq or None
    except Exception as e:
        logger.warning(
            "deep_research reflect JSON parse failed (%s); using original query as fallback", e
        )
        return True, original_query  # safe fallback: continue with original query
```

### Compression sub-step

Only triggered when `len(findings) > 3000` and there are remaining loops.
Single LLM call: "Compress these research findings into a concise summary
preserving all key facts, values, and source references. Be thorough but brief."
Uses the same `provider`/`model` as the rest of the loop. No `response_format`
override (plain text output).

### Synthesis step

Final call with all accumulated findings and the list of source titles/URLs.
Prompt asks for a structured answer with inline citations referencing the source
titles. No `response_format` override.

### Settings key

Seeded in `backend/schema.sql` via idempotent insert (at the end of the
seed section, before the final comment):

```sql
INSERT INTO global_settings (key, value)
VALUES ('deep_research_max_loops', '3')
ON CONFLICT (key) DO NOTHING;
```

This follows the `global_settings` k/v convention (CLAUDE.md: key TEXT PK,
value TEXT NOT NULL; do not use ALTER TABLE ADD COLUMN).

---

## B1: routers/chats.py endpoint

New route added to the existing `chats` router:

```
POST /api/chats/{chat_id}/deep_research
Body: {"query": str}
Auth: require_owner (same as post_messages)
Response: text/event-stream (SSE)
```

The endpoint:
1. Validates `chat_id` and `query` (non-empty, max 2000 chars).
2. Resolves `workspace_id` from the chat row.
3. Calls `run_deep_research(query, workspace_id, chat_id)` and streams its
   yielded dicts as SSE events via `_sse(json.dumps(event))`.
4. Never writes to the `messages` table directly -- the caller decides how to
   handle the result (frontend can append as a synthetic assistant message or
   display in a dedicated panel).
5. Returns `StreamingResponse(gen(), media_type="text/event-stream")`.

The endpoint is added to `backend/routers/chats.py` alongside the existing
`post_messages` and related handlers. No new router file or `main.py` mount is
needed because it lives under the existing `chats` prefix (`/api/chats`).

---

## B2: services/compaction.py prompt upgrade

Current `SUMMARY_SYSTEM_PROMPT` (lines 25-29):
```python
SUMMARY_SYSTEM_PROMPT = (
    "Summarize the following conversation for context continuity. "
    "Preserve: key medical facts, test results mentioned, dates discussed, "
    "decisions made, and action items. Be concise but complete."
)
```

New prompt (replaces the existing constant):
```python
SUMMARY_SYSTEM_PROMPT = (
    "Summarize the following conversation for context continuity. "
    "Preserve in order of priority: (1) unresolved questions and open issues, "
    "(2) lab values, vital signs, and test results with dates, "
    "(3) medications and dosages currently active or recently changed, "
    "(4) decisions made and the reasoning behind them, "
    "(5) action items and follow-up plans. "
    "Be concise but complete. Use plain prose, not bullets."
)
```

Rationale: derived from chat-langchain context_summary_prompt.py structure
(validation B.md item 7). The addition of unresolved questions and medications
is the key gap. The "plain prose, not bullets" constraint prevents the model
from producing a checklist that the compaction system injects awkwardly.

No schema changes. No version bump variable in this file (it is a prompt, not
a safeguard -- only `services/safeguards.py::SAFEGUARD_VERSION` tracks versioned
prompts per CLAUDE.md convention).

---

## Backward compatibility

- The deep_research endpoint is new and additive. Existing chat flow is untouched.
- The compaction prompt change affects future compaction summaries only.
  Existing `pruning_summary` values in the DB are preserved and valid.
- The `global_settings` key is seeded with `ON CONFLICT DO NOTHING`, so existing
  DBs that already have the key (from a prior run) are not overwritten.

---

## Concurrency and latency notes (BU-3, BU-4)

The deep research loop makes 3-4 sequential httpx calls per iteration. On a
CPU-only bundled tier with medgemma or qwen-chat, one loop iteration takes
approximately 30-90 seconds. A 3-loop run may take 2-5 minutes total. The
endpoint does not acquire any asyncpg connection during LLM calls, so DB pool
contention is limited to the initial chat row lookup and the `global_settings`
read. The llama-server single-slot serializes all LLM calls; concurrent chat
sends in other browser tabs will queue behind the deep research loop.

The endpoint never auto-fires. It requires an explicit POST. The frontend must
not wire it to the intent gate.
