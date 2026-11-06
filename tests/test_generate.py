import importlib.util
import re

from guard.parse import parse_path

from conftest import ROOT


def _gen():
    spec = importlib.util.spec_from_file_location("generate_series", ROOT / "tools" / "generate_series.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_writes_parseable_episodes_with_limited_memory(cfg, scripted, tmp_path, monkeypatch):
    gen = _gen()
    calls = {"bad_done": False}
    prompts = []

    def responder(prompt):
        prompts.append(prompt)
        m = re.search(r"Write EPISODE (\d+) of", prompt)
        if not m:
            return "Harper learns something. Cole hides it."
        ep = int(m.group(1))
        if ep == 2 and not calls["bad_done"]:          # first draft of ep 2 breaks the format
            calls["bad_done"] = True
            return "Harper walks in. Cole: hi"
        rows = [f"Episode {ep}: Title {ep}", "[00:00] INT. HOSPITAL - NIGHT"]
        for i in range(1, 15):
            rows.append(f"[00:{i * 5:02d}] HARPER: Line {i} of episode {ep}." if i % 2 else
                        f"[00:{i * 5:02d}] Cole wipes grease off his hands.")
        return "```\n" + "\n".join(rows) + "\n```"

    monkeypatch.setattr(gen, "load_config", lambda: cfg)
    monkeypatch.setattr(gen, "LLM", lambda c, role: scripted(c, responder, role))
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    gen.main(["--show", "g", "--episodes", "4", "--memory", "1",
              "--premise", str(ROOT / "tools" / "premise_example.yaml")])
    eps = parse_path(tmp_path / "data" / "generated" / "g")
    assert [e.episode for e in eps] == [1, 2, 3, 4]
    assert all(sum(l.kind == "dialogue" for l in e.all_lines()) >= 4 for e in eps)
    ep4_prompt = next(p for p in prompts if "Write EPISODE 4 of" in p)
    assert "Episode 3:" in ep4_prompt and "Episode 2:" not in ep4_prompt     # memory = 1
    assert any("broke the format" in p for p in prompts)                     # repair happened
    assert (tmp_path / "data" / "generated" / "g" / "writer_log.yaml").exists()
