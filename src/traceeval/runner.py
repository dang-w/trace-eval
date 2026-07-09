"""The runner: call one model per case and capture output plus a trace.

The seam that matters here is ``call_anthropic`` — the *only* place that touches the
Anthropic SDK. It takes a prompt and returns a fully-populated ``TraceStep``. The run
loop never imports the SDK; it just invokes a ``ModelCaller``. That keeps the provider
swappable (pass a different callable) and makes the whole harness testable without a
network or an API key (tests pass a fake caller). v1 does not build a provider
abstraction on top of this — one thin function is the whole seam.
"""

from __future__ import annotations

import time
from typing import Callable

from traceeval.config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL
from traceeval.types import (
    Case,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    TokenUsage,
    Trace,
    TraceStep,
    STEP_MODEL_CALL,
)

# A ModelCaller turns a prompt into one trace step (a single model_call). Swapping the
# provider, or faking it in a test, means passing a different callable of this shape.
ModelCaller = Callable[[str, str, int], TraceStep]


def call_anthropic(prompt: str, model: str, max_tokens: int) -> TraceStep:
    """Call Claude once via the Anthropic SDK and return a populated model_call step.

    This is the single point of contact with the SDK. Credentials resolve the standard
    way (``ANTHROPIC_API_KEY`` env var, or an ``ant`` login profile) — the client is
    constructed here, lazily, so importing this module needs no credentials.
    """
    from anthropic import Anthropic

    client = Anthropic()
    messages = [{"role": "user", "content": prompt}]

    started = time.time()
    perf_start = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    duration = time.perf_counter() - perf_start
    ended = time.time()

    # response.content is a list of blocks; concatenate the text blocks for the output.
    text = "".join(block.text for block in response.content if block.type == "text")

    return TraceStep(
        kind=STEP_MODEL_CALL,
        input=messages,
        output=text,
        model=response.model,
        usage=TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        ),
        started_at=started,
        ended_at=ended,
        duration_s=duration,
        metadata={"stop_reason": response.stop_reason},
    )


def _as_text(output: object) -> str:
    """A step's output is typed ``Any``; coerce it to the string a Result exposes."""
    return output if isinstance(output, str) else str(output)


def build_verify_prompt(case: Case, prior_answer: str) -> str:
    """Compose the second-step prompt for a self-check.

    The runner — not the case — owns this composition, so ``case.self_check`` stays a bare
    instruction and never has to know a prompt format. The prior answer is carried in
    verbatim so the verification step actually has something to check.
    """
    return (
        f"{case.input}\n\n"
        f"You previously answered:\n{prior_answer}\n\n"
        f"{case.self_check}"
    )


def run_case(
    case: Case,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model_caller: ModelCaller = call_anthropic,
) -> Result:
    """Run a single case and wrap its step(s) into a Result carrying the full Trace.

    Single-step (no ``self_check``): one ``model_call`` — the v1 behaviour, unchanged.

    Multi-step (``self_check`` set): the answer step, then a verify step that is fed the
    prior answer plus the self-check instruction. Both land in ``trace.steps``, each tagged
    with its role in metadata, and the final ``output`` is the *last* step's output — so a
    self-check can revise the answer, not merely comment on it.

    A failing call becomes a ``Result`` with ``error`` set rather than an exception, so a
    run over many cases doesn't abort on one bad call. If the answer step fails there is no
    trace to keep; if the *verify* step fails the successful answer step is preserved in the
    trace (output cleared) because that partial trace is exactly what you want to debug.
    """
    try:
        answer = model_caller(case.input, model, max_tokens)
    except Exception as exc:  # noqa: BLE001 — one bad case must not kill the whole run
        return Result(case_id=case.id, output="", trace=Trace(), error=f"{type(exc).__name__}: {exc}")
    answer.metadata["role"] = ROLE_ANSWER
    steps = [answer]

    if case.self_check:
        try:
            verify = model_caller(build_verify_prompt(case, _as_text(answer.output)), model, max_tokens)
        except Exception as exc:  # noqa: BLE001 — keep the answer step; surface the failure
            return Result(case_id=case.id, output="", trace=Trace(steps=steps), error=f"{type(exc).__name__}: {exc}")
        verify.metadata["role"] = ROLE_VERIFY
        steps.append(verify)

    return Result(case_id=case.id, output=_as_text(steps[-1].output), trace=Trace(steps=steps))


def run_cases(
    cases: list[Case],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model_caller: ModelCaller = call_anthropic,
) -> list[Result]:
    """Run every case in order and collect the Results."""
    return [
        run_case(case, model=model, max_tokens=max_tokens, model_caller=model_caller)
        for case in cases
    ]
