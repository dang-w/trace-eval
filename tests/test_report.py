"""Task 1.5 done-when: a run emits a report with pass rate and per-case rows."""

from traceeval.report import render_report, write_report
from traceeval.runner import run_cases
from traceeval.scorers import reference_scorer
from traceeval.store import RunRecord
from traceeval.types import (
    Case,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    STEP_MODEL_CALL,
    Trace,
    TraceStep,
)
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
    assert "| Case | Verified | Score | Changed | Verification | Reason |" in md
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


# --- answer_changed (task 1.1) ------------------------------------------------

def _role_step(role: str, output: str) -> TraceStep:
    return TraceStep(kind=STEP_MODEL_CALL, output=output, metadata={"role": role})


def test_answer_changed_flags_revision_kept_and_single_step():
    from traceeval.report import answer_changed

    revised = Result(case_id="c1", output="7",
                     trace=Trace(steps=[_role_step(ROLE_ANSWER, "8"), _role_step(ROLE_VERIFY, "7")]))
    assert answer_changed(revised) is True

    kept = Result(case_id="c2", output="8",
                  trace=Trace(steps=[_role_step(ROLE_ANSWER, "8"), _role_step(ROLE_VERIFY, "8")]))
    assert answer_changed(kept) is False

    # No verify step → nothing could have changed the answer → None (not False).
    single = Result(case_id="c3", output="8", trace=Trace(steps=[_role_step(ROLE_ANSWER, "8")]))
    assert answer_changed(single) is None

    # Errored run → None.
    errored = Result(case_id="c4", output="", trace=Trace(), error="boom")
    assert answer_changed(errored) is None


def test_trace_section_reports_answer_changed():
    from traceeval.types import DIM_TRACE, Score
    results = [
        Result(case_id="c1", output="7",
               trace=Trace(steps=[_role_step(ROLE_ANSWER, "8"), _role_step(ROLE_VERIFY, "7")])),
        Result(case_id="c2", output="8",
               trace=Trace(steps=[_role_step(ROLE_ANSWER, "8"), _role_step(ROLE_VERIFY, "8")])),
    ]
    scores = [
        Score(case_id="c1", scorer="verify_before_assert", value=1.0, passed=True,
              dimension=DIM_TRACE, detail={"verify_output": "recheck: 7", "reason": "ok"}),
        Score(case_id="c2", scorer="verify_before_assert", value=1.0, passed=True,
              dimension=DIM_TRACE, detail={"verify_output": "confirmed 8", "reason": "ok"}),
    ]
    md = render_report(RunRecord(results=results, scores=scores, meta={"task": "t"}))
    assert "Changed" in md  # a column surfacing whether the answer changed
    # c1's answer changed (8 → 7), c2's did not.
    lines = {ln.split("|")[1].strip(): ln for ln in md.splitlines() if ln.startswith("| c")}
    assert "yes" in lines["c1"].lower()
    assert "no" in lines["c2"].lower()


# --- meta-eval report (task 5.1) ----------------------------------------------

def _meta_record():
    from traceeval.metaeval import (
        GoldAgreement,
        GoldDisagreement,
        ItemConsistency,
        JudgeSample,
        MetaEvalRecord,
        SelfConsistency,
    )

    def item(cid, *verdicts):
        return ItemConsistency(case_id=cid, samples=[JudgeSample(v, "r", f"VERDICT: {v}") for v in verdicts])

    sc = SelfConsistency(k=3, items=[
        item("c1", "sound", "sound", "sound"),        # unanimous
        item("c2", "sound", "unsound", "sound"),      # flipped
    ])
    ga = GoldAgreement(n=2, agreement=0.5,
                       disagreements=[GoldDisagreement(case_id="c2", judge="sound", human="unsound")])
    return MetaEvalRecord(judge_meta={"judge_model": "jm", "judge_max_tokens": 256, "k": 3},
                          self_consistency=sc, gold_agreement=ga)


def test_meta_report_leads_with_trust_before_verdicts():
    from traceeval.report import render_meta_report
    md = render_meta_report(_meta_record())

    # Trust figures are present, with numbers.
    assert "Self-consistency" in md
    assert "Gold-agreement" in md
    assert "50%" in md          # gold agreement
    # The judge's own verdicts appear too...
    assert "Majority" in md or "verdict" in md.lower()
    # ...but the trust section comes strictly BEFORE the verdicts section.
    trust_pos = md.lower().find("how much to trust")
    verdict_pos = md.lower().find("judge verdict")
    assert trust_pos != -1 and verdict_pos != -1
    assert trust_pos < verdict_pos


def test_meta_report_lists_disagreements_and_flips():
    from traceeval.report import render_meta_report
    md = render_meta_report(_meta_record())
    # Disagreement with the human gold is enumerated.
    assert "c2" in md
    # The flipped item is visible as flipped / non-unanimous.
    assert "flip" in md.lower()
    # Judge model + K recorded for reproducibility.
    assert "jm" in md and "3" in md


def test_write_meta_report_creates_file(tmp_path):
    from traceeval.report import write_meta_report
    path = write_meta_report(_meta_record(), tmp_path / "meta" / "meta_report.md")
    assert path.exists()
    assert "trust" in path.read_text().lower()


def test_trace_section_shows_judge_rationale_when_no_reason():
    """A judge score carries a 'rationale' but no 'reason' — the report must still surface it."""
    from traceeval.types import DIM_TRACE, Score
    results = [Result(case_id="c1", output="5",
                      trace=Trace(steps=[_role_step(ROLE_ANSWER, "10"), _role_step(ROLE_VERIFY, "recheck: 5")]))]
    scores = [Score(case_id="c1", scorer="verification_sound", value=1.0, passed=True, dimension=DIM_TRACE,
                    detail={"verdict": "sound", "rationale": "the verification corrected 10 to 5",
                            "verify_output": "recheck: 5"})]
    md = render_report(RunRecord(results=results, scores=scores, meta={"task": "t"}))
    assert "the verification corrected 10 to 5" in md
