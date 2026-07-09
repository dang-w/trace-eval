"""Scorers.

The pluggable-scorer seam is deliberately tiny: a scorer is a plain function

    (Case, Result) -> Score

Nothing more. No registry, no base class, no plugin system — you pass the function you
want to the report/CLI. New scorers (a trace-level scorer that inspects
``result.trace.steps``, an LLM-judge, a semantic-diff scorer) are just more functions of
this shape; none of them need to change anything here.

v1 ships one reference-based scorer: a normalised exact match against ``case.reference``.
"""

from __future__ import annotations

import re
import string
from typing import Callable

from traceeval.types import (
    Case,
    DIM_TRACE,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    Score,
)

# A scorer is any function of this shape. This *is* the interface.
Scorer = Callable[[Case, Result], Score]


def _normalise(text: str) -> str:
    """Lowercase, trim, collapse internal whitespace, strip surrounding punctuation.

    Keeps the match tolerant of trivial formatting differences ("4" vs "4." vs " 4 ")
    without trying to be clever — this is the simplest useful reference scorer.
    """
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(string.punctuation + string.whitespace)


def reference_scorer(case: Case, result: Result) -> Score:
    """Score a result by normalised exact match against ``case.reference``.

    Non-matches (including a failed run or a case with no reference) score 0.0 / not
    passed, with the reason in ``detail`` so the report and any debugging can see why.
    """
    detail: dict = {"expected": case.reference, "got": result.output}

    if case.reference is None:
        detail["reason"] = "case has no reference"
        return Score(case_id=case.id, scorer="reference", value=0.0, passed=False, detail=detail)

    if result.error is not None:
        detail["reason"] = f"run errored: {result.error}"
        return Score(case_id=case.id, scorer="reference", value=0.0, passed=False, detail=detail)

    passed = _normalise(result.output) == _normalise(case.reference)
    return Score(
        case_id=case.id,
        scorer="reference",
        value=1.0 if passed else 0.0,
        passed=passed,
        detail=detail,
    )


# --- Trace-level scorer ----------------------------------------------------
# The first scorer that grades the *process*, not the output. It reads
# ``result.trace.steps`` rather than ``result.output``: was there a verification pass over
# the initial answer before it was committed?
#
# The substance bar is deliberately STRUCTURAL, and it is a floor not a ceiling: it confirms
# a real second pass happened (a verify step, after the answer, that isn't empty and isn't a
# one-token rubber-stamp). It does NOT judge whether the verification was *semantically*
# correct — whether it caught the right thing. That is an LLM-as-judge trace scorer, a later
# build (#43). Keeping v1 structural keeps it pure, deterministic, and testable offline.
MIN_VERIFY_CHARS = 10


def _trace_score(case: Case, value: float, passed: bool, detail: dict) -> Score:
    return Score(
        case_id=case.id,
        scorer="verify_before_assert",
        value=value,
        passed=passed,
        dimension=DIM_TRACE,
        detail=detail,
    )


def verify_before_assert(case: Case, result: Result) -> Score:
    """Pass iff a substantive verification step revisited the answer before it was committed.

    Reads the trace, not the output. Passes when the trace holds a ``verify``-role step that
    (a) comes after an ``answer``-role step, (b) is non-empty, and (c) clears
    ``MIN_VERIFY_CHARS`` — the structural substance floor documented above. Every failure
    records a ``reason`` in ``detail`` (no verify step / empty / too brief / run errored) so
    the report and any debugging can see exactly why.
    """
    steps = result.trace.steps
    detail: dict = {}

    if result.error is not None:
        detail["reason"] = f"run errored: {result.error}"
        return _trace_score(case, 0.0, False, detail)

    answer_idx = next(
        (i for i, s in enumerate(steps) if s.metadata.get("role") == ROLE_ANSWER),
        None,
    )
    verify_idx = next(
        (
            i
            for i, s in enumerate(steps)
            if s.metadata.get("role") == ROLE_VERIFY and answer_idx is not None and i > answer_idx
        ),
        None,
    )

    if verify_idx is None:
        detail["reason"] = "no verification step after the answer"
        return _trace_score(case, 0.0, False, detail)

    output = steps[verify_idx].output
    text = (output if isinstance(output, str) else str(output)).strip()
    detail["verify_output"] = text
    detail["char_count"] = len(text)

    if not text:
        detail["reason"] = "verification step is empty"
        return _trace_score(case, 0.0, False, detail)
    if len(text) < MIN_VERIFY_CHARS:
        detail["reason"] = f"verification step too brief (<{MIN_VERIFY_CHARS} chars)"
        return _trace_score(case, 0.0, False, detail)

    detail["reason"] = "substantive verification step revisited the answer"
    return _trace_score(case, 1.0, True, detail)
