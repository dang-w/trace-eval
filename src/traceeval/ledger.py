"""The run ledger: committed records as receipts.

``results/`` is gitignored scratch. ``runs/`` is tracked: a record lands there deliberately,
with the finding it supports, and stays. Three things make a committed record a *receipt*
rather than a stale number:

1. **Provenance.** Every record names the harness commit that produced it (and whether the
   working tree was dirty), so a finding about a scorer is tied to the scorer code that made it.
2. **An index.** ``runs/INDEX.md`` is generated from the records, never hand-edited, so the
   directory is readable without opening every file.
3. **A gate for what is deterministic.** A mutation run has no model calls, so its kill rates
   are a property of the code. Every committed mutation run must be reproduced by the current
   code (``mutation_reproduces``); a scorer change that lets a mutant through fails the suite.

LLM runs are the opposite: receipts, not baselines. They are labelled with model and date and
never diff-gated, because they vary run to run.

This is a practitioner's run log on a toy harness, not a benchmark, and the index says so.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import traceeval
from traceeval.metaeval import MetaEvalRecord
from traceeval.mutate import MutationRecord, kill_rate_verdict, run_mutation
from traceeval.store import RunRecord

RUNS_DIRNAME = "runs"
INDEX_FILENAME = "INDEX.md"
FINDINGS_FILENAME = "FINDINGS.md"        # at the repo root; the findings the records are receipts for
FINDINGS_MAP_FILENAME = "findings.json"  # sidecar in runs/: {record filename: finding id}

KIND_RUN = "run"
KIND_META = "meta"
KIND_MUTATION = "mutation"

# The harness code lives here; its git commit is the provenance every record carries.
_HARNESS_ROOT = Path(traceeval.__file__).resolve().parent


def harness_commit(root: str | Path = _HARNESS_ROOT) -> dict[str, Any] | None:
    """The git commit the code at ``root`` is checked out at, plus whether the tree is dirty.

    ``dirty`` means *uncommitted changes to tracked files*. Untracked files are not counted —
    so a brand-new, never-added mutant fixture does not flip it. That is a limitation, stated
    wherever the flag is shown, not a promise of reproducibility.

    Returns ``None`` when ``root`` is not inside a git repository (or git is unavailable), so
    a record made outside version control simply carries no provenance rather than failing.
    Provenance assumes the harness is an editable install from the repo (``pip install -e``);
    a frozen copy installed inside a repo would report that repo's HEAD, not its own source.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return {"commit": head, "dirty": bool(status.strip())}


