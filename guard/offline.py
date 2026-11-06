"""Offline baseline: regex fact extraction, no AI, no API key.

Why it exists:
1. tests and the demo run anywhere, deterministically;
2. it is the "no AI" row of the ablation table, so you can show what the
   model adds (it catches deaths, ages, stated relationships, "X learns Y";
   it misses anything implied, like lifting a box with a broken arm).
"""
from __future__ import annotations

import re

from .characters import CharacterIndex
from .schemas import Episode, FactDraft, Line

NAME = r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)?"
REL = (r"sister|brother|mother|father|mom|dad|husband|wife|son|daughter|grandmother|grandfather|grandma|"
       r"grandpa|uncle|aunt|cousin|fianc[eé]e?|boss|assistant|ex-wife|ex-husband|girlfriend|boyfriend|twin")
JOBS = (r"intern|ceo|assistant|doctor|nurse|lawyer|courier|driver|waitress|waiter|secretary|manager|chef|"
        r"teacher|student|detective|maid|bodyguard|designer|accountant|cleaner|receptionist|surgeon|pilot")
NOT_AGE_UNITS = r"(?!\s*(?:minutes?|hours?|days?|weeks?|months?|percent|%|dollars|grand|k\b|am\b|pm\b))"

P_AGE_ACTION = re.compile(rf"\b(?P<name>{NAME}),\s*(?P<age>\d{{1,2}})\b")
P_AGE_SAID = re.compile(rf"\bI(?:'m| am)\s+(?P<age>\d{{1,2}})\b{NOT_AGE_UNITS}")
P_REL_SAID_1 = re.compile(rf"\b(?i:my) (?P<rel>(?i:{REL})),?\s+(?P<name>{NAME})")
P_REL_SAID_2 = re.compile(rf"\b(?P<name>{NAME}) is my (?P<rel>(?i:{REL}))\b")
P_REL_ACTION = re.compile(rf"\b(?P<name>{NAME})(?:,\s*\d{{1,2}})?,\s*(?P<other>{NAME})'s (?P<rel>{REL})\b")
P_DEATH = [re.compile(rf"\bcovers (?P<name>{NAME})'s face"),
           re.compile(rf"\b(?P<name>{NAME}) (?:dies|is dead|passes away|stops breathing)\b"),
           re.compile(rf"\b(?P<name>{NAME})'s funeral\b")]
P_JOB_ACTION = re.compile(rf"\b(?P<name>{NAME}),\s*(?:now\s+)?(?:an?|the)\s+(?P<job>(?i:{JOBS}))\b")
P_JOB_SAID = re.compile(rf"\bI(?:'m| am)\s+(?:an?|the)\s+(?P<job>(?i:{JOBS}))\b")
P_LEARNS = re.compile(rf"\b(?P<name>{NAME}) (?:learns|discovers|finds out|realizes|realises|overhears) "
                      r"(?:that\s+)?(?P<secret>[^.!?]+)")
P_KNOWS = re.compile(r"\bI know (?:that |about )?(?P<secret>[^.!?]+)")
P_INJURY = re.compile(rf"\b(?P<name>{NAME})(?:,\s*\d{{1,2}})?\b[^.]*?\b(?P<inj>(?:(?:his|her) )?(?:left |right )?"
                      r"(?:arm|leg|wrist|hand|foot|ankle) (?:is )?in a (?:cast|sling)|bandaged (?:head|arm|hand)|"
                      r"broken (?:arm|leg|wrist))")


def _rel(word: str) -> str:
    w = word.lower()
    return {"mom": "mother", "dad": "father", "grandma": "grandmother", "grandpa": "grandfather",
            "fiance": "fiance", "fiancé": "fiance", "fiancee": "fiancee", "fiancée": "fiancee"}.get(w, w)


def _facts_for_line(line: Line, chars: CharacterIndex) -> list[FactDraft]:
    out: list[FactDraft] = []
    t = line.text
    said = line.kind == "dialogue"
    mode = f"claimed_by:{line.speaker}" if said else "stated"
    me = chars.canonical(line.speaker) if line.speaker else ""

    def add(entity, ftype, attr, value, stability, quote):
        if entity:
            out.append(FactDraft(line_id=line.line_id, entity=entity, fact_type=ftype, attribute=attr,
                                 value=value, stability=stability, mode=mode, quote=quote))

    if not said:
        for m in P_AGE_ACTION.finditer(t):
            add(chars.canonical(m.group("name")), "identity", "age", m.group("age"), "stable", m.group(0))
        for m in P_REL_ACTION.finditer(t):
            add(chars.canonical(m.group("name")), "relationship",
                f"relationship_to:{chars.canonical(m.group('other'))}", _rel(m.group("rel")), "stable", m.group(0))
        for pat in P_DEATH:
            for m in pat.finditer(t):
                add(chars.canonical(m.group("name")), "status", "alive", "false", "stable", m.group(0))
        for m in P_JOB_ACTION.finditer(t):
            add(chars.canonical(m.group("name")), "identity", "job", m.group("job").lower(), "changeable", m.group(0))
        for m in P_LEARNS.finditer(t):
            secret = m.group("secret").strip()
            if len(secret.split()) >= 3:
                add(chars.canonical(m.group("name")), "knowledge", "learns", secret, "stable", m.group(0))
        for m in P_INJURY.finditer(t):
            add(chars.canonical(m.group("name")), "physical", "injury", m.group("inj"), "changeable", m.group(0))
    else:
        for m in P_AGE_SAID.finditer(t):
            add(me, "identity", "age", m.group("age"), "stable", m.group(0))
        for pat in (P_REL_SAID_1, P_REL_SAID_2):
            for m in pat.finditer(t):
                other = chars.canonical(m.group("name"))
                if other and me and other != me:
                    add(other, "relationship", f"relationship_to:{me}", _rel(m.group("rel")), "stable", m.group(0))
        for m in P_JOB_SAID.finditer(t):
            add(me, "identity", "job", m.group("job").lower(), "changeable", m.group(0))
        for m in P_KNOWS.finditer(t):
            secret = m.group("secret").strip()
            if len(secret.split()) >= 3:
                add(me, "knowledge", "acts_on", secret, "stable", m.group(0))
    return out


def extract(episode: Episode, chars: CharacterIndex) -> list[FactDraft]:
    drafts: list[FactDraft] = []
    for line in episode.all_lines():
        if line.kind in ("action", "dialogue"):
            drafts.extend(_facts_for_line(line, chars))
    return drafts
