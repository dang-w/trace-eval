"""Phase 2 done-when: committed runs are receipts. Every persisted record names the harness
commit that produced it; a tracked ``runs/`` dir is indexed; and every committed mutation run
is reproduced by the current code (a kill rate is a property of the scorer code, so it gates).
"""

import json
import subprocess
from pathlib import Path

from traceeval.cli import main
from traceeval.ledger import (
    harness_commit,
    index_runs,
    load_record,
    mutation_reproduces,
    render_index,
)
from traceeval.mutate import MutationRecord
from tests.test_cli import SAMPLE_TASK, SOUNDNESS_TASK, always_paris, always_sound_judge_caller

REPO = Path(__file__).parents[1]
RUNS = REPO / "runs"
TASKS = REPO / "tasks"


# --- provenance -------------------------------------------------------------

def test_harness_commit_is_a_short_hash_in_this_repo_and_none_outside(tmp_path):
    commit = harness_commit(REPO)
    assert commit is not None
    assert len(commit["commit"]) >= 7 and all(c in "0123456789abcdef" for c in commit["commit"])
    assert isinstance(commit["dirty"], bool)
    assert harness_commit(tmp_path) is None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_dirty_means_uncommitted_changes_to_tracked_files_only(tmp_path):
    """The flag's definition, pinned: a modified tracked file flips it; an untracked file does not."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "root")
    (tmp_path / "tracked.txt").write_text("a")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add")
    assert harness_commit(tmp_path)["dirty"] is False

    (tmp_path / "untracked.json").write_text("{}")          # e.g. a new mutant fixture, not yet added
    assert harness_commit(tmp_path)["dirty"] is False        # documented limitation, not a promise

    (tmp_path / "tracked.txt").write_text("b")
    assert harness_commit(tmp_path)["dirty"] is True


def test_run_record_names_the_harness_commit_and_scorer_in_filename(tmp_path):
    code = main(["run", str(SAMPLE_TASK), "--scorer", "reference", "--model", "m", "--out", str(tmp_path)],
                model_caller=always_paris)
    assert code == 0
    (path,) = tmp_path.glob("sample-reference-*.json")
    meta = json.loads(path.read_text())["meta"]
    assert meta["commit"] == harness_commit(REPO)["commit"]
    assert "dirty" in meta


def test_meta_and_mutation_records_name_the_harness_commit(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps([{"id": "g1", "question": "q", "reference": "5", "first_answer": "10",
                                 "verify_output": "recheck: 5", "label": "sound"}]))
    assert main(["meta", "--gold", str(gold), "--k", "1", "--model", "j", "--out", str(tmp_path)],
                model_caller=always_sound_judge_caller) == 0
    (meta_path,) = tmp_path.glob("meta-*.json")
    jm = json.loads(meta_path.read_text())["judge_meta"]
    assert jm["commit"] == harness_commit(REPO)["commit"]
    assert jm["run_at"]

    assert main(["mutate", str(SOUNDNESS_TASK), "--out", str(tmp_path)]) == 0
    (mut_path,) = tmp_path.glob("mutation-*.json")
    assert json.loads(mut_path.read_text())["meta"]["commit"] == harness_commit(REPO)["commit"]


# --- index ------------------------------------------------------------------

def test_index_rows_cover_run_meta_and_mutation_records(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps([{"id": "g1", "question": "q", "reference": "5", "first_answer": "10",
                                 "verify_output": "recheck: 5", "label": "sound"}]))
    out = tmp_path / "runs"
    main(["run", str(SAMPLE_TASK), "--scorer", "reference", "--model", "m", "--out", str(out)], model_caller=always_paris)
    main(["meta", "--gold", str(gold), "--k", "1", "--model", "j", "--out", str(out)], model_caller=always_sound_judge_caller)
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])

    rows = index_runs(out)
    kinds = {r.kind for r in rows}
    assert kinds == {"run", "meta", "mutation"}
    by_kind = {r.kind: r for r in rows}
    assert by_kind["run"].task == "sample" and by_kind["run"].scorer == "reference" and by_kind["run"].model == "m"
    assert "1/5" in by_kind["run"].headline                      # always_paris passes one sample case
    assert by_kind["meta"].model == "j" and "gold-agreement" in by_kind["meta"].headline
    assert by_kind["mutation"].task == "soundness" and "verify_before_assert" in by_kind["mutation"].headline
    assert all(r.commit for r in rows)
    # Markdown reports (report.md etc.) in the same dir are not records and are skipped.
    assert all(r.path.suffix == ".json" for r in rows)


def test_index_marks_missing_commit_and_leads_with_framing(tmp_path):
    out = tmp_path / "runs"; out.mkdir()
    legacy = {"meta": {"task": "t", "model": "m", "scorer": "reference", "run_at": "20260708T175334Z"},
              "results": [], "scores": []}
    (out / "t-reference-20260708T175334Z.json").write_text(json.dumps(legacy))
    text = render_index(index_runs(out))
    assert text.startswith("# Run ledger")
    assert "not a benchmark" in text
    assert "untracked files are not counted" in text          # what `dirty` means, where a reader sees it
    assert "| t | run | reference | m | — |" in text            # no commit recorded → em dash


def test_load_record_rejects_non_records(tmp_path):
    """A JSON array (the gold file's shape) or a dict without record keys must not become a run."""
    for name, content in [("array.json", "[]"), ("task.json", '{"name": "x"}'), ("broken.json", "{not json")]:
        path = tmp_path / name
        path.write_text(content)
        try:
            load_record(path)
        except ValueError as exc:
            assert name in str(exc)
        else:
            raise AssertionError(f"{name} should be rejected")


def test_index_command_reports_stray_file_and_exits_2(tmp_path, capsys):
    out = tmp_path / "runs"; out.mkdir()
    (out / "stray.json").write_text('{"name": "not a record"}')
    assert main(["index", "--runs", str(out)]) == 2
    assert "stray.json" in capsys.readouterr().err


def test_undated_rows_sort_last_and_meta_without_gold_shows_dash(tmp_path):
    out = tmp_path / "runs"; out.mkdir()
    dated = {"meta": {"task": "dated", "model": "m", "scorer": "reference", "run_at": "20260101T000000Z"},
             "results": [], "scores": []}
    undated = {"meta": {"task": "undated", "model": "m", "scorer": "reference"}, "results": [], "scores": []}
    (out / "dated-reference-20260101T000000Z.json").write_text(json.dumps(dated))
    (out / "weird.json").write_text(json.dumps(undated))
    (out / "meta-legacy.json").write_text(json.dumps({"judge_meta": {"judge_model": "j", "k": 5}}))
    rows = index_runs(out)
    assert [r.task for r in rows][-1] == "undated"
    meta_row = next(r for r in rows if r.kind == "meta")
    assert meta_row.task == "—"                               # no gold recorded → not fabricated


def test_index_command_writes_index_md(tmp_path, capsys):
    out = tmp_path / "runs"
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])
    assert main(["index", "--runs", str(out)]) == 0
    text = (out / "INDEX.md").read_text()
    assert "| soundness | mutation |" in text
    assert "INDEX.md" in capsys.readouterr().out


