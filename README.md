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

## Judging soundness, and how much to trust the judge

`verify_before_assert` is structural: it confirms a verification *happened*, not that it was
any good. Judging whether a verification was **sound** — did it actually check the answer and
reach the right verdict — is a semantic call, so it needs a model. `verification_sound` is
that LLM-as-judge: given the question, the first answer, the verify step, and the reference
answer, it returns `sound` / `unsound` plus a one-line rationale.

```bash
.venv/bin/trace-eval run tasks/soundness --scorer verification_sound
```

An LLM judge is non-deterministic, which meets the harness's reproducibility discipline head
on. The answer here is not to pretend the judge is deterministic, but to **record what it
was** (model, params, the exact prompt, and every raw verdict) and to **measure how much to
trust it before trusting any verdict it makes**. That is the meta-eval:

```bash
.venv/bin/trace-eval meta --gold gold/verification_sound.json --k 5
```

It runs the judge `K` times over a small, hand-labelled **gold set** and reports two numbers,
*above* any verdict the judge produced:

- **Self-consistency** — does the judge give the same verdict across identical calls?
  (Measures stability, not correctness.) Every raw verdict is retained, never collapsed early.
- **Gold-agreement** — does the judge's verdict match a human's on the gold set? (Measures
  correctness.) The exact disagreements are listed.

The report leads with those trust figures and only then shows the judge's verdicts, so a
verdict is never read without the figures that bound how much it is worth. The gold set
([`gold/verification_sound.json`](gold/verification_sound.json)) is a **self-contained**,
hand-labelled fixture — a human label attaches to a specific verify-step output, so the
labelled material travels with the file rather than being keyed to a (varying) live run.

The task set gains [`tasks/soundness/`](tasks/soundness/): cognitive-reflection traps whose
seductive first answer is wrong, so a verification can genuinely be sound (catches it) or
unsound (rubber-stamps it) — the material the judge needs. The trace report also surfaces a
coarse **Changed** signal (first answer vs committed output); it is not a semantic correction
verdict (that is a later build).

## Mutation testing: can the scorer be made to fail?

A scorer that passes everything looks identical to a scorer that works, until you hand it
something it should reject. `verify_before_assert` posted 100% on its first task for exactly
that reason: it measured the *presence* of a verification step, not its efficacy. Mutation
testing is the systematic version of that catch: before trusting a scorer, prove it can fail.

```bash
.venv/bin/trace-eval mutate tasks/soundness
```

A task may carry a `mutants/` directory of hand-authored, deliberately broken copies of a
known-good run, each tagged with its class of breakage: `wrong-answer`, `empty-verify`,
`rubber-stamp`, `contradicted-verify`, `missing-trace`, plus an unmodified `baseline` as the
control. The mode applies every built-in deterministic scorer to every mutant and reports a
**kill rate** per scorer: mutants killed / mutants applicable (a scorer is only on the hook for
mutants that break the dimension it grades). No model calls; the run is offline and
deterministic.

```text
| Scorer | Baseline | Killed / applicable | Kill rate | Survivors |
| --- | :---: | ---: | ---: | --- |
| reference | FAIL | 1/1 | void — fails the baseline | — |
| verify_before_assert | pass | 2/4 | 50% | bat-and-ball--contradicted-verify, bat-and-ball--rubber-stamp |
```

Every survivor is named with the class it accepted (*this scorer accepted a broken run of
class rubber-stamp*). The baseline matters: a scorer that fails the unmodified run fails
everything, so its kill rate is withheld rather than reported as a free 100%. The run
surfaces both failure modes. `verify_before_assert` accepts a one-sentence rubber-stamp and a
verify step that derives a different answer, because it is a length floor. Two of its four
applicable mutants keep the *shape* of a verify step and gut only the substance; no purely
structural check can kill those, so 50% is this scorer's ceiling on this set, not a bug in
its implementation. That boundary is the finding. And `reference` fails the baseline because
on a multi-step run the final output is whatever the verify step said: it passes only when
the verify step replies with the bare answer, and fails whenever the step shows working. The
two do not compose. Both are findings about the scorers, not the model. Mutants are synthetic
fixtures and labelled as such; five classes on one case are a floor, not a taxonomy. A 100%
here would mean "not caught vacuous by these five", not "works".

## The run ledger: committed runs as receipts

`results/` is gitignored scratch. [`runs/`](runs/) is tracked: a record lands there
deliberately, with the finding it supports, and stays. Records made from here on name the
harness commit they were produced from, and whether tracked files had uncommitted changes
(untracked files are not counted), so a finding about a scorer is tied to the scorer code
that made it. The four July records predate provenance and show `—`. The index is generated,
never hand-edited:

```bash
.venv/bin/trace-eval index          # regenerates runs/INDEX.md from the records
```

Two kinds of record get two kinds of treatment. LLM runs vary run to run, so they are
receipts, not baselines: labelled with model and date, never diff-gated. Mutation runs make
no model calls, so their kill rates are a property of the scorer code, and the test suite
checks that the current code reproduces every committed one: same kills, same survivors, for
the scorers the record names. A scorer change that lets a mutant through fails the suite; a
reworded reason string or a newly added scorer does not. `examples/` stays the curated "read these" layer; `runs/` is
the ledger behind it. It is a practitioner's run log on a toy harness, not a benchmark, and
the index says so at the top.

The findings those records are the receipts for live in [`FINDINGS.md`](FINDINGS.md): four
dated entries, each stating what was expected, what was observed, and what it changed in the
harness, and each linking the run record behind it. The index carries a **Finding** column
(from the sidecar `runs/findings.json`) pointing each record back at its finding, so a row
like `4/4 passed (100%)` is never read without the finding that says why that number is
vacuous.

## Not yet (by design)

Tool-call / agent-loop traces, a web UI, a multi-provider abstraction, a config DSL,
parallelism, and a scorer registry. On the judge specifically: bias probes (position,
verbosity, self-preference), tuning the judge prompt against the gold set, a judge ensemble,
a blind (no-reference) variant, and the correction scorer proper. On mutation testing:
auto-generated mutants or a mutation-operator DSL, mutating the LLM judge, and an
answer-extraction policy so `reference` composes with multi-step runs. Those are later builds;
the point is that the seams make them cheap, not that this repo anticipates them.

## Development

```bash
.venv/bin/pytest    # 106 tests, no network or API key required (a fake model caller is used)
```
