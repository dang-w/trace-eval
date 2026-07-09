# Eval Report — soundness

- **Model:** claude-opus-4-8
- **Scorer:** verification_sound
- **Cases:** 5
- **Pass rate:** 4/5 (80%)

## Trace-level scores (process)

_Grades the process from the trace — did a substantive verification step revisit the answer — not whether the answer is correct._

_The **Changed** column is a coarse textual signal (first answer vs committed output), not a semantic correction verdict._

| Case | Verified | Score | Changed | Verification | Reason |
| --- | :---: | ---: | :---: | --- | --- |
| bat-and-ball | ✅ | 1.00 | yes | 5  The algebra confirms it: x + (x + 100) = 110, so 2x + 10… | Verification re-derived x=5 via correct algebra and confirm… |
| widget-machines | ✅ | 1.00 | yes | 5  One machine takes 5 minutes to make one widget. With 100… | The verification correctly re-derived the per-machine rate … |
| lily-pads | ❌ | 0.00 | no | 47 | The verification merely restates "47" without any re-checki… |
| months-28-days | ✅ | 1.00 | yes | 12  All twelve months have at least 28 days, since 28 is th… | The verification correctly reasons that all 12 months have … |
| raise-then-discount | ✅ | 1.00 | yes | Step 1: 100 increased by 10% = 100 × 1.10 = 110  Step 2: 11… | Verification correctly recomputes both steps and confirms t… |
