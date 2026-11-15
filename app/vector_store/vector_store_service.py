"""Local vector store.

Vectors live in their own SQLite file (``vectors.db``) beside the business
database, so the index is rebuildable, backup-friendly and never becomes the
source of truth for business data. Search is exact cosine similarity over the
filtered rows, which is fast at business-document scale and needs no server.

ChromaDB is not installed in this environment, so this is the "equivalent local
vector database" the design allows; the interface is the one the RAG pipeline
expects.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.core.logging_config import get_logger

logger = get_logger("vector_store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL,
    document_ref TEXT NOT NULL DEFAULT '',
    business_id INTEGER,
    category TEXT,
    document_version INTEGER NOT NULL DEFAULT 1,
    page_number INTEGER,
    section_heading TEXT,
    source_file TEXT,
    model_id TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    content_hash TEXT,
    content TEXT NOT NULL DEFAULT '',
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_vectors_business ON chunk_vectors(business_id);
CREATE INDEX IF NOT EXISTS ix_vectors_document ON chunk_vectors(document_id);
CREATE INDEX IF NOT EXISTS ix_vectors_category ON chunk_vectors(category);
CREATE INDEX IF NOT EXISTS ix_vectors_model ON chunk_vectors(model_id);
"""


class VectorStoreError(Exception):
    """Raised when the vector index cannot be used safely."""


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    document_id: int
    document_ref: str
    business_id: int | None
    category: str
    document_version: int
    page_number: int | None
    section_heading: str | None
    source_file: str
    model_id: str
    content: str
    content_hash: str
    vector: list[float]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    document_id: int
    document_ref: str
    business_id: int | None
    category: str
    document_version: int
    page_number: int | None
    section_heading: str | None
    source_file: str
    content: str
    score: float


