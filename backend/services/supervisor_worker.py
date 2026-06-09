"""Supervisor-worker decomposition for complex health queries.

Adapted from open_deep_research's supervisor + researcher pattern.
Decomposes complex queries into parallel sub-questions, routes to worker
agents, and synthesizes results with contradiction detection.

Public surface:
    is_complex_query(text) -> bool
    run_supervisor_worker(query, provider, model, source_context="") -> SynthesisResult
    decompose_query(query, provider, model) -> list[str]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from services.provider_client import Provider, build_headers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Complexity heuristic
# ---------------------------------------------------------------------------

_COMPLEXITY_KEYWORDS = frozenset({"compare", "contrast", "analyze", "why", "how", "explain", "evaluate", "difference", "relationship", "impact", "effect", "prognosis", "pathophysiology"})

_COMPLEXITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _COMPLEXITY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_complex_query(text: str) -> bool:
    """Heuristic: returns True if the query is complex enough for decomposition.

    Triggers when any of these conditions are met:
    1. Message length > 200 characters
    2. Multiple question marks
    3. One or more complexity keywords present
    """
    if not text or not text.strip():
        return False
    t = text.strip()
    if len(t) > 200:
        return True
    if t.count("?") >= 2:
        return True
    if _COMPLEXITY_RE.search(t):
        return True
    return False


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class WorkerAnswer:
    sub_question: str
    answer: str
    timed_out: bool = False
    error: str | None = None


@dataclass
class SynthesisResult:
    merged: str
    contradictions: list[str] = field(default_factory=list)
    worker_answers: list[WorkerAnswer] = field(default_factory=list)
    decomposed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Supervisor: decompose a complex query into sub-questions
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM_PROMPT = """You are a medical research supervisor. Your task is to decompose a complex health-related question into focused, answerable sub-questions.

Rules:
1. Break the query into 2-4 specific sub-questions that together cover all aspects of the original question.
2. Each sub-question must be self-contained and answerable independently.
3. Sub-questions should be non-overlapping when possible.
4. Output ONLY a JSON array of strings with no explanation, no markdown formatting.
5. Example: ["What are the standard treatments for condition X?", "What are the side effects of treatment Y?", "How do treatments X and Y compare in efficacy?"]"""


async def _llm_call(
    provider: Provider,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    timeout_s: float = 30.0,
    max_tokens: int = 1024,
) -> str:
    """Non-streaming call to the provider's /v1/chat/completions.

    Returns the content string, or raises on HTTP/network error.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            r = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            r.raise_for_status()
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("No choices in LLM response")
            msg = choices[0].get("message") or {}
            content = (msg.get("content") or "").strip()
            if not content:
                raise RuntimeError("Empty LLM response")
            return content
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


async def decompose_query(
    query: str,
    provider: Provider,
    model: str,
) -> list[str]:
    """Decompose a complex query into a list of sub-questions.

    Returns a list of sub-question strings. On failure, returns [query]
    as a passthrough so the caller can still get an answer.
    """
    try:
        raw = await _llm_call(
            provider,
            model,
            _DECOMPOSE_SYSTEM_PROMPT,
            f"Decompose this query into sub-questions:\n\n{query}",
            timeout_s=30.0,
            max_tokens=1024,
        )
    except Exception as exc:
        logger.warning("decompose_query failed for %r: %s", query[:80], exc)
        return [query]

    # Parse JSON array from the response — handle markdown-wrapped or bare JSON.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        sub_questions: list[str] = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("decompose_query: failed to parse JSON from %r: %s", raw[:200], exc)
        # Fallback: try to extract list-like content
        fallback = _extract_list_from_text(raw)
        if fallback:
            return fallback
        return [query]

    if not isinstance(sub_questions, list) or not sub_questions:
        logger.warning("decompose_query: parsed empty/non-list JSON; falling back")
        return [query]

    # Normalize: ensure each entry is a non-empty string
    out: list[str] = []
    for item in sub_questions:
        s = str(item).strip() if not isinstance(item, str) else item.strip()
        if s:
            out.append(s)

    logger.info(
        "decompose_query: split into %d sub-questions: %s",
        len(out), [sq[:60] for sq in out],
    )
    return out if out else [query]


