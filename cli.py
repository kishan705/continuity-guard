"""Continuity Guard command line.

  python cli.py parse      --input data/raw --show show1
  python cli.py characters --show show1 [--refresh]
  python cli.py build      --show show1 [--mode full|judge|rules] [--fresh] [--episodes 1-10]
  python cli.py check      --show show1 --episode data/raw/ep_51.txt [--commit]
  python cli.py bible      --show show1
  python cli.py stats      --show show1
  python cli.py labels     --show show1         # label sheet for the build's flags (+ precision once filled)
  python cli.py demo                      # offline run on the made-up demo show

Global: --provider / --model override config.yaml for this run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from guard.bible import write_bible  # noqa: E402
from guard.llm import load_config  # noqa: E402
from guard.pipeline import Show, build, check_file, parse_show  # noqa: E402


def parse_range(text: str | None) -> set[int] | None:
    if not text:
        return None
    out: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def print_flags(flags) -> None:
    if not flags:
        print("  no continuity problems found")
    for f in flags:
        print(f"  [{f.severity.upper()}] {f.flag_id} {f.type} ({f.rule})")
        print(f"     NEW     ep {f.new.episode} {f.new.ts}: {f.new.quote}")
        for p in f.prior:
            print(f"     EARLIER ep {p.episode} {p.ts}: {p.quote}")
        print(f"     WHY     {f.explanation}")
        if f.suggested_fix:
            print(f"     FIX     {f.suggested_fix}")


def cmd_parse(args, cfg):
    show = Show(args.show, cfg)
    eps, rep = parse_show(args.input, show)
    print(f"parsed {len(eps)} episodes -> {show.processed}")
    for r in rep["episodes"]:
        print(f"  ep {r['episode']:>3}: {r['scenes']} scenes, {r['lines']} lines, {r['dialogue']} dialogue, "
              f"{r['no_timestamp']} without timestamp")
    for w in rep["warnings"]:
        print("  WARNING", w)


def cmd_characters(args, cfg):
    show = Show(args.show, cfg)
    idx = show.characters(refresh=args.refresh)
    print(f"{len(idx.characters)} characters -> {show.chars_path}  (edit this file, then rerun build)")
    print(idx.prompt_text())


def cmd_build(args, cfg):
    show = Show(args.show, cfg)

    def progress(i, n, s):
        print(f"  [{i}/{n}] ep {s['episode']}: {s['facts']} facts, {s['candidates']} candidates, "
              f"{s['flags']} flags ({s['seconds']}s)")

    summary = build(show, mode=args.mode, fresh=args.fresh, only=parse_range(args.episodes), progress=progress)
    print(f"done: {summary['episodes']} episodes, {summary['facts']} facts, {summary['flags']} flags "
          f"(mode {summary['mode']}, model {summary['model']}, embedder {summary['embedder']}, "
          f"store {summary['vector_store']})")
    print(f"reports -> {show.out / 'reports'}\nhtml    -> {show.out / 'report.html'}\n"
          f"bible   -> {show.out / 'story_bible.md'}")


def cmd_check(args, cfg):
    show = Show(args.show, cfg)
    for ep, flags, stats in check_file(show, args.episode, mode=args.mode, commit=args.commit):
        print(f"episode {ep.episode}: {stats['facts']} facts, {stats['candidates']} candidates, {len(flags)} flags")
        print_flags(flags)
    print(f"report -> {show.out / 'checks'}" + ("  (ledger updated)" if args.commit else ""))


def cmd_bible(args, cfg):
    show = Show(args.show, cfg)
    path = write_bible(show.ledger(), show.characters(), show.out / "story_bible.md")
    print(f"bible -> {path}")


def cmd_stats(args, cfg):
    show = Show(args.show, cfg)
    if not show.log_path.exists():
        print("no run log yet")
        return
    runs = defaultdict(lambda: defaultdict(lambda: {"calls": 0, "cached": 0, "in": 0, "out": 0, "sec": 0.0,
                                                    "episodes": set()}))
    for line in show.log_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        s = runs[r.get("run")][r.get("stage")]
        s["calls"] += 1
        s["cached"] += int(bool(r.get("cached")))
        s["in"] += r.get("input_tokens", 0)
        s["out"] += r.get("output_tokens", 0)
        s["sec"] += r.get("seconds", 0)
        s["episodes"].add(r.get("episode"))
    for run, stages in runs.items():
        eps = set().union(*(s["episodes"] for s in stages.values())) - {None}
        tot_in = sum(s["in"] for s in stages.values())
        tot_out = sum(s["out"] for s in stages.values())
        print(f"{run}: {len(eps)} episodes, {tot_in + tot_out} tokens "
              f"({(tot_in + tot_out) / max(1, len(eps)):.0f} per episode)")
        for stage, s in stages.items():
            print(f"   {stage:<16} calls {s['calls']:>4} (cached {s['cached']}), in {s['in']}, out {s['out']}, "
                  f"{s['sec']:.0f}s")


def cmd_labels(args, cfg):
    from guard.report import LABELS, label_row, load_reports, read_csv_rows, write_csv_rows

    show = Show(args.show, cfg)
    path = show.out / "labels_natural.csv"
    old = {r["key"]: r for r in read_csv_rows(path) if r.get("key")} if path.exists() else {}
    rows, seen = [], set()
    for rep in load_reports(show.out / "reports"):
        for f in rep["flags"]:
            r = label_row(f, old.get(label_row(f)["key"], {}).get("label", ""))
            rows.append(r)
            seen.add(r["key"])
    rows += [r for k, r in old.items() if k not in seen]       # keep labels added by run_eval
    write_csv_rows(path, rows)
    build_rows = [r for r in rows if r["key"] in seen]
    done = [r for r in build_rows if r["label"] in LABELS]
    print(f"{len(build_rows)} flags from the build -> {path}")
    print(f"labeled {len(done)}/{len(build_rows)}. Fill the 'label' column with: {' / '.join(LABELS)}")
    if done:
        n = {k: sum(r["label"] == k for r in done) for k in LABELS}
        print(f"precision (true_error / labeled): {n['true_error']}/{len(done)} = {n['true_error'] / len(done):.0%}"
              f"   intended_twist {n['intended_twist']}, false_alarm {n['false_alarm']}")
        by_rule: dict[str, list] = {}
        for r in done:
            by_rule.setdefault(r["rule"], []).append(r["label"] == "true_error")
        for rule, v in sorted(by_rule.items()):
            print(f"   {rule:<26} {sum(v)}/{len(v)} true")


def cmd_demo(args, cfg):
    cfg["llm"]["provider"] = "offline"
    show = Show("demo", cfg)
    parse_show(ROOT / "tests" / "fixtures" / "demo_show", show)
    show.characters(refresh=True)
    summary = build(show, mode="full", fresh=True)
    for row in summary["per_episode"]:
        print(f"ep {row['episode']}: {row['facts']} facts, {row['flags']} flags")
    report = json.loads((show.out / "reports" / "ep_03.json").read_text())
    from guard.schemas import Flag

    print_flags([Flag.model_validate(f) for f in report["flags"]])
    print(f"\nOpen {show.out / 'report.html'} in a browser. Expected answers: tests/fixtures/DEMO_ANSWERS.md")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Continuity Guard")
    ap.add_argument("--config", default=None)
    ap.add_argument("--provider", default=None, help="override llm.provider for this run")
    ap.add_argument("--model", default=None, help="override llm.model for this run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse"); p.add_argument("--input", required=True); p.add_argument("--show", required=True)
    p = sub.add_parser("characters"); p.add_argument("--show", required=True); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("build"); p.add_argument("--show", required=True)
    p.add_argument("--mode", choices=["rules", "judge", "full"]); p.add_argument("--fresh", action="store_true")
    p.add_argument("--episodes", help="e.g. 1-10 or 3,5,7")
    p = sub.add_parser("check"); p.add_argument("--show", required=True); p.add_argument("--episode", required=True)
    p.add_argument("--mode", choices=["rules", "judge", "full"]); p.add_argument("--commit", action="store_true")
    p = sub.add_parser("bible"); p.add_argument("--show", required=True)
    p = sub.add_parser("stats"); p.add_argument("--show", required=True)
    p = sub.add_parser("labels"); p.add_argument("--show", required=True)
    sub.add_parser("demo")

    args = ap.parse_args(argv)
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    cfg = load_config(args.config)
    {"parse": cmd_parse, "characters": cmd_characters, "build": cmd_build, "check": cmd_check,
     "bible": cmd_bible, "stats": cmd_stats, "labels": cmd_labels, "demo": cmd_demo}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
