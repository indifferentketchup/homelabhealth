"""Iterative multi-loop deep research service.

Runs multiple SearXNG searches, summarizes per-iteration findings,
reflects on gaps using a JSON-mode LLM call (with safe fallback),
and synthesizes a cited final answer. No LangGraph, no LangChain,
no new pip dependencies.

SSE event types yielded by run_deep_research:
  {"type": "dr_phase", "phase": "searching"|"summarizing"|"reflecting"|"compressing"|"done", "loop": N}
  {"type": "dr_sources", "sources": [...], "loop": N}
  {"type": "dr_result", "content": "...", "sources": [...]}
  {"type": "dr_error", "error": "..."}
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator

from db import get_pool
from services.searx import searx_search_sources
from services.provider_client import async_llm_call, resolve_provider_for_workspace
from services.deid import is_enabled as deid_enabled, redact_text

logger = logging.getLogger(__name__)


async def _load_max_loops(default: int) -> int:
    """Read deep_research_max_loops from global_settings, falling back to default."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM global_settings WHERE key = 'deep_research_max_loops'"
            )
        if row and row["value"]:
            return int(row["value"])
    except Exception as e:
        logger.warning("_load_max_loops failed (%s); using default %d", e, default)
    return default


async def _summarize(
    query: str,
    current_query: str,
    snippets: str,
    provider,
    model: str,
) -> str:
    """Summarize search snippets as they relate to the research question.

    Returns empty string on failure (logs at WARNING).
    """
    system_prompt = (
        "You are a medical research assistant. Summarize the following web search "
        "results as they relate to the research question. Extract key facts, values, "
        "and relevant details."
    )
    user_content = (
        f"Research question: {query}\n"
        f"Current search query: {current_query}\n\n"
        f"Search results:\n{snippets}"
    )
    return await async_llm_call(
        provider,
        model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=512,
        timeout_s=60.0,
    )


async def _compress_findings(findings: str, provider, model: str) -> str:
    """Compress accumulated findings when they grow large.

    Returns original findings string on failure (safe fallback, logs at WARNING).
    """
    system_prompt = (
        "Compress the following research findings into a concise summary. "
        "Preserve all key facts, values, dates, and source references."
    )
    compressed = await async_llm_call(
        provider,
        model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": findings},
        ],
        temperature=0.1,
        max_tokens=512,
        timeout_s=60.0,
    )
    return compressed if compressed else findings


async def _reflect(
    original_query: str,
    findings: str,
    provider,
    model: str,
) -> tuple[bool, str | None]:
    """Reflect on research gaps and decide on the next search query.

    Uses JSON-mode LLM call. Falls back to (True, original_query) on ANY
    exception including JSON parse failure. Never raises.
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
    try:
        raw = await async_llm_call(
            provider,
            model,
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=128,
            timeout_s=30.0,
            response_format={"type": "json_object"},
        )
        if not raw:
            return True, original_query
        parsed = json.loads(raw)
        cont = bool(parsed.get("continue", False))
        fq = str(parsed.get("follow_up_query") or "").strip()
        return cont, fq or None
    except Exception as e:
        logger.warning(
            "deep_research reflect JSON parse failed (%s); using original query as fallback", e
        )
        return True, original_query  # safe fallback: continue with original query


async def _synthesize(
    original_query: str,
    findings: str,
    sources: list[dict],
    provider,
    model: str,
) -> str:
    """Synthesize accumulated findings into a final cited answer.

    Returns empty string on failure (logs at ERROR).
    """
    system_prompt = (
        "You are a medical research assistant. Synthesize the following research "
        "findings into a comprehensive answer to the original question. Use inline "
        "citations like [Source Title] where relevant. Be accurate and cite only "
        "facts present in the findings."
    )
    sources_block = "\n".join(
        f"- {s.get('title', 'Untitled')}: {s.get('url', '')}" for s in sources
    )
    user_content = (
        f"Original question: {original_query}\n\n"
        f"Research findings:\n{findings}\n\n"
        f"Sources:\n{sources_block}"
    )
    return await async_llm_call(
        provider,
        model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=1024,
        timeout_s=120.0,
    )


def _append_findings(findings: str, iteration_summary: str, loop_n: int) -> str:
    """Append an iteration's summary to the accumulated findings string."""
    if not iteration_summary:
        return findings
    header = f"\n\n--- Loop {loop_n} findings ---\n"
    return findings + header + iteration_summary


