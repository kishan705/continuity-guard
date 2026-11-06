"""Ledger -> story_bible.md: every character's facts in story order, with citations."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .characters import CharacterIndex
from .ledger import Ledger

TYPE_ORDER = ["identity", "relationship", "status", "physical", "knowledge", "location", "timeline"]


def bible_data(ledger: Ledger, chars: CharacterIndex) -> dict[str, list[dict]]:
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(ledger.facts, key=lambda f: (f.episode, f.line_id)):
        by_entity[f.entity].append({"episode": f.episode, "ts": f.ts, "line_id": f.line_id, "type": f.fact_type,
                                    "attribute": f.attribute, "value": f.value, "mode": f.mode, "quote": f.quote,
                                    "disputed": f.disputed})
    return dict(sorted(by_entity.items(), key=lambda kv: -len(kv[1])))


def write_bible(ledger: Ledger, chars: CharacterIndex, out_path: Path) -> Path:
    data = bible_data(ledger, chars)
    rows = ["# Story bible", "", f"{len(ledger.facts)} facts from episodes {ledger.episodes()}", ""]
    for cid, facts in data.items():
        rows += [f"## {chars.display(cid)} (`{cid}`)", ""]
        for t in TYPE_ORDER:
            group = [f for f in facts if f["type"] == t]
            if not group:
                continue
            rows.append(f"**{t.title()}**")
            rows.append("")
            for f in group:
                flag = " ⚠ disputed" if f["disputed"] else ""
                who = "" if f["mode"] == "stated" else f" ({f['mode'].replace('claimed_by:', 'claimed by ')})"
                attr = f["attribute"].replace("relationship_to:", "relationship to ").replace("_", " ")
                rows.append(f"- {attr}: **{f['value']}**{who} · ep {f['episode']} "
                            f"{f['ts'] or ''} · “{f['quote']}”{flag}")
            rows.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(rows), encoding="utf-8")
    return out_path
