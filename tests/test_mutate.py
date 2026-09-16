"""#55 done-when: a populated mutants/ dir, a `mutate` run producing a per-scorer kill-rate
table, and at least one existing scorer demonstrated against it — kill-all or caught vacuous,
either is a finding.

Mutants are static fixtures, so everything here is offline and deterministic: no model
caller, no network, no key.
"""

import json
from pathlib import Path

from traceeval.cli import load_task, main
from traceeval.mutate import (
    MUTANT_CLASSES,
    Mutant,
    MutationRecord,
    load_mutants,
    run_mutation,
)
from traceeval.report import render_mutation_report
from traceeval.scorers import reference_scorer, verify_before_assert
from traceeval.types import Case, DIM_OUTPUT, DIM_TRACE, Result, ROLE_ANSWER, ROLE_VERIFY, STEP_MODEL_CALL, Score, Trace, TraceStep

SOUNDNESS_TASK = Path(__file__).parents[1] / "tasks" / "soundness"
MUTANTS_DIR = SOUNDNESS_TASK / "mutants"


def _step(role: str, output: str) -> TraceStep:
    return TraceStep(kind=STEP_MODEL_CALL, output=output, metadata={"role": role})


def _good_result(case_id: str = "c1") -> Result:
    return Result(
        case_id=case_id,
        output="5",
        trace=Trace(steps=[_step(ROLE_ANSWER, "5"), _step(ROLE_VERIFY, "2x + 100 = 110, so x = 5. Confirmed.")]),
    )


def _mutant(cls: str, result: Result, case_id: str = "c1") -> Mutant:
    return Mutant(id=f"{case_id}--{cls}", cls=cls, case_id=case_id, result=result, synthetic=True, note="test")


CASE = Case(id="c1", input="q", reference="5")


# --- fixtures ---------------------------------------------------------------

def test_soundness_mutants_cover_every_class_and_are_labelled_synthetic():
    mutants = load_mutants(SOUNDNESS_TASK)
    classes = {m.cls for m in mutants}
    assert set(MUTANT_CLASSES) <= classes            # the five required classes, at least
    assert "baseline" in classes                     # plus the unmodified control
    assert all(m.synthetic for m in mutants)         # no fixture pretends to be a live run
    assert all(m.note for m in mutants)              # every edit is described


def test_soundness_mutants_point_at_real_cases():
    _, cases = load_task(SOUNDNESS_TASK)
    case_ids = {c.id for c in cases}
    for m in load_mutants(SOUNDNESS_TASK):
        assert m.case_id in case_ids, m.id
        assert m.result.case_id == m.case_id, m.id


def test_load_mutants_rejects_unknown_class(tmp_path):
    (tmp_path / "mutants").mkdir()
    (tmp_path / "mutants" / "x.json").write_text(json.dumps(
        {"id": "x", "class": "made-up", "case_id": "c1", "synthetic": True, "note": "n",
         "result": _good_result().to_dict()}))
    try:
        load_mutants(tmp_path)
    except ValueError as exc:
        assert "made-up" in str(exc)
    else:
        raise AssertionError("unknown mutant class should be rejected")


# --- kill semantics ---------------------------------------------------------

def test_killed_means_applicable_scorer_failed_the_mutant():
    wrong = _good_result()
    wrong.output = "10"
    record = run_mutation([CASE], [_mutant("wrong-answer", wrong)], {"reference": reference_scorer})
    (outcome,) = record.outcomes
    assert outcome.mutant_id == "c1--wrong-answer"
    assert outcome.scorer == "reference"
    assert outcome.applicable is True
    assert outcome.killed is True


def test_out_of_dimension_scorer_is_recorded_but_not_applicable():
    """The reference scorer correctly passes a trace-only mutant — that is not a survival."""
    empty = _good_result()
    empty.trace.steps[1].output = ""
    record = run_mutation([CASE], [_mutant("empty-verify", empty)], {"reference": reference_scorer})
    (outcome,) = record.outcomes
    assert outcome.applicable is False
    assert outcome.killed is False
    assert record.kill_rates["reference"].applicable == 0


