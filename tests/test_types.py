"""Task 1.1 done-when: a fixture Case and Result round-trip through serialisation cleanly."""

import json

from traceeval.types import (
    Case,
    Result,
    Score,
    TokenUsage,
    Trace,
    TraceStep,
    STEP_MODEL_CALL,
)


def _fixture_result() -> Result:
    step = TraceStep(
        kind=STEP_MODEL_CALL,
        input=[{"role": "user", "content": "What is 2 + 2?"}],
        output="4",
        model="claude-sonnet-5",
        usage=TokenUsage(input_tokens=12, output_tokens=1),
        started_at=1000.0,
        ended_at=1000.5,
        duration_s=0.5,
        metadata={"stop_reason": "end_turn"},
    )
    return Result(
        case_id="arith-1",
        output="4",
        trace=Trace(steps=[step]),
        metadata={"attempt": 1},
    )


def test_case_round_trips():
    case = Case(
        id="arith-1",
        input="What is 2 + 2?",
        reference="4",
        self_check="Recheck the arithmetic and correct if wrong.",
        metadata={"topic": "math"},
    )
    restored = Case.from_dict(json.loads(json.dumps(case.to_dict())))
    assert restored == case
    assert restored.self_check == "Recheck the arithmetic and correct if wrong."


def test_result_round_trips_through_json():
    result = _fixture_result()
    restored = Result.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored == result


def test_score_round_trips():
    score = Score(case_id="arith-1", scorer="reference", value=1.0, passed=True, detail={"expected": "4", "got": "4"})
    restored = Score.from_dict(json.loads(json.dumps(score.to_dict())))
    assert restored == score
    assert restored.dimension == "output"  # default when absent


def test_trace_dimension_score_round_trips():
    score = Score(case_id="c1", scorer="verify_before_assert", value=1.0, passed=True,
                  dimension="trace", detail={"reason": "substantive verification"})
    restored = Score.from_dict(json.loads(json.dumps(score.to_dict())))
    assert restored == score
    assert restored.dimension == "trace"


def test_pre_42_dicts_load_without_the_new_fields():
    """Backwards compatible: runs/cases saved before #42 have no self_check / dimension."""
    case = Case.from_dict({"id": "c1", "input": "x", "reference": "y"})
    assert case.self_check is None

    score = Score.from_dict({"case_id": "c1", "scorer": "reference", "value": 1.0, "passed": True})
    assert score.dimension == "output"


def test_trace_step_shape_supports_future_kinds():
    """The trace seam: a tool_call step reuses the exact same shape as a model_call."""
    tool_step = TraceStep(kind="tool_call", input={"query": "weather"}, output={"temp": 20})
    restored = TraceStep.from_dict(json.loads(json.dumps(tool_step.to_dict())))
    assert restored == tool_step
    assert restored.kind == "tool_call"


def test_trace_duration_sums_steps():
    trace = Trace(steps=[TraceStep(kind=STEP_MODEL_CALL, duration_s=0.5), TraceStep(kind=STEP_MODEL_CALL, duration_s=1.5)])
    assert trace.duration_s == 2.0
