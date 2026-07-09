"""Task 1.2 done-when: running a 3-case task returns Results with output + trace populated.

Uses a fake ModelCaller so the runner is exercised with no network and no API key.
"""

import time

from traceeval.runner import run_case, run_cases
from traceeval.types import (
    Case,
    ROLE_ANSWER,
    ROLE_VERIFY,
    TokenUsage,
    TraceStep,
    STEP_MODEL_CALL,
)


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


class ScriptedCaller:
    """A test double that returns pre-scripted outputs in order, one per model call.

    Multi-step runs call the model more than once; this scripts each step's response and
    records the prompts it received, so a test can assert what was carried into the verify
    step. Matches the ``ModelCaller`` signature (it's callable).
    """

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs)
        self._i = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model: str, max_tokens: int) -> TraceStep:
        self.prompts.append(prompt)
        out = self._outputs[self._i]
        self._i += 1
        now = time.time()
        return TraceStep(
            kind=STEP_MODEL_CALL,
            input=[{"role": "user", "content": prompt}],
            output=out,
            model=model,
            usage=TokenUsage(input_tokens=len(prompt), output_tokens=len(out)),
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


# --- Multi-step (self-check) --------------------------------------------------

def test_self_check_case_yields_answer_then_verify_trace():
    """Task 1 done-when: a self-check case yields answer step then verify step, in order."""
    caller = ScriptedCaller("7", "Rechecking 3+4 = 7, that is correct. Final answer: 7")
    case = Case(id="c1", input="What is 3 + 4?", self_check="Recheck your arithmetic.")

    result = run_case(case, model_caller=caller)

    assert result.error is None
    assert len(result.trace.steps) == 2
    assert result.trace.steps[0].metadata["role"] == ROLE_ANSWER
    assert result.trace.steps[1].metadata["role"] == ROLE_VERIFY
    # Final output is the *last* step's output — a self-check can revise the answer.
    assert result.output == "Rechecking 3+4 = 7, that is correct. Final answer: 7"
    # The prior answer and the self-check instruction were carried into the verify prompt.
    verify_prompt = caller.prompts[1]
    assert "7" in verify_prompt
    assert "Recheck your arithmetic." in verify_prompt


def test_self_check_can_revise_the_answer():
    """The verify step's output becomes the final output, so it can correct a wrong first pass."""
    caller = ScriptedCaller("8", "3 + 4 is 7, not 8. Correcting. Final answer: 7")
    case = Case(id="c1", input="What is 3 + 4?", reference="7", self_check="Recheck.")

    result = run_case(case, model_caller=caller)

    assert result.output == "3 + 4 is 7, not 8. Correcting. Final answer: 7"
    assert result.trace.steps[0].output == "8"  # the (wrong) first answer is preserved in the trace


def test_no_self_check_stays_single_step():
    """Backwards compatible: a case without self_check produces exactly one step, as in v1."""
    result = run_case(Case(id="c1", input="hi"), model_caller=fake_caller)
    assert len(result.trace.steps) == 1
    assert result.trace.steps[0].metadata["role"] == ROLE_ANSWER
    assert result.output == "answer to: hi"


def test_verify_step_failure_preserves_answer_step():
    """If the verify call fails, the successful answer step is kept in the trace for debugging."""
    calls = {"n": 0}

    def answer_then_boom(prompt, model, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            return fake_caller(prompt, model, max_tokens)
        raise RuntimeError("verify exploded")

    case = Case(id="c1", input="x", self_check="check it")
    result = run_case(case, model_caller=answer_then_boom)

    assert result.error == "RuntimeError: verify exploded"
    assert result.output == ""
    assert len(result.trace.steps) == 1  # the answer step survives
    assert result.trace.steps[0].metadata["role"] == ROLE_ANSWER
