"""Task 1.2 done-when: running a 3-case task returns Results with output + trace populated.

Uses a fake ModelCaller so the runner is exercised with no network and no API key.
"""

import time

from traceeval.runner import run_case, run_cases
from traceeval.types import Case, TokenUsage, TraceStep, STEP_MODEL_CALL


def fake_caller(prompt: str, model: str, max_tokens: int) -> TraceStep:
    """Echo a canned answer and populate a full model_call step, like the real caller."""
    now = time.time()
    return TraceStep(
        kind=STEP_MODEL_CALL,
        input=[{"role": "user", "content": prompt}],
        output=f"answer to: {prompt}",
        model=model,
        usage=TokenUsage(input_tokens=len(prompt), output_tokens=3),
        started_at=now,
        ended_at=now + 0.01,
        duration_s=0.01,
        metadata={"stop_reason": "end_turn"},
    )


def _cases():
    return [
        Case(id="c1", input="What is 2 + 2?", reference="4"),
        Case(id="c2", input="Capital of France?", reference="Paris"),
        Case(id="c3", input="Say hello", reference="hello"),
    ]


def test_run_cases_populates_output_and_trace():
    results = run_cases(_cases(), model="test-model", model_caller=fake_caller)

    assert len(results) == 3
    for result, case in zip(results, _cases()):
        assert result.case_id == case.id
        assert result.error is None
        assert result.output == f"answer to: {case.input}"
        # Trace is populated: exactly one model_call step carrying model + usage + timing.
        assert len(result.trace.steps) == 1
        step = result.trace.steps[0]
        assert step.kind == STEP_MODEL_CALL
        assert step.model == "test-model"
        assert step.usage is not None and step.usage.output_tokens == 3
        assert step.duration_s == 0.01


def test_run_case_captures_error_without_raising():
    def boom(prompt, model, max_tokens):
        raise RuntimeError("model exploded")

    result = run_case(Case(id="c1", input="x"), model_caller=boom)

    assert result.error == "RuntimeError: model exploded"
    assert result.output == ""
    assert result.trace.steps == []
