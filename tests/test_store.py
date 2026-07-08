"""Task 1.4 done-when: a run writes a results file that reloads without loss."""

from traceeval.runner import run_cases
from traceeval.scorers import reference_scorer
from traceeval.store import RunRecord, load_run, save_run
from traceeval.types import Case
from tests.test_runner import fake_caller


def test_run_round_trips_through_json_file(tmp_path):
    cases = [
        Case(id="c1", input="hi", reference="answer to: hi"),
        Case(id="c2", input="bye", reference="nope"),
    ]
    results = run_cases(cases, model="test", model_caller=fake_caller)
    scores = [reference_scorer(c, r) for c, r in zip(cases, results)]
    record = RunRecord(results=results, scores=scores, meta={"task": "sample", "model": "test"})

    path = save_run(record, tmp_path / "results" / "run.json")
    assert path.exists()

    reloaded = load_run(path)

    # No loss: results (with full traces), scores, and meta all survive the round-trip.
    assert reloaded.results == results
    assert reloaded.scores == scores
    assert reloaded.meta == {"task": "sample", "model": "test"}
    # The trace survived too — the seam a later trace-level scorer relies on.
    assert reloaded.results[0].trace.steps[0].usage == results[0].trace.steps[0].usage


def test_save_run_creates_parent_dirs(tmp_path):
    record = RunRecord(meta={"task": "empty"})
    path = save_run(record, tmp_path / "deep" / "nested" / "run.json")
    assert path.exists()
    assert load_run(path).meta == {"task": "empty"}
