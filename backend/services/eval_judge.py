"""LLM-as-judge service helpers for eval scoring.

Extracted from routers/eval.py so chats.py can call these functions without
importing from the HTTP router layer. The eval router itself now imports from
this module.

V6 / ctx DECISION: The groundedness judge runs via the WORKSPACE CHAT provider
(resolve_provider_for_workspace), NOT the gemma-tasks 270M slot. The gemma-tasks
ctx-size of 512 tokens is nearly exhausted by the GROUNDEDNESS_SYSTEM_PROMPT alone
(~1,700 chars / ~425 tokens), leaving insufficient budget for context + response.
No models.ini change is required.

Groundedness background-task helpers moved here from routers/chats.py
(2026-06-14) so chats.py can import them without a circular dependency on
eval.py and to co-locate all judge logic in one service module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Module-level set to hold live asyncio.Task references and prevent GC mid-flight.
_BG_EVAL_TASKS: set[asyncio.Task] = set()  # type: ignore[type-arg]


async def _run_groundedness_eval(
    message_id: uuid.UUID,
    workspace_id: uuid.UUID,
    assistant_text: str,
    context_text: str,
) -> None:
    """Background coroutine: run the groundedness LLM judge and write results.

    Soft-fails on any error -- never raises into the response path.
    Uses the workspace chat provider (not gemma-tasks) because GROUNDEDNESS_SYSTEM_PROMPT
    is ~1,700 chars (~425 tokens), nearly exhausting the gemma-tasks 512-token window.
    """
    try:
        from db import get_pool
        result = await resolve_judge_provider(workspace_id)
        if result is None:
            logger.info(
                "groundedness eval: no provider available, skipping msg %s", message_id
            )
            return
        provider, model = result
        # Truncate to leave budget for chat template overhead on large-context models.
        user_prompt = GROUNDEDNESS_USER_PROMPT.format(
            context=context_text[:4000],
            response=assistant_text[:2000],
        )
        eval_result = await call_llm_as_judge(
            provider, model, GROUNDEDNESS_SYSTEM_PROMPT, user_prompt
        )
        score = eval_result.get("score")
        violations = eval_result.get("violations") or []
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET groundedness_score = $2,
                    guard_flags = COALESCE(guard_flags, '{}'::jsonb)
                                  || jsonb_build_object(
                                       'groundedness_violations', $3::jsonb
                                     )
                WHERE id = $1::uuid
                """,
                message_id,
                score,
                json.dumps(violations),
            )
        logger.info(
            "groundedness eval: msg=%s score=%s violations=%d",
            message_id,
            score,
            len(violations),
        )
    except Exception as exc:
        logger.warning("groundedness eval failed (non-fatal): %s", exc)


async def maybe_fire_groundedness_eval(
    message_id: uuid.UUID,
    workspace_id: uuid.UUID,
    assistant_text: str,
    context_text: str,
) -> None:
    """Gate and fire the groundedness background task.

    Reads feature flag and sample rate from global_settings. Declared async
    so it can await the DB reads (global_settings reads are async operations).
    The caller should await this function; the actual judge work fires as an
    asyncio.create_task so it does NOT block the streaming response.
    """
    if not context_text:
        return
    try:
        from db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            enabled_val = await conn.fetchval(
                "SELECT value FROM global_settings WHERE key = 'groundedness_eval_enabled'"
            )
            if not enabled_val or enabled_val.lower() != "true":
                return
            rate_val = await conn.fetchval(
                "SELECT value FROM global_settings WHERE key = 'groundedness_eval_sample_rate'"
            )
        rate = float(rate_val or "1.0")
        if random.random() > rate:
            return
    except Exception as exc:
        logger.warning("groundedness eval: settings read failed (skipping): %s", exc)
        return

    task = asyncio.create_task(
        _run_groundedness_eval(
            message_id=message_id,
            workspace_id=workspace_id,
            assistant_text=assistant_text,
            context_text=context_text,
        )
    )
    _BG_EVAL_TASKS.add(task)
    task.add_done_callback(_BG_EVAL_TASKS.discard)

GROUNDEDNESS_SYSTEM_PROMPT = """You are an expert evaluator assessing how well an LLM response is supported by the provided context. This is a medical domain  -  factual accuracy is critical.

<Rubric>
A well-grounded output should:
- Make claims that are directly supported by the retrieved context
- Stay within the scope of information provided in the context
- Maintain the same meaning and intent as the source material
- Not introduce external facts or unsupported assertions outside of basic common knowledge

An ungrounded output:
- Makes claims without support from the context
- Contradicts the retrieved information
- Includes speculation or external knowledge outside of basic facts
- Distorts or misrepresents the context
- Hallucinates medical details, lab values, or clinical findings not present in the context
</Rubric>

<Instruction>
- Compare the response against the retrieved context carefully
- Identify claims, statements, and assertions in the response
- For each claim, locate supporting evidence in the context
- Check for:
  - Direct statements from context
  - Valid inferences from context
  - Unsupported additions
  - Contradictions with context
- Note any instances where the response extends beyond the context or combines information incorrectly
</Instruction>

<Reminder>
- Focus solely on alignment with provided context
- Consider both explicit and implicit claims
- Provide specific examples of grounded/ungrounded content
- Remember that correct grounding means staying true to the context, even if the context conflicts with common knowledge
</Reminder>

Return ONLY valid JSON with exactly these fields:
{
  "score": <float 0.0 to 1.0>,
  "explanation": "<detailed reasoning for the score>",
  "violations": ["<specific unsupported claim 1>", "<specific unsupported claim 2>", ...]
}"""

