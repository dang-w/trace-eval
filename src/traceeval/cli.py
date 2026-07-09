"""Command-line entrypoint: wire load → run → score → store → report.

    trace-eval run tasks/sample --scorer reference

A task is a directory holding ``cases.json`` (a list of case objects) and an optional
``task.json`` (metadata: ``name``, ``description``). Tasks are JSON fixtures in v1 — no
config DSL. The ``--scorer`` name resolves through a small built-in dict below; that is a
lookup for the shipped scorers, deliberately not a plugin/registry system.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from traceeval.config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL
from traceeval.judge import DEFAULT_JUDGE_MAX_TOKENS, verification_sound_judge
from traceeval.metaeval import load_gold, run_meta_eval
from traceeval.runner import ModelCaller, call_anthropic, run_cases
from traceeval.report import write_meta_report, write_report
from traceeval.scorers import Scorer, reference_scorer, verify_before_assert
from traceeval.store import RunRecord, save_run
from traceeval.types import Case

# Built-in scorers by name. A lookup for what ships, not a registry — new scorers are
# added here (or passed in code), no plugin machinery.
SCORERS: dict[str, Scorer] = {
    "reference": reference_scorer,
    "verify_before_assert": verify_before_assert,
}

# The LLM judge is a scorer *factory* (it needs a model caller bound), so it can't sit in the
# plain SCORERS dict. This name routes to a judge built from the run's model_caller + model.
JUDGE_SCORER = "verification_sound"


def load_task(task_dir: str | Path) -> tuple[str, list[Case]]:
    """Load a task directory: required ``cases.json`` plus optional ``task.json``.

    Returns the task name (from ``task.json`` if present, else the directory name) and
    the parsed cases.
    """
    task_dir = Path(task_dir)
    cases_path = task_dir / "cases.json"
    if not cases_path.exists():
        raise FileNotFoundError(f"no cases.json in task dir: {task_dir}")

    cases = [Case.from_dict(c) for c in json.loads(cases_path.read_text(encoding="utf-8"))]

    name = task_dir.name
    task_meta_path = task_dir / "task.json"
    if task_meta_path.exists():
        name = json.loads(task_meta_path.read_text(encoding="utf-8")).get("name", name)

    return name, cases


def run_command(args: argparse.Namespace, *, model_caller: ModelCaller = call_anthropic) -> int:
    """Execute the ``run`` subcommand. Returns a process exit code."""
    if args.scorer == JUDGE_SCORER:
        # The judge grades each result by LLM, using the same model_caller as the run.
        scorer = verification_sound_judge(model_caller, model=args.model, max_tokens=args.max_tokens)
    else:
        try:
            scorer = SCORERS[args.scorer]
        except KeyError:
            available = ", ".join(sorted([*SCORERS, JUDGE_SCORER]))
            print(f"unknown scorer: {args.scorer!r} (available: {available})", file=sys.stderr)
            return 2

    try:
        task_name, cases = load_task(args.task_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results = run_cases(cases, model=args.model, max_tokens=args.max_tokens, model_caller=model_caller)
    scores = [scorer(case, result) for case, result in zip(cases, results)]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = RunRecord(
        results=results,
        scores=scores,
        meta={"task": task_name, "model": args.model, "scorer": args.scorer, "run_at": stamp},
    )

    out_dir = Path(args.out)
    results_path = save_run(record, out_dir / f"{task_name}-{stamp}.json")
    report_path = write_report(record, out_dir / "report.md")

    passed = sum(1 for s in scores if s.passed)
    total = len(scores)
    pct = (100.0 * passed / total) if total else 0.0
    errored = sum(1 for r in results if r.error)

    print(f"task '{task_name}' — {passed}/{total} passed ({pct:.0f}%)" + (f", {errored} errored" if errored else ""))
    print(f"  results: {results_path}")
    print(f"  report:  {report_path}")
    return 0


def meta_command(args: argparse.Namespace, *, model_caller: ModelCaller = call_anthropic) -> int:
    """Execute the ``meta`` subcommand: measure how much to trust the judge, then report it.

    Runs the ``verification_sound`` judge K times over a hand-labelled gold set, computes
    self-consistency and gold-agreement, persists the full record (every raw verdict retained)
    and writes a report that leads with the trust figures.
    """
    try:
        gold_items = load_gold(args.gold)
    except FileNotFoundError:
        print(f"no gold file at: {args.gold}", file=sys.stderr)
        return 2

    judge = verification_sound_judge(model_caller, model=args.model, max_tokens=args.judge_max_tokens)
    record = run_meta_eval(
        gold_items, judge, k=args.k,
        judge_meta={"judge_model": args.model, "judge_max_tokens": args.judge_max_tokens},
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out)
    meta_path = out_dir / f"meta-{stamp}.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = write_meta_report(record, out_dir / "meta_report.md")

    sc = record.self_consistency
    ga = record.gold_agreement
    # Report "not measured" rather than a measured 0% when there was nothing to judge — the
    # whole point of this build is honest trust figures, so the summary line holds that line too.
    consistency = (
        f"self-consistency {sc.mean_agreement:.0%} (flip rate {sc.flip_rate:.0%})"
        if sc.items else "self-consistency not measured (no judged items)"
    )
    agreement = (
        f"gold-agreement {ga.agreement:.0%} ({ga.n - len(ga.disagreements)}/{ga.n})"
        if ga.n else "gold-agreement not measured (no gold items)"
    )
    print(f"judge '{args.model}' over {len(gold_items)} gold items (K={args.k}) — {consistency}, {agreement}")
    print(f"  record: {meta_path}")
    print(f"  report: {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trace-eval", description="A minimal eval harness with real trace capture.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task and emit a report")
    run.add_argument("task_dir", help="path to a task directory (contains cases.json)")
    run.add_argument("--scorer", default="reference", help="scorer name (default: reference)")
    run.add_argument("--model", default=DEFAULT_MODEL, help=f"model string (default: {DEFAULT_MODEL})")
    run.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, dest="max_tokens",
                     help=f"max output tokens per call (default: {DEFAULT_MAX_TOKENS})")
    run.add_argument("--out", default="results", help="output directory for results JSON + report.md (default: results)")

    meta = sub.add_parser("meta", help="measure how much to trust the verification_sound judge")
    meta.add_argument("--gold", default="gold/verification_sound.json",
                      help="path to a hand-labelled gold file (default: gold/verification_sound.json)")
    meta.add_argument("--k", type=int, default=5, help="judge samples per item for self-consistency (default: 5)")
    meta.add_argument("--model", default=DEFAULT_MODEL, help=f"judge model string (default: {DEFAULT_MODEL})")
    meta.add_argument("--judge-max-tokens", type=int, default=DEFAULT_JUDGE_MAX_TOKENS, dest="judge_max_tokens",
                      help=f"max output tokens per judge call (default: {DEFAULT_JUDGE_MAX_TOKENS})")
    meta.add_argument("--out", default="results", help="output directory for meta JSON + meta_report.md (default: results)")
    return parser


def main(argv: list[str] | None = None, *, model_caller: ModelCaller = call_anthropic) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_command(args, model_caller=model_caller)
    if args.command == "meta":
        return meta_command(args, model_caller=model_caller)
    return 1  # pragma: no cover — argparse enforces a valid subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
