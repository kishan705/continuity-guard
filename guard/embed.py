"""Text embeddings for fact similarity.

auto -> sentence-transformers (all-MiniLM-L6-v2, local and free) when installed,
otherwise a built-in hashing embedder (words + character trigrams). The hashing
one needs no download and is deterministic, which keeps tests stable; it only
captures word overlap, so semantic matches are weaker. Install
sentence-transformers for real runs.
"""
from __future__ import annotations

import re
import zlib

import numpy as np


class HashingEmbedder:
    name = "hashing-2048"
    dim = 2048

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        words = re.findall(r"[a-z0-9]+", text.lower())
        for w in words:
            v[zlib.crc32(("w:" + w).encode()) % self.dim] += 2.0
            padded = f"#{w}#"
            for i in range(len(padded) - 2):
                v[zlib.crc32(("c:" + padded[i:i + 3]).encode()) % self.dim] += 0.5
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vec(t) for t in texts])


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.name = model_name
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
                          dtype=np.float32)


def get_embedder(cfg: dict):
    ec = cfg.get("embeddings", {})
    provider = ec.get("provider", "auto")
    if provider in ("auto", "sentence_transformers"):
        try:
            return SentenceTransformerEmbedder(ec.get("model", "sentence-transformers/all-MiniLM-L6-v2"))
        except Exception:
            if provider == "sentence_transformers":
                raise
    return HashingEmbedder()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # vectors are already L2-normalised
