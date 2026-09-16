"""Render a run into a markdown report: overall pass rate + a per-case table.

The report reads a ``RunRecord`` (scores for the pass rate, results for the model
output shown per row). It stays scorer-agnostic — the per-case ``Expected`` column is
pulled from ``Score.detail`` when a scorer provides it (the reference scorer does) and
left blank otherwise.
"""

from __future__ import annotations

from pathlib import Path

from traceeval.mutate import CLASS_BASELINE, KillRate, MutationRecord, kill_rate_verdict
from traceeval.store import RunRecord
from traceeval.types import DIM_OUTPUT, DIM_TRACE, Result, ROLE_ANSWER, ROLE_VERIFY, Score

_MAX_CELL = 60


def answer_changed(result: Result) -> bool | None:
    """Whether the committed answer differs from the first answer-role step's output.

    A coarse, honest signal: it compares ``step[0]`` (the first ``answer``-role output)
    against the final ``result.output`` verbatim (whitespace-normalised only). It is *not*
    a semantic correction detector — the final output is the verify step's full text, so a
    confirming verify that restates its reasoning can read as "changed" even when the answer
    stands. Judging whether a change was a genuine right←wrong correction is the correction
    scorer, a later build. Returns ``None`` when nothing could have changed the answer: an
    errored run, or a single-step trace with no verification.
    """
    if result.error is not None:
        return None
    steps = result.trace.steps
    answer = next((s for s in steps if s.metadata.get("role") == ROLE_ANSWER), None)
    has_verify = any(s.metadata.get("role") == ROLE_VERIFY for s in steps)
    if answer is None or not has_verify:
        return None
    first = (answer.output if isinstance(answer.output, str) else str(answer.output)).strip()
    return first != (result.output or "").strip()


def _cell(value: object, *, truncate: bool = True) -> str:
    """Make an arbitrary value safe for a one-line markdown table cell.

    Long values are truncated by default; pass ``truncate=False`` for cells whose full content
    *is* the finding (a list of surviving mutant ids) and must never be elided.
    """
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    if truncate and len(text) > _MAX_CELL:
        text = text[: _MAX_CELL - 1] + "…"
    return text


def _output_section(scores: list[Score], results_by_id: dict[str, Result]) -> list[str]:
    """Output-dimension table: how the produced answer scored against the reference."""
    lines = [
        "## Output scores",
        "",
        "| Case | Pass | Score | Expected | Output |",
        "| --- | :---: | ---: | --- | --- |",
    ]
    for score in scores:
        result = results_by_id.get(score.case_id)
        # Show the error in the Output column when the run failed, else the output.
        output = result.error if (result and result.error) else (result.output if result else "")
        expected = score.detail.get("expected", "")
        lines.append(
            f"| {_cell(score.case_id)} "
            f"| {'✅' if score.passed else '❌'} "
            f"| {score.value:.2f} "
            f"| {_cell(expected)} "
            f"| {_cell(output)} |"
        )
    lines.append("")
    return lines


def _trace_section(scores: list[Score], results_by_id: dict[str, Result]) -> list[str]:
    """Trace-dimension table: whether the *process* held up, kept distinct from correctness.

    The ``Verified`` column is deliberately not headed "Pass" — this grades the trace (did a
    substantive verification happen), not whether the answer was right.
    """
    lines = [
        "## Trace-level scores (process)",
        "",
        "_Grades the process from the trace — did a substantive verification step revisit the "
        "answer — not whether the answer is correct._",
        "",
        "_The **Changed** column is a coarse textual signal (first answer vs committed output), "
        "not a semantic correction verdict._",
        "",
        "| Case | Verified | Score | Changed | Verification | Reason |",
        "| --- | :---: | ---: | :---: | --- | --- |",
    ]
    for score in scores:
        result = results_by_id.get(score.case_id)
        changed = answer_changed(result) if result else None
        changed_cell = "—" if changed is None else ("yes" if changed else "no")
        why = score.explanation
        lines.append(
            f"| {_cell(score.case_id)} "
            f"| {'✅' if score.passed else '❌'} "
            f"| {score.value:.2f} "
            f"| {changed_cell} "
            f"| {_cell(score.detail.get('verify_output', ''))} "
            f"| {_cell(why)} |"
        )
    lines.append("")
    return lines


