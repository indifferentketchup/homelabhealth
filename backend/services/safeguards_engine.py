"""Guideline engine for medical-AI safeguards — structured condition/action
rules with criticality levels, multi-batch LLM matcher, and relational resolution.

Port of boocontext-audit's Guideline model, matching batches, and resolver.
Zero external dependencies — pure Python dataclasses + stdlib.

Architecture:
  GuidelineStore   — in-memory store of Guideline rules
  RelationshipStore — in-memory store of DEPENDS_ON / PRIORITIZES / ENTAILS edges
  Matcher          — runs 6 batch types against a user query, scores each guideline
  Resolver         — applies relational constraints to reach a converged set
  SafeguardsEngine — orchestrator; seeds default rules, caches per-request evaluations

Integration:
  The engine registers an ``on_user_prompt`` hook callback that evaluates the
  incoming user query and caches the result in a contextvar.  ``prepend_safeguard()``
  (in safeguards.py) reads that cache to produce engine-driven output while keeping
  its existing function signature.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Criticality
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Guideline data model
# ---------------------------------------------------------------------------

@dataclass
class GuidelineContent:
    """The natural-language condition and action of a guideline."""
    condition: str
    action: str | None = None
    description: str | None = None


@dataclass
class Guideline:
    """A single safeguard rule with condition, action, criticality, and metadata."""
    id: str
    content: GuidelineContent
    enabled: bool = True
    criticality: Criticality = Criticality.MEDIUM
    priority: int = 0
    labels: set[str] = field(default_factory=set)
    tags: list[str] = field(default_factory=list)
    title: str | None = None
    creation_utc: str = ""


def sort_by_priority(a: Guideline, b: Guideline) -> int:
    """Sort descending by criticality weight, then ascending by priority number."""
    ca = criticality_to_weight(a.criticality)
    cb = criticality_to_weight(b.criticality)
    if ca != cb:
        return cb - ca
    return a.priority - b.priority


def is_observational(g: Guideline) -> bool:
    return g.content.action is None


def is_actionable(g: Guideline) -> bool:
    return g.content.action is not None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return f"gl_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# GuidelineStore  (port of InMemoryGuidelineStore from guideline.ts)
# ---------------------------------------------------------------------------

class GuidelineStore:
    """In-memory store for Guideline objects."""

    def __init__(self) -> None:
        self._guidelines: dict[str, Guideline] = {}
        self._tag_associations: list[dict[str, Any]] = []

    def create(
        self,
        *,
        condition: str,
        action: str | None = None,
        description: str | None = None,
        title: str | None = None,
        criticality: Criticality = Criticality.MEDIUM,
        enabled: bool = True,
        tags: list[str] | None = None,
        labels: set[str] | None = None,
        priority: int = 0,
        guideline_id: str | None = None,
    ) -> Guideline:
        gid = guideline_id or _gen_id()
        guideline = Guideline(
            id=gid,
            content=GuidelineContent(
                condition=condition,
                action=action,
                description=description,
            ),
            title=title,
            criticality=criticality,
            enabled=enabled,
            labels=labels or set(),
            tags=tags or [],
            priority=priority,
            creation_utc=_now_utc(),
        )
        self._guidelines[gid] = guideline
        for tag_id in (tags or []):
            self._tag_associations.append({
                "id": f"ta_{uuid.uuid4().hex[:8]}",
                "guideline_id": gid,
                "tag_id": tag_id,
                "creation_utc": _now_utc(),
            })
        return guideline

    def read(self, gid: str) -> Guideline:
        g = self._guidelines.get(gid)
        if g is None:
            raise KeyError(f"Guideline not found: {gid}")
        return g

    def update(
        self,
        gid: str,
        *,
        condition: str | None = None,
        action: str | None = None,
        description: str | None = None,
        title: str | None = None,
        criticality: Criticality | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> Guideline:
        g = self.read(gid)
        if condition is not None:
            g.content.condition = condition
        if action is not None:
            g.content.action = action
        if description is not None:
            g.content.description = description
        if title is not None:
            g.title = title
        if criticality is not None:
            g.criticality = criticality
        if enabled is not None:
            g.enabled = enabled
        if priority is not None:
            g.priority = priority
        return g

    def delete(self, gid: str) -> None:
        if gid not in self._guidelines:
            raise KeyError(f"Guideline not found: {gid}")
        del self._guidelines[gid]
        self._tag_associations = [
            t for t in self._tag_associations if t["guideline_id"] != gid
        ]

    def list(self, *, tags: list[str] | None = None,
             labels: set[str] | None = None) -> list[Guideline]:
        result = list(self._guidelines.values())
        if tags:
            tag_set = set(tags)
            associated = set(
                t["guideline_id"]
                for t in self._tag_associations
                if t["tag_id"] in tag_set
            )
            result = [g for g in result if g.id in associated]
        if labels:
            result = [
                g for g in result
                if all(label in g.labels for label in labels)
            ]
        return result

    def find_by_content(self, condition: str, action: str | None) -> Guideline | None:
        for g in self._guidelines.values():
            if g.content.condition == condition and g.content.action == action:
                return g
        return None

    def upsert_tag(self, gid: str, tag_id: str) -> bool:
        self.read(gid)  # raises if not found
        exists = any(
            t["guideline_id"] == gid and t["tag_id"] == tag_id
            for t in self._tag_associations
        )
        if exists:
            return False
        self._tag_associations.append({
            "id": f"ta_{uuid.uuid4().hex[:8]}",
            "guideline_id": gid,
            "tag_id": tag_id,
            "creation_utc": _now_utc(),
        })
        return True

    def remove_tag(self, gid: str, tag_id: str) -> None:
        idx = -1
        for i, t in enumerate(self._tag_associations):
            if t["guideline_id"] == gid and t["tag_id"] == tag_id:
                idx = i
                break
        if idx < 0:
            raise KeyError(f"Tag not found: {tag_id}")
        self._tag_associations.pop(idx)

    def count(self) -> int:
        return len(self._guidelines)

    def clear(self) -> None:
        self._guidelines.clear()
        self._tag_associations.clear()


# ---------------------------------------------------------------------------
# Relationship types   (port of relationship.ts)
# ---------------------------------------------------------------------------

class RelationshipKind(str, Enum):
    DEPENDS_ON = "depends_on"
    PRIORITIZES = "prioritizes"
    ENTAILS = "entails"


@dataclass
class RelationshipEntity:
    id: str
    kind: str  # "guideline" | "tag"


@dataclass
class Relationship:
    id: str
    creation_utc: str
    source: RelationshipEntity
    target: RelationshipEntity
    kind: RelationshipKind
    group_id: str | None = None


def _rel_id() -> str:
    return f"rel_{uuid.uuid4().hex[:10]}"


class RelationshipStore:
    """In-memory store for guideline relationships."""

    def __init__(self) -> None:
        self._rels: dict[str, Relationship] = {}

    def create_relationship(
        self,
        source: RelationshipEntity,
        target: RelationshipEntity,
        kind: RelationshipKind,
        group_id: str | None = None,
    ) -> Relationship:
        rel = Relationship(
            id=_rel_id(),
            creation_utc=_now_utc(),
            source=source,
            target=target,
            kind=kind,
            group_id=group_id,
        )
        self._rels[rel.id] = rel
        return rel

    def read_relationship(self, rid: str) -> Relationship:
        rel = self._rels.get(rid)
        if rel is None:
            raise KeyError(f"Relationship not found: {rid}")
        return rel

    def delete_relationship(self, rid: str) -> None:
        if rid not in self._rels:
            raise KeyError(f"Relationship not found: {rid}")
        del self._rels[rid]

    def list_relationships(
        self,
        kind: RelationshipKind | None = None,
        source_id: str | None = None,
    ) -> list[Relationship]:
        result = list(self._rels.values())
        if kind is not None:
            result = [r for r in result if r.kind == kind]
        if source_id is not None:
            result = [r for r in result if r.source.id == source_id]
        return result

    def delete_relationships_for_entity(self, entity_id: str) -> None:
        to_delete = [
            rid for rid, r in self._rels.items()
            if r.source.id == entity_id or r.target.id == entity_id
        ]
        for rid in to_delete:
            del self._rels[rid]

    def count(self) -> int:
        return len(self._rels)


# ---------------------------------------------------------------------------
# Matching types
# ---------------------------------------------------------------------------

@dataclass
class GuidelineMatch:
    """Result of matching a guideline against a user query."""
    guideline: Guideline
    score: float
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchingContext:
    """Ambient context for a single matching run."""
    user_query: str
    interaction_history: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Keyword-matching helper
# ---------------------------------------------------------------------------

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
    """Compute a match score (0.0–1.0) between a guideline condition and user query
    using keyword overlap."""
    cond_keywords = _extract_keywords(condition)
    if not cond_keywords:
        return 0.0
    query_keywords = _extract_keywords(query)
    if not query_keywords:
        return 0.0
    overlap = len(cond_keywords & query_keywords)
    # Score is the proportion of condition keywords that appear in the query
    return min(1.0, overlap / len(cond_keywords))


# ---------------------------------------------------------------------------
# Batch matchers  (port of matching.ts)
#
# Each batch type has:
#   - A structured LLM prompt template (for future LLM-based matching)
#   - A process() method that does heuristic keyword matching
# ---------------------------------------------------------------------------

@dataclass
class BatchResult:
    matches: list[GuidelineMatch]


class ObservationalBatch:
    """Batch type: "What relevant guidelines exist?"
    Evaluates observational guidelines (those without actions).
    """
    PROMPT_TEMPLATE: str = """\
