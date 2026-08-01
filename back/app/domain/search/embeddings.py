"""Embedding providers.

The gateway exposes no embedding model, so the default is a deterministic local
implementation: a hashed bag-of-features projected onto the unit sphere. It is
reproducible offline and in CI, and it is honest about what it is — lexical
overlap, not semantic understanding. Swapping in a real model means
implementing this interface and running a migration for the new dimension.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from abc import ABC, abstractmethod

from app.models.search import EMBEDDING_DIM

TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


class EmbeddingProvider(ABC):
    name: str
    dimension: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Returns a unit-length vector."""


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Hashed n-gram features. Same text always yields the same vector."""

    name = "deterministic"
    dimension = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            self._accumulate(vector, token, weight=1.0)
        # Bigrams give word order a small amount of influence, which matters
        # for prompts like "red on blue" versus "blue on red".
        for left, right in itertools.pairwise(tokens):
            self._accumulate(vector, f"{left}_{right}", weight=0.5)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        return TOKEN_PATTERN.findall(text.lower())

    def _accumulate(self, vector: list[float], token: str, *, weight: float) -> None:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % self.dimension
        # The sign bit spreads features out so unrelated tokens are less likely
        # to reinforce each other.
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * weight


_provider: EmbeddingProvider = DeterministicEmbeddingProvider()


def get_provider() -> EmbeddingProvider:
    return _provider


def set_provider(provider: EmbeddingProvider) -> None:
    global _provider
    _provider = provider


def embed(text: str) -> list[float]:
    return _provider.embed(text)
