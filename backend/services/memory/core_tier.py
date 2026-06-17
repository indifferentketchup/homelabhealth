"""Core tier  -  SQLite-backed long-term memory store with FTS5 and vector search.

Uses WAL journal mode for concurrent reads, FTS5 virtual tables for full-text
search, and BLOB storage for float32 embeddings. Thread-safe with RLock on writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.memory.hybrid_search import HybridSearchEngine
from services.memory.schemas import MemoryChunk, SearchResult

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None

_HAS_UPSERT = sqlite3.sqlite_version_info >= (3, 24, 0)
logger = logging.getLogger(__name__)


class MemoryStore:
    """SQLite-backed store for memory chunks with FTS5 and vector search support.

    Thread safety: uses ``threading.RLock()`` for all write operations.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.fts5_available = False
        self.trigram_fts5_available = False
        self._lock = threading.RLock()
        self._init_db()

    # ------------------------------------------------------------------ #
    # Initialization
    # ------------------------------------------------------------------ #

    def _check_fts5(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_test USING fts5(t)")
            self.conn.execute("DROP TABLE IF EXISTS _fts_test")
            return True
        except sqlite3.OperationalError:
            return False

    def _init_db(self):
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

        # Integrity check
        try:
            result = self.conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                self._recover_db()
        except sqlite3.DatabaseError:
            self._recover_db()

        self.fts5_available = self._check_fts5()
        self._init_schema()

    def _recover_db(self):
        logger.warning("MemoryStore: DB corrupt, recreating...")
        self.conn.close()
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            p.unlink(missing_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def _init_schema(self):
        c = self.conn
        c.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                scope TEXT NOT NULL DEFAULT 'shared',
                source TEXT NOT NULL DEFAULT 'memory',
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB,
                hash TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                updated_at INTEGER DEFAULT (strftime('%s','now'))
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_scope ON chunks(scope)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path, hash)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS _meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )

        if self.fts5_available:
            try:
                self._create_fts5_objects()
            except Exception as e:
                logger.warning("MemoryStore: FTS5 creation failed: %s", e)
            try:
                self._create_trigram_fts5()
            except Exception as e:
                logger.warning("MemoryStore: trigram FTS5 creation failed: %s", e)
        c.commit()

    def _create_fts5_objects(self):
        c = self.conn
        c.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text,
                id UNINDEXED,
                user_id UNINDEXED,
                path UNINDEXED,
                source UNINDEXED,
                scope UNINDEXED,
                content='chunks',
                content_rowid='rowid'
            )"""
        )
        for suffix in ("ai", "ad", "au"):
            c.execute(f"DROP TRIGGER IF EXISTS chunks_{suffix}")
        c.execute(
            """CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid,text,id,user_id,path,source,scope)
                VALUES(new.rowid,new.text,new.id,new.user_id,new.path,new.source,new.scope);
            END"""
        )
        c.execute(
            """CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts WHERE rowid=old.rowid;
            END"""
        )
        c.execute(
            """CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                UPDATE chunks_fts SET text=new.text, id=new.id, user_id=new.user_id,
                path=new.path, source=new.source, scope=new.scope WHERE rowid=new.rowid;
            END"""
        )

    def _create_trigram_fts5(self):
        c = self.conn
        c.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(
                text,
                id UNINDEXED,
                user_id UNINDEXED,
                path UNINDEXED,
                source UNINDEXED,
                scope UNINDEXED,
                content='chunks',
                content_rowid='rowid',
                tokenize='trigram case_sensitive 0'
            )"""
        )
        for suffix in ("ai", "ad", "au"):
            c.execute(f"DROP TRIGGER IF EXISTS chunks_trigram_{suffix}")
        c.execute(
            f"""CREATE TRIGGER IF NOT EXISTS chunks_trigram_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts_trigram(rowid,text,id,user_id,path,source,scope)
                VALUES(new.rowid,new.text,new.id,new.user_id,new.path,new.source,new.scope);
            END"""
        )
        c.execute(
            f"""CREATE TRIGGER IF NOT EXISTS chunks_trigram_ad AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts_trigram WHERE rowid=old.rowid;
            END"""
        )
        c.execute(
            f"""CREATE TRIGGER IF NOT EXISTS chunks_trigram_au AFTER UPDATE ON chunks BEGIN
                UPDATE chunks_fts_trigram SET text=new.text, id=new.id, user_id=new.user_id,
                path=new.path, source=new.source, scope=new.scope WHERE rowid=new.rowid;
            END"""
        )
        # Backfill trigram index for existing chunks
        backfill = c.execute(
            "SELECT 1 FROM _meta WHERE key='trigram_backfill_done'"
        ).fetchone()
        count = c.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
        if count > 0 and not backfill:
            c.execute(
                "INSERT INTO chunks_fts_trigram(chunks_fts_trigram) VALUES('rebuild')"
            )
            c.execute(
                "INSERT OR REPLACE INTO _meta(key,value) VALUES('trigram_backfill_done','1')"
            )
        self.trigram_fts5_available = True

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def save_chunk(self, chunk: MemoryChunk):
        emb = self._encode_embedding(chunk.embedding)
        meta = json.dumps(chunk.metadata) if chunk.metadata else None
        if _HAS_UPSERT:
            sql = (
                "INSERT INTO chunks(id,user_id,scope,source,path,start_line,end_line,"
                "text,embedding,hash,metadata,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now')) "
                "ON CONFLICT(id) DO UPDATE SET "
                "user_id=excluded.user_id, scope=excluded.scope, source=excluded.source, "
                "path=excluded.path, start_line=excluded.start_line, end_line=excluded.end_line, "
                "text=excluded.text, embedding=excluded.embedding, hash=excluded.hash, "
                "metadata=excluded.metadata, updated_at=strftime('%s','now')"
            )
        else:
            sql = (
                "INSERT OR REPLACE INTO chunks(id,user_id,scope,source,path,start_line,end_line,"
                "text,embedding,hash,metadata,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))"
            )
        with self._lock:
            self.conn.execute(
                sql,
                (
                    chunk.id,
                    chunk.user_id,
                    chunk.scope,
                    chunk.source,
                    chunk.path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.text,
                    emb,
                    chunk.hash,
                    meta,
                ),
            )
            self.conn.commit()

    def save_chunks_batch(self, chunks: List[MemoryChunk]):
        if not chunks:
            return
        if _HAS_UPSERT:
            sql = (
                "INSERT INTO chunks(id,user_id,scope,source,path,start_line,end_line,"
                "text,embedding,hash,metadata,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now')) "
                "ON CONFLICT(id) DO UPDATE SET "
                "user_id=excluded.user_id, scope=excluded.scope, source=excluded.source, "
                "path=excluded.path, start_line=excluded.start_line, end_line=excluded.end_line, "
                "text=excluded.text, embedding=excluded.embedding, hash=excluded.hash, "
                "metadata=excluded.metadata, updated_at=strftime('%s','now')"
            )
        else:
            sql = (
                "INSERT OR REPLACE INTO chunks(id,user_id,scope,source,path,start_line,end_line,"
                "text,embedding,hash,metadata,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))"
            )
        params = [
            (
                c.id,
                c.user_id,
                c.scope,
                c.source,
                c.path,
                c.start_line,
                c.end_line,
                c.text,
                self._encode_embedding(c.embedding),
                c.hash,
                json.dumps(c.metadata) if c.metadata else None,
            )
            for c in chunks
        ]
        with self._lock:
            self.conn.executemany(sql, params)
            self.conn.commit()

    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE id=?", (chunk_id,)
        ).fetchone()
        return self._row_to_chunk(row) if row else None

    def delete_chunk(self, chunk_id: str):
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE id=?", (chunk_id,))
            self.conn.commit()

    def delete_by_path(self, path: str):
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE path=?", (path,))
            self.conn.commit()

    def get_stats(self) -> Dict[str, int]:
        chunks = self.conn.execute(
            "SELECT COUNT(*) as c FROM chunks"
        ).fetchone()["c"]
        embedded = self.conn.execute(
            "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()["c"]
        return {"chunks": chunks, "embedded": embedded}

    def close(self):
        if self.conn:
            try:
                self.conn.commit()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------ #
    # Embedding serialization
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode_embedding(embedding: Optional[List[float]]) -> Optional[bytes]:
        if embedding is None:
            return None
        if _HAS_NUMPY:
            return np.array(embedding, dtype=np.float32).tobytes()
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def _decode_embedding(raw) -> Optional[List[float]]:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            if _HAS_NUMPY:
                return np.frombuffer(raw, dtype=np.float32).tolist()
            n = len(raw) // 4
            return list(struct.unpack(f"{n}f", raw))
        if isinstance(raw, str):
            return json.loads(raw)
        return None

    def _row_to_chunk(self, row) -> MemoryChunk:
        return MemoryChunk(
            id=row["id"],
            user_id=row["user_id"],
            scope=row["scope"],
            source=row["source"],
            path=row["path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            text=row["text"],
            embedding=self._decode_embedding(row["embedding"]),
            hash=row["hash"],
            metadata=json.loads(row["metadata"]) if row.get("metadata") else None,
        )

    @staticmethod
    def compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class CoreTier:
    """Long-term memory management via MemoryStore (SQLite + FTS5 + vectors).

    Wraps MemoryStore with higher-level operations: save facts, hybrid search,
    and embedding integration.
    """

    def __init__(self, store_path: Path):
        self.store = MemoryStore(store_path)
        self.search_engine = HybridSearchEngine(self.store)

    def search(
        self,
        query_embedding: Optional[List[float]] = None,
        query_text: str = "",
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        limit: int = 10,
        min_score: float = 0.1,
    ) -> List[SearchResult]:
        """Hybrid search across all stored chunks."""
        return self.search_engine.search(
            query_embedding=query_embedding,
            query_text=query_text,
            user_id=user_id,
            scopes=scopes,
            limit=limit,
            min_score=min_score,
        )

    def save_fact(
        self,
        content: str,
        user_id: Optional[str] = None,
        scope: str = "shared",
        source: str = "memory",
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> str:
        """Save a fact as a chunked, indexed memory entry.

        Args:
            content: The fact text.
            user_id: Optional user scope.
            scope: Visibility scope.
            source: Source identifier.
            metadata: Optional metadata dict.
            embedding: Pre-computed embedding vector (optional, computed later).

        Returns:
            The chunk ID.
        """
        chunk_id = hashlib.md5(content.encode("utf-8")).hexdigest()
        mc = MemoryChunk(
            id=chunk_id,
            user_id=user_id,
            scope=scope,
            source=source,
            path=f"memory/facts/{chunk_id}.md",
            start_line=0,
            end_line=0,
            text=content,
            embedding=embedding,
            hash=MemoryStore.compute_hash(content),
            metadata=metadata,
        )
        self.store.save_chunk(mc)
        return chunk_id

    def delete_fact(self, chunk_id: str):
        """Delete a fact by its chunk ID."""
        self.store.delete_chunk(chunk_id)

    def get_stats(self) -> Dict[str, int]:
        return self.store.get_stats()

    def close(self):
        self.store.close()

    def get_all_facts(
        self,
        user_id: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> List[MemoryChunk]:
        """Retrieve all facts, optionally filtered."""
        params: list = []
        conditions = []
        if user_id:
            conditions.append("(user_id=? OR scope='shared')")
            params.append(user_id)
        if scope:
            conditions.append("scope=?")
            params.append(scope)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM chunks WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.store.conn.execute(sql, params).fetchall()
        return [self.store._row_to_chunk(r) for r in rows]


__all__ = ["MemoryStore", "CoreTier"]
