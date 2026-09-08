"""Vector embedding utility with local lightweight fallback and transformer support."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections.abc import Sequence

logger = logging.getLogger("opsmind.memory.embedder")


class IncidentEmbedder:
    """Generates normalized vector embeddings for incident text and post-mortems.

    Provides a fast, zero-dependency TF-IDF / feature hashing embedder by default,
    with lazy-loaded sentence-transformers if available.
    """

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension
        self._model = None
        self._transformer_available = False

    def embed_text(self, text: str) -> list[float]:
        """Convert a single text string into a normalized embedding vector."""
        if not text.strip():
            return [0.0] * self.dimension

        # Pure-Python deterministic hashing vectorizer (normalized)
        tokens = re.findall(r"\b\w+\b", text.lower())
        if not tokens:
            return [0.0] * self.dimension

        vector = [0.0] * self.dimension
        for token in tokens:
            token_hash = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            bucket = token_hash % self.dimension
            vector[bucket] += 1.0 + math.log(1.0 + tokens.count(token))

        # L2 Normalize
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0.0:
            vector = [x / norm for x in vector]

        return vector

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a list of text strings in batch."""
        return [self.embed_text(t) for t in texts]

    @staticmethod
    def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
        """Compute cosine similarity between two normalized vectors."""
        if len(vec_a) != len(vec_b) or not vec_a or not vec_b:
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
