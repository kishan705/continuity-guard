import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guard.llm import LLM, load_config  # noqa: E402

DEMO = ROOT / "tests" / "fixtures" / "demo_show"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Offline config writing everything into a temp folder."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    c = load_config()
    c["llm"]["provider"] = "offline"
    c["llm"]["rpm_limit"] = 0
    c["embeddings"]["provider"] = "hashing"
    c["vector_store"] = "numpy"
    for k in ("processed", "store", "outputs", "cache"):
        c["paths"][k] = str(tmp_path / k)
    return c


class ScriptedLLM(LLM):
    """A fake model: answers each prompt with a function of the prompt text.
    Lets tests exercise the AI code path (parsing, grounding, judge, verify)."""

    def __init__(self, cfg, responder, role="extract"):
        cfg = json.loads(json.dumps(cfg))
        cfg["llm"]["provider"] = "scripted"
        cfg["llm"]["model"] = "fake"
        super().__init__(cfg, role)
        self.responder = responder
        self.prompts = []

    def _client(self):
        outer = self

        class _Resp:
            def __init__(self, text):
                self.content = text
                self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        class _Chat:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                return _Resp(outer.responder(prompt))

        return _Chat()


@pytest.fixture
def scripted():
    return ScriptedLLM


def case_ids(prompt: str) -> list[str]:
    return re.findall(r"CASE (C\d+)", prompt)
