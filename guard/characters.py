"""Character aliases: "ROSE", "Rose Sterling" and "Grandma Rose" -> one id.

The AI proposes groups once per show; a human corrects characters.yaml.
Without an AI model, a simple rule groups names by first name.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

import yaml

from .schemas import Episode

TITLES = re.compile(r"^(?:mr|mrs|ms|miss|dr|sir|madam|lady|lord|grandma|grandpa|aunt|uncle|young|old)\.?\s+", re.I)
MENTION = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)(?:'s)?\b")
NOT_NAMES = {"the", "a", "an", "he", "she", "they", "his", "her", "it", "we", "you", "i", "int", "ext", "room",
             "floor", "black", "promise", "who", "where", "what", "when", "why", "how", "one", "no", "yes",
             "tick", "find", "let", "my", "our", "this", "that", "then", "later", "everyone", "enjoy", "get",
             "please", "day", "night", "morning", "evening", "monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday", "forty", "corp", "city", "hospital", "mansion", "lobby"}


def norm_name(s: str) -> str:
    s = re.sub(r"'s\b|’s\b", "", str(s or "")).strip()
    s = TITLES.sub("", s)
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def slug(s: str) -> str:
    return "_".join(norm_name(s).split()) or "unknown"


class CharacterIndex:
    def __init__(self, characters: list[dict]):
        self.characters = characters
        self.alias: dict[str, str] = {}
        first: dict[str, set[str]] = {}
        for ch in characters:
            cid = ch["id"]
            for a in [cid, ch.get("name", "")] + list(ch.get("aliases", [])):
                n = norm_name(a)
                if n:
                    self.alias.setdefault(n, cid)
                    first.setdefault(n.split()[0], set()).add(cid)
        self.first = first

    def canonical(self, name: Optional[str]) -> str:
        n = norm_name(name or "")
        if not n:
            return ""
        if n in self.alias:
            return self.alias[n]
        ids = self.first.get(n.split()[0], set())
        if len(ids) == 1:
            return next(iter(ids))
        return "_".join(n.split())

    def names_for(self, cid: str) -> list[str]:
        for ch in self.characters:
            if ch["id"] == cid:
                return [ch.get("name", cid)] + list(ch.get("aliases", []))
        return [cid]

    def display(self, cid: str) -> str:
        for ch in self.characters:
            if ch["id"] == cid:
                return ch.get("name") or cid
        return cid

    def prompt_text(self) -> str:
        if not self.characters:
            return "(none yet)"
        return "\n".join(f"{c['id']}: {', '.join(dict.fromkeys([c.get('name', '')] + c.get('aliases', [])))}"
                         for c in self.characters)

    # ---- persistence
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = ("# One entry per person. Fix wrong merges, merge missed aliases, then rerun build.\n"
                  "# Names are matched case-insensitively; titles like Mr./Mrs. are ignored.\n")
        path.write_text(header + yaml.safe_dump({"characters": self.characters}, sort_keys=False,
                                                allow_unicode=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CharacterIndex":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("characters", []))


def collect_names(episodes: list[Episode]) -> Counter:
    counts: Counter = Counter()
    for ep in episodes:
        for ln in ep.all_lines():
            if ln.speaker:
                counts[("SPEAKER", ln.speaker)] += 1
            if ln.kind in ("action", "dialogue"):
                for m in MENTION.finditer(ln.text):
                    name = m.group(1)
                    if name.split()[0].lower() not in NOT_NAMES:
                        counts[("MENTION", name)] += 1
    return counts


def _heuristic(counts: Counter) -> list[dict]:
    chars: dict[str, dict] = {}
    for (kind, name), _ in counts.most_common():
        if kind != "SPEAKER":
            continue
        cid = slug(name).split("_")[0]
        ch = chars.setdefault(cid, {"id": cid, "name": name.title(), "aliases": []})
        ch["aliases"].append(name)
    for (kind, name), _ in counts.most_common():
        if kind != "MENTION":
            continue
        cid = norm_name(name).split()[0] if norm_name(name) else ""
        if cid in chars:
            ch = chars[cid]
            if name not in ch["aliases"]:
                ch["aliases"].append(name)
            if len(name.split()) > len(ch["name"].split()):
                ch["name"] = name  # prefer the full name
    return list(chars.values())


def propose_characters(episodes: list[Episode], llm=None) -> CharacterIndex:
    counts = collect_names(episodes)
    base = _heuristic(counts)
    if llm is None or llm.offline:
        return CharacterIndex(base)
    from pydantic import BaseModel

    class _Out(BaseModel):
        characters: list[dict] = []

    names = "\n".join(f"{kind} {name}: {n}" for (kind, name), n in counts.most_common(300)
                      if kind == "SPEAKER" or n >= 2)
    try:
        out = llm.call_json("resolve_aliases", {"names": names}, _Out, tag="aliases")
        chars = [c for c in out.characters if c.get("id")]
    except Exception:
        return CharacterIndex(base)
    # every speaker must belong to someone
    index = CharacterIndex(chars)
    for ch in base:
        if all(norm_name(a) not in index.alias for a in ch["aliases"]):
            chars.append(ch)
    return CharacterIndex(chars)
