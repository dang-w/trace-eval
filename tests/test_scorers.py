"""Task 1.3 done-when: the scorer produces Scores for Results (via the pluggable interface)."""

from traceeval.runner import run_cases
from traceeval.scorers import (
    MIN_VERIFY_CHARS,
    reference_scorer,
    verify_before_assert,
    _normalise,
)
from traceeval.types import (
    Case,
    DIM_TRACE,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    STEP_MODEL_CALL,
    Trace,
    TraceStep,
)
from tests.test_runner import fake_caller


def _step(role: str, output: str) -> TraceStep:
    return TraceStep(kind=STEP_MODEL_CALL, output=output, metadata={"role": role})


def _trace(*steps: TraceStep) -> Trace:
    return Trace(steps=list(steps))


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


# --- verify_before_assert (trace-level scorer) --------------------------------

def test_verify_before_assert_passes_on_substantive_verify():
    """A verify step after the answer, with real content, passes — and is a trace-dimension score."""
    result = Result(
        case_id="c1",
        output="Final answer: 7",
        trace=_trace(
            _step(ROLE_ANSWER, "8"),
            _step(ROLE_VERIFY, "3 + 4 is 7, not 8. Correcting to 7."),
        ),
    )
    score = verify_before_assert(Case(id="c1", input="x"), result)
    assert score.passed is True
    assert score.value == 1.0
    assert score.scorer == "verify_before_assert"
    assert score.dimension == DIM_TRACE
    assert "revisited" in score.detail["reason"]


def test_verify_before_assert_fails_without_verify_step():
    """Task 3: the not-verified case — a single-step trace has no verification to grade."""
    result = Result(case_id="c1", output="8", trace=_trace(_step(ROLE_ANSWER, "8")))
    score = verify_before_assert(Case(id="c1", input="x"), result)
    assert score.passed is False
    assert "no verification step" in score.detail["reason"]


def test_verify_before_assert_fails_on_trivial_and_empty_verify():
    """Task 3: the trivial/empty-verify case — a rubber-stamp doesn't clear the substance floor."""
    trivial = verify_before_assert(
        Case(id="c1", input="x"),
        Result(case_id="c1", output="ok", trace=_trace(_step(ROLE_ANSWER, "8"), _step(ROLE_VERIFY, "ok"))),
    )
    assert trivial.passed is False
    assert "too brief" in trivial.detail["reason"]
    assert trivial.detail["char_count"] < MIN_VERIFY_CHARS

    empty = verify_before_assert(
        Case(id="c1", input="x"),
        Result(case_id="c1", output="", trace=_trace(_step(ROLE_ANSWER, "8"), _step(ROLE_VERIFY, "   "))),
    )
    assert empty.passed is False
    assert "empty" in empty.detail["reason"]


def test_verify_before_assert_fails_on_errored_run():
    result = Result(case_id="c1", output="", trace=Trace(), error="RuntimeError: boom")
    score = verify_before_assert(Case(id="c1", input="x"), result)
    assert score.passed is False
    assert "errored" in score.detail["reason"]


def test_verify_before_assert_requires_verify_after_answer():
    """A verify step that precedes the answer (degenerate ordering) does not count."""
    result = Result(
        case_id="c1",
        output="8",
        trace=_trace(
            _step(ROLE_VERIFY, "this verify came first, which is wrong"),
            _step(ROLE_ANSWER, "8"),
        ),
    )
    score = verify_before_assert(Case(id="c1", input="x"), result)
    assert score.passed is False


def test_verify_before_assert_end_to_end_via_runner():
    """Through the real runner + scripted caller: a self-check case is graded from its trace."""
    from tests.test_runner import ScriptedCaller
    from traceeval.runner import run_case

    caller = ScriptedCaller("8", "Rechecking: 3 + 4 = 7, not 8. Final answer: 7")
    case = Case(id="c1", input="What is 3 + 4?", self_check="Recheck your arithmetic.")
    result = run_case(case, model_caller=caller)

    score = verify_before_assert(case, result)
    assert score.passed is True
