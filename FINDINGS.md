# Findings

Imported 2026-09-16 from the build log kept alongside this repo. These are the findings the
harness produced about itself, in the order they were found, each linked to the run record in
[`runs/`](runs/) that is its receipt. Every figure below appears in, or is a count over, the
linked record (or, where noted, in the code). Register is diagnostic, not celebratory: this is a practitioner's notebook
on a toy harness, not research. Present tense describes what the code does now; past tense
describes what was observed.

Across all four, the number was a statement about the verifier, not the model. In three of
them a clean result was the bug; in the first, a red cell was the scorer's. A green result is
a smell, not a certificate, and a suspiciously tidy metric is the diagnostic that tells you so.

---

<a id="finding-1"></a>
## Finding 1 — the scorer failed, not the model (H2O)

- **Found:** 2026-07-08
- **Receipt:** [`runs/sample-reference-20260708T175334Z.json`](runs/sample-reference-20260708T175334Z.json) — `reference` scorer over `tasks/sample`, `claude-opus-4-8`, 4/5.
- **Expected:** a 4/5 pass rate would mean the model got one case wrong.
- **Observed:** day-one run of the reference scorer: 4/5, one "failure": `formula-water`, expected `H2O`, got `H₂O` (U+2082 subscript).
- The model was not wrong - it produced the typographically correct formula. The reference scorer's normalisation folded case and whitespace but not a Unicode subscript to an ASCII digit, so exact match failed.
- The "80%" was a statement about the scorer's normalisation policy, not about the model. The 20% gap was the verifier.
- Lesson: the scorer is a source of error. Whether `H₂O == H2O` is a *policy* that depends on what the case tests (knowledge -> normalise; ASCII-only instruction-following -> real fail). Normalisation is a design surface that must be explicit and tested, not an implicit side effect.
- **What it changed:** the normalisation `reference_scorer` applies is documented in `_normalise`'s docstring and covered by a case/punctuation test; the `H₂O` policy question itself is recorded, unfixed, in `examples/sample/` as an illustrative limitation rather than "fixed" silently. Nothing in the suite yet pins the Unicode-digit behaviour either way.

<a id="finding-2"></a>
## Finding 2 — the trace scorer passed everything, which is how I knew it was broken

