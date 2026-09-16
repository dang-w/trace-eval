"""Persist a run to JSON and load it back.

A run is the results plus the scores plus a little metadata (task name, model, scorer,
timestamp). Everything serialises through the types' own ``to_dict`` / ``from_dict``, so
a saved run reloads without loss — including the full trace on every result, which is
what a later trace-level scorer will read back off disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from traceeval.types import Result, Score


@dataclass
class RunRecord:
    """One run's worth of results and scores, plus free-form metadata."""

    results: list[Result] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "results": [r.to_dict() for r in self.results],
            "scores": [s.to_dict() for s in self.scores],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunRecord:
        return cls(
            results=[Result.from_dict(r) for r in d.get("results", [])],
            scores=[Score.from_dict(s) for s in d.get("scores", [])],
            meta=d.get("meta", {}) or {},
        )


def utc_stamp() -> str:
    """The filename-safe UTC timestamp every persisted record is named with."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save_json(data: Any, path: str | Path) -> Path:
    """Write ``data`` to ``path`` as pretty, UTF-8 JSON, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_run(record: RunRecord, path: str | Path) -> Path:
    """Write a run to ``path`` as pretty JSON, creating parent dirs as needed."""
    return save_json(record.to_dict(), path)


def load_run(path: str | Path) -> RunRecord:
    """Load a run written by :func:`save_run`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RunRecord.from_dict(data)
