"""The anti-hallucination wall.

Every fact and every flag must quote its line word for word. If the quote is
not in the cited line, we look for it in the same scene (models are often off
by one line) and re-point it; otherwise the item is thrown away.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .schemas import Episode, Fact, Line, Ref

_TRANS = {ord("’"): "'", ord("‘"): "'", ord("“"): '"', ord("”"): '"', ord("–"): "-", ord("—"): "-", ord("…"): "..."}
_SPEAKER_PREFIX = re.compile(r"^[A-Z][A-Za-z .'\-]{0,30}(?:\([^)]*\))?\s*:\s+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS).lower()
    return re.sub(r"\s+", " ", s).strip()


def _bare(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", _norm(s))).strip()


def quote_in(quote: str, text: str) -> bool:
    """True when every part of the quote (split on '...') appears in text,
    ignoring case, curly quotes, extra spaces and punctuation."""
    q = (quote or "").strip().strip("\"'")
    q = _SPEAKER_PREFIX.sub("", q)
    parts = [p for p in re.split(r"\.\.\.|…", q) if len(_bare(p)) >= 2]
    if not parts or len(_bare(q)) < 3:
        return False
    nt, bt = _norm(text), _bare(text)
    for p in parts:
        pn = _norm(p).strip(" ,.;:!?\"'")
        if pn not in nt and _bare(p) not in bt:
            return False
    return True


def line_matches(quote: str, line: Line) -> bool:
    return quote_in(quote, line.text) or quote_in(quote, line.display())


def find_line(quote: str, episode: Episode, near: Optional[str] = None) -> Optional[Line]:
    """Search the cited scene first, then the whole episode."""
    scene = episode.scene_of(near) if near else None
    pools = ([scene.lines] if scene else []) + [episode.all_lines()]
    for pool in pools:
        for ln in pool:
            if line_matches(quote, ln):
                return ln
    return None


def ground_facts(facts: list[Fact], episode: Episode) -> tuple[list[Fact], list[Fact]]:
    kept, rejected = [], []
    for f in facts:
        line = episode.line(f.line_id)
        if line and line_matches(f.quote, line):
            kept.append(f)
            continue
        other = find_line(f.quote, episode, near=f.line_id if line else None)
        if other:
            sc = episode.scene_of(other.line_id)
            kept.append(f.model_copy(update={"line_id": other.line_id, "ts": other.ts,
                                             "scene_id": sc.scene_id if sc else f.scene_id, "repaired": True}))
        else:
            rejected.append(f)
    return kept, rejected


def ref_is_grounded(ref: Ref, episodes: dict[int, Episode]) -> bool:
    ep = episodes.get(ref.episode)
    line = ep.line(ref.line_id) if ep else None
    return bool(line) and line_matches(ref.quote, line)
