"""The AI code path, with a scripted fake model standing in for Gemini / Groq / Ollama."""
import json

from guard.characters import propose_characters
from guard.extract import extract_episode
from guard.judge import check_candidates
from guard.parse import parse_path
from guard.pipeline import Show, build, parse_show

from conftest import DEMO, case_ids


def test_extraction_grounds_repairs_and_rejects(cfg, scripted):
    ep = parse_path(DEMO)[1]
    chars = propose_characters(parse_path(DEMO))

    def responder(prompt):
        return json.dumps({"facts": [
            {"line_id": "E02L013", "entity": "Rose", "fact_type": "status", "attribute": "dead", "value": "yes",
             "stability": "stable", "mode": "stated", "quote": "The doctor covers Rose's face"},
            {"line_id": "E02L005", "entity": "lily", "fact_type": "injury", "attribute": "injury",
             "value": "left arm in a cast", "mode": "stated", "quote": "her left arm in a cast"},   # wrong line id
            {"line_id": "E02L013", "entity": "rose", "fact_type": "status", "attribute": "buried_in",
             "value": "Paris", "mode": "stated", "quote": "Rose is buried in Paris"},              # invented
            {"line_id": "E02L002", "entity": "maya", "fact_type": "mood", "attribute": "x", "value": "y",
             "quote": "carries a tray"},                                                          # bad type
        ]})

    facts, stats = extract_episode(ep, chars, scripted(cfg, responder), cfg)
    by_attr = {f.attribute: f for f in facts}
    assert by_attr["alive"].value == "false" and by_attr["alive"].entity == "rose"   # "dead: yes" normalised
    assert by_attr["injury"].line_id == "E02L006" and by_attr["injury"].repaired     # re-pointed to the real line
    assert by_attr["injury"].fact_type == "physical"
    assert "buried_in" not in by_attr
    assert stats["rejected"] == 1 and stats["invalid"] == 1 and stats["repaired"] == 1


def test_judge_and_verify_filter_candidates(cfg, scripted):
    show = Show("demo", cfg)
    parse_show(DEMO, show)
    show.characters(refresh=True)
    build(show, mode="rules", fresh=True)           # offline facts + rule candidates for ep 3
    from guard.rules import run_rules

    eps = {e.episode: e for e in show.episodes()}
    ledger, chars = show.ledger(), show.characters()
    facts = [f.model_copy(update={"disputed": False}) for f in ledger.facts if f.episode == 3]
    cands = run_rules(eps[3], facts, ledger, chars, cfg)
    assert {c.rule for c in cands} == {"dead_character_active", "stable_attribute_changed", "secret_before_learned"}
    by_rule = {c.rule: c.candidate_id for c in cands}

    def judge(prompt):
        out = []
        for cid in case_ids(prompt):
            verdict = "development" if cid == by_rule["secret_before_learned"] else "contradiction"
            out.append({"candidate_id": cid, "verdict": verdict, "confidence": 0.9, "severity": "high",
                        "explanation": f"judged {cid}", "suggested_fix": "fix it"})
        return json.dumps({"verdicts": out})

    def verify(prompt):
        keep = "I'm 29" not in prompt.split("New line")[1]
        return json.dumps({"keep": keep, "reason": "time skip?" if not keep else "no innocent reading"})

    flags, stats = check_candidates(cands, eps, scripted(cfg, judge, "judge"), scripted(cfg, verify, "verify"),
                                    cfg, mode="full")
    assert [f.rule for f in flags] == ["dead_character_active"]
    assert stats["judged_contradiction"] == 2 and stats["verify_dropped"] == 1
    assert flags[0].suggested_fix == "fix it" and flags[0].found_by == "rules+judge+verify"


def test_build_with_injected_models(cfg, scripted):
    """The physical error (lifting a box with a broken arm) is only catchable with an AI model."""
    show = Show("demo", cfg)
    parse_show(DEMO, show)
    show.characters(refresh=True)
    from guard import offline as off

    def extractor(prompt):
        import re
        ids = re.findall(r"^(E\d\dL\d{3}) ", prompt, re.M)
        ep = int(ids[0][1:3])
        episode = {e.episode: e for e in show.episodes()}[ep]
        facts = [d.model_dump() for d in off.extract(episode, show.characters())]
        if ep == 3:
            facts.append({"line_id": "E03L011", "entity": "lily", "fact_type": "physical",
                          "attribute": "injury", "value": "uses both arms normally, no cast",
                          "mode": "stated", "quote": "lifts a box of books with both arms"})
        return json.dumps({"facts": facts})

    def judge(prompt):
        return json.dumps({"verdicts": [{"candidate_id": c, "verdict": "contradiction", "confidence": 0.8}
                                        for c in case_ids(prompt)]})

    llms = (scripted(cfg, extractor), scripted(cfg, judge, "judge"), scripted(cfg, lambda p: '{"keep": true}', "verify"))
    summary = build(show, mode="full", fresh=True, llms=llms)
    ep3 = json.loads((show.out / "reports" / "ep_03.json").read_text())
    rules = sorted(f["rule"] for f in ep3["flags"])
    assert rules == ["dead_character_active", "secret_before_learned", "similar_fact", "stable_attribute_changed"]
    physical = next(f for f in ep3["flags"] if f["rule"] == "similar_fact")
    assert physical["prior"][0]["line_id"] == "E02L006"            # the cast
    assert summary["flags"] == 4