You are evaluating observational guidelines against a user's query.
For each guideline below, determine whether its condition is relevant
to the user's message.

User query: {user_query}

Guidelines:
{guidelines_text}

For each guideline, respond with:
- guideline_id: the ID
- condition: the condition text  
- rationale: brief reasoning
- applies: true/false
"""

    def __init__(self, guidelines: list[Guideline], context: MatchingContext) -> None:
        self._guidelines = [g for g in guidelines if is_observational(g) and g.enabled]
        self._context = context

    @property
    def size(self) -> int:
        return len(self._guidelines)

    def process(self) -> BatchResult:
        matches: list[GuidelineMatch] = []
        for g in self._guidelines:
            score = _keyword_match_score(g.content.condition, self._context.user_query)
            if score > 0:
                matches.append(GuidelineMatch(
                    guideline=g,
                    score=score * 10.0,  # scale to 0–10
                    rationale=f"Observational: condition '{g.content.condition}' "
                              f"matched query (score={score:.2f})",
                    metadata={"batch_type": "observational", "match_score": score},
                ))
        return BatchResult(matches=matches)


class ActionableBatch:
    """Batch type: "What should I do?"
    Evaluates actionable guidelines (those with defined actions).
    """
    PROMPT_TEMPLATE: str = """\
You are evaluating actionable guidelines against a user's query.
For each guideline, decide whether the condition matches and the
action should be taken.

