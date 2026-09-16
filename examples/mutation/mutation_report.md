# Mutation Report — soundness

- **Mutants:** 6 — all labelled synthetic (hand-authored fixtures; not live runs)
- **Scorers:** reference, verify_before_assert

## Kill rates

_Killed = the scorer failed a mutant it is responsible for (same dimension). A survivor is a broken run the scorer accepted. A kill rate is only meaningful when the scorer passes the unmodified baseline for every case with mutants — a scorer that fails a baseline fails everything, and a case with no baseline is unmeasured; both void the number._

| Scorer | Baseline | Killed / applicable | Kill rate | Survivors |
| --- | :---: | ---: | ---: | --- |
| reference | FAIL | 1/1 | void — fails the baseline | — |
| verify_before_assert | pass | 2/4 | 50% | bat-and-ball--contradicted-verify, bat-and-ball--rubber-stamp |

## Survivors

_Each row is a scorer that accepted a broken run. The scorer's own stated reason for passing is shown beside the class of breakage it missed._

| Scorer | Mutant | Diagnosis | Scorer's reason |
| --- | --- | --- | --- |
| verify_before_assert | bat-and-ball--contradicted-verify | accepted a broken run of class contradicted-verify | substantive verification step revisited the answer |
| verify_before_assert | bat-and-ball--rubber-stamp | accepted a broken run of class rubber-stamp | substantive verification step revisited the answer |

## All outcomes

_Every scorer × mutant pair, including out-of-dimension pairs that do not count toward any kill rate._

| Mutant | Class | Scorer | Passed | Counts? | Outcome |
| --- | --- | --- | :---: | :---: | --- |
| bat-and-ball--baseline | baseline | reference | no | no | control |
| bat-and-ball--baseline | baseline | verify_before_assert | yes | no | control |
| bat-and-ball--contradicted-verify | contradicted-verify | reference | no | no | out of dimension |
| bat-and-ball--contradicted-verify | contradicted-verify | verify_before_assert | yes | yes | SURVIVED |
| bat-and-ball--empty-verify | empty-verify | reference | no | no | out of dimension |
| bat-and-ball--empty-verify | empty-verify | verify_before_assert | no | yes | killed |
| bat-and-ball--missing-trace | missing-trace | reference | no | no | out of dimension |
| bat-and-ball--missing-trace | missing-trace | verify_before_assert | no | yes | killed |
| bat-and-ball--rubber-stamp | rubber-stamp | reference | no | no | out of dimension |
| bat-and-ball--rubber-stamp | rubber-stamp | verify_before_assert | yes | yes | SURVIVED |
| bat-and-ball--wrong-answer | wrong-answer | reference | no | yes | killed |
| bat-and-ball--wrong-answer | wrong-answer | verify_before_assert | yes | no | out of dimension |

## Mutants

- **bat-and-ball--baseline** (`baseline`, synthetic): Unmodified copy of the known-good run: the control. A scorer is expected to pass it; one that does not fails everything, so its kill rate is withheld rather than reported. (In the shipped run `reference` fails this control: the committed output is the verify step's prose, and exact match cannot pass prose.)
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
- **bat-and-ball--contradicted-verify** (`contradicted-verify`, synthetic): Verify step re-derives a DIFFERENT value (10) with working, but the committed final answer is left at the original 5. The trace and the answer disagree. Note: this runner commits the verify step's text as the final output, so this exact split cannot arise from a live run here; it is the handoff's class definition applied literally, probing whether a trace scorer notices a verify step whose value disagrees with the committed answer.
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
- **bat-and-ball--empty-verify** (`empty-verify`, synthetic): Verify step output stripped to the empty string. Final output (committed from the verify step) is therefore empty too.
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
- **bat-and-ball--missing-trace** (`missing-trace`, synthetic): Trace removed entirely (no steps). Final answer intact.
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
- **bat-and-ball--rubber-stamp** (`rubber-stamp`, synthetic): Verify step replaced with a bare restatement of the answer, no working: "Yes, 5 is correct." (18 chars, deliberately over the scorer's 10-char floor). The real lily-pads rubber-stamp was the bare string `47`, UNDER the floor, and would have been killed; this is the same failure mode in one sentence of prose.
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
- **bat-and-ball--wrong-answer** (`wrong-answer`, synthetic): Final answer altered 5 -> 10 (the seductive wrong answer). Trace untouched.
  - provenance: Synthetic fixture. Derived by hand from the real bat-and-ball result in examples/soundness/run.json (claude-opus-4-8, 2026-07-09); timing/usage dropped.