def test_survivor_carries_the_class_it_accepted():
    """A verify step that re-derives a different value but leaves the answer alone: does the
    structural trace scorer notice? This is the vacuity probe — the scorer's verdict is the finding."""
    contradicted = _good_result()
    contradicted.trace.steps[1].output = "x + (x + 100) = 110 so x = 10. The ball costs 10 cents."
    record = run_mutation([CASE], [_mutant("contradicted-verify", contradicted)],
                          {"verify_before_assert": verify_before_assert})
    (outcome,) = record.outcomes
    assert outcome.applicable is True
    assert outcome.killed is False
    assert outcome.passed is True
    assert record.kill_rates["verify_before_assert"].survivors == ["c1--contradicted-verify"]


def test_kill_rate_counts_applicable_only():
    wrong = _good_result(); wrong.output = "10"
    empty = _good_result(); empty.trace.steps[1].output = ""
    record = run_mutation(
        [CASE],
        [_mutant("baseline", _good_result()), _mutant("wrong-answer", wrong), _mutant("empty-verify", empty)],
        {"reference": reference_scorer, "verify_before_assert": verify_before_assert},
    )
    ref = record.kill_rates["reference"]
    assert (ref.killed, ref.applicable) == (1, 1)
    assert ref.rate == 1.0
    vba = record.kill_rates["verify_before_assert"]
    assert (vba.killed, vba.applicable) == (1, 1)
    # Baseline is never "applicable" — it is the control, and both scorers passed it.
    assert ref.baseline_passed is True and vba.baseline_passed is True


def test_baseline_failure_is_flagged_as_vacuous():
    """A scorer that fails the unmodified run kills every mutant for free; its kill rate is void."""
    def fail_everything(case: Case, result: Result) -> Score:
        return Score(case_id=case.id, scorer="nope", value=0.0, passed=False, dimension=DIM_TRACE)
    empty = _good_result(); empty.trace.steps[1].output = ""
    record = run_mutation([CASE], [_mutant("baseline", _good_result()), _mutant("empty-verify", empty)],
                          {"nope": fail_everything})
    kr = record.kill_rates["nope"]
    assert kr.baseline_passed is False
    assert kr.rate is None          # not a measured 100% — the number is withheld, not inflated


def test_missing_baseline_withholds_the_kill_rate():
    """No control → the scorer might fail everything → a kill rate would be free. Withhold it."""
    wrong = _good_result(); wrong.output = "10"
    record = run_mutation([CASE], [_mutant("wrong-answer", wrong)], {"reference": reference_scorer})
    kr = record.kill_rates["reference"]
    assert kr.baseline_passed is None
    assert kr.rate is None
    assert "no baseline" in render_mutation_report(record)


def test_duplicate_baseline_for_a_case_is_rejected():
    try:
        run_mutation([CASE], [_mutant("baseline", _good_result()), _mutant("baseline", _good_result())],
                     {"reference": reference_scorer})
    except ValueError as exc:
        assert "baseline" in str(exc) and "c1" in str(exc)
    else:
        raise AssertionError("two baselines for one case must be rejected")


def test_duplicate_mutant_id_is_rejected():
    wrong = _good_result(); wrong.output = "10"
    dup = [_mutant("wrong-answer", wrong), _mutant("wrong-answer", wrong)]
    try:
        run_mutation([CASE], dup, {"reference": reference_scorer})
    except ValueError as exc:
        assert "c1--wrong-answer" in str(exc)
    else:
        raise AssertionError("duplicate mutant ids must be rejected")


