"""Regression tests for problems found on the first real run (gen1)."""
import json

from guard.parse import parse_text
from guard.pipeline import Show, build, parse_show


def _show_from_text(cfg, tmp_path, episodes: dict[int, str]) -> Show:
    src = tmp_path / "src"
    src.mkdir()
    for n, body in episodes.items():
        (src / f"ep_{n:02d}.txt").write_text(f"EPISODE {n}\n{body}\n", encoding="utf-8")
    show = Show("t", cfg)
    parse_show(src, show)
    show.characters(refresh=True)
    return show


def _flags(show, ep):
    return json.loads((show.out / "reports" / f"ep_{ep:02d}.json").read_text())["flags"]


def test_one_wrong_death_does_not_flag_every_later_episode(cfg, tmp_path):
    show = _show_from_text(cfg, tmp_path, {
        1: "[00:01] INT. HOSPITAL - NIGHT\n[00:02] The doctor covers Rose's face with the sheet.\n[00:05] COLE: No.",
        2: "[00:01] ROSE: I'm back.",
        3: "[00:01] ROSE: Still here.",
        4: "[00:01] ROSE: And again.",
        5: "[00:01] ROSE: Every week."})
    build(show, mode="full", fresh=True)
    per_ep = [len(_flags(show, e)) for e in range(1, 6)]
    assert per_ep == [0, 1, 1, 0, 0]          # flagged twice, then the death itself is the suspect fact
    death = next(f for f in show.ledger().facts if f.attribute == "alive")
    assert death.disputed and death.challenges == 2


def test_possessive_is_not_the_dead_character_acting(cfg, tmp_path):
    show = _show_from_text(cfg, tmp_path, {
        1: "[00:01] The doctor covers Rose's face with the sheet.\n[00:02] COLE: No.",
        2: "[00:01] Rose's lawyer opens the will.\n[00:03] Rose walks in."})
    build(show, mode="full", fresh=True)
    assert [f["new"]["line_id"] for f in _flags(show, 2)] == ["E02L002"]


def test_same_line_same_rule_is_one_flag_with_all_priors(cfg, tmp_path):
    show = _show_from_text(cfg, tmp_path, {
        1: "[00:01] Harper Lane, 24, runs in.\n[00:02] HARPER: Hi.",
        2: "[00:01] Harper, 24, waits.",
        3: "[00:01] Harper, 32, sits down."})
    build(show, mode="full", fresh=True)
    flags = _flags(show, 3)
    assert len(flags) == 1 and flags[0]["rule"] == "stable_attribute_changed"
    assert {p["line_id"] for p in flags[0]["prior"]} == {"E01L001", "E02L001"}


def test_prompt_version_is_configurable(cfg, scripted):
    ep = parse_text("EPISODE 1\n[00:01] MAYA: Hi.", "e.txt")[0]
    from guard.characters import CharacterIndex
    from guard.extract import extract_episode

    seen = []
    llm = scripted(cfg, lambda p: (seen.append(p), '{"facts": []}')[1])
    cfg["extract"]["prompt"] = "extract_facts_v2"
    extract_episode(ep, CharacterIndex([]), llm, cfg)
    assert seen and seen[0].startswith("(v2)") and "flatline" in seen[0]
