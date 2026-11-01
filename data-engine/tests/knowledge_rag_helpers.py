"""Dobles hermeticos del RAG de conocimiento (sin modelos ni red)."""

from __future__ import annotations

import hashlib
import math
import re

from app.services.hybrid_retrieval import SparseEmbedding

_TOK = re.compile(r"\w+", re.UNICODE)


def fake_count(text: str) -> int:
    """1 token por palabra + 2 especiales (determinista, facil de razonar)."""
    return len(text.split()) + 2


def _h(word: str, mod: int) -> int:
    return int(hashlib.md5(word.lower().encode()).hexdigest(), 16) % mod  # noqa: S324  # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5 -- fixture: hash no criptografico para reparto determinista de palabras en tests; no protege secretos


class FakeEmbedder:
    dims = 384

    def dense_docs(self, texts: list[str]) -> list[list[float]]:
        return self.dense(texts)

    def dense_query(self, text: str) -> list[float]:
        return self.dense([text])[0]

    def dense(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dims
            for w in _TOK.findall(t):
                vec[_h(w, self.dims)] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    def _sparse(self, t: str) -> SparseEmbedding:
        counts: dict[int, float] = {}
        for w in _TOK.findall(t):
            counts[_h(w, 1_000_003)] = counts.get(_h(w, 1_000_003), 0.0) + 1.0
        keys = sorted(counts)
        return SparseEmbedding(indices=keys, values=[counts[k] for k in keys])

    def sparse_docs(self, texts: list[str]) -> list[SparseEmbedding]:
        return [self._sparse(t) for t in texts]

    def sparse_query(self, text: str) -> SparseEmbedding:
        return self._sparse(text)