def test_baseline_gate_is_per_case():
    """A second case with its own failing baseline voids the scorer's rate; a second case with
    NO baseline withholds it — the bat-and-ball control must not vouch for lily-pads mutants."""
    other = Case(id="c2", input="q", reference="7")
    good2 = _good_result("c2"); good2.output = "7"; good2.trace.steps[0].output = "7"
    wrong2 = _good_result("c2"); wrong2.output = "8"
    wrong1 = _good_result(); wrong1.output = "10"

    # c2 has mutants but no baseline → withheld.
    record = run_mutation([CASE, other],
                          [_mutant("baseline", _good_result()), _mutant("wrong-answer", wrong1),
                           _mutant("wrong-answer", wrong2, case_id="c2")],
                          {"reference": reference_scorer})
    kr = record.kill_rates["reference"]
    assert kr.baselines == {"c1": True, "c2": None}
    assert kr.baseline_passed is None and kr.rate is None

    # c2 baseline present and passing → measured over both cases.
    record = run_mutation([CASE, other],
                          [_mutant("baseline", _good_result()), _mutant("wrong-answer", wrong1),
                           _mutant("baseline", good2, case_id="c2"), _mutant("wrong-answer", wrong2, case_id="c2")],
                          {"reference": reference_scorer})
    kr = record.kill_rates["reference"]
    assert kr.baselines == {"c1": True, "c2": True}
    assert kr.baseline_passed is True and (kr.killed, kr.applicable) == (2, 2)


def test_mutant_for_unknown_case_is_an_error():
    try:
        run_mutation([CASE], [_mutant("baseline", _good_result(case_id="ghost"), case_id="ghost")],
                     {"reference": reference_scorer})
    except KeyError as exc:
        assert "ghost" in str(exc)
    else:
        raise AssertionError("a mutant must reference a case in the task")


# --- report -----------------------------------------------------------------

def test_report_leads_with_kill_rates_and_names_survivors_diagnostically():
    wrong = _good_result(); wrong.output = "10"
    contradicted = _good_result()
    contradicted.trace.steps[1].output = "x + (x + 100) = 110 so x = 10. The ball costs 10 cents."
    record = run_mutation(
        [CASE],
        [_mutant("baseline", _good_result()), _mutant("wrong-answer", wrong), _mutant("contradicted-verify", contradicted)],
        {"reference": reference_scorer, "verify_before_assert": verify_before_assert},
        task_name="t",
    )
    report = render_mutation_report(record)
    assert "# Mutation Report — t" in report
    assert "| reference | pass | 1/1 | 100% |" in report
    assert "| verify_before_assert | pass | 0/1 | 0% |" in report
    assert "accepted a broken run of class contradicted-verify" in report
    assert "all labelled synthetic" in report      # a fact read off the mutants, not a constant
    assert "🎉" not in report and "great" not in report.lower()   # diagnostic, not celebratory


def test_report_never_truncates_the_survivors_list():
    """Survivor ids are the finding; a '…' in that cell would hide which mutant got through."""
    survivors = []
    for i in range(4):
        m = _good_result(); m.trace.steps[1].output = f"x + (x + 100) = 110 so x = 10. Long verify number {i}."
        survivors.append(Mutant(id=f"c1--contradicted-verify-with-a-long-identifier-{i}", cls="contradicted-verify",
                                case_id="c1", result=m, synthetic=True, note="test"))
    record = run_mutation([CASE], survivors, {"verify_before_assert": verify_before_assert})
    report = render_mutation_report(record)
    for m in survivors:
        assert m.id in report.split("## Survivors")[0]     # every id, intact, in the kill-rate table


def test_report_flags_mutants_not_labelled_synthetic_and_shows_provenance():
    real = _mutant("wrong-answer", _good_result())
    real.synthetic = False
    real.provenance = "captured from a live run on 2026-09-16"
    record = run_mutation([CASE], [_mutant("baseline", _good_result()), real], {"reference": reference_scorer})
    report = render_mutation_report(record)
    assert "1 NOT labelled synthetic" in report
    assert "captured from a live run on 2026-09-16" in report


