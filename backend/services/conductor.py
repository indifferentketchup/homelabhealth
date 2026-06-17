"""Wave scheduler for multi-perspective health analysis.

Adapted from boocode's conductor (flow.ts, spine.ts, dispatch.ts).
Enables parallel analysis from multiple angles with barrier synchronization.

Architecture:
    WaveScheduler — runs steps in waves; all steps in a wave run concurrently,
    the scheduler blocks until the wave completes before starting the next
    (barrier on deps).

    SpineFactory — defines input angles (perspectives), builds a flow of steps
    (fold → synthesizer → validator), and renders the structured report.

    Each step calls the workspace's provider independently via OpenAI-compatible
    chat completions (non-streaming).

Public surface:
    Step                          — dataclass: id, prompt, deps, model
    WaveScheduler                 — wave-based step executor with barrier sync
    AngleConfig                   — per-angle definition: id, label, system_prompt
    SpineFactory                  — flow builder + renderer with default health angles
    run_analysis                  — top-level convenience: build + schedule + render
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from services.context_handoff import extractive_summary
from services.provider_client import Provider, async_llm_call
from services.stall_detector import is_stalled

logger = logging.getLogger(__name__)

_WAVE_STALL_THRESHOLD = 3
_WAVE_STALL_SIMILARITY = 0.90


@dataclass
class Step:
    """A single step in a conductor flow.

    Each step runs independently via the provider. Steps whose ``deps`` are all
    satisfied run concurrently in the same wave. A step with no deps runs in
    wave 0.
    """

    id: str
    """Unique step identifier (e.g. ``"clinical"``, ``"fold"``)."""

    prompt: str
    """User-prompt content sent to the provider."""

    deps: list[str] = field(default_factory=list)
    """IDs of steps that must complete before this step runs."""

    model: str | None = None
    """Optional per-step model override. Falls back to the flow default."""



class WaveScheduler:
    """Deterministic wave scheduler over a collection of steps.

    Each tick, every step whose dependencies are all satisfied runs concurrently
    (the fan-out). The scheduler blocks on each wave before the next (the
    fan-in / barrier on deps). Sequencing and parallelism live HERE in code —
    never in a model's context.

    Usage::

        scheduler = WaveScheduler(steps)
        results = await scheduler.run(provider, model)
    """

    def __init__(self, steps: list[Step]) -> None:
        self._steps = steps

    async def run(
        self,
        provider: Provider,
        default_model: str,
        *,
        conn: object | None = None,
        message_id: object | None = None,
        compress_context: bool = False,
    ) -> dict[str, str]:
        """Execute all steps in dependency order, returning ``{step_id: output}``.

        Raises ``RuntimeError`` on dependency cycle, unsatisfiable deps, or
        wave stall (E3, lift-durable-orchestration, 2026-06-13).

        Optional kwargs:
        - ``conn`` / ``message_id``: when provided, write an orchestration cursor
          to the messages row after each wave completes. NOTE (V3): this is a
          no-op in the current call chain -- ``run_analysis`` creates no durable
          message row and does not pass conn/message_id. Cursor persistence for
          the conductor is wired only when called from a path that has a message
          ID. This is left explicit rather than silently dead.
        - ``compress_context``: when True and accumulated results exceed 4000
          chars, replace them with an extractive summary before the next wave
          (E4, lift-durable-orchestration, 2026-06-13). Default False -- no
          behavior change for existing callers.
        """
        results: dict[str, str] = {}
        done: set[str] = set()
        total = len(self._steps)
        wave_index = 0
        wave_outputs_window: list[list[str]] = []

        while len(done) < total:
            ready = [
                s
                for s in self._steps
                if s.id not in done and all(d in done for d in (s.deps or []))
            ]
            if not ready:
                raise RuntimeError(
                    f"conductor: dependency cycle or unsatisfiable deps. "
                    f"done={done!r}, remaining={[s.id for s in self._steps if s.id not in done]!r}"
                )

            wave_index += 1
            logger.info(
                "conductor wave %d: %d step(s) starting: %s",
                wave_index,
                len(ready),
                [s.id for s in ready],
            )

            outputs: list[str] = await asyncio.gather(
                *[self._run_step(s, provider, s.model or default_model) for s in ready],
                return_exceptions=True,
            )

            string_outputs: list[str] = []
            for step, output in zip(ready, outputs):
                if isinstance(output, BaseException):
                    logger.error(
                        "conductor step %s failed: %s",
                        step.id,
                        output,
                    )
                    results[step.id] = (
                        f"[Error: {type(output).__name__}: {output}]"
                    )
                else:
                    results[step.id] = output
                    string_outputs.append(output)
                done.add(step.id)

            logger.info("conductor wave %d completed", wave_index)

            # Stall detection: check if wave outputs are not progressing (E3).
            wave_outputs_window.append(string_outputs)
            if len(wave_outputs_window) >= _WAVE_STALL_THRESHOLD:
                flat = [" ".join(w) for w in wave_outputs_window[-_WAVE_STALL_THRESHOLD:]]
                if is_stalled(flat, _WAVE_STALL_THRESHOLD, _WAVE_STALL_SIMILARITY):
                    raise RuntimeError(
                        f"conductor: wave stall detected at wave {wave_index} "
                        f"(outputs are not progressing)"
                    )

            # Context compression: replace accumulated results with an extractive
            # summary when they exceed the threshold (E4, opt-in).
            if compress_context:
                total_len = sum(len(v) for v in results.values())
                if total_len > 4000:
                    summary = extractive_summary(list(results.values()))
                    results = {"_context_summary": summary}
                    logger.debug(
                        "conductor wave %d: context compressed (%d chars -> %d)",
                        wave_index,
                        total_len,
                        len(summary),
                    )

            # Cursor write after wave barrier (E2). No-op unless conn and message_id
            # are provided. See V3 note above -- currently unreachable from run_analysis.
            if conn is not None and message_id is not None:
                try:
                    cursor_payload = {
                        "type": "wave_scheduler",
                        "sub_questions": None,
                        "completed": {k: v for k, v in results.items()},
                        "wave_index": wave_index,
                    }
                    await conn.execute(  # type: ignore[attr-defined]
                        """
                        UPDATE messages
                        SET orchestration_cursor = $1::jsonb
                        WHERE id = $2::uuid
                        """,
                        json.dumps(cursor_payload),
                        message_id,
                    )
                    logger.debug(
                        "conductor wave %d: wrote orchestration cursor (%d steps completed)",
                        wave_index,
                        len(done),
                    )
                except Exception as exc:
                    logger.warning("conductor: cursor write failed (non-fatal): %s", exc)

        return results

    async def _run_step(
        self,
        step: Step,
        provider: Provider,
        model: str,
    ) -> str:
        """Execute one step by calling the provider's chat completions."""
        return await async_llm_call(
            provider,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a focused medical analyst. "
                        "Respond with your analysis only — no meta-commentary, no disclaimers about your role. "
                        "Be specific and cite evidence where applicable."
                    ),
                },
                {"role": "user", "content": step.prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout_s=60.0,
        )