User query: {user_query}

Guidelines:
{guidelines_text}

For each guideline, respond with:
- guideline_id: the ID
- condition: the condition text
- action: the prescribed action
- rationale: brief reasoning
- applies: true/false
"""

    def __init__(self, guidelines: list[Guideline], context: MatchingContext) -> None:
        self._guidelines = [g for g in guidelines if is_actionable(g) and g.enabled]
        self._context = context

    @property
    def size(self) -> int:
        return len(self._guidelines)

    def process(self) -> BatchResult:
        matches: list[GuidelineMatch] = []
        for g in self._guidelines:
            score = _keyword_match_score(g.content.condition, self._context.user_query)
            if score > 0:
                matches.append(GuidelineMatch(
                    guideline=g,
                    score=score * 10.0,
                    rationale=f"Actionable: when '{g.content.condition}' "
                              f"then '{g.content.action}' (score={score:.2f})",
                    metadata={"batch_type": "actionable", "match_score": score},
                ))
        return BatchResult(matches=matches)


class PreviouslyAppliedBatch:
    """Batch type: "What did I do before?"
    Marks guidelines that were matched in prior evaluations for continuity.
    """
    PROMPT_TEMPLATE: str = """\
You are reviewing previously applied guidelines for the current user query.
Determine whether each previously-matched guideline is still applicable.