def render_report(record: RunRecord) -> str:
    """Return the markdown report for a run.

    Output and trace scores render in separate, clearly-labelled sections so a process
    verdict is never read as a correctness verdict. A run uses one scorer, so in practice
    one section appears; grouping by dimension keeps that honest and future-proof.
    """
    scores = record.scores
    results_by_id = {r.case_id: r for r in record.results}

    total = len(scores)
    passed = sum(1 for s in scores if s.passed)
    pct = (100.0 * passed / total) if total else 0.0

    meta = record.meta
    scorer_name = meta.get("scorer") or (scores[0].scorer if scores else "—")

    lines = [
        f"# Eval Report — {meta.get('task', 'run')}",
        "",
        f"- **Model:** {meta.get('model', '—')}",
        f"- **Scorer:** {scorer_name}",
        f"- **Cases:** {total}",
        f"- **Pass rate:** {passed}/{total} ({pct:.0f}%)",
        "",
    ]

    output_scores = [s for s in scores if s.dimension == DIM_OUTPUT]
    trace_scores = [s for s in scores if s.dimension == DIM_TRACE]
    if output_scores:
        lines += _output_section(output_scores, results_by_id)
    if trace_scores:
        lines += _trace_section(trace_scores, results_by_id)

    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(record: RunRecord, path: str | Path) -> Path:
    """Render the report and write it to ``path`` (creating parent dirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(record), encoding="utf-8")
    return path


# --- Meta-eval report ------------------------------------------------------
# The whole point of #43: a report that leads with *how much to trust the judge* and only then
# shows what the judge said — so a reader can never read a judge verdict without first seeing
# the figures that bound how much it is worth. Trust above, verdicts below, never the reverse.


def render_meta_report(record: "MetaEvalRecord") -> str:
    """Return the markdown meta-eval report: judge-trust figures first, judge verdicts second."""
    jm = record.judge_meta
    sc = record.self_consistency
    ga = record.gold_agreement

    lines = [
        "# Meta-Eval — how much to trust the `verification_sound` judge",
        "",
        f"- **Judge model:** {jm.get('judge_model', '—')}",
        f"- **Samples per item (K):** {jm.get('k', '—')}",
        f"- **Judge max tokens:** {jm.get('judge_max_tokens', '—')}",
        "",
        "## How much to trust this judge",
        "",
        "_Read these first. They bound how much weight every judge verdict below can carry — a "
        "verdict from an unreliable judge is not evidence._",
        "",
    ]

    # Self-consistency — stability across identical calls.
    if sc is not None and sc.items:
        flipped = sum(1 for i in sc.items if i.flipped)
        lines += [
            f"- **Self-consistency:** mean agreement {sc.mean_agreement:.0%}, "
            f"flip rate {sc.flip_rate:.0%} ({flipped}/{len(sc.items)} items flipped across K identical calls). "
            "_Measures stability, not correctness._",
        ]
    else:
        lines.append("- **Self-consistency:** not measured (no judged items).")

    # Gold-agreement — correctness against human labels.
    if ga is not None and ga.n:
        agree_n = ga.n - len(ga.disagreements)
        lines.append(
            f"- **Gold-agreement:** {ga.agreement:.0%} ({agree_n}/{ga.n} hand-labelled items). "
            "_Measures correctness against human judgement._"
        )
    else:
        lines.append(
            "- **Gold-agreement:** not measured. "
            "_Self-consistency alone measures stability, not correctness._"
        )
    lines.append("")

    # Disagreements table (part of the trust story, so it stays above the verdicts).
    if ga is not None and ga.disagreements:
        lines += [
            "### Disagreements with human gold",
            "",
            "| Case | Judge | Human |",
            "| --- | :---: | :---: |",
        ]
        for d in ga.disagreements:
            lines.append(f"| {_cell(d.case_id)} | {_cell(d.judge)} | {_cell(d.human)} |")
        lines.append("")

    # --- Below the line: the judge's own verdicts, explicitly qualified by the trust above.
    lines += [
        "## Judge verdicts",
        "",
        "_Per-item majority verdict across the K samples — trust it only as far as the figures "
        "above allow. Every raw sample is retained in the JSON record, not just the majority._",
        "",
        "| Case | Majority | Agreement | Flipped | Sample verdicts |",
        "| --- | :---: | ---: | :---: | --- |",
    ]
    if sc is not None:
        for item in sc.items:
            lines.append(
                f"| {_cell(item.case_id)} "
                f"| {_cell(item.majority)} "
                f"| {item.agreement:.0%} "
                f"| {'flipped' if item.flipped else '—'} "
                f"| {_cell(', '.join(item.verdicts))} |"
            )
    lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_meta_report(record: "MetaEvalRecord", path: str | Path) -> Path:
    """Render the meta-eval report and write it to ``path`` (creating parent dirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_meta_report(record), encoding="utf-8")
    return path


