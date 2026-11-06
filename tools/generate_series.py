"""Generate a test microdrama series the way an AI writing pipeline would.

  python tools/generate_series.py --show gen1 --episodes 30 --memory 3
  python tools/generate_series.py --show gen1_mem1 --episodes 30 --memory 1     # shorter memory, more drift?

The writer model sees the series bible plus summaries of only the last
`--memory` episodes, like a production pipeline with a limited context.
It is never told to make mistakes. Any contradictions it introduces are
natural AI-writer drift, which is exactly what Continuity Guard should catch.

Output: data/generated/<show>/ep_01.txt ... plus writer_log.yaml. This is
your own content, so unlike Kuku's pack it can go in the repo.
Then:  python cli.py parse --input data/generated/<show> --show <show>
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guard.llm import LLM, load_config, render, set_context  # noqa: E402
from guard.parse import parse_text  # noqa: E402


def bible_text(p: dict) -> str:
    rows = [f"Title: {p['title']}", f"Logline: {p['logline'].strip()}", f"Setting: {p['setting']}", "Characters:"]
    for c in p["characters"]:
        rows.append(f"- {c['name']}, {c['age']}, {c['job']}. {c['relationships']}. Secret: {c['secret']}")
    if p.get("rules"):
        rows.append("Rules for the season:")
        rows += [f"- {r}" for r in p["rules"]]
    return "\n".join(rows)


def beat_for(p: dict, ep: int) -> str:
    for b in p.get("beats", []):
        if b["from"] <= ep <= b["to"]:
            return b["beat"]
    return "Escalate the main conflict and end on a cliffhanger."


def clean(text: str, ep: int) -> str:
    text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if not lines:
        return f"EPISODE {ep}\n"
    if not re.match(r"^\s*episode\s*\d+", lines[0], re.I):
        lines.insert(0, f"EPISODE {ep}")
    else:
        lines[0] = re.sub(r"^\s*episode\s*\d+", f"EPISODE {ep}", lines[0], flags=re.I)
    return "\n".join(lines) + "\n"


def problems(text: str, ep: int) -> list[str]:
    try:
        eps = parse_text(text, f"ep_{ep:02d}.txt", ep)
    except Exception as exc:  # pragma: no cover
        return [f"could not parse: {exc}"]
    if len(eps) != 1:
        return [f"found {len(eps)} EPISODE headings, expected 1"]
    lines = eps[0].all_lines()
    out = []
    if len(lines) < 10:
        out.append(f"only {len(lines)} lines, need 14 to 24")
    if sum(l.kind == "dialogue" for l in lines) < 4:
        out.append("fewer than 4 dialogue lines in NAME: text form")
    if sum(l.ts is None or l.ts_inferred for l in lines) > 2:
        out.append("lines without a [MM:SS] timestamp")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", required=True)
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--memory", type=int, default=3, help="how many recent episode summaries the writer sees")
    ap.add_argument("--premise", default=str(ROOT / "tools" / "premise_example.yaml"))
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--start", type=int, default=1, help="resume from this episode")
    args = ap.parse_args(argv)

    import os

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    cfg = copy.deepcopy(load_config())
    cfg["llm"]["temperature"] = args.temperature
    writer = LLM(cfg, "writer")
    if writer.offline:
        sys.exit("the offline baseline cannot write episodes: set a real provider (e.g. --provider google_genai)")

    premise = yaml.safe_load(Path(args.premise).read_text(encoding="utf-8"))
    out_dir = ROOT / "data" / "generated" / args.show
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "writer_log.yaml"
    log = yaml.safe_load(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    log.update({"show": args.show, "model": writer.name, "memory": args.memory, "temperature": args.temperature,
                "premise": Path(args.premise).name})
    summaries: dict[int, str] = {int(k): v for k, v in (log.get("summaries") or {}).items()}
    set_context(run=f"generate-{args.show}", show=args.show,
                log_path=str(Path(cfg["paths"]["outputs"]) / args.show / "run_log.jsonl"))
    bible = bible_text(premise)

    print(f"writing {args.episodes - args.start + 1} episodes with {writer.name} "
          f"(about {60 / max(1, cfg['llm'].get('rpm_limit', 8)):.0f}s between requests to respect free-tier limits)",
          flush=True)
    for ep in range(args.start, args.episodes + 1):
        print(f"ep {ep:>2}: writing...", flush=True)
        set_context(episode=ep)
        seen = [e for e in sorted(summaries) if e < ep][-args.memory:] if args.memory > 0 else []
        recent = "\n".join(f"Episode {e}: {summaries[e]}" for e in seen) or "(this is the first episode)"
        prompt = render("write_episode", {"bible": bible, "recent": recent, "episode": str(ep),
                                          "total": str(args.episodes), "beat": beat_for(premise, ep)})
        text = clean(writer.complete(prompt, tag="write"), ep)
        issues = problems(text, ep)
        if issues:  # one repair attempt with the parser's complaints
            fix = prompt + "\n\nYour previous draft broke the format: " + "; ".join(issues) + \
                  ".\nWrite the whole episode again, following the format rules exactly."
            text = clean(writer.complete(fix, tag="write_repair"), ep)
            issues = problems(text, ep)
        (out_dir / f"ep_{ep:02d}.txt").write_text(text, encoding="utf-8")
        summary = writer.complete(render("summarize_episode", {"script": text}), tag="summarize").strip()
        summaries[ep] = re.sub(r"\s+", " ", summary)
        log["summaries"] = summaries
        log.setdefault("format_issues", {})[ep] = issues
        log_path.write_text(yaml.safe_dump(log, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"ep {ep:>2}: {len(text.splitlines())} lines" + (f"  (format issues: {issues})" if issues else "")
              + f"  writer saw episodes {seen or '-'}")
    print(f"\n{args.episodes} episodes -> {out_dir}\nnext: python cli.py parse --input {out_dir} --show {args.show}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"({time.time() - t0:.0f}s)")