async def run_deep_research(
    query: str,
    workspace_id: str,
    chat_id: str,
    *,
    max_loops: int = 3,
) -> AsyncIterator[dict]:
    """Run iterative deep research loop, yielding SSE-compatible event dicts.

    Yields:
      {"type": "dr_phase", "phase": "...", "loop": N}
      {"type": "dr_sources", "sources": [...], "loop": N}
      {"type": "dr_result", "content": "...", "sources": [...]}
      {"type": "dr_error", "error": "..."}

    NOTE: workspace_id is accepted as str (API boundary) and converted to
    uuid.UUID before calling resolve_provider_for_workspace (F2 fix).
    The llama-server single-slot serializes all LLM calls; concurrent chat
    sends in other browser tabs will queue behind this loop.
    """
    # F2 fix: convert str workspace_id to uuid.UUID before passing to the resolver.
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except (ValueError, AttributeError) as e:
        yield {"type": "dr_error", "error": f"Invalid workspace_id: {e}"}
        return

    try:
        provider, model = await resolve_provider_for_workspace(ws_uuid)
    except Exception as e:
        yield {
            "type": "dr_error",
            "error": "No provider configured for this workspace. Open Settings -> Workspace to pick one.",
        }
        return

    # Determine whether provider is bundled (same gate used by chats.py).
    provider_is_bundled: bool = True
    try:
        pool = await get_pool()
        async with pool.acquire() as _conn:
            _bundled_row = await _conn.fetchval(
                "SELECT is_bundled FROM providers WHERE id = $1::uuid",
                provider.id,
            )
        provider_is_bundled = bool(_bundled_row or False)
    except Exception as _e:
        logger.warning("deep_research: could not determine is_bundled (%s); treating as bundled", _e)

    # Apply de-identification to the original query when using an external
    # provider. The web-search path is the highest-risk PHI leak (query goes
    # to Google/Bing via SearXNG), so redact even when only deid is enabled.
    effective_query = query
    if deid_enabled() and not provider_is_bundled:
        effective_query = redact_text(query).text
        logger.info("deep_research: redacted query before external provider/search")

    max_loops = await _load_max_loops(max_loops)

    all_sources: list[dict] = []
    findings: str = ""
    current_query = effective_query
    loop_n = 1  # ensure loop_n is defined for the synthesis step even if loop body skipped

    for loop_n in range(1, max_loops + 1):
        # Phase: searching
        yield {"type": "dr_phase", "phase": "searching", "loop": loop_n}
        try:
            # current_query is already de-identified when provider is external.
            sources_list, markdown_block = await searx_search_sources(current_query)
        except Exception as e:
            logger.warning("deep_research searx call failed loop=%d (%s)", loop_n, e)
            break
        if not markdown_block:
            break
        all_sources.extend(sources_list)
        yield {"type": "dr_sources", "sources": sources_list, "loop": loop_n}

        # Phase: summarizing
        yield {"type": "dr_phase", "phase": "summarizing", "loop": loop_n}
        iteration_summary = await _summarize(
            query=effective_query,
            current_query=current_query,
            snippets=markdown_block,
            provider=provider,
            model=model,
        )
        findings = _append_findings(findings, iteration_summary, loop_n)

        # Phase: compressing (only when findings are large and there are loops remaining)
        if len(findings) > 3000 and loop_n < max_loops:
            yield {"type": "dr_phase", "phase": "compressing", "loop": loop_n}
            findings = await _compress_findings(
                findings=findings,
                provider=provider,
                model=model,
            )

        # Phase: reflecting (skip on final loop)
        if loop_n < max_loops:
            yield {"type": "dr_phase", "phase": "reflecting", "loop": loop_n}
            should_continue, next_query = await _reflect(
                original_query=effective_query,
                findings=findings,
                provider=provider,
                model=model,
            )
            if not should_continue or not next_query:
                break
            # De-identify the follow-up query from the LLM when using external provider.
            if deid_enabled() and not provider_is_bundled and next_query:
                next_query = redact_text(next_query).text
            current_query = next_query

    # Final synthesis
    yield {"type": "dr_phase", "phase": "done", "loop": loop_n}
    result = await _synthesize(
        original_query=effective_query,
        findings=findings,
        sources=all_sources,
        provider=provider,
        model=model,
    )
    yield {"type": "dr_result", "content": result, "sources": all_sources}
