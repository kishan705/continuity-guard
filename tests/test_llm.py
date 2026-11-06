import json

import pytest

from guard.llm import extract_first_json, get_llm, parse_json, render
from guard.schemas import JudgeBatch


def test_parse_json_handles_fences_and_chatter():
    assert parse_json('```json\n{"facts": []}\n```') == {"facts": []}
    assert parse_json('Sure! Here it is: {"keep": true, "reason": "a {brace} in text"} hope that helps') == \
        {"keep": True, "reason": "a {brace} in text"}
    assert extract_first_json('noise [1, 2] more') == [1, 2]
    with pytest.raises(ValueError):
        extract_first_json("no json here")


def test_render_fills_only_known_placeholders():
    text = render("verify_flag", {"prior_context": "PRIOR", "new_context": "NEW", "episode": "3",
                                  "explanation": "EXPL"})
    assert "PRIOR" in text and "NEW" in text and '{"keep": true' in text   # literal JSON example survives


def test_call_json_caches_repairs_and_logs(cfg, scripted, tmp_path):
    from guard.llm import set_context

    calls = []

    def responder(prompt):
        calls.append(prompt)
        if "could not be used" in prompt:
            return '{"verdicts": [{"candidate_id": "C1", "verdict": "contradiction", "confidence": 0.9}]}'
        return "not json at all"

    log = tmp_path / "log.jsonl"
    set_context(log_path=str(log), run="t")
    llm = scripted(cfg, responder)
    out = llm.call_json("judge_conflict", {"episode": "3", "cases": "CASE C1"}, JudgeBatch, tag="judge")
    assert out.verdicts[0].verdict == "contradiction" and len(calls) == 2      # one repair
    llm.call_json("judge_conflict", {"episode": "3", "cases": "CASE C1"}, JudgeBatch, tag="judge")
    assert len(calls) == 2              # second run: both the bad reply and the repair come from cache
    records = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(r["cached"] for r in records) and records[0]["input_tokens"] == 10
    set_context(log_path=None)


def test_offline_and_env_override(cfg, monkeypatch):
    assert get_llm(cfg).offline and get_llm(cfg).name.startswith("offline")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    assert get_llm(cfg).name == "groq/some-model"