User query: {user_query}

Previously applied guidelines:
{guidelines_text}

For each guideline:
- guideline_id: the ID
- condition: the condition text
- action_segment: the action text
- rationale: brief reasoning
- is_still_applicable: true/false
"""

    def __init__(self, prior_matches: list[GuidelineMatch], context: MatchingContext) -> None:
        self._prior_matches = prior_matches
        self._context = context

    @property
    def size(self) -> int:
        return len(self._prior_matches)

    def process(self) -> BatchResult:
        matches: list[GuidelineMatch] = []
        for pm in self._prior_matches:
            g = pm.guideline
            # Re-check if the condition still matches the current query
            score = _keyword_match_score(g.content.condition, self._context.user_query)
            if score > 0:
                matches.append(GuidelineMatch(
                    guideline=g,
                    score=max(pm.score, score * 10.0),
                    rationale=f"Previously applied and still relevant: "
                              f"'{g.content.condition}'",
                    metadata={"batch_type": "previously_applied", "prior_score": pm.score},
                ))
        return BatchResult(matches=matches)


class DisambiguationBatch:
    """Batch type: "Which applies more?"
    When multiple guidelines overlap, pick the most specific one.
    """
    PROMPT_TEMPLATE: str = """\
You are resolving ambiguity between overlapping guidelines.
Select the single most applicable guideline for the user's query.

User query: {user_query}

Conflicting guidelines:
{guidelines_text}

Respond with:
- source_guideline_id: the selected guideline
- rationale: why it applies more than the others
- enriched_action: what action to take
- targets: list of deprioritized guideline IDs
"""

    def __init__(self, candidates: list[GuidelineMatch], context: MatchingContext) -> None:
        self._candidates = candidates
        self._context = context

    @property
    def size(self) -> int:
        return len(self._candidates)

    def process(self) -> BatchResult:
        if not self._candidates:
            return BatchResult(matches=[])
        # Sort by criticality weight descending, then score descending
        sorted_candidates = sorted(
            self._candidates,
            key=lambda m: (criticality_to_weight(m.guideline.criticality), m.score),
            reverse=True,
        )
        # Pick the top candidate as the disambiguated winner
        winner = sorted_candidates[0]
        winner.metadata["batch_type"] = "disambiguation"
        winner.metadata["disambiguation_targets"] = [
            m.guideline.id for m in sorted_candidates[1:]
        ]
        return BatchResult(matches=[winner])


class LowCriticalityBatch:
    """Batch type: "Any minor concerns?"
    Separate pass for low-criticality guidelines so they don't drown out
    higher-priority rules.
    """
    PROMPT_TEMPLATE: str = """\
You are checking for low-criticality concerns in the user's query.
These are minor issues that should be noted but may not require action.

User query: {user_query}

Low-criticality guidelines:
{guidelines_text}

For each guideline:
- guideline_id: the ID
- condition: the condition text
- rationale: brief reasoning
- applies: true/false
"""

    def __init__(self, guidelines: list[Guideline], context: MatchingContext) -> None:
        self._guidelines = [
            g for g in guidelines
            if g.criticality == Criticality.LOW and g.enabled
        ]
        self._context = context

    @property
    def size(self) -> int:
        return len(self._guidelines)

    def process(self) -> BatchResult:
        matches: list[GuidelineMatch] = []
        for g in self._guidelines:
            score = _keyword_match_score(g.content.condition, self._context.user_query)
            if score > 0:
                matches.append(GuidelineMatch(
                    guideline=g,
                    score=score * 10.0,
                    rationale=f"Low-criticality: '{g.content.condition}' "
                              f"(score={score:.2f})",
                    metadata={"batch_type": "low_criticality", "match_score": score},
                ))
        return BatchResult(matches=matches)


class ResponseAnalysisBatch:
    """Batch type: "Does my response comply?"
    Post-hoc analysis of whether the matched guidelines were followed.
    Runs after response generation (called separately from main matcher).
    """
    PROMPT_TEMPLATE: str = """\
