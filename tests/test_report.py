"""Task 1.5 done-when: a run emits a report with pass rate and per-case rows."""

from traceeval.report import render_report, write_report
from traceeval.runner import run_cases
from traceeval.scorers import reference_scorer
from traceeval.store import RunRecord
from traceeval.types import Case, Result, Trace
from tests.test_runner import fake_caller


def _record():
    cases = [
        Case(id="c1", input="hi", reference="answer to: hi"),   # fake_caller passes this
        Case(id="c2", input="bye", reference="wrong"),           # this fails
    ]
    results = run_cases(cases, model="test", model_caller=fake_caller)
    scores = [reference_scorer(c, r) for c, r in zip(cases, results)]
    return RunRecord(results=results, scores=scores, meta={"task": "sample", "model": "test"})


def test_report_has_pass_rate_and_rows():
    md = render_report(_record())
    assert "# Eval Report — sample" in md
    assert "**Pass rate:** 1/2 (50%)" in md
    assert "| c1 |" in md and "| c2 |" in md
    assert "✅" in md and "❌" in md
    # Header row present
    assert "| Case | Pass | Score | Expected | Output |" in md


def test_report_shows_error_in_output_column():
    results = [Result(case_id="c1", output="", trace=Trace(), error="RuntimeError: boom")]
    scores = [reference_scorer(Case(id="c1", input="x", reference="y"), results[0])]
    md = render_report(RunRecord(results=results, scores=scores, meta={"task": "t"}))
    assert "RuntimeError: boom" in md
    assert "0/1 (0%)" in md


def test_write_report_creates_file(tmp_path):
    path = write_report(_record(), tmp_path / "out" / "report.md")
    assert path.exists()
    assert "Pass rate" in path.read_text()


def test_cell_escapes_pipes_and_newlines():
    from traceeval.report import _cell
    assert _cell("a|b\nc") == "a\\|b c"


# --- Trace-level section (task 5) ---------------------------------------------

def _trace_record():
    from traceeval.types import DIM_TRACE, Score
    results = [
        Result(case_id="c1", output="Final answer: 7", trace=Trace()),
        Result(case_id="c2", output="8", trace=Trace()),
    ]
    scores = [
        Score(case_id="c1", scorer="verify_before_assert", value=1.0, passed=True,
              dimension=DIM_TRACE, detail={"verify_output": "Rechecked: 3+4=7", "reason": "substantive verification step revisited the answer"}),
        Score(case_id="c2", scorer="verify_before_assert", value=0.0, passed=False,
              dimension=DIM_TRACE, detail={"reason": "no verification step after the answer"}),
    ]
    return RunRecord(results=results, scores=scores, meta={"task": "self-check", "scorer": "verify_before_assert"})


def test_report_renders_trace_section_distinctly():
    md = render_report(_trace_record())
    # Trace scores land in their own labelled section, with process-oriented columns.
    assert "## Trace-level scores (process)" in md
    assert "| Case | Verified | Score | Verification | Reason |" in md
    # Not conflated with output scores: no output table when only trace scores are present.
    assert "## Output scores" not in md
    assert "| Case | Pass | Score | Expected | Output |" not in md
    # The per-case verdict and reason are surfaced.
    assert "| c1 |" in md and "| c2 |" in md
    assert "no verification step after the answer" in md


def test_output_and_trace_sections_are_separate_when_both_present():
    from traceeval.types import DIM_TRACE, Score
    results = [Result(case_id="c1", output="Paris", trace=Trace())]
    scores = [
        Score(case_id="c1", scorer="reference", value=1.0, passed=True, detail={"expected": "Paris"}),
        Score(case_id="c1", scorer="verify_before_assert", value=1.0, passed=True,
              dimension=DIM_TRACE, detail={"verify_output": "checked, correct", "reason": "ok"}),
    ]
    md = render_report(RunRecord(results=results, scores=scores, meta={"task": "t"}))
    assert "## Output scores" in md
    assert "## Trace-level scores (process)" in md