# --- Mutation report --------------------------------------------------------
# Per scorer: mutants killed / mutants applicable, then every survivor named with the class it
# accepted. The language is diagnostic on purpose. A 100% kill rate over five hand-authored
# mutants says "not caught vacuous by these five," not "this scorer works."


def _synthetic_label(record: MutationRecord) -> str:
    """Read the synthetic flag off the mutants; never assert it as a constant."""
    not_synthetic = sum(1 for m in record.mutants if not m.synthetic)
    if not record.mutants:
        return "none"
    if not_synthetic == 0:
        return "all labelled synthetic (hand-authored fixtures; not live runs)"
    return f"{not_synthetic} NOT labelled synthetic — check each mutant's provenance below"


def render_mutation_report(record: MutationRecord) -> str:
    """Return the markdown mutation report: kill rates first, survivors diagnosed below."""
    meta = record.meta

    lines = [
        f"# Mutation Report — {meta.get('task', 'run')}",
        "",
        f"- **Mutants:** {len(record.mutants)} — {_synthetic_label(record)}",
        f"- **Scorers:** {', '.join(meta.get('scorers', record.kill_rates))}",
        "",
        "## Kill rates",
        "",
        "_Killed = the scorer failed a mutant it is responsible for (same dimension). A survivor "
        "is a broken run the scorer accepted. A kill rate is only meaningful when the scorer "
        "passes the unmodified baseline for every case with mutants — a scorer that fails a "
        "baseline fails everything, and a case with no baseline is unmeasured; both void the number._",
        "",
        "| Scorer | Baseline | Killed / applicable | Kill rate | Survivors |",
        "| --- | :---: | ---: | ---: | --- |",
    ]
    for name, kr in record.kill_rates.items():
        baseline = "missing" if kr.baseline_passed is None else ("pass" if kr.baseline_passed else "FAIL")
        lines.append(
            f"| {_cell(name)} "
            f"| {baseline} "
            f"| {kr.killed}/{kr.applicable} "
            f"| {kill_rate_verdict(kr)} "
            f"| {_cell(', '.join(kr.survivors) or '—', truncate=False)} |"
        )
    lines.append("")

    survivors = [o for o in record.outcomes if o.applicable and not o.killed]
    if survivors:
        lines += [
            "## Survivors",
            "",
            "_Each row is a scorer that accepted a broken run. The scorer's own stated reason for "
            "passing is shown beside the class of breakage it missed._",
            "",
            "| Scorer | Mutant | Diagnosis | Scorer's reason |",
            "| --- | --- | --- | --- |",
        ]
        for o in survivors:
            lines.append(
                f"| {_cell(o.scorer)} "
                f"| {_cell(o.mutant_id)} "
                f"| accepted a broken run of class {_cell(o.mutant_cls)} "
                f"| {_cell(o.reason)} |"
            )
        lines.append("")

    lines += [
        "## All outcomes",
        "",
        "_Every scorer × mutant pair, including out-of-dimension pairs that do not count toward "
        "any kill rate._",
        "",
        "| Mutant | Class | Scorer | Passed | Counts? | Outcome |",
        "| --- | --- | --- | :---: | :---: | --- |",
    ]
    for o in record.outcomes:
        if o.mutant_cls == CLASS_BASELINE:
            outcome = "control"
        elif not o.applicable:
            outcome = "out of dimension"
        else:
            outcome = "killed" if o.killed else "SURVIVED"
        lines.append(
            f"| {_cell(o.mutant_id)} "
            f"| {_cell(o.mutant_cls)} "
            f"| {_cell(o.scorer)} "
            f"| {'yes' if o.passed else 'no'} "
            f"| {'yes' if o.applicable else 'no'} "
            f"| {outcome} |"
        )
    lines.append("")

    lines += ["## Mutants", ""]
    for m in record.mutants:
        label = "synthetic" if m.synthetic else "NOT labelled synthetic"
        lines.append(f"- **{_cell(m.id)}** (`{m.cls}`, {label}): {m.note}")
        if m.provenance:
            lines.append(f"  - provenance: {m.provenance}")
    lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_mutation_report(record: MutationRecord, path: str | Path) -> Path:
    """Render the mutation report and write it to ``path`` (creating parent dirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_mutation_report(record), encoding="utf-8")
    return path