def test_report_marks_void_kill_rate_when_baseline_fails():
    def fail_everything(case: Case, result: Result) -> Score:
        return Score(case_id=case.id, scorer="nope", value=0.0, passed=False, dimension=DIM_OUTPUT)
    wrong = _good_result(); wrong.output = "10"
    record = run_mutation([CASE], [_mutant("baseline", _good_result()), _mutant("wrong-answer", wrong)],
                          {"nope": fail_everything})
    report = render_mutation_report(record)
    assert "fails the baseline" in report
    assert "100%" not in report


# --- CLI --------------------------------------------------------------------

def test_mutate_command_end_to_end(tmp_path):
    """`trace-eval mutate tasks/soundness` — no model calls, deterministic, writes JSON + report."""
    code = main(["mutate", str(SOUNDNESS_TASK), "--out", str(tmp_path)])
    assert code == 0

    report = (tmp_path / "mutation_report.md").read_text()
    assert "# Mutation Report — soundness" in report
    assert "| reference |" in report
    assert "| verify_before_assert |" in report

    files = list(tmp_path.glob("mutation-soundness-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert set(data["kill_rates"]) == {"reference", "verify_before_assert"}
    assert data["meta"]["task"] == "soundness"
    assert len(data["outcomes"]) == 6 * 2          # six fixtures × two scorers
    # Full round-trip: re-serialising the loaded record reproduces the file byte-for-byte.
    assert MutationRecord.from_dict(data).to_dict() == data

    # Pin the shipped headline numbers (README + examples/mutation quote them). A change to
    # MIN_VERIFY_CHARS or a class's dimension must fail here, not silently re-write the finding.
    vba = data["kill_rates"]["verify_before_assert"]
    assert (vba["killed"], vba["applicable"], vba["rate"]) == (2, 4, 0.5)
    assert vba["survivors"] == ["bat-and-ball--contradicted-verify", "bat-and-ball--rubber-stamp"]
    ref = data["kill_rates"]["reference"]
    assert ref["baseline_passed"] is False and ref["rate"] is None
    assert "| reference | FAIL | 1/1 | void" in report
    assert "| verify_before_assert | pass | 2/4 | 50% |" in report


def test_mutate_command_without_mutants_dir_exits_2(tmp_path):
    (tmp_path / "cases.json").write_text("[]")
    code = main(["mutate", str(tmp_path), "--out", str(tmp_path)])
    assert code == 2


def test_mutate_command_with_empty_mutants_dir_exits_2(tmp_path, capsys):
    (tmp_path / "cases.json").write_text("[]")
    (tmp_path / "mutants").mkdir()
    code = main(["mutate", str(tmp_path), "--out", str(tmp_path)])
    assert code == 2
    assert "no mutant" in capsys.readouterr().err


def test_mutate_command_reports_bad_fixture_and_exits_2(tmp_path, capsys):
    """Authoring errors (unknown class, unknown case, malformed JSON) get the crafted message
    and exit 2 — the same contract as a missing file — not a traceback and exit 1."""
    (tmp_path / "cases.json").write_text(json.dumps([CASE.to_dict()]))
    mutants = tmp_path / "mutants"; mutants.mkdir()
    bad = mutants / "bad.json"

    bad.write_text(json.dumps({"id": "x", "class": "made-up", "case_id": "c1", "synthetic": True,
                               "note": "n", "result": _good_result().to_dict()}))
    assert main(["mutate", str(tmp_path), "--out", str(tmp_path)]) == 2
    assert "made-up" in capsys.readouterr().err

    bad.write_text(json.dumps({"id": "x", "class": "baseline", "case_id": "ghost", "synthetic": True,
                               "note": "n", "result": _good_result("ghost").to_dict()}))
    assert main(["mutate", str(tmp_path), "--out", str(tmp_path)]) == 2
    assert "ghost" in capsys.readouterr().err

    bad.write_text("{not json")
    assert main(["mutate", str(tmp_path), "--out", str(tmp_path)]) == 2
    assert "bad.json" in capsys.readouterr().err
