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
