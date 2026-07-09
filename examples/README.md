# Example runs

Curated, real output from `trace-eval`, committed so you can read what the harness
produces without running it yourself. Each `run.json` is the full persisted run — every
result with its complete trace — and each `report.md` is the rendered markdown report.

These are **hand-picked snapshots**, not auto-generated: live output lands in the
gitignored `results/` dir, and these are copied here deliberately. They are real model
output (`claude-opus-4-8`), so they are illustrative rather than bit-reproducible — the
model version, params, and prompts are recorded in each run's `meta` and trace.

| Example | Scorer | What it shows |
| --- | --- | --- |
| [`sample/`](sample/) | `reference` | Output-level scoring: normalised match against a reference answer. The `formula-water` miss (`H₂O` vs `H2O`) is a real, illustrative normalisation limitation. |
| [`self-check/`](self-check/) | `verify_before_assert` | Trace-level scoring: each result carries a two-step `answer` → `verify` trace, and the scorer grades whether a substantive verification step revisited the answer. |

Regenerate (needs an `ANTHROPIC_API_KEY`):

```bash
trace-eval run tasks/sample --scorer reference
trace-eval run tasks/self-check --scorer verify_before_assert
# then copy the chosen results/ output into the matching examples/ dir
```
