"""Candidates -> flags.

mode "rules": every rule hit becomes a flag (no AI)          -> ablation row 1
mode "judge": AI judge keeps only real contradictions        -> ablation row 2
mode "full" : judge, then a second AI pass argues each flag away -> ablation row 3
Every flag is grounded again at the end: both quotes must exist word for word.
"""
from __future__ import annotations

from .grounding import ref_is_grounded
from .schemas import Candidate, Episode, Flag, JudgeBatch, JudgeVerdict, Ref, VerifyOutput

RULE_SEVERITY = {"dead_character_active": "high", "stable_attribute_changed": "high",
                 "relationship_changed": "medium", "secret_before_learned": "medium", "similar_fact": "low"}
CERTAIN_RULES = {"dead_character_active", "stable_attribute_changed", "relationship_changed",
                 "secret_before_learned"}


def _line_str(episodes: dict[int, Episode], episode: int, line_id: str) -> str:
    ep = episodes.get(episode)
    ln = ep.line(line_id) if ep else None
    return f"E{episode} [{ln.ts or '--:--'}] {line_id}: {ln.display()}" if ln else f"E{episode} {line_id}: (missing)"


def _context(episodes: dict[int, Episode], episode: int, line_id: str, n: int = 2) -> str:
    ep = episodes.get(episode)
    sc = ep.scene_of(line_id) if ep else None
    if not sc:
        return _line_str(episodes, episode, line_id)
    ids = [l.line_id for l in sc.lines]
    i = ids.index(line_id)
    rows = [f"  (scene: {sc.heading})"] if sc.heading else []
    for l in sc.lines[max(0, i - n): i + n + 1]:
        mark = ">>" if l.line_id == line_id else "  "
        rows.append(f"{mark} E{episode} [{l.ts or '--:--'}] {l.line_id}: {l.display()}")
    return "\n".join(rows)


def format_case(c: Candidate, episodes: dict[int, Episode]) -> str:
    rows = [f"CASE {c.candidate_id} (rule: {c.rule}, type: {c.type})",
            f"NEW: {_line_str(episodes, c.episode, c.new_line_id)}"]
    if c.new_fact:
        rows.append(f"New fact: {c.new_fact.short()}")
    if c.note:
        rows.append(f"Why it was raised: {c.note}")
    rows.append("EARLIER:")
    for p in c.prior_facts:
        rows.append(f"- {_line_str(episodes, p.episode, p.line_id)}   (fact: {p.short()})")
    return "\n".join(rows)


def judge(cands: list[Candidate], episodes: dict[int, Episode], llm, cfg: dict) -> dict[str, JudgeVerdict]:
    if not cands:
        return {}
    if llm.offline:  # deterministic stand-in: trust certain rules, skip fuzzy ones
        out = {}
        for c in cands:
            certain = c.rule in CERTAIN_RULES
            out[c.candidate_id] = JudgeVerdict(
                candidate_id=c.candidate_id, verdict="contradiction" if certain else "unclear",
                prior_line_ids=[p.line_id for p in c.prior_facts], explanation=c.note,
                severity=RULE_SEVERITY.get(c.rule, "medium"), confidence=0.75 if certain else 0.3,
                suggested_fix="")
        return out
    size = int(cfg.get("check", {}).get("judge_batch_size", 8))
    out: dict[str, JudgeVerdict] = {}
    for i in range(0, len(cands), size):
        batch = cands[i:i + size]
        cases = "\n\n".join(format_case(c, episodes) for c in batch)
        try:
            res = llm.call_json("judge_conflict", {"episode": str(batch[0].episode), "cases": cases},
                                JudgeBatch, tag="judge")
            for v in res.verdicts:
                out[v.candidate_id.strip()] = v
        except Exception as exc:  # keep going; these candidates stay unjudged
            for c in batch:
                out[c.candidate_id] = JudgeVerdict(candidate_id=c.candidate_id, verdict="unclear",
                                                   explanation=f"judge failed: {str(exc)[:120]}")
    return out


def verify(flag: Flag, cand: Candidate, episodes: dict[int, Episode], llm) -> tuple[bool, str]:
    if llm.offline:
        return True, "offline baseline: verify pass skipped"
    prior_ctx = "\n\n".join(_context(episodes, r.episode, r.line_id) for r in flag.prior)
    new_ctx = _context(episodes, flag.new.episode, flag.new.line_id)
    try:
        res = llm.call_json("verify_flag", {"prior_context": prior_ctx, "new_context": new_ctx,
                                            "episode": str(flag.new.episode), "explanation": flag.explanation},
                            VerifyOutput, tag="verify")
        return bool(res.keep), res.reason
    except Exception as exc:
        return True, f"verify failed, flag kept: {str(exc)[:120]}"