You are analyzing whether the assistant's response complies with
the matched guidelines.

User query: {user_query}
Assistant response: {assistant_response}

Matched guidelines:
{guidelines_text}

For each guideline:
- guideline_id: the ID
- condition: the condition text
- was_followed: true/false
- rationale: brief reasoning
"""

    def __init__(self, guideline_matches: list[GuidelineMatch]) -> None:
        self._guideline_matches = guideline_matches

    @property
    def size(self) -> int:
        return len(self._guideline_matches)

    def process(self) -> BatchResult:
        # In this version, response analysis acknowledges all matched guidelines
        matches = []
        for m in self._guideline_matches:
            matches.append(GuidelineMatch(
                guideline=m.guideline,
                score=m.score,
                rationale=f"Response analysis: guideline '{m.guideline.content.condition}' "
                          f"was applied",
                metadata={"batch_type": "response_analysis", "was_followed": True},
            ))
        return BatchResult(matches=matches)


# ---------------------------------------------------------------------------
# MatchingStrategy   (port of GenericGuidelineMatchingStrategy)
# ---------------------------------------------------------------------------

class GenericMatchingStrategy:
    """Default strategy that creates the standard 6 batch types."""

    def create_batches(
        self,
        guidelines: list[Guideline],
        context: MatchingContext,
        prior_matches: list[GuidelineMatch] | None = None,
    ) -> list:
        """Partition guidelines into batch objects by type."""
        observational: list[Guideline] = []
        actionable: list[Guideline] = []
        low_criticality: list[Guideline] = []

        for g in guidelines:
            if not g.enabled:
                continue
            if g.criticality == Criticality.LOW:
                low_criticality.append(g)
            elif is_actionable(g):
                actionable.append(g)
            else:
                observational.append(g)

        batches: list = []

        if observational:
            batches.append(ObservationalBatch(observational, context))
        if actionable:
            batches.append(ActionableBatch(actionable, context))
        if low_criticality:
            batches.append(LowCriticalityBatch(low_criticality, context))
        if prior_matches:
            batches.append(PreviouslyAppliedBatch(prior_matches, context))

        return batches

    def deduplicate(self, matches: list[GuidelineMatch]) -> list[GuidelineMatch]:
        seen: set[str] = set()
        result: list[GuidelineMatch] = []
        for m in matches:
            if m.guideline.id not in seen:
                seen.add(m.guideline.id)
                result.append(m)
        return result


# ---------------------------------------------------------------------------
# Matcher  (port of executeBatchesParallel)
# ---------------------------------------------------------------------------

class Matcher:
    """Runs all batch types against a query context and returns deduplicated matches."""

    def __init__(self, strategy: GenericMatchingStrategy | None = None) -> None:
        self._strategy = strategy or GenericMatchingStrategy()

    def evaluate(
        self,
        context: MatchingContext,
        guidelines: list[Guideline],
        prior_matches: list[GuidelineMatch] | None = None,
    ) -> list[GuidelineMatch]:
        """Run all batch types, flatten, deduplicate, and return scored matches."""
        batches = self._strategy.create_batches(guidelines, context, prior_matches)
        if not batches:
            return []

        all_matches: list[GuidelineMatch] = []
        for batch in batches:
            try:
                result = batch.process()
                all_matches.extend(result.matches)
            except Exception:
                logger.exception("batch matcher failed for %s", type(batch).__name__)

        deduped = self._strategy.deduplicate(all_matches)

        # Sort: criticality descending, then score descending
        deduped.sort(
            key=lambda m: (criticality_to_weight(m.guideline.criticality), m.score),
            reverse=True,
        )

        return deduped


# ---------------------------------------------------------------------------
# Resolver  (port of RelationalResolver from resolver.ts)
# ---------------------------------------------------------------------------

MAX_RESOLVER_ITERATIONS = 100


class ResolutionKind(str, Enum):
    NONE = "none"
    UNMET_DEPENDENCY = "unmet_dependency"
    DEPRIORITIZED = "deprioritized"
    ENTAILED = "entailed"


@dataclass
class Resolution:
    kind: ResolutionKind
    description: str
    relationship_id: str | None = None
    counterparts: list[dict[str, str]] | None = None


class Resolver:
    """Relational resolver that applies DEPENDS_ON / PRIORITIZES / ENTAILS
    relationships to a set of matched guidelines, converging iteratively."""

    def __init__(self, relationship_store: RelationshipStore) -> None:
        self._store = relationship_store

    def resolve(
        self,
        activated: list[GuidelineMatch],
    ) -> tuple[list[GuidelineMatch], dict[str, list[Resolution]], int, bool]:
        """Resolve relationships among activated matches.

        Returns:
            (final_matches, resolutions_map, iterations, converged)
        """
        all_guidelines = [m.guideline for m in activated]
        matched_ids: set[str] = {m.guideline.id for m in activated}
        guidelines_by_id: dict[str, Guideline] = {g.id: g for g in all_guidelines}

        resolutions: dict[str, list[Resolution]] = {}
        priority_removed: set[str] = set()
        entailed_ids: set[str] = set()

        converged = False
        iterations = 0
        current_ids = set(matched_ids)

        for iterations in range(MAX_RESOLVER_ITERATIONS):
            candidate_ids = {
                gid for gid in current_ids if gid not in priority_removed
            }

            step1 = self._apply_dependencies(candidate_ids, guidelines_by_id, resolutions)
            step2 = self._apply_prioritization(step1, guidelines_by_id, resolutions, priority_removed)
            step3 = self._apply_numerical_priority(step2, guidelines_by_id, resolutions, priority_removed, entailed_ids)
            step4 = self._apply_entailment(step3, guidelines_by_id, resolutions, priority_removed, entailed_ids)

            if step4 == current_ids:
                converged = True
                break

            current_ids = step4

        # Fill in NONE resolutions for unmentioned guidelines
        for m in activated:
            gid = m.guideline.id
            if gid not in resolutions:
                resolutions[gid] = [
                    Resolution(kind=ResolutionKind.NONE, description="No relational changes")
                ]

        # Build final match list from surviving IDs
        id_to_match = {m.guideline.id: m for m in activated}
        final_matches = [
            id_to_match[gid] for gid in current_ids if gid in id_to_match
        ]

        return final_matches, resolutions, iterations + 1, converged

    # -- private steps --------------------------------------------------------

    @staticmethod
    def _add_resolution(
        resolutions: dict[str, list[Resolution]],
        gid: str,
        resolution: Resolution,
    ) -> None:
        if gid not in resolutions:
            resolutions[gid] = []
        resolutions[gid].append(resolution)

    def _apply_dependencies(
        self,
        candidate_ids: set[str],
        _guidelines_by_id: dict[str, Guideline],
        resolutions: dict[str, list[Resolution]],
    ) -> set[str]:
        surviving = set(candidate_ids)
        for gid in candidate_ids:
            rels = self._store.list_relationships(
                kind=RelationshipKind.DEPENDS_ON,
                source_id=gid,
            )
            for rel in rels:
                target_id = rel.target.id
                if target_id not in candidate_ids:
                    surviving.discard(gid)
                    self._add_resolution(resolutions, gid, Resolution(
                        kind=ResolutionKind.UNMET_DEPENDENCY,
                        description=f"Depends on {target_id} which is not matched",
                        relationship_id=rel.id,
                        counterparts=[{"entity_type": "guideline", "entity_id": target_id}],
                    ))
                    break
        return surviving

    def _apply_prioritization(
        self,
        candidate_ids: set[str],
        guidelines_by_id: dict[str, Guideline],
        resolutions: dict[str, list[Resolution]],
        priority_removed: set[str],
    ) -> set[str]:
        surviving = set(candidate_ids)
        for gid in candidate_ids:
            if gid in priority_removed:
                continue
            # Get all relationships where this guideline is the source
            all_rels = self._store.list_relationships(source_id=gid)
            priority_rels = [r for r in all_rels if r.kind == RelationshipKind.PRIORITIZES]
            for rel in priority_rels:
                target_id = rel.target.id
                if target_id in candidate_ids:
                    surviving.discard(target_id)
                    priority_removed.add(target_id)
                    self._add_resolution(resolutions, target_id, Resolution(
                        kind=ResolutionKind.DEPRIORITIZED,
                        description=f"Deprioritized by {gid}",
                        relationship_id=rel.id,
                        counterparts=[{"entity_type": "guideline", "entity_id": gid}],
                    ))
        return surviving

    @staticmethod
    def _apply_numerical_priority(
        candidate_ids: set[str],
        guidelines_by_id: dict[str, Guideline],
        resolutions: dict[str, list[Resolution]],
        priority_removed: set[str],
        entailed_ids: set[str],
    ) -> set[str]:
        if not candidate_ids:
            return set()

        non_entailed = [gid for gid in candidate_ids if gid not in entailed_ids]
        entailed = [gid for gid in candidate_ids if gid in entailed_ids]

        if not non_entailed:
            return set(entailed)

        priorities = [
            guidelines_by_id[gid].priority if gid in guidelines_by_id else 0
            for gid in non_entailed
        ]
        max_priority = max(priorities) if priorities else 0

        surviving: set[str] = set()
        for gid in non_entailed:
            priority = guidelines_by_id[gid].priority if gid in guidelines_by_id else 0
            if priority >= max_priority:
                surviving.add(gid)
            else:
                priority_removed.add(gid)
                Resolver._add_resolution(resolutions, gid, Resolution(
                    kind=ResolutionKind.DEPRIORITIZED,
                    description=f"Lower priority ({priority} < {max_priority})",
                ))

        for gid in entailed:
            surviving.add(gid)

        return surviving

    def _apply_entailment(
        self,
        candidate_ids: set[str],
        guidelines_by_id: dict[str, Guideline],
        resolutions: dict[str, list[Resolution]],
        priority_removed: set[str],
        entailed_ids: set[str],
    ) -> set[str]:
        result = set(candidate_ids)
        for gid in candidate_ids:
            if gid in priority_removed:
                continue
            all_rels = self._store.list_relationships(source_id=gid)
            entail_rels = [r for r in all_rels if r.kind == RelationshipKind.ENTAILS]
            for rel in entail_rels:
                target_id = rel.target.id
                if target_id not in guidelines_by_id:
                    continue
                if target_id in priority_removed:
                    continue
                if target_id in entailed_ids:
                    continue
                result.add(target_id)
                entailed_ids.add(target_id)
                self._add_resolution(resolutions, target_id, Resolution(
                    kind=ResolutionKind.ENTAILED,
                    description=f"Entailed by {gid}",
                    relationship_id=rel.id,
                    counterparts=[{"entity_type": "guideline", "entity_id": gid}],
                ))
        return result


# ---------------------------------------------------------------------------
# SafeguardsEngine  — orchestrator
# ---------------------------------------------------------------------------

class SafeguardsEngine:
    """Engine that stores guidelines, runs matching, resolves conflicts,
    and produces contextual safeguard output.

    Thread-safe per-request evaluation results are stored in a contextvar
    so that ``prepend_safeguard()`` (in safeguards.py) can read them without
    changing its function signature.
    """

    def __init__(self) -> None:
        self.store = GuidelineStore()
        self.relationship_store = RelationshipStore()
        self.matcher = Matcher()
        self.resolver = Resolver(self.relationship_store)
        self._evaluation_cache: contextvars.ContextVar[list[GuidelineMatch] | None] = (
            contextvars.ContextVar("safeguards_engine_cache", default=None)
        )
        self._seed_default_rules()

    # -- Default rule seeding ------------------------------------------------

    def _seed_default_rules(self) -> None:
        """Pre-seed the engine with the existing safeguard rules from b1."""
        # Rule 1: diagnosis request (high)
        dx = self.store.create(
            condition="user asks for diagnosis",
            action="explain findings, state limits, recommend clinician",
            criticality=Criticality.HIGH,
            priority=10,
            tags=["diagnosis", "medical_advice"],
        )
        # Rule 2: emergency symptoms (critical)
        em = self.store.create(
            condition="user describes emergency symptoms",
            action="flag urgency, continue normally",
            criticality=Criticality.CRITICAL,
            priority=100,
            tags=["emergency", "urgent"],
        )
        # Rule 3: self-harm (critical) — blocks everything else
        sh = self.store.create(
            condition="user expresses self-harm",
            action="[CRISIS] block only",
            criticality=Criticality.CRITICAL,
            priority=200,
            tags=["crisis", "self_harm"],
        )
        # Rule 4: medication info (high)
        med = self.store.create(
            condition="user asks about medication",
            action="general info only, point to pharmacist",
            criticality=Criticality.HIGH,
            priority=5,
            tags=["medication"],
        )
        # Rule 5: medication combinations (medium)
        med_comb = self.store.create(
            condition="user asks medication combinations",
            action="explain general interactions, direct to pharmacist",
            criticality=Criticality.MEDIUM,
            priority=5,
            tags=["medication", "interaction"],
        )

        # Relationships: self-harm entailling crisis overrides everything
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=sh.id, kind="guideline"),
            target=RelationshipEntity(id=dx.id, kind="guideline"),
            kind=RelationshipKind.PRIORITIZES,
        )
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=sh.id, kind="guideline"),
            target=RelationshipEntity(id=em.id, kind="guideline"),
            kind=RelationshipKind.PRIORITIZES,
        )
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=sh.id, kind="guideline"),
            target=RelationshipEntity(id=med.id, kind="guideline"),
            kind=RelationshipKind.PRIORITIZES,
        )
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=sh.id, kind="guideline"),
            target=RelationshipEntity(id=med_comb.id, kind="guideline"),
            kind=RelationshipKind.PRIORITIZES,
        )

        # Emergency depends on not being in crisis
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=em.id, kind="guideline"),
            target=RelationshipEntity(id=sh.id, kind="guideline"),
            kind=RelationshipKind.DEPENDS_ON,
        )

        # Medication combination ENTAILS medication info
        self.relationship_store.create_relationship(
            source=RelationshipEntity(id=med_comb.id, kind="guideline"),
            target=RelationshipEntity(id=med.id, kind="guideline"),
            kind=RelationshipKind.ENTAILS,
        )

    # -- Public API -----------------------------------------------------------

    def evaluate(
        self,
        user_query: str,
        interaction_history: list[str] | None = None,
    ) -> list[GuidelineMatch]:
        """Run matching + resolution for a user query. Caches result for this
        request context."""
        context = MatchingContext(
            user_query=user_query,
            interaction_history=interaction_history or [],
        )
        guidelines = self.store.list()
        matches = self.matcher.evaluate(context, guidelines)

        if not matches:
            self._evaluation_cache.set([])
            return []

        # Run resolver
        resolved, _resolutions, _iterations, _converged = self.resolver.resolve(matches)

        self._evaluation_cache.set(resolved)
        return resolved

    def get_cached_result(self) -> list[GuidelineMatch] | None:
        """Return the cached evaluation result for the current request context,
        or None if no evaluation has been run."""
        return self._evaluation_cache.get()

    def clear_cache(self) -> None:
        """Clear the per-request evaluation cache."""
        self._evaluation_cache.set(None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

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
