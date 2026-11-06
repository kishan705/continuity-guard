import importlib.util
import json

from guard.pipeline import Show, build, check_text, parse_show

from conftest import DEMO, ROOT


def _demo(cfg):
    show = Show("demo", cfg)
    parse_show(DEMO, show)
    show.characters(refresh=True)
    return show


def test_offline_demo_build_finds_the_three_rule_errors(cfg):
    show = _demo(cfg)
    summary = build(show, mode="full", fresh=True)
    assert [r["flags"] for r in summary["per_episode"]] == [0, 0, 3]
    ep3 = json.loads((show.out / "reports" / "ep_03.json").read_text())
    got = {(f["rule"], f["new"]["line_id"], f["prior"][0]["line_id"]) for f in ep3["flags"]}
    assert got == {("dead_character_active", "E03L003", "E02L013"),
                   ("stable_attribute_changed", "E03L007", "E01L002"),
                   ("secret_before_learned", "E03L009", "E02L016")}
    assert (show.out / "report.html").exists() and (show.out / "story_bible.md").exists()


def test_rebuild_is_idempotent_and_flagged_facts_are_disputed(cfg):
    show = _demo(cfg)
    build(show, fresh=True)
    n = len(show.ledger().facts)
    build(show)                                   # same episodes again
    led = show.ledger()
    assert len(led.facts) == n
    assert any(f.disputed and f.attribute == "age" and f.value == "29" for f in led.facts)


def test_check_new_episode_and_commit(cfg):
    show = _demo(cfg)
    build(show, fresh=True)
    text = ("EPISODE 4\n[00:00] INT. LOBBY - DAY\n[00:02] Victor Hale, Ethan's brother, blocks the door.\n"
            "[00:06] MAYA: I'm 26 and I'm not scared of you.\n[00:09] Rose walks in and slaps Victor.")
    (ep, flags, stats), = check_text(show, text, "ep_04.txt")
    assert ep.episode == 4
    assert sorted(f.rule for f in flags) == ["dead_character_active", "relationship_changed"]
    assert 4 not in show.ledger().episodes()
    check_text(show, text, "ep_04.txt", commit=True)
    assert 4 in show.ledger().episodes()


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_and_eval_offline(cfg, monkeypatch):
    show = _demo(cfg)
    build(show, fresh=True)
    seed = _load_script("seed_errors")
    monkeypatch.setattr(seed, "load_config", lambda: cfg)
    seed.main(["--show", "demo", "--episodes", "2-3", "--per-type", "2"])
    key = json.loads((show.out / "eval" / "answer_key.json").read_text())
    assert {k["type"] for k in key} >= {"identity", "relationship", "knowledge", "physical"}
    ev = _load_script("run_eval")
    monkeypatch.setattr(ev, "load_config", lambda: cfg)
    ev.main(["--show", "demo", "--modes", "rules"])
    res = json.loads((show.out / "eval" / "eval_results.json").read_text())["rules"]
    pt = res["per_type"]
    assert pt["identity"]["caught"] == pt["identity"]["planted"]
    assert pt["knowledge"]["caught"] == pt["knowledge"]["planted"]
    assert pt["physical"]["caught"] == 0              # the regex baseline can't see this; the AI path can
    assert (show.out / "labels_natural.csv").exists()


def test_labels_sheet_round_trip_with_excel_encodings(cfg, capsys):
    import csv
    import sys
    sys.path.insert(0, str(ROOT))
    import cli
    from guard.report import read_csv_rows

    show = _demo(cfg)
    build(show, fresh=True)
    args = type("A", (), {"show": "demo"})()
    cli.cmd_labels(args, cfg)
    path = show.out / "labels_natural.csv"
    rows = read_csv_rows(path)
    assert len(rows) == 3 and all(r["label"] == "" for r in rows)
    # simulate Excel "CSV (Comma delimited)" = cp1252, no BOM, with two labels filled in
    rows[0]["label"], rows[1]["label"] = "true_error", "false_alarm"
    with open(path, "w", newline="", encoding="cp1252") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    capsys.readouterr()
    cli.cmd_labels(args, cfg)
    out = capsys.readouterr().out
    assert "labeled 2/3" in out and "1/2 = 50%" in out
    assert [r["label"] for r in read_csv_rows(path)][:2] == ["true_error", "false_alarm"]   # labels kept
