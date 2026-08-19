"""Architecture-neutral execution contract.

An adapter is anything that can hold a conversation against the pinned
snapshot and return what a human would see plus what the sandbox observed.
Nothing here knows about intent extraction, candidate handling, state, or
any other detail of a specific implementation -- Track A (structured) and
Track B (frontier-simple) both speak this contract and nothing else.

Neutrality rules encoded in the shape of `Turn` (see docs/toesca-analyst-
benchmark-v1-design.md section 3):

  - `queries` and `gate_violations` are filled in by the runner from the
    SnapshotSandbox's own trace, never by the adapter. An adapter cannot
    self-report a query it didn't run, or hide one it did.
  - `asked_clarification` is left for the grader to infer from `text`.
    Track A has an internal `clarify` flag; using it here would give A an
    unfair advantage over a track that has no such flag.
  - `tool_calls` is optional. An adapter that doesn't instrument its own
    tool use returns an empty list; the runner then marks
    `tool_requirements` checks as `unscored`, not `fail`.

Stage A1 of the Alpha v0.1 extraction moved `Turn`/`ToolCall`/`Usage`/
`Artifact` to `tools.analyst_runtime.base` (reusable outside the benchmark
harness). This module re-imports `Turn` for the Protocols below, which stay
here because `Session`/`BenchmarkAdapter` encode eval-harness-only concepts
(`session_id`, "one adapter instance per benchmark run").
"""
from __future__ import annotations

from typing import Protocol

from tools.analyst_runtime.base import Artifact, Turn, ToolCall, Usage  # noqa: F401 -- re-exported for existing call sites

__all__ = ["Artifact", "Turn", "ToolCall", "Usage", "Session", "BenchmarkAdapter"]


class Session(Protocol):
    """One conversation. `ask` is called once per turn, in order."""

    def ask(self, message: str) -> Turn: ...


class BenchmarkAdapter(Protocol):
    """Factory for sessions. One adapter instance per benchmark run."""

    name: str

    def new_session(self, session_id: str) -> Session: ...
