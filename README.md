# trace-eval

A minimal eval harness that runs one evaluation end to end — and captures a real,
structured **trace** for every result, not just the final string.

It is deliberately small. The value is in getting two interface seams right, so the
things that come next (richer traces, semantic diff, experiments) are cheap to add
without a refactor:

1. **A pluggable scorer** is just a function `(Case, Result) -> Score`. No registry, no
   base class, no plugin system.
2. **Trace capture**: a `Result` carries a `Trace` — an ordered list of typed
   `TraceStep`s. A scorer that inspects `result.trace.steps` needs no change to these
   seams to do it.

The first payoff is the `verify_before_assert` scorer: it grades the *process* — did the
model verify its answer before committing — by reading the trace, not the output. See
[Grading the process](#grading-the-process-a-trace-level-scorer) below.

## Install

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run the sample task

Live runs call Claude via the Anthropic SDK, so set a key first (or use an `ant` login
profile):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/trace-eval run tasks/sample --scorer reference
```

This runs the 5-case sample task, scores each result against its reference, writes the
run to `results/<task>-<timestamp>.json`, and emits `results/report.md`:

```text
# Eval Report — sample

- **Model:** claude-opus-4-8
- **Scorer:** reference
- **Cases:** 5
- **Pass rate:** 4/5 (80%)

| Case | Pass | Score | Expected | Output |
| --- | :---: | ---: | --- | --- |
| arith-sum | ✅ | 1.00 | 4 | 4 |
| ...
```

Flags: `--model` (default `claude-opus-4-8`), `--max-tokens` (default 1024),
`--out` (default `results/`).

## Task format

A task is a directory with a `cases.json` (a list of case objects) and an optional
`task.json` (`name`, `description`). Tasks are JSON fixtures in v1 — there is no config
DSL.

```json
[
  { "id": "arith-sum", "input": "What is 2 + 2? Reply with just the number.", "reference": "4" }
]
```

A case may also declare an optional `self_check` — a plain instruction for a verification
pass. When present, the runner runs the answer, then feeds the answer plus that
instruction back in as a second `model_call`, so the trace has a real verify step to
grade. This is a **fixed two-step sequence** (answer, then verify) — not an agent loop,
tool use, or planning.

```json
[
  {
    "id": "count-r",
    "input": "How many times does 'r' appear in 'strawberry'? Reply with just the number.",
    "reference": "3",
    "self_check": "Recount the 'r's one character at a time; correct your answer if it was wrong."
  }
]
```

## Writing a scorer

A scorer is any function of the shape `(Case, Result) -> Score`:

```python
from traceeval.types import Case, Result, Score

def length_scorer(case: Case, result: Result) -> Score:
    ok = len(result.output) <= 10
    return Score(case_id=case.id, scorer="length", value=1.0 if ok else 0.0, passed=ok)
```

The shipped `reference` scorer does a normalised exact match against `case.reference`.
The CLI resolves scorer names through a small built-in dict in `cli.py`.

## The trace

Every `Result` carries the full trace, persisted to JSON:

```json
"trace": {
  "steps": [
    {
      "kind": "model_call",
      "input": [{"role": "user", "content": "..."}],
      "output": "4",
      "model": "claude-opus-4-8",
      "usage": {"input_tokens": 33, "output_tokens": 3},
      "duration_s": 4.13,
      "metadata": {"stop_reason": "end_turn"}
    }
  ]
}
```

A multi-step (self-check) run appends a second step; each step is tagged with its role
(`answer` / `verify`) in `metadata`, so a trace scorer tells them apart without guessing
by position. `tool_call` and `agent_step` kinds are reserved for later builds.

## Grading the process (a trace-level scorer)

`verify_before_assert` reads `result.trace.steps` instead of `result.output`. It passes
when the trace holds a substantive verification step that revisited the answer:

```bash
.venv/bin/trace-eval run tasks/self-check --scorer verify_before_assert
```

```text
## Trace-level scores (process)

_Grades the process from the trace — did a substantive verification step revisit the
answer — not whether the answer is correct._

| Case | Verified | Score | Verification | Reason |
| --- | :---: | ---: | --- | --- |
| count-r-strawberry | ✅ | 1.00 | Rechecking each letter: s-t-r-a-w-b-e-r-r-y … | substantive verification step revisited the answer |
```

The substance bar is deliberately **structural**: a verify step exists, follows the
answer, is non-empty, and clears a small character floor (a real second pass, not a
one-token rubber-stamp). It does **not** judge whether the verification was
*semantically* correct — whether it caught the right thing. That is an LLM-as-judge trace
scorer, a later build. Keeping it structural keeps it pure, deterministic, and testable
offline with no key.

Output scores and trace scores render in separate, clearly-labelled report sections, so a
process verdict is never read as a correctness verdict.

Real output from both scorers — full runs with complete traces — is committed under
[`examples/`](examples/), so you can read what the harness produces without running it.

## Not yet (by design)

Tool-call / agent-loop traces, an LLM-judged trace scorer, a web UI, a multi-provider
abstraction, a config DSL, parallelism, and a scorer registry. Those are later builds;
the point is that the seams make them cheap, not that this repo anticipates them.

## Development

```bash
.venv/bin/pytest    # 37 tests, no network or API key required (a fake model caller is used)
```
