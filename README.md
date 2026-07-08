# trace-eval

A minimal eval harness that runs one evaluation end to end — and captures a real,
structured **trace** for every result, not just the final string.

It is deliberately small. The value is in getting two interface seams right, so the
things that come next (a trace-level scorer, semantic diff, experiments) are cheap to
add without a refactor:

1. **A pluggable scorer** is just a function `(Case, Result) -> Score`. No registry, no
   base class, no plugin system.
2. **Trace capture**: a `Result` carries a `Trace` — an ordered list of typed
   `TraceStep`s. v1 only ever emits one `model_call` step, but the shape is designed so
   agent steps and tool calls slot in later; a future scorer that inspects
   `result.trace.steps` needs no change here to do it.

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

`kind` is `model_call` in v1; `tool_call` and `agent_step` are reserved for later. A
trace-level scorer reads `result.trace.steps` — that is what the trace seam buys.

## Not in v1 (by design)

Web UI, a multi-provider abstraction, a config DSL, parallelism, a scorer registry, and
the trace-level scorer itself. Those are later builds; the point of v1 is that they
become cheap, not that v1 anticipates them.

## Development

```bash
.venv/bin/pytest    # 21 tests, no network or API key required (a fake model caller is used)
```
