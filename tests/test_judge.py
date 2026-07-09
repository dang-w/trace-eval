"""Task 2.1 done-when: the verification_sound judge returns a verdict + rationale per case
and records the judge's model, params, and prompt — all offline via a scripted fake judge.

The judge reuses the ``ModelCaller`` seam, so a ``ScriptedCaller`` (from test_runner) scripts
each judge response with no network and no key.
"""

from traceeval.judge import (
    build_judge_prompt,
    parse_verdict,
    verification_sound_judge,
    VERDICT_SOUND,
    VERDICT_UNSOUND,
    VERDICT_UNPARSEABLE,
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
from tests.test_runner import ScriptedCaller


def _step(role: str, output: str) -> TraceStep:
    return TraceStep(kind=STEP_MODEL_CALL, output=output, metadata={"role": role})


def _self_check_result(first_answer: str, verify_output: str) -> Result:
    return Result(
        case_id="c1",
        output=verify_output,
        trace=Trace(steps=[_step(ROLE_ANSWER, first_answer), _step(ROLE_VERIFY, verify_output)]),
    )


def _case() -> Case:
    return Case(id="c1", input="A bat and a ball cost $1.10 ...", reference="5",
                self_check="Set up the algebra and recheck.")


# --- parse_verdict ------------------------------------------------------------

def test_parse_verdict_reads_sound_and_rationale():
    verdict, rationale = parse_verdict("VERDICT: sound\nRATIONALE: the recheck reached 5 correctly")
    assert verdict == VERDICT_SOUND
    assert rationale == "the recheck reached 5 correctly"


def test_parse_verdict_prefers_unsound_over_sound_substring():
    # "unsound" contains "sound" — the parser must not misread it as sound.
    verdict, _ = parse_verdict("VERDICT: unsound\nRATIONALE: it rubber-stamped the wrong answer")
    assert verdict == VERDICT_UNSOUND


def test_parse_verdict_marks_unparseable():
    verdict, _ = parse_verdict("I think it was probably fine, hard to say")
    assert verdict == VERDICT_UNPARSEABLE


def test_parse_verdict_does_not_guess_a_verdict_from_prose():
    """A response with no VERDICT line must not be substring-guessed.

    'not sound' contains 'sound' — the parser must call this unparseable, not sound, or a
    clearly-negative prose verdict would score as passing and corrupt the meta-eval.
    """
    verdict, _ = parse_verdict("The verification is not sound; it rubber-stamps the wrong answer.")
    assert verdict == VERDICT_UNPARSEABLE


def test_parse_verdict_accepts_a_bare_word_answer():
    """An exact one-word answer is unambiguous (not prose-guessing), so it still parses."""
    assert parse_verdict("unsound")[0] == VERDICT_UNSOUND
    assert parse_verdict("sound")[0] == VERDICT_SOUND


# --- build_judge_prompt -------------------------------------------------------

def test_judge_prompt_contains_all_four_inputs():
    prompt = build_judge_prompt(
        question="A bat and a ball cost $1.10 ...",
        first_answer="10",
        verify_output="Rechecking: the ball is 5 cents.",
        reference="5",
    )
    assert "A bat and a ball cost $1.10 ..." in prompt
    assert "10" in prompt
    assert "Rechecking: the ball is 5 cents." in prompt
    assert "5" in prompt


# --- the judge scorer ---------------------------------------------------------

def test_judge_returns_sound_verdict_and_rationale():
    caller = ScriptedCaller("VERDICT: sound\nRATIONALE: the recheck caught the error and corrected to 5")
    judge = verification_sound_judge(caller, model="judge-model", max_tokens=256)
    result = _self_check_result("10", "Rechecking algebraically, the ball is 5 cents. Final answer: 5")

    score = judge(_case(), result)

    assert score.scorer == "verification_sound"
    assert score.dimension == DIM_TRACE
    assert score.passed is True
    assert score.value == 1.0
    assert score.detail["verdict"] == VERDICT_SOUND
    assert "corrected" in score.detail["rationale"]


def test_judge_returns_unsound_verdict():
    caller = ScriptedCaller("VERDICT: unsound\nRATIONALE: verification rubber-stamped the wrong answer")
    judge = verification_sound_judge(caller, model="judge-model", max_tokens=256)
    result = _self_check_result("10", "Yes, 10 cents looks right. Final answer: 10")

    score = judge(_case(), result)

    assert score.passed is False
    assert score.value == 0.0
    assert score.detail["verdict"] == VERDICT_UNSOUND


def test_judge_records_model_params_and_prompt():
    caller = ScriptedCaller("VERDICT: sound\nRATIONALE: ok")
    judge = verification_sound_judge(caller, model="judge-model", max_tokens=256)
    result = _self_check_result("10", "Rechecking: the ball is 5 cents.")

    score = judge(_case(), result)

    assert score.detail["judge_model"] == "judge-model"
    assert score.detail["judge_max_tokens"] == 256
    # The recorded prompt is the exact text the judge was asked — carries all four inputs.
    prompt = score.detail["judge_prompt"]
    assert "A bat and a ball cost $1.10 ..." in prompt
    assert "10" in prompt and "Rechecking: the ball is 5 cents." in prompt and "5" in prompt
    assert caller.prompts == [prompt]  # the judge called the model exactly once with that prompt


def test_judge_does_not_call_model_when_no_verify_step():
    caller = ScriptedCaller("VERDICT: sound\nRATIONALE: should never be used")
    judge = verification_sound_judge(caller, model="judge-model", max_tokens=256)
    result = Result(case_id="c1", output="10", trace=Trace(steps=[_step(ROLE_ANSWER, "10")]))

    score = judge(_case(), result)

    assert score.passed is False
    assert score.detail.get("judged") is False
    assert "no verification step" in score.detail["reason"]
    assert caller.prompts == []  # nothing to judge → the model is never consulted


def test_judge_marks_unparseable_verdict():
    caller = ScriptedCaller("hmm, hard to tell honestly")
    judge = verification_sound_judge(caller, model="judge-model", max_tokens=256)
    result = _self_check_result("10", "Rechecking: the ball is 5 cents.")

    score = judge(_case(), result)

    assert score.detail["verdict"] == VERDICT_UNPARSEABLE
    assert score.passed is False
