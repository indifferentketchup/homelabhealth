"""Hybrid search engine — vector cosine similarity + FTS5 keyword with weighted merge.

Weighted score formula::

    final_score = (0.7 * vector_cosine + 0.3 * bm25_normalized) * temporal_decay

Temporal decay::

    decay = 2^(-days_ago / half_life)

BM25 normalization::

    bm25_norm = 0.3 + 0.69 * (rank / (1 + rank))
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Callable, List, Optional, TYPE_CHECKING

from services.memory.schemas import SearchResult

if TYPE_CHECKING:
    from services.memory.core_tier import MemoryStore

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None

# CJK character ranges for trigram tokenization
_CJK_RANGE = re.compile(
    r"[\u3000-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff\U00020000-\U0002fa1f]"
)
_CJK_WORDS = re.compile(
    r"[\u3000-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff\U00020000-\U0002fa1f]+"
)
_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_DEFAULT_VECTOR_WEIGHT = 0.7
_DEFAULT_KEYWORD_WEIGHT = 0.3
_DEFAULT_HALF_LIFE_DAYS = 30.0
_DEFAULT_MAX_RESULTS = 10
_DEFAULT_MIN_SCORE = 0.1


class HybridSearchEngine:
    """Combines vector similarity and FTS5 keyword search with weighted fusion."""

    def __init__(
        self,
        store: "MemoryStore",
        vector_weight: float = _DEFAULT_VECTOR_WEIGHT,
        keyword_weight: float = _DEFAULT_KEYWORD_WEIGHT,
        half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
        max_results: int = _DEFAULT_MAX_RESULTS,
        min_score: float = _DEFAULT_MIN_SCORE,
    ):
        self.store = store
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.half_life_days = half_life_days
        self.max_results = max_results
        self.min_score = min_score

    # ------------------------------------------------------------------ #
    # Vector search (cosine similarity)
    # ------------------------------------------------------------------ #

    def search_vector(
        self,
        query_embedding: List[float],
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")

        scope_ph = ",".join("?" * len(scopes))
        params: list = list(scopes)
        if user_id:
            sql = (
                f"SELECT * FROM chunks WHERE scope IN ({scope_ph}) "
                "AND (scope='shared' OR user_id=?) AND embedding IS NOT NULL"
            )
            params.append(user_id)
        else:
            sql = (
                f"SELECT * FROM chunks WHERE scope IN ({scope_ph}) "
                "AND embedding IS NOT NULL"
            )

        rows = self.store.conn.execute(sql, params).fetchall()
        if not rows:
            return []

        expected_dim = len(query_embedding)
        valid_rows = []
        vectors = []
        for row in rows:
            vec = self.store._decode_embedding(row["embedding"])
            if not vec or len(vec) != expected_dim:
                continue
            valid_rows.append(row)
            vectors.append(vec)

        if not vectors:
            return []

        if _HAS_NUMPY:
            return self._vector_search_numpy(vectors, valid_rows, query_embedding, limit)
        else:
            return self._vector_search_pure(vectors, valid_rows, query_embedding, limit)

    def _vector_search_numpy(
        self,
        vectors: list,
        rows: list,
        query_embedding: List[float],
        limit: int,
    ) -> List[SearchResult]:
        matrix = np.array(vectors, dtype=np.float32)
        q_vec = np.array(query_embedding, dtype=np.float32)
        dots = matrix @ q_vec
        row_norms = np.linalg.norm(matrix, axis=1)
        q_norm = float(np.linalg.norm(q_vec))
        denoms = np.maximum(row_norms * q_norm, 1e-10)
        sims = dots / denoms
        k = min(limit, len(rows))
        top_idx = np.argpartition(sims, -k)[-k:]
        top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]
        return [
            SearchResult(
                path=rows[i]["path"],
                start_line=rows[i]["start_line"],
                end_line=rows[i]["end_line"],
                score=float(sims[i]),
                snippet=rows[i]["text"][:500],
                source=rows[i]["source"],
                user_id=rows[i]["user_id"],
            )
            for i in top_idx
            if sims[i] > 0
        ]

    def _vector_search_pure(
        self,
        vectors: list,
        rows: list,
        query_embedding: List[float],
        limit: int,
    ) -> List[SearchResult]:
        q = query_embedding
        qn = math.sqrt(sum(x * x for x in q)) or 1e-10
        scored = []
        for i, vec in enumerate(vectors):
            dot = sum(a * b for a, b in zip(vec, q))
            vn = math.sqrt(sum(x * x for x in vec)) or 1e-10
            sim = dot / (vn * qn)
            if sim > 0:
                scored.append((sim, rows[i]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(
                path=r["path"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                score=s,
                snippet=r["text"][:500],
                source=r["source"],
                user_id=r["user_id"],
            )
            for s, r in scored[:limit]
        ]

    # ------------------------------------------------------------------ #
    # Keyword search — three-tier fallback (FTS5 -> trigram -> LIKE)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_fts_query(raw: str) -> Optional[str]:
        tokens = re.findall(r"[A-Za-z0-9_]+", raw)
        if not tokens:
            return None
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _build_trigram_query(raw: str) -> Optional[str]:
        tokens = re.findall(
            r"[\u3000-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff"
            r"\U00020000-\U0002fa1f]+|[A-Za-z0-9_]+",
            raw,
        )
        tokens = [t for t in tokens if t]
        if not tokens:
            return None
        return " AND ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens)

    def _search_fts5(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int,
    ) -> List[SearchResult]:
        fts_q = self._build_fts_query(query)
        if not fts_q:
            return []
        scope_ph = ",".join("?" * len(scopes))
        params = [fts_q] + scopes
        if user_id:
            sql = (
                "SELECT chunks.*, bm25(chunks_fts) as rank FROM chunks_fts "
                "JOIN chunks ON chunks.rowid = chunks_fts.rowid "
                f"WHERE chunks_fts MATCH ? AND chunks.scope IN ({scope_ph}) "
                "AND (chunks.scope='shared' OR chunks.user_id=?) ORDER BY rank LIMIT ?"
            )
            params += [user_id, limit]
        else:
            sql = (
                "SELECT chunks.*, bm25(chunks_fts) as rank FROM chunks_fts "
                "JOIN chunks ON chunks.rowid = chunks_fts.rowid "
                f"WHERE chunks_fts MATCH ? AND chunks.scope IN ({scope_ph}) "
                "ORDER BY rank LIMIT ?"
            )
            params.append(limit)
        try:
            rows = self.store.conn.execute(sql, params).fetchall()
            return [
                SearchResult(
                    path=r["path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    score=self._bm25_score(r["rank"]),
                    snippet=r["text"][:500],
                    source=r["source"],
                    user_id=r["user_id"],
                )
                for r in rows
            ]
        except Exception:
            return []

    def _search_trigram(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int,
    ) -> List[SearchResult]:
        tq = self._build_trigram_query(query)
        if not tq:
            return []
        scope_ph = ",".join("?" * len(scopes))
        params = [tq] + scopes
        if user_id:
            sql = (
                "SELECT chunks.*, bm25(chunks_fts_trigram) as rank FROM chunks_fts_trigram "
                "JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid "
                f"WHERE chunks_fts_trigram MATCH ? AND chunks.scope IN ({scope_ph}) "
                "AND (chunks.scope='shared' OR chunks.user_id=?) ORDER BY rank LIMIT ?"
            )
            params += [user_id, limit]
        else:
            sql = (
                "SELECT chunks.*, bm25(chunks_fts_trigram) as rank FROM chunks_fts_trigram "
                "JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid "
                f"WHERE chunks_fts_trigram MATCH ? AND chunks.scope IN ({scope_ph}) "
                "ORDER BY rank LIMIT ?"
            )
            params.append(limit)
        try:
            rows = self.store.conn.execute(sql, params).fetchall()
            return [
                SearchResult(
                    path=r["path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    score=self._bm25_score(r["rank"]),
                    snippet=r["text"][:500],
                    source=r["source"],
                    user_id=r["user_id"],
                )
                for r in rows
            ]
        except Exception:
            return []

    def _search_like(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int,
    ) -> List[SearchResult]:
        cjk_words = _CJK_WORDS.findall(query)
        ascii_words = [t for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) >= 3]
        words = cjk_words + ascii_words
        if not words:
            return []
        scope_ph = ",".join("?" * len(scopes))
        conditions = " OR ".join(["LOWER(text) LIKE ?"] * len(words))
        params = [f"%{w.lower()}%" for w in words] + scopes
        if user_id:
            sql = (
                f"SELECT * FROM chunks WHERE ({conditions}) AND scope IN ({scope_ph}) "
                "AND (scope='shared' OR user_id=?) LIMIT ?"
            )
            params += [user_id, limit]
        else:
            sql = (
                f"SELECT * FROM chunks WHERE ({conditions}) AND scope IN ({scope_ph}) LIMIT ?"
            )
            params.append(limit)
        try:
            rows = self.store.conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                text_lower = r["text"].lower()
                matched = sum(1 for w in words if w.lower() in text_lower)
                if matched == 0:
                    continue
                score = min(0.85, 0.3 + 0.15 * matched)
                results.append(
                    SearchResult(
                        path=r["path"],
                        start_line=r["start_line"],
                        end_line=r["end_line"],
                        score=score,
                        snippet=r["text"][:500],
                        source=r["source"],
                        user_id=r["user_id"],
                    )
                )
            results.sort(key=lambda x: x.score, reverse=True)
            return results
        except Exception:
            return []

    def search_keyword(
        self,
        query: str,
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """Full-text search with fallback chain: FTS5 -> trigram -> LIKE."""
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")

        has_cjk = bool(_CJK_RANGE.search(query))
        fts_avail = getattr(self.store, "fts5_available", False)
        trigram_avail = getattr(self.store, "trigram_fts5_available", False)

        # Tier 1: standard FTS5 for ASCII
        if fts_avail and not has_cjk:
            results = self._search_fts5(query, user_id, scopes, limit)
            if results:
                return results

        # Tier 2: trigram FTS5 for CJK
        if trigram_avail and has_cjk:
            results = self._search_trigram(query, user_id, scopes, limit)
            if results:
                return results

        # Tier 3: LIKE fallback
        return self._search_like(query, user_id, scopes, limit)

    # ------------------------------------------------------------------ #
    # Temporal decay
    # ------------------------------------------------------------------ #

    def _compute_temporal_decay(
        self,
        path: str,
        half_life_days: Optional[float] = None,
    ) -> float:
        hl = half_life_days or self.half_life_days
        m = _DATE_PATTERN.search(path)
        if not m:
            return 1.0  # no date in path -> evergreen
        try:
            file_date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            age = (datetime.now() - file_date).days
            if age <= 0:
                return 1.0
            return math.exp(-math.log(2) / hl * age)
        except (ValueError, OverflowError):
            return 1.0

    # ------------------------------------------------------------------ #
    # Merged hybrid search
    # ------------------------------------------------------------------ #

    def search(
        self,
        query_embedding: Optional[List[float]] = None,
        query_text: str = "",
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        limit: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> List[SearchResult]:
        """Run vector + keyword search and merge results with temporal decay.

        Args:
            query_embedding: Optional vector for cosine similarity search.
            query_text: Text query for FTS5/keyword search.
            user_id: Optional user scope filter.
            scopes: Scope list filter (defaults to ``["shared"]``).
            limit: Maximum results.
            min_score: Minimum combined score threshold.

        Returns:
            Ranked list of SearchResult with fused scores.
        """
        lim = limit or self.max_results
        ms = min_score if min_score is not None else self.min_score

        vec_results = (
            self.search_vector(query_embedding, user_id, scopes, lim * 2)
            if query_embedding
            else []
        )
        kw_results = self.search_keyword(query_text, user_id, scopes, lim * 2)

        merged: dict = {}
        for r in vec_results:
            key = (r.path, r.start_line, r.end_line)
            merged[key] = {"result": r, "vec": r.score, "kw": 0.0}
        for r in kw_results:
            key = (r.path, r.start_line, r.end_line)
            if key in merged:
                merged[key]["kw"] = r.score
            else:
                merged[key] = {"result": r, "vec": 0.0, "kw": r.score}

        final = []
        for entry in merged.values():
            combined = (
                self.vector_weight * entry["vec"]
                + self.keyword_weight * entry["kw"]
            )
            decay = self._compute_temporal_decay(entry["result"].path)
            combined *= decay
            if combined >= ms:
                r = entry["result"]
                r.score = combined
                final.append(r)

        final.sort(key=lambda x: x.score, reverse=True)
        return final[:lim]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bm25_score(rank: float) -> float:
        """Normalize a BM25 rank to a [0.3, 1.0] score."""
        if rank is None:
            return 0.0
        return 0.3 + 0.69 * (abs(rank) / (1.0 + abs(rank)))


__all__ = ["HybridSearchEngine"]
