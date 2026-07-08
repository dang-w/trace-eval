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

from traceeval.types import Case, Result, Score

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