def _extract_list_from_text(text: str) -> list[str]:
    """Fallback: extract numbered or bulleted lines as a list."""
    lines = text.strip().split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Match "- item", "1. item", "* item"
        cleaned = re.sub(r"^[\s]*[-*\d.]+[\s]*", "", stripped).strip()
        if cleaned and len(cleaned) > 10:
            # Remove surrounding quotes if any
            cleaned = cleaned.strip("\"'")
            out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# Worker: answer a single sub-question
# ---------------------------------------------------------------------------

_WORKER_SYSTEM_PROMPT = """You are a medical research assistant. Answer the given question concisely and accurately based on available context.

Guidelines:
- Be specific and factual. Use the provided context when available.
- If the question asks about treatments, tests, or diagnoses, include relevant details.
- If you are unsure, state that rather than guessing.
- Keep answers to 2-4 paragraphs unless more detail is needed.
- Do NOT reference that this is a sub-question or part of a larger analysis — answer directly."""


async def _answer_sub_question(
    sub_question: str,
    provider: Provider,
    model: str,
    source_context: str,
    *,
    timeout_s: float = 30.0,
) -> WorkerAnswer:
    """Answer one sub-question via the provider.

    Returns a WorkerAnswer with the answer text or error/timeout detail.
    """
    system_prompt = _WORKER_SYSTEM_PROMPT
    user_prompt = sub_question
    if source_context:
        user_prompt = (
            f"Using the following context, answer the question below.\n\n"
            f"### Context\n{source_context}\n\n"
            f"### Question\n{sub_question}"
        )

    try:
        content = await _llm_call(
            provider,
            model,
            system_prompt,
            user_prompt,
            timeout_s=timeout_s,
            max_tokens=2048,
        )
        return WorkerAnswer(sub_question=sub_question, answer=content)
    except httpx.TimeoutException:
        logger.warning("worker timed out for sub-question: %s", sub_question[:80])
        return WorkerAnswer(
            sub_question=sub_question,
            answer="[This sub-question timed out and was not answered.]",
            timed_out=True,
        )
    except Exception as exc:
        logger.warning("worker failed for sub-question %r: %s", sub_question[:80], exc)
        return WorkerAnswer(
            sub_question=sub_question,
            answer="",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Synthesizer: merge worker answers and detect contradictions
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM_PROMPT = """You are a medical research synthesis expert. Merge the following parallel research answers into a coherent, comprehensive response to the original query.

Guidelines:
1. Combine information from all answers into a well-structured response.
2. Resolve any contradictions by noting them explicitly and explaining the uncertainty.
3. PRESERVE all specific details (numbers, names, treatments, dosages) from the source answers — do not hallucinate or invent data.
4. If two answers conflict on a factual point, flag the contradiction clearly with "CONTRADICTION:" followed by the conflicting claims.
5. The final response should read as a unified answer, not as separate sections.
6. Organize by topic, not by which worker produced each part.

Output your merged answer. Then, on a new line, output '---CONTRADICTIONS---' followed by a bullet list of any contradictions found. If there are no contradictions, output '---CONTRADICTIONS---\\nNone detected.'"""


async def _synthesize(
    original_query: str,
    answers: list[WorkerAnswer],
    provider: Provider,
    model: str,
) -> SynthesisResult:
    """Merge worker answers into a coherent response and detect contradictions."""
    # Collect non-empty, non-timed-out answers
    valid = [a for a in answers if a.answer and not a.timed_out]
    if not valid:
        # All workers failed or timed out
        fallback_parts: list[str] = []
        for a in answers:
            if a.error:
                fallback_parts.append(f"Q: {a.sub_question}\nError: {a.error}")
            elif a.timed_out:
                fallback_parts.append(f"Q: {a.sub_question}\n[Timed out]")
        merged = "Could not complete analysis. Details:\n\n" + "\n\n".join(fallback_parts) if fallback_parts else "Could not complete analysis."
        return SynthesisResult(
            merged=merged,
            contradictions=[],
            worker_answers=answers,
            decomposed=[],
        )

    answers_block = "\n\n---\n\n".join(
        f"## Research finding {i+1}\nQ: {a.sub_question}\nA: {a.answer}"
        for i, a in enumerate(valid)
    )
    user_prompt = (
        f"Original query: {original_query}\n\n"
        f"Below are parallel research findings. Merge them into one coherent response:\n\n{answers_block}"
    )

    try:
        raw = await _llm_call(
            provider,
            model,
            _SYNTHESIS_SYSTEM_PROMPT,
            user_prompt,
            timeout_s=30.0,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.warning("synthesize failed: %s", exc)
        # Fallback: concatenate worker answers verbatim
        fallback = "\n\n".join(
            f"**{a.sub_question}**\n{a.answer}" for a in valid
        )
        return SynthesisResult(
            merged=fallback,
            contradictions=[],
            worker_answers=answers,
            decomposed=[],
        )

    # Split on --CONTRADICTIONS-- marker
    contradictions: list[str] = []
    merged = raw
    sep = "---CONTRADICTIONS---"
    if sep in raw:
        parts = raw.split(sep, 1)
        merged = parts[0].strip()
        contra_text = parts[1].strip()
        if contra_text and contra_text.lower() not in ("none detected.", "none"):
            for line in contra_text.split("\n"):
                cl = line.strip().lstrip("-* ").strip()
                if cl:
                    contradictions.append(cl)

    logger.info(
        "synthesize: merged %d worker answers, %d contradictions found",
        len(valid),
        len(contradictions),
    )
    return SynthesisResult(
        merged=merged,
        contradictions=contradictions,
        worker_answers=answers,
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

_WORKER_TIMEOUT_S = 30.0


async def run_supervisor_worker(
    query: str,
    provider: Provider,
    model: str,
    source_context: str = "",
) -> SynthesisResult:
    """Run the full supervisor-worker-synthesize pipeline.

    Steps:
    1. Decompose the query into sub-questions (supervisor).
    2. Answer each sub-question in parallel (workers).
    3. Synthesize results with contradiction detection.

    Workers run via ``asyncio.gather`` with ``return_exceptions=True``.
    A 30-second timeout is applied per worker; timed-out workers produce
    a soft-fail notice rather than an exception.
    """
    # 1. Decompose
    sub_questions = await decompose_query(query, provider, model)
    if len(sub_questions) <= 1:
        # No meaningful decomposition — run single worker
        worker = await _answer_sub_question(
            query, provider, model, source_context,
            timeout_s=_WORKER_TIMEOUT_S,
        )
        merged = worker.answer or "Could not answer this question."
        return SynthesisResult(
            merged=merged,
            contradictions=[],
            worker_answers=[worker],
            decomposed=sub_questions,
        )

    # 2. Run workers in parallel
    worker_tasks = [
        _answer_sub_question(
            sq, provider, model, source_context,
            timeout_s=_WORKER_TIMEOUT_S,
        )
        for sq in sub_questions
    ]
    answers: list[WorkerAnswer] = list(
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    )

    # Unwrap any unexpected exception that wasn't caught inside workers
    for i, a in enumerate(answers):
        if isinstance(a, BaseException):
            logger.error("worker %d raised unexpected %s: %s", i, type(a).__name__, a)
            answers[i] = WorkerAnswer(
                sub_question=sub_questions[i] if i < len(sub_questions) else "unknown",
                answer="",
                error=f"Unexpected worker error: {a}",
            )

    # 3. Synthesize
    result = await _synthesize(query, answers, provider, model)
    result.decomposed = sub_questions
    return result
