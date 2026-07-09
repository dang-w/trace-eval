"""Task 1.6 done-when: `run tasks/sample` produces report.md end to end.

Runs the real CLI against the real sample task, with a fake ModelCaller so there's no
network or API key — proving the full load → run → score → store → report wiring.
"""

import json
import time
from pathlib import Path

from traceeval.cli import load_task, main
from traceeval.types import STEP_MODEL_CALL, TokenUsage, TraceStep

SAMPLE_TASK = Path(__file__).parents[1] / "tasks" / "sample"


def always_paris(prompt: str, model: str, max_tokens: int) -> TraceStep:
    """A stand-in model that always answers 'Paris' — so exactly one sample case passes."""
    now = time.time()
    return TraceStep(
        kind=STEP_MODEL_CALL,
        input=[{"role": "user", "content": prompt}],
        output="Paris",
        model=model,
        usage=TokenUsage(input_tokens=len(prompt), output_tokens=1),
        started_at=now,
        ended_at=now + 0.01,
        duration_s=0.01,
        metadata={"stop_reason": "end_turn"},
    )


def test_sample_task_loads():
    name, cases = load_task(SAMPLE_TASK)
    assert name == "sample"
    assert len(cases) == 5
    assert cases[0].reference == "4"


def test_run_sample_end_to_end(tmp_path):
    code = main(
        ["run", str(SAMPLE_TASK), "--scorer", "reference", "--model", "test-model", "--out", str(tmp_path)],
        model_caller=always_paris,
    )
    assert code == 0

    # report.md is produced with a pass rate and per-case rows.
    report = (tmp_path / "report.md").read_text()
    assert "1/5 (20%)" in report            # only capital-france matches "Paris"
    assert "| capital-france |" in report
    assert report.count("| ") > 5           # header + 5 case rows

    # results JSON persisted and reloads as valid JSON carrying traces.
    run_files = list(tmp_path.glob("sample-*.json"))
    assert len(run_files) == 1
    data = json.loads(run_files[0].read_text())
    assert len(data["results"]) == 5
    assert data["results"][0]["trace"]["steps"][0]["kind"] == STEP_MODEL_CALL
    assert data["meta"]["model"] == "test-model"


def test_unknown_scorer_exits_2(tmp_path):
    code = main(["run", str(SAMPLE_TASK), "--scorer", "nope", "--out", str(tmp_path)], model_caller=always_paris)
    assert code == 2


# --- self-check task, graded by the trace scorer (task 4) ---------------------

SELF_CHECK_TASK = Path(__file__).parents[1] / "tasks" / "self-check"


def self_checking_caller(prompt: str, model: str, max_tokens: int) -> TraceStep:
    """Answer briefly on the first call; on the verify call (recognised by the carried-in
    prior answer) return a substantive check. Works for any number of cases."""
    now = time.time()
    is_verify = "You previously answered:" in prompt
    output = "Rechecked the working step by step; the answer holds." if is_verify else "42"
    return TraceStep(
        kind=STEP_MODEL_CALL,
        input=[{"role": "user", "content": prompt}],
        output=output,
        model=model,
        usage=TokenUsage(input_tokens=len(prompt), output_tokens=len(output)),
        started_at=now,
        ended_at=now + 0.01,
        duration_s=0.01,
        metadata={"stop_reason": "end_turn"},
    )


def test_self_check_task_loads():
    name, cases = load_task(SELF_CHECK_TASK)
    assert name == "self-check"
    assert len(cases) == 4
    assert all(c.self_check for c in cases)


def test_run_self_check_end_to_end(tmp_path):
    code = main(
        ["run", str(SELF_CHECK_TASK), "--scorer", "verify_before_assert",
         "--model", "test-model", "--out", str(tmp_path)],
        model_caller=self_checking_caller,
    )
    assert code == 0

    # The report surfaces trace-level verdicts distinctly. Every case verified → 4/4.
    report = (tmp_path / "report.md").read_text()
    assert "## Trace-level scores (process)" in report
    assert "4/4 (100%)" in report
    assert "| count-r-strawberry |" in report

    # Persisted run carries a real 2-step trace per case, roles tagged.
    run_files = list(tmp_path.glob("self-check-*.json"))
    assert len(run_files) == 1
    data = json.loads(run_files[0].read_text())
    steps = data["results"][0]["trace"]["steps"]
    assert len(steps) == 2
    assert steps[0]["metadata"]["role"] == "answer"
    assert steps[1]["metadata"]["role"] == "verify"
    assert data["scores"][0]["dimension"] == "trace"
