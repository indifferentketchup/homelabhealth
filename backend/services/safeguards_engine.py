"""Medical-AI safeguards engine: five fixed rules, keyword matching, priority resolution.

The engine holds five hardcoded safeguard rules (diagnosis, emergency, self-harm,
medication, medication-combination), matches an incoming user query against each rule's
condition by keyword overlap, and resolves overlapping matches down to the surviving
set. ``safeguards.py`` reads the cached result via ``get_cached_result()`` and turns it
into either contextual directives or (for self-harm) the locked full prompt.

Integration: ``safeguards.py`` registers an ``on_user_prompt`` hook that calls
``evaluate()`` and caches the result in a contextvar for the current request.

This replaced a ported generic guideline framework (CRUD store, relationship graph,
multi-batch matcher, iterative resolver) on 2026-06-15; for the five fixed rules that
framework produced the same output as the compact resolution below. See
openspec/changes/trim-safeguards-engine. Public names preserved for consumers:
Criticality, Guideline, GuidelineContent, GuidelineMatch, get_engine, reset_engine.
"""
from __future__ import annotations

import contextvars
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Criticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


CRITICALITY_ORDER: dict[Criticality, int] = {
    Criticality.LOW: 0,
    Criticality.MEDIUM: 1,
    Criticality.HIGH: 2,
    Criticality.CRITICAL: 3,
}


def criticality_to_weight(c: Criticality) -> int:
    return CRITICALITY_ORDER[c]


@dataclass
class GuidelineContent:
    """The natural-language condition and action of a guideline."""
    condition: str
    action: str | None = None


@dataclass
class Guideline:
    """A single safeguard rule with condition, action, criticality, and relationships.

    Relationships reference other rules by id:
      depends_on  — this rule is dropped unless every target also matched.
      prioritizes — when this rule survives, its targets are removed.
      entails     — targets that should accompany this rule (see _resolve).
    """
    id: str
    content: GuidelineContent
    criticality: Criticality = Criticality.MEDIUM
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    depends_on: tuple[str, ...] = ()
    prioritizes: tuple[str, ...] = ()
    entails: tuple[str, ...] = ()


@dataclass
class GuidelineMatch:
    """A guideline that matched (and survived resolution for) the current query."""
    guideline: Guideline


# -- Keyword matching (unchanged: defines which queries match which rules) ----

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "but", "and", "or", "if", "while", "about", "up",
    "what", "which", "who", "whom", "this", "that", "these", "those", "it",
    "its", "you", "your", "they", "them", "their", "he", "she", "his",
    "her", "him", "my", "me", "i", "we", "us", "our", "tell", "explain",
    "describe", "what", "does", "mean", "should", "like", "know", "get",
    "give", "make", "want", "ask", "say", "would", "could", "please",
    "help", "need", "looking", "trying", "told", "had", "has", "have",
    "been", "being", "was", "were", "did", "doing", "go", "went", "gone",
    "take", "took", "taken", "see", "saw", "seen", "think", "thought",
    "thanks", "thank",
})


def _extract_keywords(text: str) -> set[str]:
    """Extract significant lowercase words from text, excluding stop words."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _keyword_match_score(condition: str, query: str) -> float:
    """Match score (0.0-1.0): proportion of condition keywords present in the query."""
    cond_keywords = _extract_keywords(condition)
    if not cond_keywords:
        return 0.0
    query_keywords = _extract_keywords(query)
    if not query_keywords:
        return 0.0
    overlap = len(cond_keywords & query_keywords)
    return min(1.0, overlap / len(cond_keywords))


# -- The five fixed rules -----------------------------------------------------

_DEFAULT_GUIDELINES: list[Guideline] = [
    Guideline(
        id="dx",
        content=GuidelineContent(
            condition="user asks for diagnosis",
            action="explain findings, state limits, recommend clinician",
        ),
        criticality=Criticality.HIGH,
        priority=10,
        tags=["diagnosis", "medical_advice"],
    ),
    Guideline(
        id="em",
        content=GuidelineContent(
            condition="user describes emergency symptoms",
            action="flag urgency, continue normally",
        ),
        criticality=Criticality.CRITICAL,
        priority=100,
        tags=["emergency", "urgent"],
        depends_on=("sh",),
    ),
    Guideline(
        id="sh",
        content=GuidelineContent(
            condition="user expresses self-harm",
            action="[CRISIS] block only",
        ),
        criticality=Criticality.CRITICAL,
        priority=200,
        tags=["crisis", "self_harm"],
        prioritizes=("dx", "em", "med", "med_comb"),
    ),
    Guideline(
        id="med",
        content=GuidelineContent(
            condition="user asks about medication",
            action="general info only, point to pharmacist",
        ),
        criticality=Criticality.HIGH,
        priority=5,
        tags=["medication"],
    ),
    Guideline(
        id="med_comb",
        content=GuidelineContent(
            condition="user asks medication combinations",
            action="explain general interactions, direct to pharmacist",
        ),
        criticality=Criticality.MEDIUM,
        priority=5,
        tags=["medication", "interaction"],
        entails=("med",),
    ),
]


def _resolve(matched: list[Guideline]) -> list[Guideline]:
    """Reduce matched rules to the surviving set.

    Reproduces the original relationship + numerical-priority resolver:
      1. drop a rule whose depends_on target did not also match;
      2. a surviving rule removes its prioritizes targets;
      3. keep only the highest-priority survivors.

    The ENTAILS edge is inert under this ordering (numerical priority runs before
    entailment, and a target survives step 2/3 only if it is already in the set), so it
    is not applied. The `entails` field is retained on Guideline so the rule data stays
    complete; see openspec/changes/trim-safeguards-engine/design.md.
    """
    by_id = {g.id: g for g in matched}
    matched_ids = set(by_id)
    surviving = set(matched_ids)

    for g in matched:
        if any(dep not in matched_ids for dep in g.depends_on):
            surviving.discard(g.id)

    for g in matched:
        if g.id in surviving:
            for target in g.prioritizes:
                surviving.discard(target)

    if surviving:
        top = max(by_id[i].priority for i in surviving)
        surviving = {i for i in surviving if by_id[i].priority >= top}

    return [g for g in matched if g.id in surviving]


class SafeguardsEngine:
    """Matches a user query against the fixed rules and caches the surviving set
    per request. ``safeguards.py`` reads the cache via ``get_cached_result()``."""

    def __init__(self) -> None:
        self._guidelines = _DEFAULT_GUIDELINES
        self._evaluation_cache: contextvars.ContextVar[list[GuidelineMatch] | None] = (
            contextvars.ContextVar("safeguards_engine_cache", default=None)
        )

    def evaluate(self, user_query: str) -> list[GuidelineMatch]:
        """Match the query against the rules, resolve overlaps, cache and return."""
        matched = [
            g for g in self._guidelines
            if _keyword_match_score(g.content.condition, user_query) > 0
        ]
        result = [GuidelineMatch(guideline=g) for g in _resolve(matched)]
        self._evaluation_cache.set(result)
        return result

    def get_cached_result(self) -> list[GuidelineMatch] | None:
        """Return the cached evaluation result for the current request, or None."""
        return self._evaluation_cache.get()

    def clear_cache(self) -> None:
        """Clear the per-request evaluation cache."""
        self._evaluation_cache.set(None)


_engine: SafeguardsEngine | None = None


def get_engine() -> SafeguardsEngine:
    global _engine
    if _engine is None:
        _engine = SafeguardsEngine()
    return _engine


def reset_engine() -> None:
    """For testing — reset the singleton engine."""
    global _engine
    _engine = None
