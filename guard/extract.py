"""Episode -> facts. The AI reads; code cleans up and grounds every quote.

A whole short episode goes in one call (microdrama episodes are 1-2 minutes);
longer ones are chunked by scene so no call exceeds max_lines_per_call.
"""
from __future__ import annotations

import re

from pydantic import ValidationError

from . import offline
from .characters import CharacterIndex
from .grounding import ground_facts
from .schemas import Episode, ExtractOutput, Fact, FactDraft, Line

ATTR_ALIASES = {"is_alive": "alive", "dead": "alive", "deceased": "alive", "living": "alive", "life_status": "alive",
                "occupation": "job", "profession": "job", "work": "job", "job_title": "job", "position": "job",
                "knows": "acts_on", "knows_secret": "acts_on", "reveals": "acts_on", "uses_secret": "acts_on",
                "learned": "learns", "discovers": "learns", "finds_out": "learns", "learns_secret": "learns",
                "injured": "injury", "wound": "injury", "years_old": "age", "full_name": "name",
                "lives": "lives_in", "residence": "lives_in", "time": "time_marker"}
ALIVE_WORDS = {"dead": "false", "deceased": "false", "died": "false", "killed": "false", "no": "false",
               "alive": "true", "living": "true", "yes": "true"}


def format_lines(lines: list[Line]) -> str:
    out = []
    for l in lines:
        ts = l.ts or "--:--"
        if l.kind == "dialogue":
            out.append(f"{l.line_id} [{ts}] {l.speaker}: {l.text}")
        elif l.kind == "heading":
            out.append(f"{l.line_id} [{ts}] (scene) {l.text}")
        elif l.kind == "transition":
            out.append(f"{l.line_id} [{ts}] (transition) {l.text}")
        else:
            out.append(f"{l.line_id} [{ts}] (action) {l.text}")
    return "\n".join(out)


def chunks(episode: Episode, max_lines: int) -> list[list[Line]]:
    groups, cur = [], []
    for sc in episode.scenes:
        lines = sc.lines
        if len(lines) > max_lines:              # a single huge scene: split it
            for i in range(0, len(lines), max_lines):
                if cur:
                    groups.append(cur)
                    cur = []
                groups.append(lines[i:i + max_lines])
            continue
        if len(cur) + len(lines) > max_lines and cur:
            groups.append(cur)
            cur = []
        cur.extend(lines)
    if cur:
        groups.append(cur)
    return groups


def normalise(d: FactDraft, chars: CharacterIndex) -> FactDraft:
    attr = re.sub(r"\s+", "_", d.attribute.strip().lower())
    value = d.value.strip()
    if attr.startswith("relationship") and ":" in attr:
        other = attr.split(":", 1)[1]
        attr = f"relationship_to:{chars.canonical(other)}"
    attr = ATTR_ALIASES.get(attr, attr)
    if attr == "alive":
        value = ALIVE_WORDS.get(value.lower(), value.lower())
        if d.attribute.strip().lower() in ("dead", "deceased") and value in ("true", "yes"):
            value = "false"
    mode = d.mode.strip() if d.mode else "stated"
    if mode.lower().startswith("claimed"):
        who = mode.split(":", 1)[1].strip().upper() if ":" in mode else ""
        mode = f"claimed_by:{who}"
    else:
        mode = "stated"
    return d.model_copy(update={"entity": chars.canonical(d.entity) or d.entity.lower(), "attribute": attr,
                                "value": value, "mode": mode})


def extract_episode(episode: Episode, chars: CharacterIndex, llm, cfg: dict) -> tuple[list[Fact], dict]:
    stats = {"calls": 0, "drafts": 0, "invalid": 0, "grounded": 0, "rejected": 0, "repaired": 0}
    drafts: list[FactDraft] = []
    if llm.offline:
        drafts = offline.extract(episode, chars)
    else:
        max_lines = int(cfg.get("extract", {}).get("max_lines_per_call", 140))
        for group in chunks(episode, max_lines):
            stats["calls"] += 1
            prompt = cfg.get("extract", {}).get("prompt", "extract_facts")
            out = llm.call_json(prompt, {"episode": str(episode.episode),
                                                  "characters": chars.prompt_text(),
                                                  "lines": format_lines(group)}, ExtractOutput, tag="extract")
            for item in out.facts:
                try:
                    drafts.append(FactDraft.model_validate(item))
                except ValidationError:
                    stats["invalid"] += 1
    stats["drafts"] = len(drafts) + stats["invalid"]

    facts: list[Fact] = []
    seen = set()
    for d in drafts:
        d = normalise(d, chars)
        if not d.entity or not d.attribute or not d.value:
            stats["invalid"] += 1
            continue
        key = (d.entity, d.attribute, d.value.lower(), d.line_id)
        if key in seen:
            continue
        seen.add(key)
        line = episode.line(d.line_id)
        scene = episode.scene_of(d.line_id)
        facts.append(Fact(**d.model_dump(), episode=episode.episode, ts=line.ts if line else None,
                          scene_id=scene.scene_id if scene else ""))
    kept, rejected = ground_facts(facts, episode)
    for i, f in enumerate(kept, 1):
        f.fact_id = f"F-E{episode.episode:02d}-{i:03d}"
    stats.update(grounded=len(kept), rejected=len(rejected), repaired=sum(f.repaired for f in kept))
    return kept, stats
