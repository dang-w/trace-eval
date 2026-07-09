"""Render a run into a markdown report: overall pass rate + a per-case table.

The report reads a ``RunRecord`` (scores for the pass rate, results for the model
output shown per row). It stays scorer-agnostic — the per-case ``Expected`` column is
pulled from ``Score.detail`` when a scorer provides it (the reference scorer does) and
left blank otherwise.
"""

from __future__ import annotations

from pathlib import Path

from traceeval.store import RunRecord
from traceeval.types import DIM_OUTPUT, DIM_TRACE, Result, Score

_MAX_CELL = 60


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
        "| Case | Verified | Score | Verification | Reason |",
        "| --- | :---: | ---: | --- | --- |",
    ]
    for score in scores:
        lines.append(
            f"| {_cell(score.case_id)} "
            f"| {'✅' if score.passed else '❌'} "
            f"| {score.value:.2f} "
            f"| {_cell(score.detail.get('verify_output', ''))} "
            f"| {_cell(score.detail.get('reason', ''))} |"
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
