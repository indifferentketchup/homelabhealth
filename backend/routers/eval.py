"""LLM-as-judge RAG evaluation endpoints.

Adapted from OpenEvals RAG evaluator prompts for the medical domain.
Each endpoint uses the workspace's configured provider for LLM-as-judge
and returns structured scores with explanations and violations.

Endpoints:
  POST /api/eval/groundedness       — is the response supported by the context?
  POST /api/eval/helpfulness         — does the response address the query?
  POST /api/eval/retrieval-relevance — are the retrieved docs relevant to the query?
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import require_admin
from services.audit import AuditEventHandle, audit_event
from services.provider_client import build_headers, resolve_provider_for_workspace

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EvalWorkspaceMixin(BaseModel):
    """Every eval request must specify which workspace's provider to use."""

    workspace_id: uuid.UUID = Field(
        ..., description="Workspace whose inference provider runs the evaluation"
    )


class GroundednessRequest(EvalWorkspaceMixin):
    """Evaluate whether the response is supported by the provided context."""

    query: str = Field(..., min_length=1)
    context: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1)


class HelpfulnessRequest(EvalWorkspaceMixin):
    """Evaluate whether the response addresses the user query."""

    query: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1)


class RetrievalRelevanceRequest(EvalWorkspaceMixin):
    """Evaluate whether the retrieved documents are relevant to the query."""

    query: str = Field(..., min_length=1)
    documents: list[str] = Field(..., min_length=1)


class EvalViolation(BaseModel):
    """A single violation or issue identified by the evaluator."""

    detail: str = ""


class EvalResponse(BaseModel):
    """Structured evaluation result.

    score is None when the LLM call or JSON parsing fails (error-tolerant).
    """

    score: float | None = None
    explanation: str = ""
    violations: list[str] = []


# ---------------------------------------------------------------------------
# Prompt templates (adapted from OpenEvals, medical-domain-tuned)
# ---------------------------------------------------------------------------

GROUNDEDNESS_SYSTEM_PROMPT = """You are an expert evaluator assessing how well an LLM response is supported by the provided context. This is a medical domain — factual accuracy is critical.

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

HELPFULNESS_SYSTEM_PROMPT = """You are an expert evaluator assessing how helpful and relevant an LLM response is in addressing a user query. This is a medical domain — responses should be thorough, accurate, and directly address the user's health information needs.

<Rubric>
A helpful and relevant output should:
- Directly address the core question or need in the query
- Provide accurate and necessary information
- Be appropriately detailed for the query's scope
- May reference the provided context without needing external verification

An unhelpful or irrelevant output:
- Fails to address the main question
- Contains primarily unrelated information
- Is too vague or generic to be useful
- Omits critical information the query explicitly requests
</Rubric>

<Instruction>
- Read and understand the full meaning of the query
- Identify any implicit requirements or context
- Identify the expected scope of the answer
- Analyze the response to identify:
  - How well it addresses the core question
  - The relevance of included information
  - Any critical missing information
  - Any extraneous or unhelpful content
</Instruction>

<Reminder>
- Evaluate based on practical usefulness to the query
- Consider both direct relevance and helpful context
- Identify specific strengths and weaknesses in the response
- Provide clear reasoning for your assessment
</Reminder>

Return ONLY valid JSON with exactly these fields:
{
  "score": <float 0.0 to 1.0>,
  "explanation": "<detailed reasoning for the score>",
  "violations": ["<specific way the response fails 1>", "<specific way the response fails 2>", ...]
}"""

HELPFULNESS_USER_PROMPT = """User query:
{query}

Response to evaluate:
{response}

Evaluate the helpfulness of this response in addressing the user query."""

RETRIEVAL_RELEVANCE_SYSTEM_PROMPT = """You are an expert evaluator assessing how relevant retrieved documents are to a user query in the medical domain.

<Rubric>
Relevant retrieved documents:
- Contain information that could help answer the query, even if incomplete
- May include superfluous information, but it should still be somewhat related to the query
- Provide clinically useful context even if not a direct answer

