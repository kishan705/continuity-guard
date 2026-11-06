"""Model layer: one place that knows about providers.

- get_llm(cfg, role) builds a chat model from config.yaml (or env overrides)
- call_json() renders a prompt file, calls the model, parses + validates JSON,
  repairs once if the reply is broken, caches replies on disk and logs tokens.

Swap models with:  LLM_PROVIDER=groq LLM_MODEL=<name> python cli.py ...
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Type

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

try:  # optional: load API keys from .env
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass


# --------------------------------------------------------------------------- config

def load_config(path: Optional[str | Path] = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    # make relative paths absolute so the CLI works from any folder
    for key, val in cfg.get("paths", {}).items():
        p = Path(val)
        cfg["paths"][key] = str(p if p.is_absolute() else ROOT / p)
    return cfg


# --------------------------------------------------------------------------- run context + logging

_CTX: dict[str, Any] = {"run": "default", "show": None, "episode": None, "log_path": None}
_LOCK = threading.Lock()


def set_context(**kwargs) -> None:
    _CTX.update(kwargs)


def _log(record: dict) -> None:
    path = _CTX.get("log_path")
    if not path:
        return
    record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": _CTX.get("run"),
              "show": _CTX.get("show"), "episode": _CTX.get("episode"), **record}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# --------------------------------------------------------------------------- prompts + JSON

def render(prompt_name: str, variables: dict[str, Any]) -> str:
    """Fill {name} placeholders. Literal JSON braces in the prompt are left alone
    because only the keys we pass are replaced."""
    text = (PROMPTS / f"{prompt_name}.md").read_text(encoding="utf-8")
    for key, val in variables.items():
        if not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False, indent=1)
        text = text.replace("{" + key + "}", val)
    return text


def extract_first_json(text: str) -> Any:
    """Balanced-brace scan (from the Autonomous Coder Agent's fallback parser),
    generalised to objects and arrays. Returns the first block that parses."""
    openers = {"{": "}", "[": "]"}
    for start, ch in enumerate(text):
        if ch not in openers:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no JSON object found in model reply")


def parse_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return extract_first_json(t)


def _coerce(data: Any, schema: Type[BaseModel]) -> BaseModel:
    if isinstance(data, list):  # model returned the list without its wrapper object
        list_fields = [n for n, f in schema.model_fields.items() if "list" in str(f.annotation).lower()]
        if list_fields:
            data = {list_fields[0]: data}
    return schema.model_validate(data)


# --------------------------------------------------------------------------- the model

_LAST_CALL: dict[str, float] = {}
_RETRYABLE = ("429", "rate", "quota", "resource_exhausted", "timeout", "timed out", "overloaded",
              "503", "502", "500", "connection", "temporarily")


class LLM:
    def __init__(self, cfg: dict, role: str = "extract"):
        lc = cfg["llm"]
        self.cfg = cfg
        self.role = role
        self.provider = os.getenv("LLM_PROVIDER") or lc["provider"]
        model = os.getenv("LLM_MODEL") or lc["model"]
        judge_model = os.getenv("LLM_JUDGE_MODEL") or lc.get("judge_model")
        if role in ("judge", "verify") and judge_model:
            model = judge_model
        self.model = model
        self.temperature = lc.get("temperature", 0)
        self.max_retries = int(lc.get("max_retries", 4))
        self.rpm = float(lc.get("rpm_limit", 0) or 0)
        self.timeout = float(lc.get("timeout_seconds", 120) or 120)
        self.cache_dir = Path(cfg["paths"]["cache"])
        self.offline = self.provider == "offline"
        self._chat = None

    @property
    def name(self) -> str:
        return "offline/regex-baseline" if self.offline else f"{self.provider}/{self.model}"

    # -- provider client (LangChain), created lazily so `offline` needs no installs
    def _client(self):
        if self._chat is None:
            try:
                from langchain.chat_models import init_chat_model
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "LangChain is not installed. Run `pip install -r requirements.txt`, "
                    "or set llm.provider: offline to run the no-AI baseline.") from exc
            kwargs = {"temperature": self.temperature}
            key = self.cfg["llm"].get("api_key")       # set per session by the Streamlit app
            if key:
                kwargs["google_api_key" if self.provider == "google_genai" else "api_key"] = key
            try:  # short provider-side retries + a timeout, so our own retry loop (which prints) is in charge
                self._chat = init_chat_model(self.model, model_provider=self.provider, **kwargs,
                                             timeout=self.timeout, max_retries=1)
            except Exception:  # some providers don't take these arguments
                self._chat = init_chat_model(self.model, model_provider=self.provider, **kwargs)
        return self._chat

    def _throttle(self) -> None:
        if self.rpm <= 0:
            return
        gap = 60.0 / self.rpm
        last = _LAST_CALL.get(self.provider, 0.0)
        wait = last + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[self.provider] = time.time()

    def _cache_path(self, prompt: str) -> Path:
        key = hashlib.sha256(f"{self.provider}|{self.model}|{self.temperature}|{prompt}".encode()).hexdigest()
        return self.cache_dir / f"{key[:40]}.json"

    def complete(self, prompt: str, tag: str = "") -> str:
        if self.offline:
            raise RuntimeError("the offline baseline has no text model; stages call their regex path instead")
        cpath = self._cache_path(prompt)
        if cpath.exists():
            data = json.loads(cpath.read_text(encoding="utf-8"))
            _log({"stage": tag, "model": self.name, "cached": True, "seconds": 0,
                  "input_tokens": 0, "output_tokens": 0})
            return data["text"]

        attempt, t0 = 0, time.time()
        while True:
            self._throttle()
            try:
                resp = self._client().invoke(prompt)
                break
            except Exception as exc:  # network / rate limit
                attempt += 1
                msg = str(exc).lower()
                if "limit: 0" in msg or "limit\": 0" in msg:
                    raise RuntimeError(
                        f"{self.name} has no free-tier quota on this API key (Google reports a limit of 0). "
                        "Pick another model from your key's list, e.g. --model gemini-3.5-flash-lite, "
                        "or set llm.model in config.yaml.") from exc
                if "api key not valid" in msg or "api_key_invalid" in msg:
                    raise RuntimeError("The API key was rejected. Check .env: it must contain "
                                       "GOOGLE_API_KEY=<your key> on one line.") from exc
                if attempt > self.max_retries or not any(k in msg for k in _RETRYABLE):
                    raise
                wait = min(90, 5 * 2 ** (attempt - 1))
                reason = re.sub(r"\s+", " ", str(exc))[:110]
                print(f"   [model] {self.name} busy or rate-limited ({reason}); retry {attempt}/{self.max_retries} "
                      f"in {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)

        content = resp.content
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        usage = getattr(resp, "usage_metadata", None) or {}
        in_tok = usage.get("input_tokens") or len(prompt) // 4
        out_tok = usage.get("output_tokens") or len(content) // 4
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({"text": content, "model": self.name}), encoding="utf-8")
        _log({"stage": tag, "model": self.name, "cached": False, "seconds": round(time.time() - t0, 2),
              "input_tokens": in_tok, "output_tokens": out_tok, "estimated": not usage})
        return content

    def call_json(self, prompt_name: str, variables: dict, schema: Type[BaseModel], tag: str = "") -> BaseModel:
        prompt = render(prompt_name, variables)
        text = self.complete(prompt, tag=tag or prompt_name)
        try:
            return _coerce(parse_json(text), schema)
        except Exception as exc:
            repair = (f"{prompt}\n\nYour previous reply could not be used: {str(exc)[:300]}\n"
                      "Reply again with ONLY valid JSON in exactly the requested format.")
            text = self.complete(repair, tag=(tag or prompt_name) + "_repair")
            return _coerce(parse_json(text), schema)


def get_llm(cfg: dict, role: str = "extract") -> LLM:
    return LLM(cfg, role)