def test_index_command_on_empty_dir_says_so(tmp_path):
    out = tmp_path / "runs"; out.mkdir()
    assert main(["index", "--runs", str(out)]) == 0
    assert "no runs recorded yet" in (out / "INDEX.md").read_text()


# --- the gate ---------------------------------------------------------------

def test_mutation_reproduces_detects_tampering(tmp_path):
    out = tmp_path / "runs"
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])
    (path,) = out.glob("mutation-*.json")
    record = load_record(path)
    assert isinstance(record, MutationRecord)
    assert mutation_reproduces(record, TASKS) == []

    record.kill_rates["verify_before_assert"].killed += 1
    diffs = mutation_reproduces(record, TASKS)
    assert diffs and "verify_before_assert" in diffs[0]


def test_gate_is_scoped_to_the_scorers_the_record_names(tmp_path):
    """Adding a scorer to SCORERS is the documented extension point; it must not fail old records."""
    out = tmp_path / "runs"
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])
    (path,) = out.glob("mutation-*.json")
    record = load_record(path)
    from traceeval.cli import SCORERS
    from traceeval.scorers import reference_scorer
    extended = {**SCORERS, "reference_again": reference_scorer}
    assert mutation_reproduces(record, TASKS, extended) == []


def test_gate_ignores_explanation_wording_but_not_behaviour(tmp_path):
    out = tmp_path / "runs"
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])
    (path,) = out.glob("mutation-*.json")
    record = load_record(path)
    record.outcomes[0].reason = "reworded"
    assert mutation_reproduces(record, TASKS) == []
    record.outcomes[0].passed = not record.outcomes[0].passed
    assert mutation_reproduces(record, TASKS)


def test_gate_tolerates_stray_directories_under_tasks(tmp_path):
    tasks = tmp_path / "tasks"
    (tasks / "archive").mkdir(parents=True)                    # no cases.json — must be skipped, not fatal
    import shutil
    shutil.copytree(SOUNDNESS_TASK, tasks / "soundness")
    out = tmp_path / "runs"
    main(["mutate", str(SOUNDNESS_TASK), "--out", str(out)])
    (path,) = out.glob("mutation-*.json")
    assert mutation_reproduces(load_record(path), tasks) == []


def test_every_committed_mutation_run_is_reproduced_by_current_code():
    """The regression gate. Selected by record kind (as the index does), not by filename."""
    records = [(p, load_record(p)) for p in sorted(RUNS.glob("*.json"))]
    mutation_records = [(p, r) for p, r in records if isinstance(r, MutationRecord)]
    assert mutation_records, "runs/ must hold at least one committed mutation run"
    for path, record in mutation_records:
        assert mutation_reproduces(record, TASKS) == [], path.name


def test_committed_runs_dir_is_indexed_and_current():
    """runs/INDEX.md is generated; it must match what the records say."""
    assert (RUNS / "INDEX.md").read_text() == render_index(index_runs(RUNS))
