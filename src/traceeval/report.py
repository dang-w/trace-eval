"""Render a run into a markdown report: overall pass rate + a per-case table.

The report reads a ``RunRecord`` (scores for the pass rate, results for the model
output shown per row). It stays scorer-agnostic — the per-case ``Expected`` column is
pulled from ``Score.detail`` when a scorer provides it (the reference scorer does) and
left blank otherwise.
"""

from __future__ import annotations

from pathlib import Path

from traceeval.store import RunRecord

_MAX_CELL = 60


def _cell(value: object) -> str:
    """Make an arbitrary value safe for a one-line markdown table cell."""
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    if len(text) > _MAX_CELL:
        text = text[: _MAX_CELL - 1] + "…"
    return text


def render_report(record: RunRecord) -> str:
    """Return the markdown report for a run."""
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

    return "\n".join(lines) + "\n"


def write_report(record: RunRecord, path: str | Path) -> Path:
    """Render the report and write it to ``path`` (creating parent dirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(record), encoding="utf-8")
    return path
