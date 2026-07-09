"""Render a run into a markdown report: overall pass rate + a per-case table.

The report reads a ``RunRecord`` (scores for the pass rate, results for the model
output shown per row). It stays scorer-agnostic — the per-case ``Expected`` column is
pulled from ``Score.detail`` when a scorer provides it (the reference scorer does) and
left blank otherwise.
"""

from __future__ import annotations

from pathlib import Path

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


def _cell(value: object) -> str:
    """Make an arbitrary value safe for a one-line markdown table cell."""
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    if len(text) > _MAX_CELL:
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
        # A structural scorer records a 'reason'; an LLM judge records a 'rationale'. Show
        # whichever is present so both kinds of trace score explain themselves in this column.
        why = score.detail.get("reason") or score.detail.get("rationale", "")
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
