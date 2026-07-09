"""Meta-eval: measure how much to trust the judge — *before* trusting any score it makes.

The ``verification_sound`` judge is an LLM, so two questions must be answered with numbers
before its verdicts mean anything:

1. **Self-consistency.** Ask the same question K times. A judge that flips its verdict across
   identical calls is unstable, and its single verdicts can't be trusted. We run the judge K
   times per item, **retain every raw verdict** (never collapse to a point estimate early),
   and report the spread: per-item agreement and an aggregate flip rate.

2. **Gold-agreement.** Self-consistency measures *stability*, not *correctness* — a judge can
   be perfectly consistent and consistently wrong. So we also compare the judge's verdict to a
   small hand-labelled human gold set and report agreement plus the exact disagreements.

Neither number is the judge's score of a task. They are the *trust* you place in that score,
and the report leads with them for exactly that reason (see ``report.py``). This module is the
thesis applied to itself: verify the verifier, including when the verifier is a judge.

Everything is offline-testable: the judge is a closure over a ``ModelCaller``, so a scripted
fake judge (including a deliberately inconsistent one) drives the whole measurement in tests.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from traceeval.judge import VERDICT_SOUND, VERDICT_UNSOUND
from traceeval.scorers import Scorer
from traceeval.types import (
    Case,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    STEP_MODEL_CALL,
    Trace,
    TraceStep,
)

_VALID_LABELS = {VERDICT_SOUND, VERDICT_UNSOUND}


@dataclass
class JudgeSample:
    """One raw judge run: its verdict, its rationale, and the untouched raw output.

    The raw is kept, not discarded, because "the raw judgements are all recorded" is what
    reproducibility means for a stochastic judge — not that the judge is deterministic.
    """

    verdict: str
    rationale: str
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "rationale": self.rationale, "raw": self.raw}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JudgeSample:
        return cls(verdict=d["verdict"], rationale=d.get("rationale", ""), raw=d.get("raw", ""))


@dataclass
class ItemConsistency:
    """The K judge samples for one item, plus the stability figures derived from them."""

    case_id: str
    samples: list[JudgeSample] = field(default_factory=list)

    @property
    def verdicts(self) -> list[str]:
        return [s.verdict for s in self.samples]

    @property
    def majority(self) -> str:
        """The most common verdict across the K samples (ties broken by first-seen order)."""
        return Counter(self.verdicts).most_common(1)[0][0]

    @property
    def agreement(self) -> float:
        """Fraction of samples that share the majority verdict (1.0 = unanimous)."""
        counts = Counter(self.verdicts)
        return counts.most_common(1)[0][1] / len(self.samples)

    @property
    def flipped(self) -> bool:
        """True if the judge did not return the same verdict every time."""
        return len(set(self.verdicts)) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "samples": [s.to_dict() for s in self.samples],
            "majority": self.majority,
            "agreement": self.agreement,
            "flipped": self.flipped,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ItemConsistency:
        return cls(case_id=d["case_id"], samples=[JudgeSample.from_dict(s) for s in d.get("samples", [])])


@dataclass
class SelfConsistency:
    """Aggregate self-consistency over all judged items."""

    k: int
    items: list[ItemConsistency] = field(default_factory=list)

    @property
    def mean_agreement(self) -> float:
        return sum(i.agreement for i in self.items) / len(self.items) if self.items else 0.0

    @property
    def flip_rate(self) -> float:
        """Fraction of items on which the judge flipped at least once."""
        return sum(1 for i in self.items if i.flipped) / len(self.items) if self.items else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "mean_agreement": self.mean_agreement,
            "flip_rate": self.flip_rate,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SelfConsistency:
        return cls(k=d["k"], items=[ItemConsistency.from_dict(i) for i in d.get("items", [])])


@dataclass
class GoldDisagreement:
    case_id: str
    judge: str
    human: str

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "judge": self.judge, "human": self.human}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GoldDisagreement:
        return cls(case_id=d["case_id"], judge=d["judge"], human=d["human"])


@dataclass
class GoldAgreement:
    """Judge-vs-human agreement over the gold items, and the exact disagreements."""

    n: int
    agreement: float
    disagreements: list[GoldDisagreement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "agreement": self.agreement,
            "disagreements": [d.to_dict() for d in self.disagreements],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GoldAgreement:
        return cls(
            n=d["n"],
            agreement=d["agreement"],
            disagreements=[GoldDisagreement.from_dict(x) for x in d.get("disagreements", [])],
        )


@dataclass
class MetaEvalRecord:
    """Everything a reader needs to weigh the judge: trust figures + every raw judgement."""

    judge_meta: dict[str, Any] = field(default_factory=dict)
    self_consistency: SelfConsistency | None = None
    gold_agreement: GoldAgreement | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_meta": self.judge_meta,
            "self_consistency": self.self_consistency.to_dict() if self.self_consistency else None,
            "gold_agreement": self.gold_agreement.to_dict() if self.gold_agreement else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetaEvalRecord:
        sc = d.get("self_consistency")
        ga = d.get("gold_agreement")
        return cls(
            judge_meta=d.get("judge_meta", {}) or {},
            self_consistency=SelfConsistency.from_dict(sc) if sc else None,
            gold_agreement=GoldAgreement.from_dict(ga) if ga else None,
        )


def run_self_consistency(
    cases: list[Case], results: list[Result], judge: Scorer, *, k: int
) -> SelfConsistency:
    """Run ``judge`` K times over each (case, result) and collect the raw samples.

    Items the judge declines (``judged=False`` — e.g. no verification step to grade) carry no
    verdict, so they are skipped: there is nothing whose stability to measure. Every retained
    item keeps all K raw samples.
    """
    items: list[ItemConsistency] = []
    for case, result in zip(cases, results):
        samples: list[JudgeSample] = []
        for _ in range(k):
            score = judge(case, result)
            if not score.detail.get("judged"):
                break  # deterministic decline — nothing to sample for this item
            samples.append(
                JudgeSample(
                    verdict=score.detail["verdict"],
                    rationale=score.detail.get("rationale", ""),
                    raw=score.detail.get("judge_raw", ""),
                )
            )
        if samples:
            items.append(ItemConsistency(case_id=case.id, samples=samples))
    return SelfConsistency(k=k, items=items)


@dataclass
class GoldItem:
    """One hand-labelled gold example: a full judge input plus the human verdict.

    The gold set is **self-contained**, not keyed to a live run. A human label attaches to a
    *specific* verify-step output; live traces vary run to run, so the labelled material has to
    travel with the fixture. Each item carries exactly what the judge sees (question, first
    answer, verify output, reference) and what the human decided (``label``).
    """

    id: str
    question: str
    first_answer: str
    verify_output: str
    label: str  # human verdict: sound | unsound
    reference: str | None = None

    def to_case_and_result(self) -> tuple[Case, Result]:
        """Reconstitute the judge's inputs as a ``(Case, Result)`` so the judge runs unchanged."""
        case = Case(id=self.id, input=self.question, reference=self.reference)
        result = Result(
            case_id=self.id,
            output=self.verify_output,
            trace=Trace(steps=[
                TraceStep(kind=STEP_MODEL_CALL, output=self.first_answer, metadata={"role": ROLE_ANSWER}),
                TraceStep(kind=STEP_MODEL_CALL, output=self.verify_output, metadata={"role": ROLE_VERIFY}),
            ]),
        )
        return case, result


