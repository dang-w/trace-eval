"""Task 1.3 done-when: the scorer produces Scores for Results (via the pluggable interface)."""

from traceeval.runner import run_cases
from traceeval.scorers import reference_scorer, _normalise
from traceeval.types import Case, Result, Trace
from tests.test_runner import fake_caller


def test_reference_scorer_matches_normalised():
    case = Case(id="c1", input="What is 2 + 2?", reference="4")
    result = Result(case_id="c1", output="  4.  ", trace=Trace())
    score = reference_scorer(case, result)
    assert score.passed is True
    assert score.value == 1.0
    assert score.scorer == "reference"


def test_reference_scorer_reports_mismatch():
    case = Case(id="c1", input="Capital of France?", reference="Paris")
    result = Result(case_id="c1", output="London", trace=Trace())
    score = reference_scorer(case, result)
    assert score.passed is False
    assert score.detail["expected"] == "Paris"
    assert score.detail["got"] == "London"


def test_reference_scorer_handles_missing_reference_and_errors():
    no_ref = reference_scorer(Case(id="c1", input="x"), Result(case_id="c1", output="anything"))
    assert no_ref.passed is False and "no reference" in no_ref.detail["reason"]

    errored = reference_scorer(
        Case(id="c2", input="x", reference="y"),
        Result(case_id="c2", output="", error="RuntimeError: boom"),
    )
    assert errored.passed is False and "errored" in errored.detail["reason"]


def test_scorer_runs_over_runner_results():
    """End-to-end through the pluggable interface: run cases, then score each result."""
    cases = [Case(id="c1", input="hi", reference="answer to: hi")]
    results = run_cases(cases, model="test", model_caller=fake_caller)
    scores = [reference_scorer(c, r) for c, r in zip(cases, results)]
    assert len(scores) == 1
    assert scores[0].passed is True  # fake_caller echoes "answer to: {prompt}"


def test_normalise_strips_punctuation_and_case():
    assert _normalise("  The Answer!! ") == "the answer"
