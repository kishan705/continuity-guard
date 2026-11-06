"""Cheap, certain checks. Plain code, no AI, unit-tested.

Each rule turns a suspicious pattern into a Candidate for the judge:
- dead_character_active     a character who died speaks or acts
- stable_attribute_changed  age / name / birth family / nationality changes
- relationship_changed      "my sister Lily" becomes "my cousin Lily"
- secret_before_learned     someone uses a secret they never learned
- similar_fact              (retrieval) a related earlier fact with a different value
"""
from __future__ import annotations

import re

from .characters import CharacterIndex
from .ledger import Ledger
from .schemas import Candidate, Episode, Fact

STABLE_ATTRS = {"name", "age", "nationality", "hometown"}
NOT_ACTIVE = re.compile(r"\b(funeral|grave|photo|photograph|portrait|picture|memory|memories|remember|remembers|"
                        r"ashes|coffin|casket|body|corpse|ghost|flashback|dream|dreams|imagines|hallucinat|"
                        r"will|urn|tombstone|obituary|late)\b", re.I)
FLASHBACK = re.compile(r"\b(flashback|flash back|years? (?:ago|earlier)|dream|memory)\b", re.I)
BOOL = {"dead": "false", "deceased": "false", "died": "false", "no": "false", "false": "false",
        "alive": "true", "living": "true", "yes": "true", "true": "true"}


def norm_value(v: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(v).lower())
    s = re.sub(r"\b(a|an|the|is|was|her|his|their|years? old)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return BOOL.get(s, s)


def _latest(facts: list[Fact], n: int = 3) -> list[Fact]:
    return sorted(facts, key=lambda f: (f.episode, f.line_id), reverse=True)[:n]


def _in_flashback(episode: Episode, line_id: str) -> bool:
    sc = episode.scene_of(line_id)
    if not sc:
        return False
    if FLASHBACK.search(sc.heading or ""):
        return True
    for ln in sc.lines:  # an explicit FLASHBACK marker earlier in the scene
        if ln.line_id == line_id:
            break
        if ln.kind == "transition" and FLASHBACK.search(ln.text):
            return True
    return False


def run_rules(episode: Episode, new_facts: list[Fact], ledger: Ledger, chars: CharacterIndex,
              cfg: dict) -> list[Candidate]:
    cc = cfg.get("check", {})
    ep_no = episode.episode
    prior = ledger.prior(ep_no)
    if not prior:
        return []
    by_key: dict[tuple[str, str], list[Fact]] = {}
    for f in prior:
        by_key.setdefault(f.key(), []).append(f)
    cands: list[Candidate] = []

    def add(rule, ftype, line_id, new_fact, priors, note, score=1.0):
        cands.append(Candidate(candidate_id="", rule=rule, type=ftype, episode=ep_no, new_line_id=line_id,
                               new_fact=new_fact, prior_facts=priors, note=note, score=score))

    # 1. dead character speaks or acts ------------------------------------------------
    dead: dict[str, list[Fact]] = {}
    for f in sorted(prior, key=lambda f: (f.episode, f.line_id)):
        if f.attribute == "alive" and f.mode == "stated":
            if norm_value(f.value) == "false":
                dead.setdefault(f.entity, []).append(f)
            elif norm_value(f.value) == "true":
                dead.pop(f.entity, None)              # revived on screen earlier: fine
    if dead:
        flagged: set[tuple[str, str]] = set()           # one flag per dead character per scene
        for ln in episode.all_lines():
            who = None
            if ln.kind == "dialogue" and ln.speaker:
                who = chars.canonical(ln.speaker)
            elif ln.kind == "action" and not NOT_ACTIVE.search(ln.text):
                first = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b(?!['’]s\b)", ln.text)
                if first:
                    cand_id = chars.canonical(first.group(1))
                    who = cand_id if cand_id in dead else None
            sc = episode.scene_of(ln.line_id)
            where = (who, sc.scene_id if sc else "")
            if who in dead and where not in flagged and not _in_flashback(episode, ln.line_id):
                flagged.add(where)
                add("dead_character_active", "status", ln.line_id, None, dead[who][-1:],
                    f"{chars.display(who)} died earlier but {'speaks' if ln.kind == 'dialogue' else 'acts'} here")

    for nf in new_facts:
        if nf.disputed:
            continue
        priors = by_key.get(nf.key(), [])
        nv = norm_value(nf.value)
        # 2. stable attribute changed ------------------------------------------------
        if nf.attribute != "alive" and (nf.attribute in STABLE_ATTRS or
                                        (nf.stability == "stable" and nf.fact_type in ("identity",))):
            diff = [p for p in priors if norm_value(p.value) != nv]
            if diff:
                add("stable_attribute_changed", nf.fact_type, nf.line_id, nf, _latest(diff),
                    f"{nf.attribute} was '{_latest(diff)[0].value}', now '{nf.value}'")
                continue
        # 3. relationship changed -----------------------------------------------------
        if nf.attribute.startswith("relationship_to:"):
            diff = [p for p in priors if norm_value(p.value) != nv]
            if diff:
                add("relationship_changed", "relationship", nf.line_id, nf, _latest(diff),
                    f"relationship was '{_latest(diff)[0].value}', now '{nf.value}'")
                continue
        # 4. secret used before it was learned ------------------------------------------
        if nf.attribute == "acts_on":
            thr = float(cc.get("secret_match", 0.45))
            learned = [p for p in prior if p.attribute == "learns" and ledger.similarity(p.value, nf.value) >= thr]
            learned_now = [f for f in new_facts if f.attribute == "learns" and f.entity == nf.entity
                           and f.line_id < nf.line_id and ledger.similarity(f.value, nf.value) >= thr]
            if learned and not learned_now and all(p.entity != nf.entity for p in learned):
                add("secret_before_learned", "knowledge", nf.line_id, nf, _latest(learned),
                    f"{chars.display(nf.entity)} uses a secret only "
                    f"{', '.join(sorted({chars.display(p.entity) for p in learned}))} learned on screen")
                continue
        later_learn = [f for f in new_facts if f.attribute == "learns" and f.entity == nf.entity
                       and f.line_id > nf.line_id and nf.attribute == "acts_on"
                       and ledger.similarity(f.value, nf.value) >= float(cc.get("secret_match", 0.45))]
        if later_learn:
            add("secret_before_learned", "knowledge", nf.line_id, nf, later_learn[:1],
                "uses the secret before learning it later in this same episode")
            continue
        # 5. similar earlier fact with a different value (goes to the AI judge) -----------
        if nf.attribute in ("acts_on", "learns"):
            continue
        hits = ledger.similar(nf.as_text(), ep_no, k=int(cc.get("similar_k", 8)), entity=nf.entity,
                              min_sim=float(cc.get("min_similarity", 0.35)))
        related = [(f, s) for f, s in hits if f.fact_type == nf.fact_type and norm_value(f.value) != nv]
        if related:
            add("similar_fact", nf.fact_type, nf.line_id, nf, [f for f, _ in related[:3]],
                "related earlier fact with a different value", score=max(s for _, s in related))

    # dedupe + rank + cap -------------------------------------------------------------
    seen, unique = set(), []
    for c in sorted(cands, key=lambda c: -c.score):
        key = (c.rule, c.new_line_id, c.new_fact.attribute if c.new_fact else "",
               tuple(sorted(p.fact_id for p in c.prior_facts)))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    unique = unique[: int(cc.get("max_candidates_per_episode", 40))]
    for i, c in enumerate(unique, 1):
        c.candidate_id = f"C{i}"
    return unique
