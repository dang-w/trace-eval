"""trace-eval: a minimal eval harness with pluggable scorers, real trace capture, and a public findings ledger where the harness catches its own vacuous scorers."""

from traceeval.types import (
    Case,
    Result,
    Score,
    Trace,
    TraceStep,
    TokenUsage,
)

__all__ = [
    "Case",
    "Result",
    "Score",
    "Trace",
    "TraceStep",
    "TokenUsage",
]

__version__ = "0.1.0"
