"""Continuity Guard - Streamlit UI.   Run:  streamlit run app.py

Tabs: Load show · Check episode · Story bible · Eval
The sidebar picks the model; an API key typed there stays in this session only.
No Kuku data ships with the app: upload episodes at runtime, or load the demo show.
"""
from __future__ import annotations

import copy
import io
import json
import tempfile
import time
import zipfile
from pathlib import Path

import streamlit as st

from guard.bible import bible_data
from guard.llm import load_config
from guard.pipeline import Show, build, check_text, parse_show
from guard.report import load_reports
from guard.schemas import Flag

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "tests" / "fixtures" / "demo_show"
PROVIDERS = ["offline", "google_genai", "groq", "ollama", "openai", "anthropic"]
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "🔵"}

st.set_page_config(page_title="Continuity Guard", page_icon="🎬", layout="wide")


# ----------------------------------------------------------------------------- sidebar / config
@st.cache_data
def _base_cfg() -> dict:
    return load_config()


def session_cfg() -> dict:
    cfg = copy.deepcopy(_base_cfg())
    sb = st.sidebar
    sb.title("🎬 Continuity Guard")
    sb.caption("Flags story contradictions in a new episode script before it is generated.")
    show_name = sb.text_input("Show name", value=st.session_state.get("show", "demo"),
                              help="Each show keeps its own story ledger.")
    st.session_state["show"] = show_name.strip() or "demo"
    default_p = cfg["llm"]["provider"] if cfg["llm"]["provider"] in PROVIDERS else "offline"
    provider = sb.selectbox("Model provider", PROVIDERS, index=PROVIDERS.index(default_p),
                            help="offline = no API key, regex baseline")
    model = sb.text_input("Model name", value=cfg["llm"]["model"], disabled=provider == "offline")
    key = sb.text_input("API key (this session only)", type="password", disabled=provider in ("offline", "ollama"))
    mode = sb.selectbox("Checking mode", ["full", "judge", "rules"],
                        help="full = rules + AI judge + AI verify; judge = no verify; rules = no AI judging")
    cfg["llm"].update(provider=provider, model=model)
    if key:
        cfg["llm"]["api_key"] = key
    cfg["check"]["mode"] = mode
    sb.divider()
    sb.caption("Every flag quotes both lines word for word; anything a model cannot ground in the script "
               "is dropped before you see it.")
    return cfg


def flag_card(f: Flag, show: Show, key_prefix: str) -> None:
    with st.container(border=True):
        st.markdown(f"{SEV_ICON[f.severity]} **{f.severity.upper()}** · `{f.flag_id}` · **{f.type}** "
                    f"· _{f.rule.replace('_', ' ')}_")
        left, right = st.columns(2)
        left.markdown(f"**New** · ep {f.new.episode} · {f.new.ts}\n\n> {f.new.quote}")
        right.markdown("\n\n".join(f"**Earlier** · ep {p.episode} · {p.ts}\n\n> {p.quote}" for p in f.prior)
                       or "**Earlier** · (none)")
        st.markdown(f"**Why:** {f.explanation}")
        if f.suggested_fix:
            st.markdown(f"**Suggested fix:** {f.suggested_fix}")
        st.caption(f"found by {f.found_by} · confidence {f.confidence} · {f.model}"
                   + (f" · verify: {f.verify_reason}" if f.verify_reason else ""))
        b1, b2, b3, _ = st.columns([1, 1, 1.4, 4])
        for col, label, decision in ((b1, "✅ Accept", "accept"), (b2, "❌ Reject", "reject"),
                                     (b3, "🎭 Intended twist", "intended_twist")):
            if col.button(label, key=f"{key_prefix}-{f.flag_id}-{decision}"):
                show.out.mkdir(parents=True, exist_ok=True)
                with open(show.out / "feedback.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "flag_id": f.flag_id,
                                         "episode": f.new.episode, "line_id": f.new.line_id, "rule": f.rule,
                                         "decision": decision, "model": f.model}) + "\n")
                st.toast(f"Saved: {decision}")


def save_uploads(files) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="cg_upload_"))
    for up in files:
        data = up.getvalue()
        if up.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    name = Path(member).name
                    if name and not member.endswith("/") and not name.startswith("."):
                        (tmp / name).write_bytes(zf.read(member))
        else:
            (tmp / Path(up.name).name).write_bytes(data)
    return tmp


# ----------------------------------------------------------------------------- tabs
cfg = session_cfg()
show = Show(st.session_state["show"], cfg)
tab_load, tab_check, tab_bible, tab_eval = st.tabs(["1 · Load show", "2 · Check episode", "3 · Story bible",
                                                     "4 · Eval"])