def _ref(episodes: dict[int, Episode], episode: int, line_id: str) -> Ref | None:
    ep = episodes.get(episode)
    ln = ep.line(line_id) if ep else None
    return Ref(episode=episode, ts=ln.ts, line_id=line_id, quote=ln.display()) if ln else None


def _make_flag(c: Candidate, v: JudgeVerdict, episodes: dict[int, Episode], n: int, model: str,
               found_by: str) -> Flag | None:
    new = _ref(episodes, c.episode, c.new_line_id)
    if not new:
        return None
    by_line = {p.line_id: p for p in c.prior_facts}
    chosen = [by_line[i] for i in v.prior_line_ids if i in by_line] or c.prior_facts
    prior = [r for r in (_ref(episodes, p.episode, p.line_id) for p in chosen) if r]
    return Flag(flag_id=f"FL-E{c.episode:02d}-{n:02d}", type=c.type, rule=c.rule, severity=v.severity,
                verdict=v.verdict, confidence=round(v.confidence, 2), new=new, prior=prior,
                explanation=v.explanation or c.note, suggested_fix=v.suggested_fix, found_by=found_by, model=model,
                prior_fact_ids=[p.fact_id for p in chosen])


def _merge(flags: list[Flag]) -> list[Flag]:
    """Several candidates on the same line for the same rule are one problem for the editor."""
    out: dict[tuple[str, str], Flag] = {}
    for f in flags:
        k = (f.new.line_id, f.rule)
        if k not in out:
            out[k] = f
            continue
        keep = out[k] if out[k].confidence >= f.confidence else f
        other = f if keep is out[k] else out[k]
        seen = {r.line_id for r in keep.prior}
        keep.prior += [r for r in other.prior if r.line_id not in seen]
        keep.prior_fact_ids = list(dict.fromkeys(keep.prior_fact_ids + other.prior_fact_ids))
        out[k] = keep
    return list(out.values())


def check_candidates(cands: list[Candidate], episodes: dict[int, Episode], llm_judge, llm_verify,
                     cfg: dict, mode: str = "full") -> tuple[list[Flag], dict]:
    stats = {"candidates": len(cands), "judged_contradiction": 0, "verify_dropped": 0, "ungrounded_dropped": 0}
    flags: list[Flag] = []
    if mode == "rules":
        for c in cands:
            if c.rule not in CERTAIN_RULES:
                continue
            v = JudgeVerdict(candidate_id=c.candidate_id, verdict="contradiction", explanation=c.note,
                             severity=RULE_SEVERITY.get(c.rule, "medium"), confidence=0.5)
            f = _make_flag(c, v, episodes, len(flags) + 1, "rules-only", "rules")
            if f:
                flags.append(f)
    else:
        min_conf = float(cfg.get("check", {}).get("min_confidence", 0.6))
        verdicts = judge(cands, episodes, llm_judge, cfg)
        for c in cands:
            v = verdicts.get(c.candidate_id)
            if not v or v.verdict != "contradiction" or v.confidence < min_conf:
                continue
            stats["judged_contradiction"] += 1
            found_by = "rules+judge" if mode == "judge" else "rules+judge+verify"
            f = _make_flag(c, v, episodes, len(flags) + 1, llm_judge.name, found_by)
            if not f:
                continue
            if mode == "full":
                keep, reason = verify(f, c, episodes, llm_verify)
                f.verify_reason = reason
                if not keep:
                    stats["verify_dropped"] += 1
                    continue
            flags.append(f)
    flags = _merge(flags)
    grounded = []
    for f in flags:
        if ref_is_grounded(f.new, episodes) and all(ref_is_grounded(r, episodes) for r in f.prior):
            grounded.append(f)
        else:
            stats["ungrounded_dropped"] += 1
    for i, f in enumerate(grounded, 1):
        f.flag_id = f"FL-E{f.new.episode:02d}-{i:02d}"
    order = {"high": 0, "medium": 1, "low": 2}
    grounded.sort(key=lambda f: (order[f.severity], -f.confidence))
    return grounded, stats
