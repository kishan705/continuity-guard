"""Every data shape in the pipeline, defined once.

Episode -> (extract) -> Fact -> (rules / judge) -> Candidate -> Flag
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

LineKind = Literal["dialogue", "action", "heading", "transition"]
FactType = Literal["identity", "relationship", "status", "knowledge", "physical", "location", "timeline"]
FACT_TYPES = ("identity", "relationship", "status", "knowledge", "physical", "location", "timeline")
Verdict = Literal["contradiction", "development", "consistent", "unclear"]
Severity = Literal["high", "medium", "low"]


# --------------------------------------------------------------------------- screenplay

class Line(BaseModel):
    line_id: str                      # E12L041 (stable, episode-wide counter)
    ts: Optional[str] = None          # timestamp as written in the source, e.g. "00:45"
    ts_sec: Optional[float] = None
    ts_inferred: bool = False         # True when the line had no timestamp and inherited one
    kind: LineKind = "action"
    speaker: Optional[str] = None     # as written, e.g. "ROSE"
    text: str

    def display(self) -> str:
        return f"{self.speaker}: {self.text}" if self.speaker else self.text


class Scene(BaseModel):
    scene_id: str                     # E12S03
    episode: int
    heading: str = ""
    start: Optional[str] = None
    lines: list[Line] = Field(default_factory=list)


class Episode(BaseModel):
    episode: int
    source_file: str = ""
    title: str = ""
    scenes: list[Scene] = Field(default_factory=list)

    def all_lines(self) -> list[Line]:
        return [ln for sc in self.scenes for ln in sc.lines]

    def line(self, line_id: str) -> Optional[Line]:
        for ln in self.all_lines():
            if ln.line_id == line_id:
                return ln
        return None

    def scene_of(self, line_id: str) -> Optional[Scene]:
        for sc in self.scenes:
            if any(ln.line_id == line_id for ln in sc.lines):
                return sc
        return None


# --------------------------------------------------------------------------- facts

class FactDraft(BaseModel):
    """What the model returns. Code adds ids, episode and timestamps afterwards."""
    line_id: str
    entity: str
    fact_type: FactType
    attribute: str
    value: str
    stability: Literal["stable", "changeable"] = "changeable"
    mode: str = "stated"              # "stated" | "claimed_by:<SPEAKER>"
    quote: str

    @field_validator("fact_type", mode="before")
    @classmethod
    def _norm_type(cls, v):
        v = str(v).strip().lower()
        aliases = {"relation": "relationship", "relationships": "relationship", "secret": "knowledge",
                   "injury": "physical", "appearance": "physical", "time": "timeline", "place": "location"}
        return aliases.get(v, v)

    @field_validator("value", "attribute", "entity", "quote", "line_id", mode="before")
    @classmethod
    def _to_str(cls, v):
        return "" if v is None else str(v)

    @field_validator("stability", mode="before")
    @classmethod
    def _norm_stab(cls, v):
        v = str(v or "changeable").strip().lower()
        return v if v in ("stable", "changeable") else "changeable"


class ExtractOutput(BaseModel):
    facts: list[dict] = Field(default_factory=list)   # validated one by one so a bad item doesn't sink the batch


class Fact(FactDraft):
    fact_id: str = ""
    episode: int = 0
    scene_id: str = ""
    ts: Optional[str] = None
    disputed: bool = False            # set when this fact is part of a confirmed flag
    repaired: bool = False            # grounding moved it to the line that really holds the quote
    challenges: int = 0               # how many later episodes were flagged against this fact

    def key(self) -> tuple[str, str]:
        return (self.entity, self.attribute)

    def as_text(self) -> str:
        return f"{self.entity} {self.attribute.replace('_', ' ')} {self.value}"

    def short(self) -> str:
        return f"[{self.fact_type}] {self.entity}.{self.attribute} = {self.value} ({self.mode})"


# --------------------------------------------------------------------------- checking

class Candidate(BaseModel):
    candidate_id: str
    rule: str                         # dead_character_active | stable_attribute_changed | ...
    type: FactType
    episode: int
    new_line_id: str
    new_fact: Optional[Fact] = None   # None when the trigger is a line, not a fact (e.g. a dead character speaks)
    prior_facts: list[Fact] = Field(default_factory=list)
    note: str = ""
    score: float = 1.0                # priority; rule hits = 1.0, similarity hits = cosine


class JudgeVerdict(BaseModel):
    candidate_id: str
    verdict: Verdict = "unclear"
    prior_line_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    severity: Severity = "medium"
    confidence: float = 0.5
    suggested_fix: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _v(cls, v):
        v = str(v).strip().lower()
        return v if v in ("contradiction", "development", "consistent", "unclear") else "unclear"

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        v = str(v).strip().lower()
        return v if v in ("high", "medium", "low") else "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class JudgeBatch(BaseModel):
    verdicts: list[JudgeVerdict] = Field(default_factory=list)


class VerifyOutput(BaseModel):
    keep: bool = True
    reason: str = ""
    quotes_checked: list[str] = Field(default_factory=list)


class Ref(BaseModel):
    episode: int
    ts: Optional[str] = None
    line_id: str
    quote: str


class Flag(BaseModel):
    flag_id: str
    type: FactType
    rule: str
    severity: Severity = "medium"
    verdict: Verdict = "contradiction"
    confidence: float = 0.5
    new: Ref
    prior: list[Ref] = Field(default_factory=list)
    explanation: str = ""
    suggested_fix: str = ""
    found_by: str = ""                # rules | rules+judge | rules+judge+verify
    model: str = ""
    verify_reason: str = ""
    prior_fact_ids: list[str] = Field(default_factory=list)
