from guard.characters import propose_characters
from guard.embed import HashingEmbedder
from guard.ledger import Ledger
from guard.parse import parse_path, parse_text
from guard.rules import norm_value, run_rules
from guard.schemas import Fact

from conftest import DEMO


def F(ep, line_id, entity, attr, value, ftype="identity", mode="stated", stability="stable", quote="x"):
    return Fact(fact_id=f"{line_id}-{attr}", episode=ep, line_id=line_id, entity=entity, fact_type=ftype,
                attribute=attr, value=value, mode=mode, stability=stability, quote=quote)


def setup(tmp_path, facts):
    led = Ledger(tmp_path, HashingEmbedder(), "numpy")
    led.add_facts(facts)
    return led, propose_characters(parse_path(DEMO))


def test_dead_character_speaking_is_flagged_but_flashback_is_not(cfg, tmp_path):
    led, chars = setup(tmp_path, [F(2, "E02L013", "rose", "alive", "false", "status")])
    ep = parse_text("EPISODE 3\n[00:00] INT. HOUSE - DAY\n[00:05] ROSE: Get out.\n"
                    "[00:09] INT. HOUSE - DAY (FLASHBACK)\n[00:10] ROSE: Welcome home.", "e.txt")[0]
    cands = run_rules(ep, [], led, chars, cfg)
    assert [(c.rule, c.new_line_id) for c in cands] == [("dead_character_active", "E03L002")]


def test_mentioning_the_dead_is_fine(cfg, tmp_path):
    led, chars = setup(tmp_path, [F(2, "E02L013", "rose", "alive", "false", "status")])
    ep = parse_text("EPISODE 3\n[00:05] Rose's portrait hangs above the fireplace.", "e.txt")[0]
    assert run_rules(ep, [], led, chars, cfg) == []


def test_stable_attribute_change_and_consistency(cfg, tmp_path):
    led, chars = setup(tmp_path, [F(1, "E01L002", "maya", "age", "26")])
    ep = parse_text("EPISODE 3\n[00:20] MAYA: I'm 29.\n[00:30] MAYA: I'm 26.", "e.txt")[0]
    changed = F(3, "E03L001", "maya", "age", "29", mode="claimed_by:MAYA")
    same = F(3, "E03L002", "maya", "age", "26 years old", mode="claimed_by:MAYA")
    cands = run_rules(ep, [changed, same], led, chars, cfg)
    assert [(c.rule, c.new_line_id) for c in cands] == [("stable_attribute_changed", "E03L001")]


def test_relationship_change(cfg, tmp_path):
    led, chars = setup(tmp_path, [F(1, "E01L014", "victor", "relationship_to:ethan", "cousin", "relationship")])
    ep = parse_text("EPISODE 4\n[00:02] Victor Hale, Ethan's brother, waits.", "e.txt")[0]
    nf = F(4, "E04L001", "victor", "relationship_to:ethan", "brother", "relationship")
    assert [c.rule for c in run_rules(ep, [nf], led, chars, cfg)] == ["relationship_changed"]


def test_secret_used_before_learned(cfg, tmp_path):
    learned = F(2, "E02L016", "victor", "learns", "Maya is Ethan's wife", "knowledge")
    led, chars = setup(tmp_path, [learned])
    ep = parse_text("EPISODE 3\n[00:31] DAVID: I know that Maya is Ethan's wife.\n"
                    "[00:40] VICTOR: I know that Maya is Ethan's wife.", "e.txt")[0]
    david = F(3, "E03L001", "david", "acts_on", "Maya is Ethan's wife", "knowledge", mode="claimed_by:DAVID")
    victor = F(3, "E03L002", "victor", "acts_on", "Maya is Ethan's wife", "knowledge", mode="claimed_by:VICTOR")
    cands = run_rules(ep, [david, victor], led, chars, cfg)
    assert [(c.rule, c.new_line_id) for c in cands] == [("secret_before_learned", "E03L001")]


def test_no_prior_episodes_means_no_candidates(cfg, tmp_path):
    led, chars = setup(tmp_path, [])
    ep = parse_path(DEMO)[0]
    assert run_rules(ep, [F(1, "E01L002", "maya", "age", "26")], led, chars, cfg) == []


def test_norm_value():
    assert norm_value("Dead") == "false" and norm_value("26 years old") == "26" and norm_value("the CEO") == "ceo"
