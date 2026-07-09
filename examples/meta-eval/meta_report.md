# Meta-Eval — how much to trust the `verification_sound` judge

- **Judge model:** claude-opus-4-8
- **Samples per item (K):** 5
- **Judge max tokens:** 512

## How much to trust this judge

_Read these first. They bound how much weight every judge verdict below can carry — a verdict from an unreliable judge is not evidence._

- **Self-consistency:** mean agreement 100%, flip rate 0% (0/10 items flipped across K identical calls). _Measures stability, not correctness._
- **Gold-agreement:** 100% (10/10 hand-labelled items). _Measures correctness against human judgement._

## Judge verdicts

_Per-item majority verdict across the K samples — trust it only as far as the figures above allow. Every raw sample is retained in the JSON record, not just the majority._

| Case | Majority | Agreement | Flipped | Sample verdicts |
| --- | :---: | ---: | :---: | --- |
| batball-corrected | sound | 100% | — | sound, sound, sound, sound, sound |
| batball-rubberstamped | unsound | 100% | — | unsound, unsound, unsound, unsound, unsound |
| widget-corrected | sound | 100% | — | sound, sound, sound, sound, sound |
| widget-rubberstamped | unsound | 100% | — | unsound, unsound, unsound, unsound, unsound |
| widget-confirmed-right | sound | 100% | — | sound, sound, sound, sound, sound |
| lily-corrected | sound | 100% | — | sound, sound, sound, sound, sound |
| lily-rubberstamped | unsound | 100% | — | unsound, unsound, unsound, unsound, unsound |
| months-corrected | sound | 100% | — | sound, sound, sound, sound, sound |
| raise-discount-broke-right-answer | unsound | 100% | — | unsound, unsound, unsound, unsound, unsound |
| raise-discount-confirmed-right | sound | 100% | — | sound, sound, sound, sound, sound |