- **Found:** 2026-07-09
- **Receipt:** [`runs/self-check-verify_before_assert-20260709T103951Z.json`](runs/self-check-verify_before_assert-20260709T103951Z.json) — `verify_before_assert` over `tasks/self-check`, `claude-opus-4-8`, 4/4.
- **Expected:** a trace scorer that grades whether verification did its job.
- **Observed:** `verify_before_assert` on the self-check task: 4/4, 100%.
- The runner *forces* a verify step by construction, so "a verification step occurred" is guaranteed true. The scorer can effectively only fail on a too-short/empty verify step. So 100% isn't the model verifying well - it's the metric unable to discriminate. It grades whether the harness did its job (always yes), not whether verification does anything.
- Worse: every case in the task set had a *correct first answer* (strawberry=3, 17x24=408, 80 less 15%=68, Mar 1-15 inclusive=15 - the first-answer steps in the record). So every verify step was a confirmation, never a correction. The scorer has never once observed the scenario it exists to measure - verification catching a wrong answer, or (the dangerous quadrant) falsely confirming one.
- The reason string "substantive verification step revisited the answer" is itself a mild overclaim if the underlying check is really just length - it asserts an engagement the code hasn't confirmed.
- Lesson: measuring the *presence* of process is not measuring the *efficacy* of process. `verify_before_assert` is really `has_verification_step`. Standing applied to a metric name.
- **What it changed:** the report gained a `Changed` column (computed by `answer_changed`: first answer vs committed output) so an uninformative 100% carries the one signal it can: verified-unchanged vs verified-corrected. `tasks/soundness/` was added with cases that *invite* a wrong first answer; in the live run (Finding 3's receipt) all five first answers were still correct, so the wrong-first-answer scenario is observed only in the fixed gold corpus (`gold/verification_sound.json`), not yet in a live trace. Those two seeded the next build: a judge that measures *soundness*, not presence, and the meta-eval that measures the judge (Finding 3).

<a id="finding-3"></a>
## Finding 3 — the meta-eval, and the gold bug nearly shipped (#43)

- **Found:** 2026-07-09
- **Receipts:** [`runs/meta-20260709T122122Z.json`](runs/meta-20260709T122122Z.json) — `verification_sound` judge, `claude-opus-4-8`, K=5 over 10 gold items: 0 flipped, 10/10 gold-agreement. [`runs/soundness-verification_sound-20260709T121930Z.json`](runs/soundness-verification_sound-20260709T121930Z.json) — the same judge over `tasks/soundness`, 4/5 sound; the `lily-pads` verdict is the catch.
- **Expected:** a judge you can trust because you measured it.
- **Observed:** the third beat is the method, not just a third problem: build a judge that can measure *soundness* (not mere presence), then measure the judge before trusting it - self-consistency (does it give the same verdict across identical calls?) and gold-agreement (does it match a human?). Verify the verifier, including when the verifier is a judge.
- **The design bug (a real receipt, caught in-build):** the first gold-agreement design keyed human labels to the live run's `case_id`s - `{case_id: sound/unsound}`. That is meaningless. A human labels a *specific* verify-step output; the judge is an LLM and the trace varies run to run, so next run the label describes material that no longer exists. The tidy `{id: label}` map was the same failure mode as findings 1 and 2 - a clean-looking structure hiding that it measures nothing. Fix: the gold set is **self-contained** - each item carries the exact judge input (question, first answer, verify output, reference) *plus* the label, so trust is measured over a fixed, controlled corpus, not a moving one.
- The judge preserves the one-function scorer seam by being a *factory* (`(model_caller) -> (Case, Result) -> Score`), so the whole stochastic judge is still offline-testable with the same scripted fake caller - including a deliberately inconsistent judge fixture whose only job is to prove the self-consistency measurement actually detects inconsistency. The test for the meter is a broken meter.
- Reproducibility for a stochastic judge is redefined honestly: not "the judge is deterministic" but "every raw verdict is recorded." K samples retained, distribution reported, never collapsed to a point estimate early. The report *leads* with the trust figures and puts the judge's own verdicts strictly below them - you cannot read a verdict without first seeing what it's worth.
- **The live receipt.** The judge (`claude-opus-4-8`, K=5) over the confirmed 10-item gold set: **self-consistency 100% (flip rate 0/10), gold-agreement 100% (10/10).** And here is the through-line biting again: *that clean 100% is the tell, not a triumph.* The gold set is 10 deliberately clear-cut items with the reference visible - so 100% means "the judge is stable and correct on unambiguous cases," and says nothing about the borderline cases that would actually make it flip or disagree, because there are none in this gold yet. A perfect meta number is only as strong as the set behind it; this set is easy by construction. The honest verdict is "trustworthy on easy cases, unmeasured on hard ones" - which is exactly why the *next* build is harder/ambiguous gold and bias probes, not "the judge is 100% reliable."
- **The one live catch that is a real receipt (`lily-pads`).** On the soundness task the model answered `47` - correct, not fooled by the trap - but its verify step was the bare string `47`, no working. The judge called it **unsound**; the rationale in the record: "The verification merely restates "47" without any re-checking or reasoning, so it rubber-stamped the answer even though the result is correct." That is Finding 2's dangerous quadrant caught in the wild, and the sharpest single demonstration in the whole arc: the judge separates *the answer is right* from *the verification did its job*. A right answer with an empty verification is still an unsound verification - and the soundness judge is the first scorer that can say so.
- **What it changed:** `gold/verification_sound.json` is a self-contained, hand-labelled fixture; `trace-eval meta` reports self-consistency and gold-agreement above any verdict; every raw judge sample is persisted.

<a id="finding-4"></a>
## Finding 4 — mutation testing: the scorers, fed broken runs, mostly did not notice (#55)

- **Found:** 2026-09-16
- **Receipt:** [`runs/mutation-soundness-20260916T113410Z.json`](runs/mutation-soundness-20260916T113410Z.json) — `trace-eval mutate tasks/soundness`, no model calls, harness commit `1578b87`.
- **Expected:** a scorer that can be made to fail. A scorer that passes deliberately broken runs is vacuous, exactly like a test suite that passes when the code is deleted.
- **Observed:** six hand-authored mutants of the real `bat-and-ball` result (baseline control + wrong-answer, empty-verify, rubber-stamp, contradicted-verify, missing-trace), every built-in deterministic scorer applied, kill rate = killed / applicable. The whole thing is a static fixture and runs in milliseconds.
- **`verify_before_assert`: killed 2/4.** Killed `empty-verify` and `missing-trace`. **Accepted `rubber-stamp`** (verify step = "Yes, 5 is correct." - 18 chars, no working) and **accepted `contradicted-verify`** (verify step re-derives 10 with working; committed answer still 5). Both survivors were passed with the scorer's own reason string "substantive verification step revisited the answer" - the overclaim named in Finding 2, now with a receipt. The scorer is a character-length floor (`MIN_VERIFY_CHARS = 10` in `src/traceeval/scorers.py`). The real `lily-pads` rubber-stamp (bare `47`, 2 chars) would have been killed by that floor; one sentence of restatement sails through. The scorer separates rubber-stamps from real verification only by *length*, which is the vacuity.
- **`reference`: kill rate void - it fails the baseline.** The unmodified good run's final output is the verify step's full prose ("5\n\nThe algebra confirms it: ..."), and normalised exact match against "5" cannot pass that. So on a multi-step task the reference scorer fails any run whose verify step shows working, correct or not (it passes only when the verify step replies with the bare answer, as the real `lily-pads` run did) - and *would have posted a 100% kill rate* (1/1 on `wrong-answer`) if the report had no baseline control. This is Finding 1's shape again (the scorer's normalisation/extraction policy, not the model, decides the number) and it is a real pre-existing gap: `reference` and the self-check runner do not compose. Not fixed here - it needs an answer-extraction policy for multi-step outputs, a separate build.
- **Method receipt:** the baseline control did its job immediately. "Kill rate" with no baseline is the same clean-number trap as Findings 2 and 3: a scorer that fails everything and a scorer that discriminates look identical in a killed/applicable column.
- **Fairness to the scorer (from the cold read):** the two survivors both keep the *shape* of a verify step and gut only the substance, and `verify_before_assert` disclaims semantic judgement in its own docstring. So 2/4 is the ceiling for any purely structural check on this set, not an implementation bug - the boundary is the finding. Also: the `contradicted-verify` split (trace says 10, committed answer says 5) cannot arise from this runner, which commits the verify text as the final output; the fixture applies the class definition literally and its note says so.
- **Review receipts (2026-09-16):** the baseline gate as first written was one boolean per scorer, so a task with no baseline fixture - or per-case baselines - would have published a free kill rate anyway. Exactly the failure the gate exists to stop, in the gate. Fixed to per-(scorer, case) with "no baseline" withheld like "failed baseline". And the report's "synthetic" label was a string literal, not a fact read off the fixtures - a label that cannot be wrong cannot be right. Now computed.
- **What this can't say:** five mutant classes on one case are a floor, not a taxonomy. A 100% here would mean "not caught vacuous by these five," not "works." The LLM judge is not under test in this mode (needs a caller; its trust is measured by `meta`). Mutants are synthetic and labelled so in every fixture and in the report header.
- Lesson: presence-of-process scorers pass mutants that preserve the *shape* of process. The only mutants a length floor kills are the ones that remove the shape entirely. Everything that keeps the shape and guts the substance - the interesting failures - survives.
- **What it changed:** `trace-eval mutate` and `tasks/<task>/mutants/` exist; kill rates are gated per (scorer, case) on a baseline; the committed mutation record is reproduced by the test suite, so a scorer change that lets a mutant through fails the build.