def load_record(path: str | Path) -> RunRecord | MetaEvalRecord | MutationRecord:
    """Load any persisted record, telling the three kinds apart by their top-level keys.

    Anything that is not one of the three record shapes raises ``ValueError`` naming the
    file — a stray JSON in the ledger must never be indexed as a fabricated run.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a trace-eval record: {path} (invalid JSON: {exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"not a trace-eval record: {path} (top level is not an object)")
    if "kill_rates" in data:
        return MutationRecord.from_dict(data)
    if "judge_meta" in data:
        return MetaEvalRecord.from_dict(data)
    if "results" in data and "scores" in data:
        return RunRecord.from_dict(data)
    raise ValueError(f"not a trace-eval record: {path} (no run, meta, or mutation keys)")


def load_findings_map(runs_dir: str | Path) -> dict[str, str]:
    """The sidecar ``findings.json``: which finding each record is the receipt for.

    A sidecar, rather than a field in each record, so committed receipts are never edited to
    annotate them. Absent file → empty map (records simply show no finding). An entry naming a
    record that does not exist is an error: a receipt pointer that points at nothing is worse
    than none.
    """
    runs_dir = Path(runs_dir)
    path = runs_dir / FINDINGS_MAP_FILENAME
    if not path.exists():
        return {}
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed findings map {path}: {exc}") from exc
    if not isinstance(mapping, dict) or not all(isinstance(v, str) for v in mapping.values()):
        raise ValueError(f"malformed findings map {path}: expected {{record filename: finding id}}")
    missing = [name for name in mapping if not (runs_dir / name).exists()]
    if missing:
        raise ValueError(f"findings map {path} names record(s) that do not exist: {', '.join(missing)}")
    return mapping


@dataclass
class IndexRow:
    """One line of the ledger index: what ran, on what, when, the one-line result, and which
    finding (if any) the record is the receipt for."""

    path: Path
    kind: str
    task: str
    scorer: str
    model: str
    commit: str | None
    dirty: bool | None
    run_at: str
    headline: str
    finding: str | None = None


def _stamp_from_filename(path: Path) -> str:
    tail = path.stem.rsplit("-", 1)[-1]
    return tail if tail.endswith("Z") and tail[:8].isdigit() else "—"


def _row_for(path: Path, record: RunRecord | MetaEvalRecord | MutationRecord) -> IndexRow:
    if isinstance(record, MutationRecord):
        meta = record.meta
        headline = "; ".join(
            f"{name}: {kr.killed}/{kr.applicable} ({kill_rate_verdict(kr)})" for name, kr in record.kill_rates.items()
        )
        return IndexRow(
            path=path, kind=KIND_MUTATION, task=meta.get("task", "—"),
            scorer=", ".join(meta.get("scorers", [])) or "—", model="— (no model calls)",
            commit=meta.get("commit"), dirty=meta.get("dirty"),
            run_at=meta.get("run_at") or _stamp_from_filename(path), headline=headline,
        )
    if isinstance(record, MetaEvalRecord):
        jm = record.judge_meta
        sc, ga = record.self_consistency, record.gold_agreement
        parts = []
        parts.append(
            f"self-consistency {sc.mean_agreement:.0%} (flip rate {sc.flip_rate:.0%})"
            if sc and sc.items else "self-consistency not measured"
        )
        parts.append(
            f"gold-agreement {ga.agreement:.0%} ({ga.n - len(ga.disagreements)}/{ga.n})"
            if ga and ga.n else "gold-agreement not measured"
        )
        return IndexRow(
            path=path, kind=KIND_META, task=jm.get("gold") or "—",
            scorer=f"verification_sound (judge, K={jm.get('k', '—')})", model=jm.get("judge_model", "—"),
            commit=jm.get("commit"), dirty=jm.get("dirty"),
            run_at=jm.get("run_at") or _stamp_from_filename(path), headline=", ".join(parts),
        )
    meta = record.meta
    total = len(record.scores)
    passed = sum(1 for s in record.scores if s.passed)
    errored = sum(1 for r in record.results if r.error)
    pct = (100.0 * passed / total) if total else 0.0
    headline = f"{passed}/{total} passed ({pct:.0f}%)" + (f", {errored} errored" if errored else "")
    return IndexRow(
        path=path, kind=KIND_RUN, task=meta.get("task", "—"), scorer=meta.get("scorer", "—"),
        model=meta.get("model", "—"), commit=meta.get("commit"), dirty=meta.get("dirty"),
        run_at=meta.get("run_at") or _stamp_from_filename(path), headline=headline,
    )


def index_runs(runs_dir: str | Path) -> list[IndexRow]:
    """One row per JSON record in ``runs_dir``, newest first. Non-JSON files are ignored."""
    runs_dir = Path(runs_dir)
    findings = load_findings_map(runs_dir)
    rows = []
    for p in sorted(runs_dir.glob("*.json")):
        if p.name == FINDINGS_MAP_FILENAME:
            continue
        row = _row_for(p, load_record(p))
        row.finding = findings.get(p.name)
        rows.append(row)
    # Newest first; rows with no date at all go last, never to the top as if newest.
    return sorted(rows, key=lambda r: (r.run_at != "—", r.run_at), reverse=True)


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_index(rows: list[IndexRow]) -> str:
    """The ledger index as markdown: framing first, then one row per record."""
    lines = [
        "# Run ledger",
        "",
        "_Generated by `trace-eval index`; do not edit by hand. Committed records of real runs, "
        "kept as the receipts behind the findings in this repo. This is a practitioner's run log "
        "on a toy harness, not a benchmark. LLM runs vary run to run: they are labelled with model "
        "and date and are never treated as baselines. Mutation runs make no model calls, so their "
        "kill rates are a property of the scorer code and the test suite checks that the current "
        "code reproduces every committed one. `Commit` is the harness commit the record was "
        "produced from; `*` means uncommitted changes to tracked files were present, so the record "
        "is not reproducible from that commit alone (untracked files are not counted); `—` means "
        "the record predates provenance tracking. `Finding` links the entry in "
        f"`{FINDINGS_FILENAME}` this record is the receipt for; read it before the number._",
        "",
    ]
    if not rows:
        lines += ["_no runs recorded yet_", ""]
        return "\n".join(lines)
    lines += [
        "| Task | Kind | Scorer | Model | Commit | Run at | Headline | Finding | File |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        commit = "—" if not r.commit else (f"{r.commit}*" if r.dirty else r.commit)
        finding = f"[{_finding_label(r.finding)}](../{FINDINGS_FILENAME}#{r.finding})" if r.finding else "—"
        lines.append(
            f"| {_md(r.task)} | {r.kind} | {_md(r.scorer)} | {_md(r.model)} | {commit} "
            f"| {r.run_at} | {_md(r.headline)} | {finding} | [{r.path.name}]({r.path.name}) |"
        )
    lines.append("")
    return "\n".join(lines)


def _finding_label(finding_id: str) -> str:
    """``finding-2`` → ``Finding 2``; any other id is shown as written."""
    return finding_id.replace("-", " ").capitalize()


def write_index(runs_dir: str | Path) -> Path:
    """Regenerate ``INDEX.md`` inside ``runs_dir`` and return its path."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / INDEX_FILENAME
    path.write_text(render_index(index_runs(runs_dir)), encoding="utf-8")
    return path