GROUNDEDNESS_USER_PROMPT = """Context:
{context}

Response to evaluate:
{response}

Evaluate the groundedness of this response against the provided context."""



def _parse_eval_response(raw: str) -> dict[str, Any]:
    """Parse JSON from the model response.

    Tries direct JSON parsing first, then falls back to extracting the first
    JSON object from markdown-fenced blocks or bare braces.
    """
    text = raw.strip()
    # Try direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Fallback: extract from ```json ... ``` or ``` ... ``` fences
    for pattern in (
        r"```json\s*\n(.*?)\n```",
        r"```\s*\n(.*?)\n```",
        r"\{.*\}",
    ):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                # Use group(1) for fenced patterns (capture group), group(0) for
                # the bare-braces pattern which has no capture group.
                fragment = m.group(1) if m.lastindex else m.group(0)
                data = json.loads(fragment)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not parse JSON from model output")


def _normalize_score(raw: Any) -> float | None:
    """Coerce score to float 0-1, or None if unparseable."""
    if raw is None:
        return None
    try:
        s = float(raw)
        return max(0.0, min(1.0, s))
    except (ValueError, TypeError):
        return None


def _build_eval_response(data: dict[str, Any]) -> dict[str, Any]:
    """Extract score, explanation, violations from parsed JSON.

    Tolerates missing or malformed fields -- returns defaults.
    """
    score = _normalize_score(data.get("score"))
    explanation = str(data.get("explanation", ""))
    raw_violations = data.get("violations")
    if isinstance(raw_violations, list):
        violations = [str(v) for v in raw_violations]
    else:
        violations = []
    return {
        "score": score,
        "explanation": explanation,
        "violations": violations,
    }


async def call_llm_as_judge(
    provider: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call the LLM provider with system+user prompts and parse JSON response.

    Public-facing counterpart of eval.py's _call_llm_as_judge (leading underscore
    removed). Error-tolerant: returns score=None on any failure (timeout, HTTP
    error, parse failure, empty response) with an explanation describing the error.
    """
    from services.provider_client import build_headers

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            if resp.status_code >= 400:
                error_text = resp.text[:500]
                logger.warning("Eval LLM returned %d: %s", resp.status_code, error_text)
                return _build_eval_response(
                    {
                        "score": None,
                        "explanation": f"LLM returned {resp.status_code}: {error_text}",
                        "violations": [],
                    }
                )
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Eval LLM timed out")
        return _build_eval_response(
            {"score": None, "explanation": "LLM request timed out", "violations": []}
        )
    except httpx.HTTPError as e:
        logger.warning("Eval LLM HTTP error: %s", e)
        return _build_eval_response(
            {"score": None, "explanation": f"LLM request failed: {e}", "violations": []}
        )
    except Exception as e:
        logger.warning("Eval LLM unexpected error: %s", e)
        return _build_eval_response(
            {
                "score": None,
                "explanation": f"Unexpected error: {e}",
                "violations": [],
            }
        )

    choices = data.get("choices") or []
    msg = choices[0].get("message") if choices else {}
    msg = msg or {}
    content = (msg.get("content") or "").strip()
    if not content:
        return _build_eval_response(
            {
                "score": None,
                "explanation": "LLM returned empty response",
                "violations": [],
            }
        )

    try:
        parsed = _parse_eval_response(content)
    except ValueError as e:
        logger.warning("Eval JSON parse failed: %s -- raw: %.200s", e, content)
        return _build_eval_response(
            {
                "score": None,
                "explanation": f"Could not parse LLM output: {e}",
                "violations": [],
            }
        )

    return _build_eval_response(parsed)


async def resolve_judge_provider(
    workspace_id: uuid.UUID | None,
) -> tuple[Any, str] | None:
    """Resolve the provider and model to use for LLM-as-judge calls.

    V6 / ctx DECISION: Uses the workspace chat provider (resolve_provider_for_workspace)
    rather than the gemma-tasks 270M slot. The GROUNDEDNESS_SYSTEM_PROMPT is ~1,700
    chars (~425 tokens), nearly filling the gemma-tasks ctx-size of 512 tokens and
    leaving no room for context + response text. The workspace chat provider (typically
    the 4B or 27B model) has a large enough context window to accommodate the full
    groundedness prompt.

    Returns (provider, model) tuple, or None if no provider is available.
    None means the caller should skip eval gracefully.
    """
    from services.provider_client import resolve_provider_for_workspace

    if workspace_id is not None:
        try:
            return await resolve_provider_for_workspace(workspace_id)
        except Exception as exc:
            logger.warning("resolve_judge_provider: workspace provider lookup failed: %s", exc)
            return None
    return None