def load_gold(path: str | Path) -> list[GoldItem]:
    """Load a hand-labelled gold file: a list of self-contained, labelled judge examples.

    Validates every label, so a typo in the human gold surfaces loudly rather than silently
    skewing agreement. The gold set is small and hand-labelled by design — treated as a tested
    fixture, not generated.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[GoldItem] = []
    for d in data:
        label = str(d["label"]).strip().lower()
        if label not in _VALID_LABELS:
            raise ValueError(
                f"gold label for {d.get('id')!r} must be one of {sorted(_VALID_LABELS)}, got {label!r}"
            )
        items.append(
            GoldItem(
                id=d["id"],
                question=d["question"],
                first_answer=d["first_answer"],
                verify_output=d["verify_output"],
                label=label,
                reference=d.get("reference"),
            )
        )
    return items


def gold_to_cases(items: list[GoldItem]) -> tuple[list[Case], list[Result], dict[str, str]]:
    """Split gold items into the cases, results, and ``{id: label}`` map the meta-eval needs."""
    cases: list[Case] = []
    results: list[Result] = []
    labels: dict[str, str] = {}
    for item in items:
        case, result = item.to_case_and_result()
        cases.append(case)
        results.append(result)
        labels[item.id] = item.label
    return cases, results, labels


def compute_gold_agreement(consistency: SelfConsistency, gold: dict[str, str]) -> GoldAgreement:
    """Compare the judge's majority verdict to the human gold label, item by item.

    Only items present in both the run and the gold set count. The judge's verdict is its
    *majority* across the K samples — the most representative single call — so agreement is
    read against the judge's central tendency, not one lucky sample.
    """
    by_id = {i.case_id: i for i in consistency.items}
    shared = [cid for cid in gold if cid in by_id]
    disagreements: list[GoldDisagreement] = []
    for cid in shared:
        judge_verdict = by_id[cid].majority
        human = gold[cid]
        if judge_verdict != human:
            disagreements.append(GoldDisagreement(case_id=cid, judge=judge_verdict, human=human))
    n = len(shared)
    agreement = (n - len(disagreements)) / n if n else 0.0
    return GoldAgreement(n=n, agreement=agreement, disagreements=disagreements)


def run_meta_eval(
    gold_items: list[GoldItem],
    judge: Scorer,
    *,
    k: int,
    judge_meta: dict[str, Any] | None = None,
) -> MetaEvalRecord:
    """Full meta-eval over the gold set: K-sample the judge once, derive both trust figures.

    Both figures are measured on the same controlled corpus — the hand-labelled gold set — so
    self-consistency (stability) and gold-agreement (correctness) describe the *same* judge on
    the *same* fixed inputs. The single K-sampling pass feeds both: gold-agreement reads the
    majority verdicts self-consistency already computed, so the judge is never called twice for
    one job.
    """
    cases, results, labels = gold_to_cases(gold_items)
    consistency = run_self_consistency(cases, results, judge, k=k)
    gold_agreement = compute_gold_agreement(consistency, labels)
    return MetaEvalRecord(
        judge_meta=dict(judge_meta or {}, k=k),
        self_consistency=consistency,
        gold_agreement=gold_agreement,
    )
