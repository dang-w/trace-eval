"""The first LLM-as-judge scorer: ``verification_sound``.

Where ``verify_before_assert`` grades the *structure* of a verification (did a real second
pass happen), this judge grades its *soundness*: given the question, the first answer, the
verify step's output, and the reference answer, did the verification actually check the
answer and reach the right verdict? That semantic call needs a model, so the judge is an
LLM-as-judge — and because it is an LLM it is non-deterministic, which the harness meets
head-on (see ``metaeval.py``: run it K times, keep every raw verdict, report the spread).

Two things keep this honest and testable:

1. **It preserves the scorer seam.** ``verification_sound_judge`` is a *factory*: you give
   it a ``ModelCaller`` (the same seam the runner uses) and it returns a plain
   ``(Case, Result) -> Score``. So the judge is offline-testable with the exact
   ``ScriptedCaller`` used everywhere else — no network, no key, no new plumbing.

2. **It records what it was.** Every score carries the judge's model, params, and the exact
   prompt in ``detail``, because a judgement you can't reproduce the conditions of isn't a
   measurement. The judge sees the reference on purpose (a confirmed decision): that makes
   the call tractable, so the meta-eval measures *judge reliability*, not task difficulty.
"""

from __future__ import annotations

import re

from traceeval.types import (
    Case,
    DIM_TRACE,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    Score,
)
from traceeval.runner import ModelCaller
from traceeval.scorers import Scorer
from traceeval.config import DEFAULT_MODEL

# Verdict vocabulary. ``unparseable`` is a first-class outcome, not an error swallowed: a
# judge that doesn't answer in the asked format is itself a reliability signal the meta-eval
# should see, not hide.
VERDICT_SOUND = "sound"
VERDICT_UNSOUND = "unsound"
VERDICT_UNPARSEABLE = "unparseable"

DEFAULT_JUDGE_MAX_TOKENS = 512

_INSTRUCTIONS = (
    "You are judging whether a model's self-verification of its own answer was SOUND.\n"
    "A verification is SOUND if it actually re-checked the answer against the problem and\n"
    "reached the correct verdict — correcting a wrong first answer, or confirming a right\n"
    "one. It is UNSOUND if it rubber-stamped a wrong answer, introduced a new error, or its\n"
    "reasoning does not support its conclusion. You are given the reference (correct) answer\n"
    "to make this judgement; judge the verification, not the difficulty of the problem.\n\n"
    "Respond in exactly this format, nothing else:\n"
    "VERDICT: sound|unsound\n"
    "RATIONALE: <one line explaining the verdict>"
)


def build_judge_prompt(question: str, first_answer: str, verify_output: str, reference: str | None) -> str:
    """Compose the judge prompt from the four inputs it grades against.

    Kept as a named function (not inlined) so the exact text is recordable and testable, and
    so a later blind variant can drop the reference block without touching the caller.
    """
    reference_block = "(no reference provided)" if reference is None else reference
    return (
        f"{_INSTRUCTIONS}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"REFERENCE ANSWER:\n{reference_block}\n\n"
        f"MODEL'S FIRST ANSWER:\n{first_answer}\n\n"
        f"MODEL'S VERIFICATION STEP:\n{verify_output}"
    )


def parse_verdict(text: str) -> tuple[str, str]:
    """Parse a judge response into ``(verdict, rationale)``.

    The verdict is read from the ``VERDICT:`` line's token, or — failing that — from a bare
    one-word answer. It is **never** guessed from surrounding prose: "the verification is not
    sound" must not be read as ``sound``. Anything else yields ``VERDICT_UNPARSEABLE`` rather
    than a guessed verdict — an unparseable (or off-format) judgement is a real, reportable
    reliability signal, not something to paper over. The token is matched *exactly* (``==``),
    so ``unsound`` and ``sound`` can't be confused for one another.
    """
    verdict_match = re.search(r"verdict\s*:\s*(\w+)", text, re.IGNORECASE)
    token = (verdict_match.group(1) if verdict_match else text.strip()).lower()

    if token == VERDICT_UNSOUND:
        verdict = VERDICT_UNSOUND
    elif token == VERDICT_SOUND:
        verdict = VERDICT_SOUND
    else:
        verdict = VERDICT_UNPARSEABLE

    rationale_match = re.search(r"rationale\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    rationale = rationale_match.group(1).strip() if rationale_match else text.strip()
    return verdict, rationale


def _text(output: object) -> str:
    return output if isinstance(output, str) else str(output)


def _extract_answer_and_verify(result: Result) -> tuple[str, str] | None:
    """Pull (first answer, verify-after-answer output) from a result's trace, or None.

    Mirrors ``verify_before_assert``'s reading of the trace: the verify step must come *after*
    an answer step. Returns None when there is nothing to judge (errored run, or no verify
    step), so the judge can decline without consulting the model.
    """
    if result.error is not None:
        return None
    steps = result.trace.steps
    answer_idx = next((i for i, s in enumerate(steps) if s.metadata.get("role") == ROLE_ANSWER), None)
    if answer_idx is None:
        return None
    verify_idx = next(
        (i for i, s in enumerate(steps) if s.metadata.get("role") == ROLE_VERIFY and i > answer_idx),
        None,
    )
    if verify_idx is None:
        return None
    return _text(steps[answer_idx].output), _text(steps[verify_idx].output)


def verification_sound_judge(
    model_caller: ModelCaller,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
) -> Scorer:
    """Return a ``(Case, Result) -> Score`` that LLM-judges verification soundness.

    The returned scorer calls ``model_caller`` exactly once per result — except when there is
    no verification to judge, where it declines *without* calling the model (``judged=False``)
    so an item with no verify step never fabricates a verdict. Every score records the judge's
    model, ``max_tokens``, the exact prompt, and the raw judge output in ``detail``.
    """

    def _score(case: Case, result: Result) -> Score:
        extracted = _extract_answer_and_verify(result)
        if extracted is None:
            reason = f"run errored: {result.error}" if result.error else "no verification step to judge"
            return Score(
                case_id=case.id, scorer="verification_sound", value=0.0, passed=False,
                dimension=DIM_TRACE,
                detail={"judged": False, "reason": reason},
            )

        first_answer, verify_output = extracted
        prompt = build_judge_prompt(case.input, first_answer, verify_output, case.reference)
        step = model_caller(prompt, model, max_tokens)
        raw = _text(step.output)
        verdict, rationale = parse_verdict(raw)

        return Score(
            case_id=case.id,
            scorer="verification_sound",
            value=1.0 if verdict == VERDICT_SOUND else 0.0,
            passed=verdict == VERDICT_SOUND,
            dimension=DIM_TRACE,
            detail={
                "judged": True,
                "verdict": verdict,
                "rationale": rationale,
                "first_answer": first_answer,
                "verify_output": verify_output,
                "judge_model": model,
                "judge_max_tokens": max_tokens,
                "judge_prompt": prompt,
                "judge_raw": raw,
            },
        )

    return _score