def mutation_reproduces(
    record: MutationRecord,
    tasks_root: str | Path,
    scorers: dict | None = None,
) -> list[str]:
    """Re-run the mutation the record describes against the current code; list every difference.

    An empty list means the committed record is what the current scorers and fixtures produce.
    The gate is scoped to the scorers the record names, so adding a scorer to the harness does
    not invalidate old receipts; and it compares *behaviour* (passed / applicable / killed),
    not the scorer's explanation wording, so a reworded reason string is not a regression.
    Kill rates are compared first (the headline), then every outcome, then the mutants
    themselves, so a changed fixture is flagged as loudly as a changed scorer.
    """
    # Lazy import: the CLI imports this module, and the built-in scorer lookup lives there.
    from traceeval.cli import SCORERS, load_task
    from traceeval.mutate import load_mutants

    available = SCORERS if scorers is None else scorers
    named = record.meta.get("scorers") or list(record.kill_rates)
    missing = [n for n in named if n not in available]
    if missing:
        return [f"scorer(s) named by the record no longer exist: {', '.join(missing)}"]
    scorers = {n: available[n] for n in named}

    task_name = record.meta.get("task", "")
    task_dir = _find_task_dir(Path(tasks_root), task_name, load_task)
    if task_dir is None:
        return [f"task {task_name!r} not found under {tasks_root}"]

    _, cases = load_task(task_dir)
    current = run_mutation(cases, load_mutants(task_dir), scorers, task_name=task_name)

    diffs: list[str] = []
    for name in named:
        committed, now = record.kill_rates.get(name), current.kill_rates.get(name)
        if (committed.to_dict() if committed else None) != (now.to_dict() if now else None):
            diffs.append(
                f"kill_rates[{name}]: committed {committed.to_dict() if committed else None} "
                f"vs current {now.to_dict() if now else None}"
            )
    if _behaviour(record.outcomes) != _behaviour(current.outcomes):
        diffs.append("outcomes differ from a fresh run")
    if [m.to_dict() for m in record.mutants] != [m.to_dict() for m in current.mutants]:
        diffs.append("mutant fixtures differ from those on disk")
    return diffs


def _behaviour(outcomes: list) -> list[tuple]:
    """The parts of an outcome that constitute behaviour — everything but the wording."""
    return [(o.mutant_id, o.mutant_cls, o.scorer, o.passed, o.applicable) for o in outcomes]


def _find_task_dir(tasks_root: Path, task_name: str, load_task) -> Path | None:
    """The first task directory whose declared name matches; non-task dirs are skipped."""
    for d in sorted(tasks_root.iterdir()):
        if not d.is_dir():
            continue
        try:
            name, _ = load_task(d)
        except FileNotFoundError:
            continue
        if name == task_name:
            return d
    return None
