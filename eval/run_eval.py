"""Score the checker: recall on planted errors, precision from your labels, cost.

  python eval/run_eval.py --show show1                      # all three modes
  python eval/run_eval.py --show show1 --modes full
  LLM_MODEL=<other model> python eval/run_eval.py --show show1 --tag modelB

For every mode it checks (a) the seeded episodes -> recall per error type and
(b) the same episodes unseeded -> flags you label in labels_natural.csv as
true_error / intended_twist / false_alarm -> precision. Label a flag once; the
label is reused for every mode and model that raises the same flag.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guard.llm import load_config  # noqa: E402
from guard.parse import load_episodes  # noqa: E402
from guard.pipeline import Show, check_episode  # noqa: E402
from guard.report import LABELS, read_csv_rows, write_csv_rows  # noqa: E402


def _caught(seed: dict, flags: list, episode) -> tuple[bool, bool]:
    ids = [l.line_id for l in episode.all_lines()]
    idx = ids.index(seed["line_id"]) if seed["line_id"] in ids else -1
    near = set(ids[max(0, idx - 1): idx + 2]) if idx >= 0 else {seed["line_id"]}
    want_prior = {c["line_id"] for c in seed.get("contradicts", [])}
    hit = [f for f in flags if f.new.line_id == seed["line_id"]
           or (f.new.line_id in near and f.type == seed["type"])]
    right = any(want_prior & {p.line_id for p in f.prior} for f in hit) if want_prior else bool(hit)
    return bool(hit), right


def _label_key(f) -> str:
    return f"{f.new.episode}|{f.new.line_id}|{f.rule}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", required=True)
    ap.add_argument("--modes", default="rules,judge,full")
    ap.add_argument("--tag", default="", help="name for this run in the results table, e.g. modelB")
    ap.add_argument("--provider", default=None, help="override llm.provider (works on Windows too)")
    ap.add_argument("--model", default=None, help="override llm.model")
    args = ap.parse_args(argv)
    import os

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    cfg = load_config()
    show = Show(args.show, cfg)
    out = show.out / "eval"
    key_path = out / "answer_key.json"
    if not key_path.exists():
        sys.exit("no answer key: run eval/seed_errors.py first")
    seeds = json.loads(key_path.read_text(encoding="utf-8"))
    seeded = {e.episode: e for e in load_episodes(show.processed.parent / f"{show.name}__seeded")}
    clean = {e.episode: e for e in show.episodes()}
    ledger = show.ledger()
    labels_path = show.out / "labels_natural.csv"
    labels: dict[str, str] = {}
    if labels_path.exists():
        for row in read_csv_rows(labels_path):
            if row.get("label", "") in LABELS and row.get("key"):
                labels[row["key"]] = row["label"]

    results, to_label = [], {}
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        name = f"{mode}{'-' + args.tag if args.tag else ''}"
        rdir = out / name
        # (a) seeded episodes -> recall
        per_type = defaultdict(lambda: {"planted": 0, "caught": 0, "caught_right_prior": 0})
        missed, secs_seeded = [], 0.0
        flags_by_ep = {}
        for ep_no, ep in sorted(seeded.items()):
            flags, stats = check_episode(show, ep, mode=mode, ledger=ledger, report_dir=rdir / "seeded",
                                         run=f"eval-{name}")
            flags_by_ep[ep_no] = flags
            secs_seeded += stats["seconds"]
        for s in seeds:
            t = per_type[s["type"]]
            t["planted"] += 1
            hit, right = _caught(s, flags_by_ep.get(s["episode"], []), seeded[s["episode"]])
            t["caught"] += hit
            t["caught_right_prior"] += right
            if not hit:
                missed.append({"seed_id": s["seed_id"], "type": s["type"], "episode": s["episode"], "text": s["text"]})
        # (b) the same episodes unseeded -> precision (needs your labels)
        n_flags, secs_clean, lab = 0, 0.0, defaultdict(int)
        for ep_no in sorted(seeded):
            flags, stats = check_episode(show, clean[ep_no], mode=mode, ledger=ledger, report_dir=rdir / "clean",
                                         run=f"eval-{name}")
            n_flags += len(flags)
            secs_clean += stats["seconds"]
            for f in flags:
                k = _label_key(f)
                to_label.setdefault(k, {"key": k, "episode": f.new.episode, "ts": f.new.ts, "rule": f.rule,
                                        "new_quote": f.new.quote,
                                        "earlier_quote": " || ".join(p.quote for p in f.prior),
                                        "explanation": f.explanation, "label": labels.get(k, "")})
                lab[labels.get(k, "unlabeled")] += 1
        labeled = sum(v for k, v in lab.items() if k != "unlabeled")
        planted = sum(t["planted"] for t in per_type.values())
        caught = sum(t["caught"] for t in per_type.values())
        tokens = _tokens(show, f"eval-{name}")
        results.append({
            "setup": name, "recall": round(caught / planted, 3) if planted else None,
            "caught": caught, "planted": planted, "per_type": dict(per_type),
            "precision": round(lab["true_error"] / labeled, 3) if labeled else None,
            "labels": dict(lab), "flags_per_episode_clean": round(n_flags / max(1, len(seeded)), 2),
            "seconds_per_episode": round((secs_seeded + secs_clean) / max(1, 2 * len(seeded)), 2),
            "tokens_logged_for_mode": tokens, "missed": missed})
        print(f"{name:<14} recall {caught}/{planted}  flags/ep {results[-1]['flags_per_episode_clean']}  "
              f"precision {results[-1]['precision'] if labeled else 'needs labels'}")

    # label sheet: keep existing labels, add new rows
    rows = list(to_label.values())
    if labels_path.exists():
        old = {r["key"]: r for r in read_csv_rows(labels_path) if r.get("key")}
        for r in rows:
            old.setdefault(r["key"], r)
        rows = list(old.values())
    write_csv_rows(labels_path, rows)

    prev = out / "eval_results.json"
    allres = json.loads(prev.read_text()) if prev.exists() else {}
    allres.update({r["setup"]: r for r in results})
    prev.write_text(json.dumps(allres, indent=1), encoding="utf-8")
    (out / "eval_results.md").write_text(_table(allres), encoding="utf-8")
    print(f"\nresults -> {prev}\ntable   -> {out / 'eval_results.md'}\nlabel the flags in {labels_path} "
          f"(label = {' / '.join(LABELS)}), then rerun to get precision")


def _tokens(show: Show, run: str) -> int:
    if not show.log_path.exists():
        return 0
    total = 0
    for line in show.log_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("run") == run:
            total += r.get("input_tokens", 0) + r.get("output_tokens", 0)
    return total


def _table(allres: dict) -> str:
    types = sorted({t for r in allres.values() for t in r["per_type"]})
    head = "| Setup | Recall | " + " | ".join(t.title() for t in types) + \
           " | Precision | Flags / ep | Sec / ep |\n|" + " --- |" * (len(types) + 5)
    rows = [head]
    for r in allres.values():
        pt = " | ".join(f"{r['per_type'].get(t, {}).get('caught', 0)}/{r['per_type'].get(t, {}).get('planted', 0)}"
                        for t in types)
        prec = "needs labels" if r["precision"] is None else f"{r['precision']:.0%}"
        rec = "-" if r["recall"] is None else f"{r['recall']:.0%}"
        rows.append(f"| {r['setup']} | {rec} | {pt} | {prec} | {r['flags_per_episode_clean']} | "
                    f"{r['seconds_per_episode']} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    main()
