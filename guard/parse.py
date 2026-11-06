"""Raw screenplay files -> Episode JSON. Plain code, no AI.

Handles .txt .md .fountain .docx .pdf .json, and these line styles:
    [00:12] MAYA: You lied to me.          00:12 - MAYA (V.O.): You lied.
    00:12 | MAYA | You lied to me.         (00:12) Maya slaps Ethan.
    00:12 INT. STERLING TOWER - NIGHT      MAYA            <- Fountain style:
                                           You lied to me.    speaker line, then dialogue
One file per episode, or one file with "EPISODE 12" headings.
If the input pack uses another layout, only this file needs to change.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .schemas import Episode, Line, Scene

SUPPORTED = {".txt", ".md", ".fountain", ".docx", ".pdf", ".json"}

_TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
LEAD_TS = re.compile(rf"^\s*[\[(]?\s*(?P<ts>{_TS})(?:\s*(?:-|–|—|to)\s*(?P<end>{_TS}))?\s*[\])]?\s*(?:[-–—|:>]\s*)?(?P<rest>.*)$")
TRAIL_TS = re.compile(rf"^(?P<rest>.*?)\s*[\[(](?P<ts>{_TS})(?:\s*(?:-|–|—|to)\s*{_TS})?[\])]\s*$")
EPISODE_HEAD = re.compile(r"^\s*(?:#+\s*)?(?:episode|ep\.?)\s*[-#:]?\s*(?P<num>\d{1,3})\s*"
                          r"(?:$|[:.\-–—]\s*(?P<title>.*)$|\s+(?P<title2>[A-Z\"'].*)$)", re.I)
SCENE_HEAD = re.compile(r"^(?:\d+[.)]?\s*)?(?:INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.|EXT\.|INT\b|EXT\b|SCENE\s+\d+|SC\.?\s*\d+)", re.I)
TRANSITION = re.compile(r"^(?:CUT TO|SMASH CUT|MATCH CUT|FADE (?:IN|OUT|TO)|DISSOLVE TO|INTERCUT|BACK TO|"
                        r"FLASHBACK|END (?:OF )?FLASHBACK|FLASH FORWARD|TO BE CONTINUED|THE END)\b", re.I)
DIALOGUE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9 .'\-]{0,38}?)\s*(?P<paren>\([^)]*\))?\s*:\s*(?P<text>\S.*)$")
PIPE_ROW = re.compile(r"^(?P<name>[^|]{0,40})\|(?P<text>.+)$")
NOISE = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:of\s*\d+)?\s*$|^\s*[-=*_~]{3,}\s*$", re.I)
NOT_SPEAKERS = {"sfx", "music", "super", "caption", "text", "on screen", "title", "note", "notes", "action",
                "visual", "sound", "setting", "location", "time", "camera", "shot", "angle", "insert",
                "description", "scene", "later", "transition", "vfx", "graphic", "subtitle", "logline"}
VOICE_TAGS = re.compile(r"\((?:v\.?o\.?|o\.?s\.?|o\.?c\.?|cont'?d|continued|off)\)", re.I)


# --------------------------------------------------------------------------- reading files

def read_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".txt", ".md", ".fountain"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suf == ".docx":
        import docx  # python-docx

        doc = docx.Document(str(path))
        out = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                out.append(" | ".join(cells))
        return "\n".join(out)
    if suf == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                return "\n".join((page.extract_text() or "") for page in pdf.pages)
        except ImportError:
            from pypdf import PdfReader

            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    raise ValueError(f"unsupported file type: {path.name}")


def ts_to_sec(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    parts = ts.replace(",", ".").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def episode_number_from_name(name: str) -> Optional[int]:
    m = re.search(r"(?:e|ep|episode)[\s_\-.]*(\d{1,3})", name, re.I) or re.findall(r"\d{1,3}", name)
    if isinstance(m, list):
        return int(m[-1]) if m else None
    return int(m.group(1))


# --------------------------------------------------------------------------- line classification

def _clean(raw: str) -> str:
    s = raw.replace(" ", " ").strip()
    s = re.sub(r"^[\-*•]\s+", "", s)                  # bullets
    s = s.replace("**", "").replace("__", "")         # markdown bold
    if s.startswith("|") and s.endswith("|"):         # markdown table row
        s = s.strip("|").strip()
    return s


def _is_speaker_name(name: str) -> bool:
    name = VOICE_TAGS.sub("", name).strip()
    if not name or name.lower() in NOT_SPEAKERS or len(name.split()) > 4:
        return False
    letters = re.sub(r"[^A-Za-z]", "", name)
    if not letters:
        return False
    if letters.isupper():
        return True
    words = name.split()
    return len(words) <= 3 and all(w[0].isupper() for w in words if w[0].isalpha())


def _speaker(name: str) -> str:
    return re.sub(r"\s+", " ", VOICE_TAGS.sub("", name)).strip().upper()


def _fountain_speaker(s: str) -> bool:
    core = VOICE_TAGS.sub("", s).strip()
    return (bool(core) and core.isupper() and len(core.split()) <= 4 and len(core) <= 40
            and re.fullmatch(r"[A-Z0-9 .'\-]+", core) is not None and core.lower() not in NOT_SPEAKERS
            and not SCENE_HEAD.match(core) and not TRANSITION.match(core))


# --------------------------------------------------------------------------- parsing

class _Builder:
    def __init__(self, episode: int, source: str, title: str = ""):
        self.ep = Episode(episode=episode, source_file=source, title=title.strip())
        self.n_line = 0
        self.last_ts: Optional[str] = None
        self.pending_speaker: Optional[str] = None
        self.prev_kind: Optional[str] = None
        self.blank_since_prev = True

    def _scene(self, heading: str = "", ts: Optional[str] = None) -> Scene:
        sc = Scene(scene_id=f"E{self.ep.episode:02d}S{len(self.ep.scenes) + 1:02d}",
                   episode=self.ep.episode, heading=heading, start=ts)
        self.ep.scenes.append(sc)
        return sc

    def add(self, kind: str, text: str, ts: Optional[str], speaker: Optional[str] = None) -> None:
        inferred = ts is None
        ts = ts or self.last_ts
        self.last_ts = ts
        if kind == "heading" or not self.ep.scenes:
            self._scene(text if kind == "heading" else "", ts)
        self.n_line += 1
        self.ep.scenes[-1].lines.append(Line(
            line_id=f"E{self.ep.episode:02d}L{self.n_line:03d}", ts=ts, ts_sec=ts_to_sec(ts),
            ts_inferred=inferred and ts is not None, kind=kind, speaker=speaker, text=text.strip()))
        self.prev_kind = kind
        self.blank_since_prev = False

    def feed(self, raw: str) -> None:
        s = _clean(raw)
        if not s:
            self.blank_since_prev = True
            self.pending_speaker = None
            return
        if NOISE.match(s):
            return

        ts = None
        m = LEAD_TS.match(s)
        if m and m.group("ts"):
            ts, s = m.group("ts"), m.group("rest").strip()
        else:
            m2 = TRAIL_TS.match(s)
            if m2:
                ts, s = m2.group("ts"), m2.group("rest").strip()
        if not s:
            if ts:
                self.last_ts = ts
            return

        # Fountain style: the previous line was a bare speaker name
        if self.pending_speaker:
            speaker, self.pending_speaker = self.pending_speaker, None
            if re.fullmatch(r"\(.*\)", s):           # parenthetical under the name
                self.pending_speaker = speaker
                self._pending_paren = s
                return
            paren = getattr(self, "_pending_paren", "")
            self._pending_paren = ""
            self.add("dialogue", f"{paren} {s}".strip(), ts, speaker)
            return

        if SCENE_HEAD.match(s):
            self.add("heading", s, ts)
            return
        if TRANSITION.match(s):
            self.add("transition", s, ts)
            return
        if re.match(r"^(?:action|description|visual)\s*:\s*", s, re.I):
            self.add("action", re.sub(r"^(?:action|description|visual)\s*:\s*", "", s, flags=re.I), ts)
            return

        dm = DIALOGUE.match(s)
        if dm and dm.group("name").strip().lower() in NOT_SPEAKERS:
            self.add("action", s, ts)                 # "Note: ...", "SFX: ..." are not speakers
            return
        if dm and _is_speaker_name(dm.group("name")):
            paren = dm.group("paren") or ""
            text = dm.group("text")
            if paren and not VOICE_TAGS.fullmatch(paren):
                text = f"{paren} {text}"
            self.add("dialogue", text, ts, _speaker(dm.group("name")))
            return

        pm = PIPE_ROW.match(s)
        if pm:
            name, text = pm.group("name").strip(), pm.group("text").strip(" |")
            if not name or name.lower() in NOT_SPEAKERS:
                self.add("action", text, ts)
                return
            if _is_speaker_name(name):
                self.add("dialogue", text, ts, _speaker(name))
                return

        if _fountain_speaker(s):
            self.pending_speaker = _speaker(s)
            if ts:
                self.last_ts = ts
            return

        # continuation of a dialogue line wrapped onto the next line
        if self.prev_kind == "dialogue" and ts is None and not self.blank_since_prev and self.ep.scenes:
            last = self.ep.scenes[-1].lines[-1]
            last.text = f"{last.text} {s}"
            return
        self.add("action", s, ts)


def parse_text(text: str, source_file: str = "", default_episode: Optional[int] = None) -> list[Episode]:
    lines = text.splitlines()
    heads = [(i, EPISODE_HEAD.match(_clean(l))) for i, l in enumerate(lines)]
    heads = [(i, m) for i, m in heads if m]
    if not heads:
        b = _Builder(default_episode or 1, source_file)
        for raw in lines:
            b.feed(raw)
        return [b.ep]
    episodes = []
    for k, (i, m) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        b = _Builder(int(m.group("num")), source_file, m.group("title") or m.group("title2") or "")
        for raw in lines[i + 1:end]:
            b.feed(raw)
        episodes.append(b.ep)
    return episodes


def parse_file(path: Path) -> list[Episode]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        return [Episode.model_validate(d) for d in items]
    return parse_text(read_text(path), path.name, episode_number_from_name(path.stem))


def parse_path(path: str | Path) -> list[Episode]:
    path = Path(path)
    skip = re.compile(r"^(readme|answers|notes?|license)", re.I)
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED and not skip.match(p.stem))
    seen: dict[int, Episode] = {}
    for f in files:
        for ep in parse_file(f):
            if ep.episode in seen:
                raise ValueError(f"episode {ep.episode} appears twice: {seen[ep.episode].source_file} "
                                 f"and {f.name}. Rename one file or fix its EPISODE heading.")
            seen[ep.episode] = ep
    return [seen[k] for k in sorted(seen)]


# --------------------------------------------------------------------------- save / load / report

def save_episodes(episodes: list[Episode], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ep in episodes:
        (out / f"ep_{ep.episode:02d}.json").write_text(ep.model_dump_json(indent=1), encoding="utf-8")


def load_episodes(in_dir: str | Path) -> list[Episode]:
    files = sorted(Path(in_dir).glob("ep_*.json"))
    eps = [Episode.model_validate_json(f.read_text(encoding="utf-8")) for f in files]
    return sorted(eps, key=lambda e: e.episode)


def parse_report(episodes: list[Episode]) -> dict:
    rows, warnings = [], []
    for ep in episodes:
        lines = ep.all_lines()
        n_dlg = sum(1 for l in lines if l.kind == "dialogue")
        n_no_ts = sum(1 for l in lines if l.ts is None)
        n_inf = sum(1 for l in lines if l.ts_inferred)
        backwards = sum(1 for a, b in zip(lines, lines[1:])
                        if a.ts_sec is not None and b.ts_sec is not None and b.ts_sec + 1 < a.ts_sec)
        rows.append({"episode": ep.episode, "scenes": len(ep.scenes), "lines": len(lines), "dialogue": n_dlg,
                     "no_timestamp": n_no_ts, "inherited_timestamp": n_inf, "timestamps_backwards": backwards})
        if not lines:
            warnings.append(f"ep {ep.episode}: no lines parsed")
        elif n_dlg == 0:
            warnings.append(f"ep {ep.episode}: no dialogue detected - check the speaker format in parse.py")
        if lines and n_no_ts == len(lines):
            warnings.append(f"ep {ep.episode}: no timestamps found - check the timestamp format in parse.py")
        if backwards:
            warnings.append(f"ep {ep.episode}: timestamps go backwards {backwards} time(s)")
    return {"episodes": rows, "warnings": warnings}
