"""Tasks 3 & 4 done-when: meta-eval measures how much to trust the judge.

Self-consistency — run the judge K times per item, retain every raw verdict, flag flips.
Gold-agreement — compare the judge's verdict to a small hand-labelled gold set.

All offline via the scripted fake judge, including a deliberately inconsistent judge fixture
that proves the self-consistency measurement actually detects inconsistency.
"""

import json

import pytest

from traceeval.judge import VERDICT_SOUND, VERDICT_UNSOUND, verification_sound_judge
from traceeval.metaeval import (
    compute_gold_agreement,
    load_gold,
    run_meta_eval,
    run_self_consistency,
)
from traceeval.types import (
    Case,
    Result,
    ROLE_ANSWER,
    ROLE_VERIFY,
    STEP_MODEL_CALL,
    Trace,
    TraceStep,
)
from tests.test_runner import ScriptedCaller


def _verdict(v: str, rationale: str = "because") -> str:
    return f"VERDICT: {v}\nRATIONALE: {rationale}"


def _step(role: str, output: str) -> TraceStep:
    return TraceStep(kind=STEP_MODEL_CALL, output=output, metadata={"role": role})


def _result(case_id: str, first: str, verify: str) -> Result:
    return Result(case_id=case_id, output=verify,
                  trace=Trace(steps=[_step(ROLE_ANSWER, first), _step(ROLE_VERIFY, verify)]))


def _case(case_id: str) -> Case:
    return Case(id=case_id, input="q", reference="5", self_check="recheck")


# --- self-consistency ---------------------------------------------------------

def test_self_consistency_flags_unanimous_run():
    caller = ScriptedCaller(_verdict("sound"), _verdict("sound"), _verdict("sound"))
    judge = verification_sound_judge(caller, model="jm")
    sc = run_self_consistency([_case("c1")], [_result("c1", "10", "the ball is 5")], judge, k=3)

    assert sc.k == 3
    item = sc.items[0]
    assert item.agreement == 1.0
    assert item.flipped is False
    assert item.majority == VERDICT_SOUND
    assert sc.flip_rate == 0.0
    assert sc.mean_agreement == 1.0


def test_self_consistency_detects_an_inconsistent_judge():
    # The fixture that matters: a judge that flips across identical calls must be caught.
    caller = ScriptedCaller(_verdict("sound"), _verdict("unsound"), _verdict("sound"))
    judge = verification_sound_judge(caller, model="jm")
    sc = run_self_consistency([_case("c1")], [_result("c1", "10", "the ball is 5")], judge, k=3)

    item = sc.items[0]
    assert item.flipped is True
    assert item.agreement == pytest.approx(2 / 3)
    assert item.majority == VERDICT_SOUND  # 2 of 3
    assert sc.flip_rate == 1.0  # the one item flipped


def test_self_consistency_retains_every_raw_verdict():
    caller = ScriptedCaller(_verdict("sound"), _verdict("unsound"), _verdict("sound"))
    judge = verification_sound_judge(caller, model="jm")
    sc = run_self_consistency([_case("c1")], [_result("c1", "10", "v")], judge, k=3)

    verdicts = [s.verdict for s in sc.items[0].samples]
    assert verdicts == [VERDICT_SOUND, VERDICT_UNSOUND, VERDICT_SOUND]
    # Raw judge output is kept, not collapsed to just the verdict.
    assert all(s.raw.startswith("VERDICT:") for s in sc.items[0].samples)


# --- gold-agreement -----------------------------------------------------------

def _gold_item(item_id: str, label: str) -> dict:
    return {
        "id": item_id,
        "question": "A bat and a ball cost $1.10 ...",
        "reference": "5",
        "first_answer": "10",
        "verify_output": "Rechecking: the ball is 5 cents.",
        "label": label,
    }


def test_load_gold_parses_self_contained_items(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([_gold_item("g1", "sound"), _gold_item("g2", "unsound")]))
    items = load_gold(path)
    assert [i.id for i in items] == ["g1", "g2"]
    assert [i.label for i in items] == [VERDICT_SOUND, VERDICT_UNSOUND]
    # Each item is self-contained: it carries the judge's inputs, not just an id→label.
    assert items[0].question.startswith("A bat")
    assert items[0].first_answer == "10"
    assert items[0].reference == "5"


def test_load_gold_rejects_bad_label(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps([_gold_item("g1", "maybe")]))
    with pytest.raises(ValueError):
        load_gold(path)


def test_gold_agreement_scores_and_lists_disagreements():
    caller = ScriptedCaller(_verdict("sound"), _verdict("unsound"))  # c1 sound, c2 unsound
    judge = verification_sound_judge(caller, model="jm")
    cases = [_case("c1"), _case("c2")]
    results = [_result("c1", "10", "v"), _result("c2", "10", "v")]
    sc = run_self_consistency(cases, results, judge, k=1)

    gold = {"c1": VERDICT_SOUND, "c2": VERDICT_SOUND}  # human says both sound; judge said c2 unsound
    ga = compute_gold_agreement(sc, gold)

    assert ga.n == 2
    assert ga.agreement == 0.5
    assert len(ga.disagreements) == 1
    d = ga.disagreements[0]
    assert d.case_id == "c2" and d.judge == VERDICT_UNSOUND and d.human == VERDICT_SOUND


# --- orchestration ------------------------------------------------------------

def test_run_meta_eval_end_to_end_records_trust_figures(tmp_path):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps([_gold_item("g1", "sound"), _gold_item("g2", "sound")]))

    caller = ScriptedCaller(
        _verdict("sound"), _verdict("sound"),      # g1 ×2 (unanimous 'sound', agrees with human)
        _verdict("unsound"), _verdict("sound"),    # g2 ×2 (a tie → majority tie-breaks to first-seen)
    )
    judge = verification_sound_judge(caller, model="jm", max_tokens=256)

    record = run_meta_eval(load_gold(gold_path), judge, k=2,
                           judge_meta={"judge_model": "jm", "judge_max_tokens": 256})

    assert record.self_consistency.k == 2
    assert record.self_consistency.flip_rate == 0.5  # g2 flipped, g1 did not
    assert record.gold_agreement is not None
    assert record.gold_agreement.n == 2
    # g1 majority 'sound' agrees; g2's 1-1 tie breaks to first-seen 'unsound', disagreeing.
    assert record.gold_agreement.agreement == 0.5
    assert [d.case_id for d in record.gold_agreement.disagreements] == ["g2"]
    assert record.judge_meta["judge_model"] == "jm"
    assert record.judge_meta["k"] == 2
    # Round-trips through JSON without loss (raw verdicts retained on disk).
    restored = type(record).from_dict(record.to_dict())
    assert restored.self_consistency.items[0].samples[0].verdict in (VERDICT_SOUND, VERDICT_UNSOUND)
