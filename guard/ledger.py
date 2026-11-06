"""The story so far.

Facts are kept in ledger.json (the source of truth, human-readable) and their
embeddings in vectors.npy. When LanceDB is installed and vector_store is
auto/lancedb, the vectors are mirrored into a LanceDB table and similarity
search runs there (the same setup as ChronoSearch and the Coder Agent);
otherwise numpy brute force is used, which is instant for one show.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

from .schemas import Fact


class Ledger:
    def __init__(self, show_dir: str | Path, embedder, backend: str = "auto"):
        self.dir = Path(show_dir)
        self.embedder = embedder
        self.facts: list[Fact] = []
        self.vectors = np.zeros((0, embedder.dim), dtype=np.float32)
        self.backend = "numpy"
        self._tbl = None
        if backend in ("auto", "lancedb"):
            try:
                import lancedb  # noqa: F401

                self.backend = "lancedb"
            except ImportError:
                if backend == "lancedb":
                    raise
        self._encode_cache: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------ persistence
    @property
    def _json(self) -> Path:
        return self.dir / "ledger.json"

    @classmethod
    def load(cls, show_dir: str | Path, embedder, backend: str = "auto") -> "Ledger":
        led = cls(show_dir, embedder, backend)
        if led._json.exists():
            data = json.loads(led._json.read_text(encoding="utf-8"))
            led.facts = [Fact.model_validate(f) for f in data.get("facts", [])]
            vec_path = led.dir / "vectors.npy"
            if (data.get("embedder") == embedder.name and vec_path.exists()):
                vecs = np.load(vec_path)
                if vecs.shape[0] == len(led.facts):
                    led.vectors = vecs.astype(np.float32)
            if led.vectors.shape[0] != len(led.facts):   # embedder changed: re-embed (cheap)
                led.vectors = led.embedder.encode([f.as_text() for f in led.facts])
        led._sync_lance(rebuild=True)
        return led

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {"embedder": self.embedder.name, "episodes": self.episodes(),
                "facts": [f.model_dump() for f in self.facts]}
        self._json.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        np.save(self.dir / "vectors.npy", self.vectors)

    def _sync_lance(self, rebuild: bool = False) -> None:
        if self.backend != "lancedb":
            return
        try:
            import lancedb

            db = lancedb.connect(str(self.dir / "lancedb"))
            names = db.table_names() if hasattr(db, "table_names") else list(db.list_tables())
            if "facts" in names and not rebuild:
                self._tbl = db.open_table("facts")
                return
            if "facts" in names:
                db.drop_table("facts")
            rows = self._rows(range(len(self.facts)))
            if rows:
                self._tbl = db.create_table("facts", data=rows)
            else:
                self._tbl = None
        except Exception as exc:  # never let the vector DB stop a run
            warnings.warn(f"LanceDB unavailable ({exc}); falling back to numpy search")
            self.backend, self._tbl = "numpy", None

    def _rows(self, idxs) -> list[dict]:
        return [{"vector": self.vectors[i].tolist(), "row": int(i), "fact_id": self.facts[i].fact_id,
                 "entity": self.facts[i].entity, "episode": int(self.facts[i].episode)} for i in idxs]

    # ------------------------------------------------------------------ edits
    def episodes(self) -> list[int]:
        return sorted({f.episode for f in self.facts})

    def add_facts(self, facts: list[Fact]) -> None:
        if not facts:
            return
        start = len(self.facts)
        self.facts.extend(facts)
        self.vectors = np.vstack([self.vectors, self.embedder.encode([f.as_text() for f in facts])])
        if self.backend == "lancedb":
            if self._tbl is None:
                self._sync_lance(rebuild=True)
            else:
                try:
                    self._tbl.add(self._rows(range(start, len(self.facts))))
                except Exception:
                    self._sync_lance(rebuild=True)

    def remove_episode(self, episode: int) -> None:
        keep = [i for i, f in enumerate(self.facts) if f.episode != episode]
        if len(keep) == len(self.facts):
            return
        self.facts = [self.facts[i] for i in keep]
        self.vectors = self.vectors[keep] if keep else np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._sync_lance(rebuild=True)

    # ------------------------------------------------------------------ queries
    def prior(self, before_episode: int, include_disputed: bool = False) -> list[Fact]:
        return [f for f in self.facts if f.episode < before_episode and (include_disputed or not f.disputed)]

    def history(self, entity: str, attribute: str, before_episode: int) -> list[Fact]:
        return [f for f in self.prior(before_episode) if f.entity == entity and f.attribute == attribute]

    def encode(self, text: str) -> np.ndarray:
        if text not in self._encode_cache:
            self._encode_cache[text] = self.embedder.encode([text])[0]
        return self._encode_cache[text]

    def similarity(self, a: str, b: str) -> float:
        return float(np.dot(self.encode(a), self.encode(b)))

    def similar(self, text: str, before_episode: int, k: int = 8, entity: Optional[str] = None,
                min_sim: float = 0.0) -> list[tuple[Fact, float]]:
        if not self.facts:
            return []
        q = self.encode(text)

        def keep(i: int) -> bool:
            f = self.facts[i]
            return f.episode < before_episode and not f.disputed and (entity is None or f.entity == entity)

        idxs: list[int] = []
        if self.backend == "lancedb" and self._tbl is not None:
            try:
                where = f"episode < {int(before_episode)}"
                if entity:
                    where += " AND entity = '" + entity.replace("'", "''") + "'"
                query = self._tbl.search(q.tolist())
                try:
                    query = query.where(where, prefilter=True)
                except TypeError:                      # older lancedb
                    query = query.where(where)
                idxs = [int(h["row"]) for h in query.limit(max(k * 4, 20)).to_list()]
                idxs = [i for i in idxs if 0 <= i < len(self.facts) and keep(i)]
            except Exception:
                idxs = []
        if len(idxs) < k:                              # numpy is exact and cheap at one-show scale
            idxs = [i for i in range(len(self.facts)) if keep(i)]
        if not idxs:
            return []
        sims = self.vectors[idxs] @ q
        order = np.argsort(-sims)[:k]
        return [(self.facts[idxs[j]], float(sims[j])) for j in order if sims[j] >= min_sim]