@dataclass
class AngleConfig:
    """Configuration for one analysis angle / perspective."""

    id: str
    """Unique identifier (e.g. ``"clinical"``)."""

    label: str
    """Human-readable label (e.g. ``"Clinical Analysis"``)."""

    system_prompt: str
    """System prompt for this angle's worker step."""

    user_prompt_template: str
    """Template string. Use ``{query}`` as placeholder for the user's question."""

    def build_prompt(self, query: str) -> str:
        """Build the user-prompt for this angle by substituting ``{query}``."""
        return self.user_prompt_template.format(query=query)



class SpineFactory:
    """Builds a conductor flow from named analysis angles (perspectives).

    Flow shape::

        angle₁ ─┐
        angle₂ ─┼─▶ fold (merge) ─▶ synthesizer ─▶ validator ─▶ render
        angle₃ ─┘
        angle₄ ─┘

    Default health angles: clinical, safety, data-integrity, patient-facing.
    """

    ANGLES: dict[str, AngleConfig] = {
        "clinical": AngleConfig(
            id="clinical",
            label="Clinical Analysis",
            system_prompt=(
                "You are a clinical analyst reviewing a health query. "
                "Provide a thorough clinical assessment covering diagnosis, "
                "treatment options, prognosis, and relevant medical literature. "
                "Be specific about symptoms, medications, and interventions. "
                "Flag any information gaps that would affect clinical decision-making."
            ),
            user_prompt_template=(
                "Analyze the following health query from a clinical perspective:\n\n"
                "{query}\n\n"
                "Cover: (1) key clinical findings and their significance, "
                "(2) differential diagnoses if applicable, "
                "(3) treatment or management considerations, "
                "(4) gaps in the available information. "
                "Cite specific medical knowledge where relevant."
            ),
        ),
        "safety": AngleConfig(
            id="safety",
            label="Safety & Risk Assessment",
            system_prompt=(
                "You are a patient safety analyst. Identify potential risks, "
                "contraindications, adverse effects, and safety concerns. "
                "Flag any recommendations or claims that could be harmful. "
                "Use a conservative, evidence-based approach."
            ),
            user_prompt_template=(
                "Assess the following health query for safety concerns:\n\n"
                "{query}\n\n"
                "Identify: (1) potential risks or adverse effects, "
                "(2) contraindications or interactions to watch for, "
                "(3) any statements that could be misinterpreted or harmful, "
                "(4) recommended precautions. "
                "Be conservative — flag uncertainty rather than assuming safety."
            ),
        ),
        "data-integrity": AngleConfig(
            id="data-integrity",
            label="Data Integrity & Source Quality",
            system_prompt=(
                "You are a data integrity analyst. Evaluate the factual accuracy "
                "and completeness of information in health queries. Identify "
                "missing context, outdated claims, numerical inconsistencies, "
                "and unsupported assertions. Do not fabricate citations."
            ),
            user_prompt_template=(
                "Evaluate the data integrity and source quality for:\n\n"
                "{query}\n\n"
                "Check: (1) factual accuracy of any specific claims, "
                "(2) missing context that could change interpretation, "
                "(3) numerical or dosage consistency, "
                "(4) unsupported or speculative assertions. "
                "Note where information appears to be incomplete."
            ),
        ),
        "patient-facing": AngleConfig(
            id="patient-facing",
            label="Patient-Facing Communication",
            system_prompt=(
                "You are a patient communication specialist. Frame the health "
                "information in clear, accessible language suitable for a patient "
                "or caregiver. Prioritize actionable guidance, explain medical "
                "terms, and highlight when to seek professional care."
            ),
            user_prompt_template=(
                "Rephrase and analyze the following health query for a patient audience:\n\n"
                "{query}\n\n"
                "Provide: (1) a plain-language summary of the key information, "
                "(2) clear explanations of any medical terms, "
                "(3) actionable next steps or recommendations, "
                "(4) clear guidance on when to consult a healthcare professional. "
                "Assume the reader has no medical training."
            ),
        ),
    }

    @classmethod
    def build_flow(cls, angle_ids: list[str], query: str) -> list[Step]:
        """Build a list of Steps from angle IDs and a query.

        Produces one Step per angle, plus fold, synthesis, and validation steps.
        """
        steps: list[Step] = []
        angle_steps: list[str] = []

        for aid in angle_ids:
            config = cls.ANGLES.get(aid)
            if config is None:
                logger.warning("conductor: unknown angle %r, skipping", aid)
                continue
            steps.append(
                Step(
                    id=config.id,
                    prompt=config.build_prompt(query),
                )
            )
            angle_steps.append(config.id)

        if not angle_steps:
            raise ValueError("conductor: no valid angles provided")

        # Fold step — merge angle outputs
        steps.append(
            Step(
                id="fold",
                prompt=(
                    "Below are analyses from multiple perspectives on a health query. "
                    "Merge them into a coherent summary organized by topic.\n\n"
                    "For each topic area, synthesize what each angle contributed. "
                    "Do NOT simply repeat each angle's output verbatim — integrate them."
                ),
                deps=list(angle_steps),
            )
        )

        # Synthesis step — produce unified assessment
        steps.append(
            Step(
                id="synthesis",
                prompt=(
                    "Based on the merged analysis below, produce a unified health assessment. "
                    "Identify: (1) the key conclusions that all perspectives agree on, "
                    "(2) areas of disagreement or uncertainty, "
                    "(3) the most important actionable recommendations. "
                    "End with a one-paragraph bottom-line summary."
                ),
                deps=["fold"],
            )
        )

        # Validation step — adversarial gate
        steps.append(
            Step(
                id="validation",
                prompt=(
                    "Adversarially validate the analysis below. "
                    "Attack the evidence, the framing, the conclusions, and the integrity "
                    "of how the information was gathered.\n\n"
                    "Emit findings as V1, V2, … each with a severity (HIGH / MEDIUM / LOW) "
                    "and whether it changes the conclusion.\n\n"
                    "End with, in this order:\n"
                    "- VERDICT: does the conclusion survive? (Yes / Partially / No)\n"
                    "- CONTRADICTIONS: list any factual contradictions found\n"
                    "- CONFIDENCE: High | Medium | Low"
                ),
                deps=["synthesis"],
            )
        )

        return steps

    @classmethod
    def render_report(
        cls,
        query: str,
        angle_ids: list[str],
        results: dict[str, str],
    ) -> dict[str, Any]:
        """Render results into a structured JSON report.

        Returns a dict with per-angle findings, synthesis, validation,
        contradictions, and citations.
        """
        per_angle: list[dict[str, Any]] = []
        for aid in angle_ids:
            config = cls.ANGLES.get(aid)
            raw = results.get(aid, "")
            confidence = cls._extract_confidence(raw)
            per_angle.append(
                {
                    "angle": aid,
                    "label": config.label if config else aid,
                    "content": raw,
                    "confidence": confidence,
                    "status": "completed" if raw else "skipped",
                }
            )

        fold_text = results.get("fold", "")
        synthesis_text = results.get("synthesis", "")
        validation_text = results.get("validation", "")

        contradictions = cls._extract_contradictions(validation_text or synthesis_text or fold_text)
        citations = cls._extract_citations(fold_text + synthesis_text)

        verdict = ""
        confidence = "Medium"
        if validation_text:
            v_match = re.search(r"VERDICT\s*:\s*(.+)", validation_text, re.IGNORECASE)
            if v_match:
                verdict = v_match.group(1).strip()
            c_match = re.search(r"CONFIDENCE\s*:\s*(High|Medium|Low)", validation_text, re.IGNORECASE)
            if c_match:
                confidence = c_match.group(1)

        return {
            "query": query,
            "angles": angle_ids,
            "per_angle_findings": per_angle,
            "fold": fold_text,
            "synthesis": synthesis_text,
            "validation": validation_text,
            "verdict": verdict,
            "confidence": confidence,
            "contradictions": contradictions,
            "citations": citations,
            "status": "completed",
        }

    @staticmethod
    def _extract_confidence(text: str) -> str:
        """Extract a confidence rating from free-form text."""
        if not text:
            return "unknown"
        m = re.search(r"\b(HIGH|MEDIUM|LOW)\b", text.upper())
        if m:
            return m.group(1).title()
        return "unknown"

    @staticmethod
    def _extract_contradictions(text: str) -> list[str]:
        """Extract contradiction lines from validation/synthesis output."""
        if not text:
            return []
        results: list[str] = []
        in_section = False
        for line in text.split("\n"):
            stripped = line.strip()
            if re.search(r"CONTRADICTIONS", stripped, re.IGNORECASE):
                in_section = True
                continue
            if in_section:
                if re.search(r"^(VERDICT|CONFIDENCE)", stripped, re.IGNORECASE):
                    break
                if stripped and not stripped.startswith("-") and not stripped.startswith("*"):
                    # Could still be continuation — check length
                    if len(stripped) > 10 and not stripped.startswith("None"):
                        results.append(stripped)
                elif stripped.startswith("-") or stripped.startswith("*"):
                    cleaned = stripped.lstrip("-* ").strip()
                    if cleaned and cleaned.lower() not in ("none detected.", "none"):
                        results.append(cleaned)
        return results

    @staticmethod
    def _extract_citations(text: str) -> list[str]:
        """Extract inline citations from text."""
        if not text:
            return []
        found: list[str] = []
        # Match [1], [2,3], [Author, Year], etc.
        for m in re.finditer(r'\[([^\]]+)\]', text):
            ref = m.group(1).strip()
            if ref and ref not in found:
                found.append(ref)
        return found



async def run_analysis(
    query: str,
    provider: Provider,
    model: str,
    angle_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full multi-perspective analysis pipeline.

    Args:
        query: The health query to analyze.
        provider: Resolved provider to call.
        model: Model name to use.
        angle_ids: Which angles to include. Defaults to all four health angles.

    Returns:
        A structured report dict (see ``SpineFactory.render_report``).
    """
    if angle_ids is None:
        angle_ids = list(SpineFactory.ANGLES.keys())

    steps = SpineFactory.build_flow(angle_ids, query)
    scheduler = WaveScheduler(steps)
    results = await scheduler.run(provider, model)

    return SpineFactory.render_report(query, angle_ids, results)
