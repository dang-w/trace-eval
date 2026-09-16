# Example runs

Curated, real output from `trace-eval`, committed so you can read what the harness
produces without running it yourself. Each JSON file (`run.json`, `meta.json`,
`mutation.json`) is the full persisted record — for a task run, every result with its
complete trace — and each `*report.md` is the rendered markdown report.

These are **hand-picked snapshots**, not auto-generated: live output lands in the
gitignored `results/` dir, and these are copied here deliberately. They are real model
output (`claude-opus-4-8`), so they are illustrative rather than bit-reproducible — the
model version, params, and prompts are recorded in each run's `meta` and trace.

| Example | Scorer | What it shows |
| --- | --- | --- |
| [`sample/`](sample/) | `reference` | Output-level scoring: normalised match against a reference answer. The `formula-water` miss (`H₂O` vs `H2O`) is a real, illustrative normalisation limitation. |
| [`self-check/`](self-check/) | `verify_before_assert` | Trace-level scoring: each result carries a two-step `answer` → `verify` trace, and the scorer grades whether a substantive verification step revisited the answer. |
| [`soundness/`](soundness/) | `verification_sound` | LLM-judged soundness on the cognitive-reflection task. The `lily-pads` case is the payoff: the model answered `47` (correct) but its verify step was the bare string `47`, and the judge flagged it **unsound** — a rubber-stamp that did no work, even though the answer is right. The judge separates "answer correct" from "verification sound." |
| [`mutation/`](mutation/) | (all deterministic scorers) | Mutation testing: six hand-authored, synthetic mutants of the real `bat-and-ball` run fed to every built-in deterministic scorer. `verify_before_assert` killed 2/4 and **accepted** the one-sentence rubber-stamp and the contradicted verify (it is a length floor; those two keep the shape of a verify step, so 50% is its ceiling here). `reference` **fails the baseline** — it cannot pass a multi-step run's prose output — so its kill rate is void rather than a free 100%. Unlike the other examples this one is deterministic and reproducible apart from the record's timestamp: no model calls. |
| [`meta-eval/`](meta-eval/) | (meta) | How much to trust that judge: self-consistency 100% (flip rate 0%) and gold-agreement 100% (10/10) over the gold set. **Read the caveat:** the gold set is 10 deliberately clear-cut items with the reference visible, so 100% means the judge is reliable *on unambiguous cases*, not everywhere — the borderline cases that would actually flip it aren't in this gold yet. A clean number is only as strong as the set behind it. |

Regenerate (needs an `ANTHROPIC_API_KEY`):

```bash
trace-eval run tasks/sample --scorer reference
trace-eval run tasks/self-check --scorer verify_before_assert
trace-eval run tasks/soundness --scorer verification_sound
trace-eval meta --gold gold/verification_sound.json --k 5
trace-eval mutate tasks/soundness   # no key needed; deterministic
# then copy the chosen results/ output into the matching examples/ dir
```
