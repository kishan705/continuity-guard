"""Build and check. Used by the CLI, the Streamlit app and the evaluation.

build: episodes 1..N in order. Each episode is checked against the ledger of
       the episodes before it, then its facts join the ledger. Facts on a
       flagged line join as disputed, so one error can't cause a chain of flags.
check: one new episode against the saved ledger. The ledger is unchanged
       unless commit=True.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from .bible import write_bible
from .characters import CharacterIndex, propose_characters
from .embed import get_embedder
from .extract import extract_episode
from .judge import check_candidates
from .ledger import Ledger
from .llm import get_llm, set_context
from .parse import load_episodes, parse_path, parse_report, parse_text, save_episodes
from .report import load_reports, write_episode_report, write_html
from .rules import run_rules
from .schemas import Episode, Fact, Flag


class Show:
    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, cfg
        p = cfg["paths"]
        self.processed = Path(p["processed"]) / name
        self.store = Path(p["store"]) / name
        self.out = Path(p["outputs"]) / name
        self.chars_path = self.store / "characters.yaml"
        self.facts_dir = self.store / "facts"
        self.log_path = self.out / "run_log.jsonl"

    def episodes(self) -> list[Episode]:
        return load_episodes(self.processed)

    def ledger(self, fresh: bool = False) -> Ledger:
        emb = get_embedder(self.cfg)
        backend = self.cfg.get("vector_store", "auto")
        if fresh:
            return Ledger(self.store, emb, backend)
        return Ledger.load(self.store, emb, backend)

    def characters(self, episodes: Optional[list[Episode]] = None, refresh: bool = False) -> CharacterIndex:
        if self.chars_path.exists() and not refresh:
            return CharacterIndex.load(self.chars_path)
        episodes = episodes if episodes is not None else self.episodes()
        idx = propose_characters(episodes, get_llm(self.cfg, "extract"))
        idx.save(self.chars_path)
        return idx


def _mode(cfg: dict, mode: Optional[str]) -> str:
    return mode or cfg.get("check", {}).get("mode", "full")


def parse_show(input_path: str | Path, show: Show) -> tuple[list[Episode], dict]:
    eps = parse_path(input_path)
    save_episodes(eps, show.processed)
    rep = parse_report(eps)
    show.out.mkdir(parents=True, exist_ok=True)
    (show.out / "parse_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return eps, rep


def process_episode(ep: Episode, show: Show, chars: CharacterIndex, ledger: Ledger, by_num: dict[int, Episode],
                    mode: str, llms: tuple) -> tuple[list[Fact], list[Flag], dict]:
    llm_x, llm_j, llm_v = llms
    t0 = time.time()
    set_context(episode=ep.episode)
    facts, xstats = extract_episode(ep, chars, llm_x, show.cfg)
    cands = run_rules(ep, facts, ledger, chars, show.cfg)
    flags, cstats = check_candidates(cands, by_num, llm_j, llm_v, show.cfg, mode)
    flagged_lines = {f.new.line_id for f in flags}
    for f in facts:
        if f.line_id in flagged_lines:
            f.disputed = True
    stats = {"episode": ep.episode, "facts": len(facts), **{f"extract_{k}": v for k, v in xstats.items()},
             **cstats, "flags": len(flags), "seconds": round(time.time() - t0, 2)}
    return facts, flags, stats


def challenge_priors(ledger: Ledger, flags: list[Flag], threshold: int = 2) -> list[str]:
    """Stop chain reactions. Each episode that is flagged against an earlier fact counts one
    challenge; at `threshold` challenges from different episodes the earlier fact is marked
    disputed, so it stops producing new flags (e.g. a flatline wrongly read as a death would
    otherwise flag every later scene with that character). Returns the ids it disputed."""
    cited = {fid for f in flags for fid in f.prior_fact_ids}
    newly = []
    for fact in ledger.facts:
        if fact.fact_id in cited and not fact.disputed:
            fact.challenges += 1
            if fact.challenges >= threshold:
                fact.disputed = True
                newly.append(fact.fact_id)
    return newly


def build(show: Show, mode: Optional[str] = None, fresh: bool = False, only: Optional[set[int]] = None,
          progress: Optional[Callable[[int, int, dict], None]] = None, llms: Optional[tuple] = None) -> dict:
    mode = _mode(show.cfg, mode)
    episodes = show.episodes()
    if not episodes:
        raise RuntimeError(f"no parsed episodes for show '{show.name}'. Run `python cli.py parse` first.")
    by_num = {e.episode: e for e in episodes}
    chars = show.characters(episodes)
    ledger = show.ledger(fresh=fresh)
    llms = llms or (get_llm(show.cfg, "extract"), get_llm(show.cfg, "judge"), get_llm(show.cfg, "verify"))
    run_id = f"build-{mode}-{time.strftime('%Y%m%d-%H%M%S')}"
    set_context(run=run_id, show=show.name, log_path=str(show.log_path))
    reports_dir = show.out / "reports"
    show.facts_dir.mkdir(parents=True, exist_ok=True)
    todo = [e for e in episodes if only is None or e.episode in only]
    rows = []
    for i, ep in enumerate(todo, 1):
        ledger.remove_episode(ep.episode)                 # rerunnable
        facts, flags, stats = process_episode(ep, show, chars, ledger, by_num, mode, llms)
        stats["priors_disputed"] = len(challenge_priors(
            ledger, flags, int(show.cfg.get("check", {}).get("dispute_after_challenges", 2))))
        ledger.add_facts(facts)
        ledger.save()
        (show.facts_dir / f"ep_{ep.episode:02d}.json").write_text(
            json.dumps([f.model_dump() for f in facts], indent=1, ensure_ascii=False), encoding="utf-8")
        write_episode_report(reports_dir, ep.episode, flags, stats)
        rows.append(stats)
        if progress:
            progress(i, len(todo), stats)
    write_html(show.out / "report.html", show.name, load_reports(reports_dir))
    write_bible(ledger, chars, show.out / "story_bible.md")
    summary = {"show": show.name, "run": run_id, "mode": mode, "model": llms[1].name,
               "embedder": ledger.embedder.name, "vector_store": ledger.backend, "episodes": len(rows),
               "facts": sum(r["facts"] for r in rows), "flags": sum(r["flags"] for r in rows), "per_episode": rows}
    (show.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def check_episode(show: Show, ep: Episode, mode: Optional[str] = None, commit: bool = False,
                  ledger: Optional[Ledger] = None, report_dir: Optional[Path] = None,
                  extra_episodes: Optional[dict[int, Episode]] = None,
                  run: Optional[str] = None, llms: Optional[tuple] = None) -> tuple[list[Flag], dict]:
    mode = _mode(show.cfg, mode)
    ledger = ledger or show.ledger()
    chars = show.characters()
    by_num = {e.episode: e for e in show.episodes()}
    if extra_episodes:
        by_num.update(extra_episodes)
    by_num[ep.episode] = ep
    llms = llms or (get_llm(show.cfg, "extract"), get_llm(show.cfg, "judge"), get_llm(show.cfg, "verify"))
    set_context(run=run or f"check-{mode}", show=show.name, log_path=str(show.log_path))
    facts, flags, stats = process_episode(ep, show, chars, ledger, by_num, mode, llms)
    if commit:
        challenge_priors(ledger, flags, int(show.cfg.get("check", {}).get("dispute_after_challenges", 2)))
        ledger.remove_episode(ep.episode)
        ledger.add_facts(facts)
        ledger.save()
        save_episodes([ep], show.processed)
    write_episode_report(report_dir or show.out / "checks", ep.episode, flags, stats)
    return flags, stats


def check_file(show: Show, path: str | Path, mode: Optional[str] = None, commit: bool = False):
    results = []
    for ep in parse_path(path):
        results.append((ep, *check_episode(show, ep, mode, commit)))
    return results


def check_text(show: Show, text: str, filename: str = "new_episode.txt", mode: Optional[str] = None,
               commit: bool = False):
    from .parse import episode_number_from_name

    results = []
    known = show.episodes()
    default = episode_number_from_name(Path(filename).stem) or ((known[-1].episode + 1) if known else 1)
    for ep in parse_text(text, filename, default):
        results.append((ep, *check_episode(show, ep, mode, commit)))
    return results
