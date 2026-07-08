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


def run_case(
    case: Case,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model_caller: ModelCaller = call_anthropic,
) -> Result:
    """Run a single case: call the model, wrap the step into a Result with its Trace.

    A failing call becomes a ``Result`` with ``error`` set (and empty output) rather
    than an exception, so a run over many cases doesn't abort on one bad call.
    """
    try:
        step = model_caller(case.input, model, max_tokens)
    except Exception as exc:  # noqa: BLE001 — one bad case must not kill the whole run
        return Result(case_id=case.id, output="", trace=Trace(), error=f"{type(exc).__name__}: {exc}")

    return Result(
        case_id=case.id,
        output=step.output if isinstance(step.output, str) else str(step.output),
        trace=Trace(steps=[step]),
    )


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