with tab_load:
    st.subheader("Load the story so far")
    c1, c2 = st.columns([1, 2])
    if c1.button("Load demo show (3 made-up episodes)"):
        st.session_state["show"] = "demo"
        show = Show("demo", cfg)
        eps, rep = parse_show(DEMO, show)
        show.characters(eps, refresh=True)
        st.success(f"Parsed {len(eps)} demo episodes. Now press Build below.")
    ups = c2.file_uploader("…or upload episode files (.txt .md .docx .pdf .json .fountain) or one .zip",
                           accept_multiple_files=True)
    if ups and st.button("Parse uploaded files"):
        eps, rep = parse_show(save_uploads(ups), show)
        show.characters(eps, refresh=True)
        st.success(f"Parsed {len(eps)} episodes for show '{show.name}'.")
        st.dataframe(rep["episodes"], use_container_width=True)
        for w in rep["warnings"]:
            st.warning(w)

    episodes = show.episodes()
    if episodes:
        st.markdown(f"**{len(episodes)} episodes parsed** for `{show.name}`: "
                    f"{episodes[0].episode}–{episodes[-1].episode}")
        st.markdown("**Characters** — fix wrong merges or add aliases, then save. "
                    "This is the human-in-the-loop step.")
        idx = show.characters(episodes)
        rows = [{"id": c["id"], "name": c.get("name", ""), "aliases": ", ".join(c.get("aliases", []))}
                for c in idx.characters]
        edited = st.data_editor(rows, num_rows="dynamic", use_container_width=True, key=f"chars-{show.name}")
        if st.button("Save characters"):
            from guard.characters import CharacterIndex

            if hasattr(edited, "to_dict"):              # some Streamlit versions hand back a DataFrame
                edited = edited.to_dict("records")

            chars = [{"id": r["id"].strip(), "name": r["name"].strip(),
                      "aliases": [a.strip() for a in str(r["aliases"]).split(",") if a.strip()]}
                     for r in edited if r.get("id")]
            CharacterIndex(chars).save(show.chars_path)
            st.success("Saved. Rebuild to apply.")
        if st.button("Build story ledger", type="primary"):
            bar = st.progress(0.0, text="Building…")

            def progress(i, n, s):
                bar.progress(i / n, text=f"Episode {s['episode']}: {s['facts']} facts, {s['flags']} flags")

            try:
                summary = build(show, fresh=True, progress=progress)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Episodes", summary["episodes"])
                m2.metric("Facts", summary["facts"])
                m3.metric("Flags", summary["flags"])
                m4.metric("Model", summary["model"].split("/")[-1])
                st.caption(f"embedder {summary['embedder']} · vector store {summary['vector_store']}")
            except Exception as exc:
                st.error(f"Build failed: {exc}")

    reports = load_reports(show.out / "reports") if (show.out / "reports").exists() else []
    flagged = [r for r in reports if r["flags"]]
    if flagged:
        st.markdown("**Flags found while building** (each episode checked against the ones before it)")
        pick = st.selectbox("Episode", [r["episode"] for r in flagged], key="build-ep")
        for fd in next(r for r in flagged if r["episode"] == pick)["flags"]:
            flag_card(Flag.model_validate(fd), show, f"build-{pick}")

with tab_check:
    st.subheader("Check a new episode against the story so far")
    if not (show.store / "ledger.json").exists():
        st.info("Build the story ledger in tab 1 first.")
    else:
        up = st.file_uploader("New episode script", type=["txt", "md", "fountain", "docx", "pdf", "json"],
                              key="new-ep")
        pasted = st.text_area("…or paste it", height=180,
                              placeholder="EPISODE 4\n[00:00] INT. OFFICE - DAY\n[00:03] ROSE: I'm back.")
        commit = st.checkbox("Add this episode to the story after checking", value=False)
        if st.button("Check episode", type="primary"):
            with st.spinner("Reading the episode and checking it against the ledger…"):
                try:
                    if up is not None:
                        folder = save_uploads([up])
                        from guard.pipeline import check_file

                        results = check_file(show, folder / Path(up.name).name, commit=commit)
                    elif pasted.strip():
                        results = check_text(show, pasted, "pasted.txt", commit=commit)
                    else:
                        results = []
                        st.warning("Upload or paste an episode first.")
                    st.session_state["last_check"] = [(ep.episode, [f.model_dump() for f in flags], stats)
                                                      for ep, flags, stats in results]
                except Exception as exc:
                    st.error(f"Check failed: {exc}")
        for ep_no, flags, stats in st.session_state.get("last_check", []):
            st.markdown(f"### Episode {ep_no}: {len(flags)} flag(s)")
            st.caption(f"{stats['facts']} facts extracted · {stats['candidates']} candidates · "
                       f"{stats.get('verify_dropped', 0)} dropped by verify · {stats['seconds']}s")
            if not flags:
                st.success("No continuity problems found.")
            for fd in flags:
                flag_card(Flag.model_validate(fd), show, f"check-{ep_no}")

with tab_bible:
    st.subheader("Story bible")
    if not (show.store / "ledger.json").exists():
        st.info("Build the story ledger first.")
    else:
        ledger, chars = show.ledger(), show.characters()
        data = bible_data(ledger, chars)
        who = st.selectbox("Character", list(data), format_func=lambda c: f"{chars.display(c)} ({len(data[c])} facts)")
        if who:
            st.dataframe([{k: v for k, v in f.items()} for f in data[who]], use_container_width=True)

with tab_eval:
    st.subheader("How good is it?")
    res_path = show.out / "eval" / "eval_results.md"
    if res_path.exists():
        st.markdown(res_path.read_text(encoding="utf-8"))
    else:
        st.info("Run `python eval/seed_errors.py` and `python eval/run_eval.py` to fill this table.")
    fb = show.out / "feedback.jsonl"
    if fb.exists():
        rows = [json.loads(l) for l in fb.read_text(encoding="utf-8").splitlines() if l.strip()]
        n = len(rows)
        acc = sum(r["decision"] == "accept" for r in rows)
        twist = sum(r["decision"] == "intended_twist" for r in rows)
        c1, c2, c3 = st.columns(3)
        c1.metric("Editor decisions", n)
        c2.metric("Acceptance rate (live precision)", f"{acc / n:.0%}" if n else "-")
        c3.metric("Marked intended twist", twist)
