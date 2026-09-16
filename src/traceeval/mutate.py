"""Mutation testing for scorers: feed each scorer deliberately broken runs and see which fail to fail.

The motivating pathology (buildlog Finding 2): ``verify_before_assert`` posted 100% because it
could not discriminate — it measured the *presence* of a verification step, not its efficacy.
A scorer that passes everything looks identical to a scorer that works, until you hand it
something it should reject. This module is the systematic version of that catch: before
trusting a scorer's pass rate, prove the scorer can be made to fail.

Mutants are static fixtures (``tasks/<task>/mutants/*.json``), each a hand-edited copy of a
known-good ``Result`` tagged with the *class* of breakage. No model calls: the mode is cheap,
deterministic, and offline. v1 mutants are hand-authored — there is deliberately no mutation
operator DSL or auto-generation here.

Kill semantics, kept honest in three ways:

1. **Killed** = an *applicable* scorer returned ``passed=False`` on the mutant. A scorer is
   applicable to a mutant when the mutant breaks the dimension the scorer grades (an output
   scorer vs a wrong answer; a trace scorer vs a gutted verify step). A reference scorer that
   correctly passes an intact answer over a broken trace has not "survived" anything — that
   result is recorded, but it does not count either way.
2. **Baseline** = the unmodified run, included as a control, one per case that has mutants. A
   scorer that fails a baseline fails everything and would post a perfect kill rate for free —
   so its kill rate is withheld (``None``), not reported as 100%. A case with mutants but *no*
   baseline is withheld too: an unmeasured control is not a passed control.
3. **Survivors are named with the class they accepted** so the report reads as a diagnosis
   ("this scorer accepted a broken run of class X"), never as a score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from traceeval.scorers import Scorer
from traceeval.types import Case, DIM_OUTPUT, DIM_TRACE, Result

# --- Mutant classes ---------------------------------------------------------
# Each class names what was broken; the dimension says which scorers are on the hook for it.
CLASS_BASELINE = "baseline"  # the unmodified control — applicable to nothing, passed by everything

MUTANT_CLASSES: dict[str, str] = {
    "wrong-answer": DIM_OUTPUT,        # final answer altered; trace untouched
    "empty-verify": DIM_TRACE,         # verify step content stripped to nothing
    "rubber-stamp": DIM_TRACE,         # verify step is a bare restatement, no working
    "contradicted-verify": DIM_TRACE,  # verify derives a different value; final answer unchanged
    "missing-trace": DIM_TRACE,        # trace absent entirely
}

MUTANTS_DIRNAME = "mutants"


@dataclass
class Mutant:
    """One deliberately broken run: a Result plus the class of breakage and its provenance."""

    id: str
    cls: str
    case_id: str
    result: Result
    synthetic: bool = True
    note: str = ""
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class": self.cls,
            "case_id": self.case_id,
            "synthetic": self.synthetic,
            "provenance": self.provenance,
            "note": self.note,
            "result": self.result.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Mutant:
        mutant_cls = d["class"]
        if mutant_cls != CLASS_BASELINE and mutant_cls not in MUTANT_CLASSES:
            known = ", ".join([CLASS_BASELINE, *MUTANT_CLASSES])
            raise ValueError(f"unknown mutant class {mutant_cls!r} in {d.get('id')!r} (known: {known})")
        return cls(
            id=d["id"],
            cls=mutant_cls,
            case_id=d["case_id"],
            result=Result.from_dict(d["result"]),
            synthetic=bool(d.get("synthetic", True)),
            note=d.get("note", ""),
            provenance=d.get("provenance", ""),
        )


def load_mutants(task_dir: str | Path) -> list[Mutant]:
    """Load every ``mutants/*.json`` under a task directory, in filename order.

    Raises ``FileNotFoundError`` if the task has no mutants directory, so the CLI can say so
    rather than silently reporting a kill rate over nothing.
    """
    mutants_dir = Path(task_dir) / MUTANTS_DIRNAME
    if not mutants_dir.is_dir():
        raise FileNotFoundError(f"no {MUTANTS_DIRNAME}/ directory in task dir: {task_dir}")
    paths = sorted(mutants_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"no mutant files (*.json) in {mutants_dir}")
    mutants = []
    for path in paths:
        try:
            mutants.append(Mutant.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"malformed mutant fixture {path}: {type(exc).__name__}: {exc}") from exc
    return mutants


# --- Outcomes ---------------------------------------------------------------

@dataclass
class MutantOutcome:
    """One scorer's verdict on one mutant, plus whether that verdict counts."""

    mutant_id: str
    mutant_cls: str
    scorer: str
    passed: bool
    applicable: bool
    reason: str = ""

    @property
    def killed(self) -> bool:
        return self.applicable and not self.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "mutant_cls": self.mutant_cls,
            "scorer": self.scorer,
            "passed": self.passed,
            "applicable": self.applicable,
            "killed": self.killed,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MutantOutcome:
        return cls(
            mutant_id=d["mutant_id"],
            mutant_cls=d["mutant_cls"],
            scorer=d["scorer"],
            passed=d["passed"],
            applicable=d["applicable"],
            reason=d.get("reason", ""),
        )


@dataclass
class KillRate:
    """Per-scorer tally: mutants killed over mutants applicable, gated on the baselines.

    ``baselines`` maps every case that has mutants to this scorer's verdict on that case's
    baseline: ``True`` passed, ``False`` failed, ``None`` no baseline fixture exists.
    """

    scorer: str
    killed: int
    applicable: int
    survivors: list[str] = field(default_factory=list)
    baselines: dict[str, bool | None] = field(default_factory=dict)

    @property
    def baseline_passed(self) -> bool | None:
        """``True`` only if every case's baseline exists and passed; ``False`` if any failed;
        ``None`` if any is missing (or there are no cases at all)."""
        verdicts = list(self.baselines.values())
        if any(v is False for v in verdicts):
            return False
        if not verdicts or any(v is None for v in verdicts):
            return None
        return True

    @property
    def rate(self) -> float | None:
        """Killed / applicable — or ``None`` when the number would be misleading.

        Withheld unless every baseline passed (a scorer that fails a control fails everything,
        so its kills are free; a missing control is unmeasured, not passed) and when nothing
        was applicable (0/0 is not a measurement).
        """
        if self.baseline_passed is not True or self.applicable == 0:
            return None
        return self.killed / self.applicable

    def to_dict(self) -> dict[str, Any]:
        # ``rate`` and ``baseline_passed`` are derived; they are written for readers of the JSON
        # and ignored on load, so a hand-edited value can never disagree with its inputs.
        return {
            "scorer": self.scorer,
            "killed": self.killed,
            "applicable": self.applicable,
            "rate": self.rate,
            "survivors": list(self.survivors),
            "baselines": dict(self.baselines),
            "baseline_passed": self.baseline_passed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KillRate:
        return cls(
            scorer=d["scorer"],
            killed=d["killed"],
            applicable=d["applicable"],
            survivors=list(d.get("survivors", [])),
            baselines=dict(d.get("baselines", {})),
        )


def kill_rate_verdict(kr: KillRate) -> str:
    """The one-line reading of a kill rate, shared by the CLI summary and the report."""
    if kr.baseline_passed is False:
        return "void — fails the baseline"
    if kr.baseline_passed is None:
        return "void — no baseline"
    if kr.applicable == 0:
        return "n/a — nothing applicable"
    return f"{kr.rate:.0%}"


@dataclass
class MutationRecord:
    """A whole mutation run: every outcome, the per-scorer kill rates, and the mutants used."""

    outcomes: list[MutantOutcome] = field(default_factory=list)
    kill_rates: dict[str, KillRate] = field(default_factory=dict)
    mutants: list[Mutant] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "kill_rates": {name: kr.to_dict() for name, kr in self.kill_rates.items()},
            "outcomes": [o.to_dict() for o in self.outcomes],
            "mutants": [m.to_dict() for m in self.mutants],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MutationRecord:
        return cls(
            outcomes=[MutantOutcome.from_dict(o) for o in d.get("outcomes", [])],
            kill_rates={name: KillRate.from_dict(kr) for name, kr in d.get("kill_rates", {}).items()},
            mutants=[Mutant.from_dict(m) for m in d.get("mutants", [])],
            meta=d.get("meta", {}) or {},
        )


def _check_mutant_set(mutants: list[Mutant], cases_by_id: dict[str, Case]) -> None:
    """Reject a mutant set that would make the tally lie: unknown cases, duplicate ids, or
    more than one baseline for a case (last-write-wins would let one control hide another)."""
    seen_ids: set[str] = set()
    baseline_cases: set[str] = set()
    for m in mutants:
        if m.case_id not in cases_by_id:
            raise KeyError(f"mutant {m.id!r} references unknown case {m.case_id!r}")
        if m.id in seen_ids:
            raise ValueError(f"duplicate mutant id {m.id!r}")
        seen_ids.add(m.id)
        if m.cls == CLASS_BASELINE:
            if m.case_id in baseline_cases:
                raise ValueError(f"more than one baseline mutant for case {m.case_id!r}")
            baseline_cases.add(m.case_id)


def run_mutation(
    cases: list[Case],
    mutants: list[Mutant],
    scorers: dict[str, Scorer],
    *,
    task_name: str = "",
) -> MutationRecord:
    """Apply every scorer to every mutant and tally kill rates.

    ``scorers`` maps a display name to a scorer function. Applicability is decided per
    outcome from the *scored* dimension (``Score.dimension``) against the mutant class's
    dimension, so a scorer never has to declare itself.
    """
    cases_by_id = {c.id: c for c in cases}
    _check_mutant_set(mutants, cases_by_id)

    case_ids = sorted({m.case_id for m in mutants})
    outcomes: list[MutantOutcome] = []
    # scorer -> case -> baseline verdict; None until (unless) a baseline for that case is scored.
    baselines: dict[str, dict[str, bool | None]] = {name: {c: None for c in case_ids} for name in scorers}

    for mutant in mutants:
        case = cases_by_id[mutant.case_id]
        for name, scorer in scorers.items():
            score = scorer(case, mutant.result)
            if mutant.cls == CLASS_BASELINE:
                baselines[name][mutant.case_id] = score.passed
                applicable = False
            else:
                applicable = MUTANT_CLASSES[mutant.cls] == score.dimension
            outcomes.append(MutantOutcome(
                mutant_id=mutant.id, mutant_cls=mutant.cls, scorer=name,
                passed=score.passed, applicable=applicable, reason=score.explanation,
            ))

    kill_rates: dict[str, KillRate] = {}
    for name in scorers:
        mine = [o for o in outcomes if o.scorer == name and o.applicable]
        kill_rates[name] = KillRate(
            scorer=name,
            killed=sum(1 for o in mine if o.killed),
            applicable=len(mine),
            survivors=[o.mutant_id for o in mine if not o.killed],
            baselines=baselines[name],
        )

    return MutationRecord(
        outcomes=outcomes,
        kill_rates=kill_rates,
        mutants=list(mutants),
        meta={"task": task_name, "scorers": list(scorers), "mutant_count": len(mutants)},
    )
