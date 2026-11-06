"""Flags -> files an editor can read: JSON (raw output), Markdown, one HTML page."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .schemas import Flag


def _md(episode: int, flags: list[Flag], stats: dict) -> str:
    rows = [f"# Continuity report: episode {episode}", ""]
    if not flags:
        rows += ["No continuity problems found.", ""]
    for f in flags:
        rows += [f"## {f.flag_id} · {f.severity.upper()} · {f.type}",
                 "",
                 f"**New (ep {f.new.episode}, {f.new.ts}, {f.new.line_id}):** {f.new.quote}",
                 ""]
        for p in f.prior:
            rows.append(f"**Earlier (ep {p.episode}, {p.ts}, {p.line_id}):** {p.quote}")
            rows.append("")
        rows += [f"**Why:** {f.explanation}", ""]
        if f.suggested_fix:
            rows += [f"**Suggested fix:** {f.suggested_fix}", ""]
        rows += [f"_Rule: {f.rule} · found by: {f.found_by} · confidence {f.confidence} · model {f.model}_", ""]
    rows += ["---", "", "Stats: " + ", ".join(f"{k} {v}" for k, v in stats.items())]
    return "\n".join(rows)


def write_episode_report(out_dir: Path, episode: int, flags: list[Flag], stats: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"episode": episode, "flags": [f.model_dump() for f in flags], "stats": stats}
    path = out_dir / f"ep_{episode:02d}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"ep_{episode:02d}.md").write_text(_md(episode, flags, stats), encoding="utf-8")
    return path


def load_reports(reports_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(reports_dir.glob("ep_*.json"))]


_CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:980px;margin:32px auto;padding:0 16px;color:#222}
h1{font-size:22px}h2{font-size:17px;margin-top:28px}.card{border:1px solid #ddd;border-radius:8px;padding:12px 14px;margin:10px 0}
.sev{font-weight:600;font-size:12px;padding:2px 8px;border-radius:10px;margin-right:6px}
.high{background:#fbe3e3}.medium{background:#fbefd9}.low{background:#e8eef7}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0}.q{background:#f6f6f4;border-radius:6px;padding:8px}
.meta{color:#666;font-size:12px}.ok{color:#2b7a3b}"""


def write_html(out_path: Path, show: str, reports: list[dict]) -> Path:
    total = sum(len(r["flags"]) for r in reports)
    body = [f"<h1>Continuity report: {html.escape(show)}</h1>",
            f"<p class='meta'>{len(reports)} episodes checked · {total} flags</p>"]
    for r in reports:
        body.append(f"<h2>Episode {r['episode']}</h2>")
        if not r["flags"]:
            body.append("<p class='ok'>No continuity problems found.</p>")
        for f in r["flags"]:
            prior = "".join(f"<div class='q'><b>Earlier · ep {p['episode']} · {p['ts']}</b><br>"
                            f"{html.escape(p['quote'])}</div>" for p in f["prior"])
            body.append(
                f"<div class='card'><span class='sev {f['severity']}'>{f['severity'].upper()}</span>"
                f"<b>{f['flag_id']}</b> · {f['type']} · <span class='meta'>{f['rule']}</span>"
                f"<div class='pair'><div class='q'><b>New · ep {f['new']['episode']} · {f['new']['ts']}</b><br>"
                f"{html.escape(f['new']['quote'])}</div>{prior}</div>"
                f"<div>{html.escape(f['explanation'])}</div>"
                + (f"<div><b>Fix:</b> {html.escape(f['suggested_fix'])}</div>" if f.get("suggested_fix") else "")
                + f"<div class='meta'>found by {f['found_by']} · confidence {f['confidence']} · {f['model']}</div></div>")
    out_path.write_text(f"<!doctype html><meta charset='utf-8'><title>{html.escape(show)} continuity</title>"
                        f"<style>{_CSS}</style>{''.join(body)}", encoding="utf-8")
    return out_path


LABEL_FIELDS = ["key", "episode", "ts", "rule", "new_quote", "earlier_quote", "explanation", "label"]
LABELS = ("true_error", "intended_twist", "false_alarm")


def flag_key(f: dict) -> str:
    return f"{f['new']['episode']}|{f['new']['line_id']}|{f['rule']}"


def read_csv_rows(path: Path) -> list[dict]:
    """Reads a CSV saved by this tool, by Excel (with or without BOM) or by Google Sheets."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                rows = list(csv.DictReader(fh))
            return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]
        except UnicodeDecodeError:
            continue
    return []


def write_csv_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:   # BOM so Excel shows quotes correctly
        w = csv.DictWriter(fh, fieldnames=LABEL_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def label_row(f: dict, label: str = "") -> dict:
    return {"key": flag_key(f), "episode": f["new"]["episode"], "ts": f["new"]["ts"], "rule": f["rule"],
            "new_quote": f["new"]["quote"], "earlier_quote": " || ".join(p["quote"] for p in f["prior"]),
            "explanation": f["explanation"], "label": label}
