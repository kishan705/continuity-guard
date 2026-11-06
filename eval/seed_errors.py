"""Plant known continuity errors in copies of clean episodes and write an answer key.

  python eval/seed_errors.py --show show1 --episodes 31-40 --per-type 5
  python eval/seed_errors.py --show show1 --episodes 31-40 --manual eval/manual_seeds.json

Run a clean `build` first: seeds are generated from real facts in the ledger,
so every planted line contradicts a specific earlier line of the show.
Auto types: identity, relationship, status, knowledge, physical.
Timeline errors are hard to generate well, so plant them by hand in
manual_seeds.json (see manual_seeds.example.json). Hand-written seeds are
also more realistic: aim for about a third of the total.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guard.llm import load_config  # noqa: E402
from guard.parse import save_episodes  # noqa: E402
from guard.pipeline import Show  # noqa: E402
from guard.rules import norm_value  # noqa: E402
from guard.schemas import Episode, Line  # noqa: E402

SWAP = {"sister": "cousin", "brother": "cousin", "cousin": "brother", "mother": "aunt", "father": "uncle",
        "aunt": "mother", "uncle": "father", "husband": "brother", "wife": "sister", "son": "nephew",
        "daughter": "niece", "grandmother": "aunt", "grandfather": "uncle", "boss": "intern",
        "assistant": "boss", "fiance": "brother", "fiancee": "sister", "girlfriend": "sister",
        "boyfriend": "brother", "friend": "enemy", "enemy": "friend"}
EXPECTED = {"identity": "stable_attribute_changed", "relationship": "relationship_changed",
            "status": "dead_character_active", "knowledge": "secret_before_learned", "physical": "similar_fact",
            "timeline": "similar_fact"}


def parse_range(text: str) -> list[int]:
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    return out


def speaker_tag(cid: str, episodes: list[Episode], chars) -> str | None:
    for ep in episodes:
        for ln in ep.all_lines():
            if ln.speaker and chars.canonical(ln.speaker) == cid:
                return ln.speaker
    return None


def insert_line(ep: Episode, rng: random.Random, kind: str, text: str, speaker: str | None,
                n: int, after_line_id: str | None = None) -> Line:
    lines = [l for l in ep.all_lines() if l.kind != "heading"]
    if after_line_id:
        anchor = ep.line(after_line_id)
    else:
        mid = lines[len(lines) // 4: max(len(lines) // 4 + 1, 3 * len(lines) // 4)] or lines
        anchor = rng.choice(mid)
    scene = ep.scene_of(anchor.line_id)
    new = Line(line_id=f"{anchor.line_id}_S{n}", ts=anchor.ts, ts_sec=anchor.ts_sec, kind=kind,
               speaker=speaker, text=text)
    scene.lines.insert(scene.lines.index(anchor) + 1, new)
    return new


def _already_active(ep: Episode, cid: str, chars) -> bool:
    return any(ln.speaker and chars.canonical(ln.speaker) == cid for ln in ep.all_lines())


def auto_seed(kind: str, target: int, ledger, chars, episodes, rng):
    """Returns (line kind, text, speaker, contradicted facts) or None."""
    prior = [f for f in ledger.prior(target) if not f.disputed]
    display = chars.display
    if kind == "identity":
        pool = [f for f in prior if f.attribute == "age" and norm_value(f.value).isdigit()]
        if not pool:
            return None
        f = rng.choice(pool)
        age = int(norm_value(f.value)) + rng.choice([3, 4, 5, -3, -4])
        tag = speaker_tag(f.entity, episodes, chars)
        if tag:
            return "dialogue", f"I'm {age}, and I know exactly what I'm doing.", tag, [f]
        return "action", f"{display(f.entity)}, {age}, waits by the door.", None, [f]
    if kind == "relationship":
        pool = [f for f in prior if f.attribute.startswith("relationship_to:") and norm_value(f.value) in SWAP]
        if not pool:
            return None
        f = rng.choice(pool)
        other = f.attribute.split(":", 1)[1]
        return ("action", f"{display(f.entity)}, {display(other)}'s {SWAP[norm_value(f.value)]}, walks in.",
                None, [f])
    if kind == "status":
        pool = [f for f in prior if f.attribute == "alive" and norm_value(f.value) == "false" and f.mode == "stated"]
        if not pool:
            return None
        f = rng.choice(pool)
        tag = speaker_tag(f.entity, episodes, chars)
        if tag:
            return "dialogue", "I'm not finished with this family yet.", tag, [f]
        return "action", f"{display(f.entity)} walks into the room and sits down.", None, [f]
    if kind == "knowledge":
        learns = [f for f in prior if f.attribute == "learns"]
        rng.shuffle(learns)
        for f in learns:
            knowers = {g.entity for g in prior if g.attribute == "learns" and ledger.similarity(g.value, f.value) > 0.6}
            others = [c["id"] for c in chars.characters if c["id"] not in knowers
                      and speaker_tag(c["id"], episodes, chars)]
            if others:
                who = rng.choice(others)
                secret = f.value.rstrip(".")
                return "dialogue", f"I know that {secret[0].lower() + secret[1:]}.", speaker_tag(who, episodes, chars), [f]
        return None
    if kind == "physical":
        pool = [f for f in prior if f.attribute == "injury" and f.episode >= target - 1]
        if not pool:
            return None
        f = rng.choice(pool)
        return "action", f"{display(f.entity)} lifts a heavy box with both arms and carries it outside.", None, [f]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", required=True)
    ap.add_argument("--episodes", required=True, help="target episodes, e.g. 31-40")
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--types", default="identity,relationship,status,knowledge,physical")
    ap.add_argument("--manual", default=None, help="JSON list of hand-written seeds")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    cfg = load_config()
    show = Show(args.show, cfg)
    episodes = show.episodes()
    by_num = {e.episode: e for e in episodes}
    ledger, chars = show.ledger(), show.characters()
    if not ledger.facts:
        sys.exit("ledger is empty: run `python cli.py build --show ...` on the clean episodes first")
    rng = random.Random(args.seed)
    targets = [t for t in parse_range(args.episodes) if t in by_num]
    seeded: dict[int, Episode] = {t: by_num[t].model_copy(deep=True) for t in targets}
    key, counter = [], 0

    for kind in [k.strip() for k in args.types.split(",") if k.strip()]:
        made, tries = 0, 0
        while made < args.per_type and tries < args.per_type * 10:
            tries += 1
            target = targets[(made + tries) % len(targets)]
            res = auto_seed(kind, target, ledger, chars, episodes, rng)
            if not res:
                continue
            line_kind, text, speaker, facts = res
            if kind == "status" and _already_active(seeded[target], facts[0].entity, chars):
                continue                                    # the episode already has this error naturally
            counter += 1
            line = insert_line(seeded[target], rng, line_kind, text, speaker, counter)
            key.append({"seed_id": f"S{counter:02d}", "episode": target, "line_id": line.line_id, "type": kind,
                        "expected_rule": EXPECTED[kind], "kind": line_kind, "speaker": speaker, "text": text,
                        "contradicts": [{"episode": f.episode, "line_id": f.line_id, "quote": f.quote} for f in facts],
                        "source": "auto", "ai_only": kind in ("physical",)})
            made += 1
        print(f"{kind:<13} planted {made}/{args.per_type}" + ("" if made == args.per_type else
                                                               "  (not enough usable source facts in the ledger)"))

    if args.manual:
        for m in json.loads(Path(args.manual).read_text(encoding="utf-8")):
            t = int(m["episode"])
            if t not in seeded:
                seeded[t] = by_num[t].model_copy(deep=True)
            counter += 1
            line = insert_line(seeded[t], rng, m.get("kind", "action"), m["text"], m.get("speaker"), counter,
                               after_line_id=m.get("after_line_id"))
            key.append({"seed_id": f"S{counter:02d}", "episode": t, "line_id": line.line_id, "type": m["type"],
                        "expected_rule": EXPECTED.get(m["type"], "similar_fact"), "kind": m.get("kind", "action"),
                        "speaker": m.get("speaker"), "text": m["text"],
                        "contradicts": [{"episode": int(c.split("L")[0][1:]), "line_id": c}
                                        for c in m.get("contradicts", [])],
                        "source": "manual", "ai_only": m.get("ai_only", False), "note": m.get("note", "")})
        print(f"manual        planted {sum(1 for k in key if k['source'] == 'manual')}")

    seeded_dir = show.processed.parent / f"{show.name}__seeded"
    save_episodes(list(seeded.values()), seeded_dir)
    out = show.out / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "answer_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(key)} seeds in {len(seeded)} episodes -> {seeded_dir}\nanswer key -> {out / 'answer_key.json'}")


if __name__ == "__main__":
    main()
