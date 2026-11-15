"""Embedding generation.

Two models are supported:

* ``lexical-hashing-v1`` — a deterministic hashed term-frequency vectoriser that
  ships with the application. It needs no download and always works offline, so
  semantic search is available on a machine with no model cache.
* ``sentence-transformers/all-MiniLM-L6-v2`` — a real neural embedding model,
  used automatically when the package and the model files are present.

Vectors from different models are never mixed: the index records which model
produced it and refuses cross-model search until a re-index is done.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.database.models.knowledge import EmbeddingModelRegistry
from app.utils.date_utils import utcnow

logger = get_logger("embeddings")

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenise(text: str) -> list[str]:
    """Split words and hyphenated compounds, and normalise simple plurals."""
    tokens: list[str] = []
    for raw in re.split(r"[^A-Za-z0-9]+", (text or "").lower()):
        if not raw:
            continue
        tokens.append(raw)
        if len(raw) > 3 and raw.endswith("s") and not raw.endswith("ss"):
            tokens.append(raw[:-1])
    return tokens


class EmbeddingError(BizPilotError):
    default_user_message = "Embeddings could not be generated."


class EmbeddingModel(Protocol):
    model_id: str
    dimension: int
    version: str

    @property
    def available(self) -> bool: ...

    def encode(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class LexicalHashingEmbedding:
    """Deterministic hashed TF vectoriser (always available, fully offline)."""

    model_id: str = "lexical-hashing-v1"
    dimension: int = 256
    version: str = "1.0"

    @property
    def available(self) -> bool:
        return True

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = tokenise(text)
        if not tokens:
            return vector
        counts = Counter(tokens)
        # Bigrams keep short business phrases together.
        bigrams = [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        counts.update(bigrams)
        for token, count in counts.items():
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector


class SentenceTransformerEmbedding:
    """Optional neural embeddings, used only when genuinely installed."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_id = model_name
        self.dimension = 384
        self.version = "1.0"
        self._model = None
        self._error: str | None = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_id.split("/")[-1])
        except Exception as exc:  # noqa: BLE001 - absence is expected offline
            self._error = f"{type(exc).__name__}: {exc}"
            self._model = None

    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._model is not None

    @property
    def unavailable_reason(self) -> str | None:
        self._ensure_loaded()
        return self._error

    def encode(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        if self._model is None:
            raise EmbeddingError(
                "The sentence-transformers model is not installed; no neural embeddings "
                "were produced."
            )
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


class EmbeddingService:
    """Resolves the configured embedding model and records it."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        model_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lexical = LexicalHashingEmbedding()
        self._neural = SentenceTransformerEmbedding()
        self._model = self._resolve(model_id)

    def _resolve(self, model_id: str | None) -> EmbeddingModel:
        if model_id and model_id.startswith("sentence-transformers"):
            if self._neural.available:
                return self._neural
            logger.warning(
                "Neural embedding model requested but unavailable (%s); using the "
                "lexical hashing model instead",
                self._neural.unavailable_reason,
            )
        return self._lexical

    # -- properties --------------------------------------------------------
    @property
    def model_id(self) -> str:
        return self._model.model_id

    @property
    def dimension(self) -> int:
        return self._model.dimension

    @property
    def version(self) -> str:
        return self._model.version

    def model_info(self) -> dict:
        is_neural = self._model is self._neural
        return {
            "model_id": self.model_id,
            "dimension": self.dimension,
            "version": self.version,
            "kind": "NEURAL" if is_neural else "LEXICAL_HASHING",
            "neural_available": self._neural.available if is_neural else False,
            "neural_unavailable_reason": self._neural.unavailable_reason if is_neural else None,
        }

    def available_models(self) -> list[dict]:
        return [
            {
                "model_id": self._lexical.model_id,
                "dimension": self._lexical.dimension,
                "available": True,
                "kind": "LEXICAL_HASHING",
                "note": "Deterministic hashed term-frequency vectors; always available offline.",
            },
            {
                "model_id": self._neural.model_id,
                "dimension": self._neural.dimension,
                "available": self._neural.available,
                "kind": "NEURAL",
                "note": self._neural.unavailable_reason
                or "Neural sentence embeddings (384 dimensions).",
            },
        ]

    # -- generation --------------------------------------------------------
    def embed_texts(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            encoded = self._model.encode(batch)
            for vector in encoded:
                if len(vector) != self.dimension:
                    raise EmbeddingError(
                        f"The embedding model returned {len(vector)} dimensions but "
                        f"{self.dimension} were expected."
                    )
                vectors.append(vector)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        vectors = self.embed_texts([query])
        if not vectors:
            raise EmbeddingError("An empty query cannot be embedded")
        return vectors[0]

    # -- registry ----------------------------------------------------------
    def ensure_registered(self, *, make_active: bool = True) -> None:
        with self._session_factory() as db:
            row = db.scalars(
                select(EmbeddingModelRegistry).where(
                    EmbeddingModelRegistry.model_id == self.model_id
                )
            ).first()
            if row is None:
                row = EmbeddingModelRegistry(
                    model_id=self.model_id,
                    provider="local",
                    dimension=self.dimension,
                    version=self.version,
                    is_active=False,
                    notes=(
                        "Deterministic lexical hashing embeddings"
                        if self._model is self._lexical
                        else "Sentence-transformers neural embeddings"
                    ),
                )
                db.add(row)
            row.dimension = self.dimension
            row.version = self.version
            if make_active:
                for other in db.scalars(select(EmbeddingModelRegistry)).all():
                    other.is_active = other.model_id == self.model_id
            row.registered_at = utcnow()
            db.commit()

    def active_model_record(self) -> dict | None:
        with self._session_factory() as db:
            row = db.scalars(
                select(EmbeddingModelRegistry).where(EmbeddingModelRegistry.is_active.is_(True))
            ).first()
            if row is None:
                return None
            return {
                "model_id": row.model_id,
                "dimension": row.dimension,
                "version": row.version,
                "indexed_chunks": row.indexed_chunks,
                "is_active": row.is_active,
            }

    def reindex_required(self) -> bool:
        """True when the active index was built by a different model."""
        record = self.active_model_record()
        return record is not None and record["model_id"] != self.model_id