Irrelevant retrieved documents:
- Contain no useful information for answering the query
- Are entirely unrelated to the query
- Contain misleading or incorrect information
- Contain only tangentially related information with no practical utility
</Rubric>

<Instruction>
- Read and understand the full meaning of the query
- Formulate a list of facts and relevant context that would be needed to respond to the query
- Analyze the retrieved documents to identify:
  - Information directly relevant to answering the query
  - Information partially relevant or contextually helpful
  - Information completely irrelevant to the query
- For each piece of information needed, determine whether it is addressed by the retrieved documents
- Note any facts needed to answer the query that are not found in the documents
</Instruction>

<Reminder>
- Focus solely on whether the retrieved documents provide useful information for answering the query
- Think deeply about why each document is or isn't relevant
- Use partial credit where applicable, recognizing documents that are somewhat helpful even if incomplete
</Reminder>

Return ONLY valid JSON with exactly these fields:
{
  "score": <float 0.0 to 1.0>,
  "explanation": "<detailed reasoning for the score>",
  "violations": ["<missing or irrelevant aspect 1>", "<missing or irrelevant aspect 2>", ...]
}"""

RETRIEVAL_RELEVANCE_USER_PROMPT = """User query:
{query}

Retrieved documents:
{documents}

Evaluate the relevance of these retrieved documents to the user query."""

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
                data = json.loads(m.group(1))
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

    Tolerates missing or malformed fields — returns defaults.
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


async def _call_llm_as_judge(
    provider,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call the LLM provider with system+user prompts and parse JSON response.

    Error-tolerant: returns score=None on any failure (timeout, HTTP error,
    parse failure, empty response) with an explanation describing the error.
    """
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
        logger.warning("Eval JSON parse failed: %s — raw: %.200s", e, content)
        return _build_eval_response(
            {
                "score": None,
                "explanation": f"Could not parse LLM output: {e}",
                "violations": [],
            }
        )

    return _build_eval_response(parsed)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/groundedness", response_model=EvalResponse)
async def eval_groundedness(
    body: GroundednessRequest,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Evaluate whether the response is supported by the provided context.

    Returns a score (0-1), explanation, and list of unsupported claims.
    """
    provider, model = await resolve_provider_for_workspace(body.workspace_id)
    user_prompt = GROUNDEDNESS_USER_PROMPT.format(
        context=body.context, response=body.response
    )
    result = await _call_llm_as_judge(
        provider, model, GROUNDEDNESS_SYSTEM_PROMPT, user_prompt
    )
    async with audit.targeting("eval", None):
        pass
    return result


@router.post("/helpfulness", response_model=EvalResponse)
async def eval_helpfulness(
    body: HelpfulnessRequest,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Evaluate whether the response addresses the user query.

    Returns a score (0-1), explanation, and list of ways the response falls short.
    """
    provider, model = await resolve_provider_for_workspace(body.workspace_id)
    user_prompt = HELPFULNESS_USER_PROMPT.format(
        query=body.query, response=body.response
    )
    result = await _call_llm_as_judge(
        provider, model, HELPFULNESS_SYSTEM_PROMPT, user_prompt
    )
    async with audit.targeting("eval", None):
        pass
    return result


@router.post("/retrieval-relevance", response_model=EvalResponse)
async def eval_retrieval_relevance(
    body: RetrievalRelevanceRequest,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Evaluate whether the retrieved documents are relevant to the query.

    Returns a score (0-1), explanation, and list of missing/irrelevant aspects.
    """
    provider, model = await resolve_provider_for_workspace(body.workspace_id)
    documents_text = "\n\n".join(
        f"Document {i + 1}:\n{doc}" for i, doc in enumerate(body.documents)
    )
    user_prompt = RETRIEVAL_RELEVANCE_USER_PROMPT.format(
        query=body.query, documents=documents_text
    )
    result = await _call_llm_as_judge(
        provider, model, RETRIEVAL_RELEVANCE_SYSTEM_PROMPT, user_prompt
    )
    async with audit.targeting("eval", None):
        pass
    return result