class LocalVectorStore:
    """Exact-search vector index with metadata filtering."""

    def __init__(self, path: Path, *, dimension: int, model_id: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._dimension = dimension
        self._model_id = model_id
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # -- connection --------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    # -- writes ------------------------------------------------------------
    def add_embeddings(self, records: Iterable[VectorRecord]) -> int:
        added = 0
        with self._lock, self._connect() as conn:
            for record in records:
                if len(record.vector) != self._dimension:
                    raise VectorStoreError(
                        f"Vector for chunk {record.chunk_id} has {len(record.vector)} "
                        f"dimensions; the index expects {self._dimension}."
                    )
                conn.execute(
                    """
                    INSERT INTO chunk_vectors (
                        chunk_id, document_id, document_ref, business_id, category,
                        document_version, page_number, section_heading, source_file,
                        model_id, dimension, content_hash, content, vector
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        content=excluded.content,
                        vector=excluded.vector,
                        model_id=excluded.model_id,
                        dimension=excluded.dimension,
                        content_hash=excluded.content_hash,
                        page_number=excluded.page_number,
                        section_heading=excluded.section_heading
                    """,
                    (
                        record.chunk_id,
                        record.document_id,
                        record.document_ref,
                        record.business_id,
                        record.category,
                        record.document_version,
                        record.page_number,
                        record.section_heading,
                        record.source_file,
                        record.model_id,
                        len(record.vector),
                        record.content_hash,
                        record.content[:8000],
                        _pack(record.vector),
                    ),
                )
                added += 1
        return added

    def delete_document_vectors(self, document_id: int) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM chunk_vectors WHERE document_id = ?", (document_id,)
            )
            return cursor.rowcount

    def delete_chunk(self, chunk_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chunk_vectors WHERE chunk_id = ?", (chunk_id,))

    # -- reads -------------------------------------------------------------
    def count(self, *, business_id: int | None = None) -> int:
        with self._connect() as conn:
            if business_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM chunk_vectors").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM chunk_vectors WHERE business_id = ?",
                    (business_id,),
                ).fetchone()
        return int(row["n"]) if row else 0

    def models_present(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT model_id, COUNT(*) AS n FROM chunk_vectors GROUP BY model_id"
            ).fetchall()
        return {row["model_id"]: int(row["n"]) for row in rows}

    def search_similar_chunks(
        self,
        query_vector: list[float],
        *,
        top_k: int = 8,
        business_id: int | None = None,
        document_ids: list[int] | None = None,
        categories: list[str] | None = None,
        min_similarity: float = 0.05,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[VectorHit]:
        if len(query_vector) != self._dimension:
            raise VectorStoreError(
                f"The query vector has {len(query_vector)} dimensions but the index "
                f"was built with {self._dimension}."
            )
        clauses = ["model_id = ?"]
        params: list[Any] = [self._model_id]
        if business_id is not None:
            clauses.append("business_id = ?")
            params.append(business_id)
        if document_ids:
            clauses.append(f"document_id IN ({','.join('?' for _ in document_ids)})")
            params.extend(document_ids)
        if categories:
            clauses.append(f"category IN ({','.join('?' for _ in categories)})")
            params.extend(categories)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to)

        sql = "SELECT * FROM chunk_vectors WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        hits: list[VectorHit] = []
        for row in rows:
            vector = _unpack(row["vector"])
            if len(vector) != len(query_vector):
                continue
            dot = sum(a * b for a, b in zip(query_vector, vector))
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            score = dot / (query_norm * norm)
            if score < min_similarity:
                continue
            hits.append(
                VectorHit(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    document_ref=row["document_ref"],
                    business_id=row["business_id"],
                    category=row["category"],
                    document_version=row["document_version"],
                    page_number=row["page_number"],
                    section_heading=row["section_heading"],
                    source_file=row["source_file"],
                    content=row["content"],
                    score=round(float(score), 6),
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def search_by_document(self, document_id: int, *, limit: int = 50) -> list[VectorHit]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk_vectors WHERE document_id = ? "
                "ORDER BY page_number, chunk_id LIMIT ?",
                (document_id, limit),
            ).fetchall()
        return [self._hit(row, 0.0) for row in rows]

    def search_by_category(self, category: str, *, limit: int = 50) -> list[VectorHit]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk_vectors WHERE category = ? LIMIT ?",
                (category, limit),
            ).fetchall()
        return [self._hit(row, 0.0) for row in rows]

    def filter_by_business(self, business_id: int | None, *, limit: int = 200) -> list[VectorHit]:
        with self._connect() as conn:
            if business_id is None:
                rows = conn.execute(
                    "SELECT * FROM chunk_vectors WHERE business_id IS NULL LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chunk_vectors WHERE business_id = ? LIMIT ?",
                    (business_id, limit),
                ).fetchall()
        return [self._hit(row, 0.0) for row in rows]

    def validate_vector_index(self) -> dict[str, Any]:
        """Consistency report used by the UI and the re-index button."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM chunk_vectors").fetchone()["n"]
            by_model = {
                row["model_id"]: int(row["n"])
                for row in conn.execute(
                    "SELECT model_id, COUNT(*) AS n FROM chunk_vectors GROUP BY model_id"
                ).fetchall()
            }
            bad_dimensions = conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_vectors WHERE dimension != ?", (self._dimension,)
            ).fetchone()["n"]
            missing_docs = conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_vectors WHERE document_ref = ''"
            ).fetchone()["n"]
        problems: list[str] = []
        if bad_dimensions:
            problems.append(f"{bad_dimensions} vector(s) have the wrong dimension")
        if missing_docs:
            problems.append(f"{missing_docs} vector(s) have no document reference")
        if len(by_model) > 1:
            problems.append("the index mixes embeddings from more than one model")
        return {
            "total_vectors": int(total),
            "by_model": by_model,
            "expected_model": self._model_id,
            "dimension": self._dimension,
            "problems": problems,
            "healthy": not problems,
        }

    def _hit(self, row: sqlite3.Row, score: float) -> VectorHit:
        return VectorHit(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_ref=row["document_ref"],
            business_id=row["business_id"],
            category=row["category"],
            document_version=row["document_version"],
            page_number=row["page_number"],
            section_heading=row["section_heading"],
            source_file=row["source_file"],
            content=row["content"],
            score=score,
        )


def _pack(vector: list[float]) -> bytes:
    import struct

    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    import struct

    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))
