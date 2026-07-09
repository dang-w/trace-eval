"""Core types for trace-eval.

The two seams this whole harness is built around live here:

1. The scorer interface (see ``scorers.py``): a scorer is just a plain function
   ``(Case, Result) -> Score``. Nothing in these types needs to know a scorer exists.

2. Trace capture: a ``Result`` carries a ``Trace`` — an ordered list of typed
   ``TraceStep``s. v1 only ever emits a single ``model_call`` step, but the *shape*
   is designed so agent steps and tool calls slot in later (just more steps with a
   different ``kind``). A future trace-level scorer inspects ``result.trace.steps``
   and needs no refactor here to do it.

Everything is a plain dataclass with explicit ``to_dict`` / ``from_dict`` so results
round-trip through JSON without loss and without a serialization dependency — this
artifact is meant to be forked and read, so the serde stays legible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- TraceStep kinds -------------------------------------------------------
# v1 only produces MODEL_CALL. The others are named now so the trace-level scorer
# and the agent runner that come later have a stable vocabulary to target.
STEP_MODEL_CALL = "model_call"
STEP_TOOL_CALL = "tool_call"  # reserved for later
STEP_AGENT_STEP = "agent_step"  # reserved for later

# --- Step roles -----------------------------------------------------------
# A model_call step also carries a *role* in its metadata, so a trace-level scorer can
# tell the first answer apart from a later verification without guessing by position.
# v1 uses exactly two: the answer, and an optional self-check that verifies it.
ROLE_ANSWER = "answer"
ROLE_VERIFY = "verify"


@dataclass
class TokenUsage:
    """Token counts for a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TokenUsage:
        return cls(
            input_tokens=d.get("input_tokens", 0),
            output_tokens=d.get("output_tokens", 0),
        )


@dataclass
class TraceStep:
    """One step in a trace.

    In v1 there is exactly one step per result, of kind ``model_call``. The fields
    are deliberately generic (``input``/``output`` are ``Any``) so a tool call
    (input = tool args, output = tool result) or an agent step reuses the same shape.
    """

    kind: str
    input: Any = None
    output: Any = None
    model: str | None = None
    usage: TokenUsage | None = None
    started_at: float | None = None  # epoch seconds
    ended_at: float | None = None  # epoch seconds
    duration_s: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "input": self.input,
            "output": self.output,
            "model": self.model,
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": self.duration_s,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceStep:
        usage = d.get("usage")
        return cls(
            kind=d["kind"],
            input=d.get("input"),
            output=d.get("output"),
            model=d.get("model"),
            usage=TokenUsage.from_dict(usage) if usage is not None else None,
            started_at=d.get("started_at"),
            ended_at=d.get("ended_at"),
            duration_s=d.get("duration_s"),
            metadata=d.get("metadata", {}) or {},
        )


@dataclass
class Trace:
    """An ordered sequence of steps taken to produce a result."""

    steps: list[TraceStep] = field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        """Total wall-clock across steps that recorded a duration."""
        durations = [s.duration_s for s in self.steps if s.duration_s is not None]
        return sum(durations) if durations else None

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trace:
        return cls(steps=[TraceStep.from_dict(s) for s in d.get("steps", [])])


@dataclass
class Case:
    """A single evaluation case: an input, and optionally the reference answer.

    ``self_check`` is the one field that turns a case multi-step: when set, it is a plain
    instruction for a verification pass ("recheck the arithmetic; correct it if wrong").
    The runner runs the answer, then feeds that instruction plus the prior answer back in
    as a second ``model_call`` — no placeholder syntax, no DSL, just an instruction string.
    Left ``None``, the case stays single-step and behaves exactly as it did in v1.
    """

    id: str
    input: str
    reference: str | None = None
    self_check: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input": self.input,
            "reference": self.reference,
            "self_check": self.self_check,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Case:
        return cls(
            id=d["id"],
            input=d["input"],
            reference=d.get("reference"),
            self_check=d.get("self_check"),
            metadata=d.get("metadata", {}) or {},
        )


@dataclass
class Result:
    """The outcome of running one case: the final output plus the full trace.

    ``error`` is set (and ``output`` left empty) if the run failed, so a run of many
    cases doesn't abort on one bad call.
    """

    case_id: str
    output: str = ""
    trace: Trace = field(default_factory=Trace)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "output": self.output,
            "trace": self.trace.to_dict(),
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Result:
        return cls(
            case_id=d["case_id"],
            output=d.get("output", ""),
            trace=Trace.from_dict(d.get("trace", {})),
            error=d.get("error"),
            metadata=d.get("metadata", {}) or {},
        )


# --- Score dimensions -----------------------------------------------------
# A score grades either the *output* (does the answer match) or the *trace* (was the
# process sound — did a verification happen). The report renders the two dimensions in
# separate, clearly-labelled sections so a process verdict is never read as a correctness
# verdict. Defaults to output, so every existing scorer and stored run is unchanged.
DIM_OUTPUT = "output"
DIM_TRACE = "trace"


@dataclass
class Score:
    """A scorer's judgement of one result.

    ``value`` is a numeric score (reference scorers use 0.0/1.0); ``passed`` is the
    boolean the pass rate aggregates over; ``detail`` carries scorer-specific context
    (e.g. what was expected vs. what was produced) for the report and for debugging.
    ``dimension`` says whether this grades the output or the trace, so the report can keep
    the two apart.
    """

    case_id: str
    scorer: str
    value: float
    passed: bool
    dimension: str = DIM_OUTPUT
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scorer": self.scorer,
            "value": self.value,
            "passed": self.passed,
            "dimension": self.dimension,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Score:
        return cls(
            case_id=d["case_id"],
            scorer=d["scorer"],
            value=d["value"],
            passed=d["passed"],
            dimension=d.get("dimension", DIM_OUTPUT),
            detail=d.get("detail", {}) or {},
        )
