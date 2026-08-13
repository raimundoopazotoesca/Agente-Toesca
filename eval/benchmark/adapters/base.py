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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    duration_ms: float | None = None


@dataclass
class Artifact:
    kind: str  # table | chart | xlsx | file
    payload: Any = None
    path: str | None = None
    spec: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    provider: str | None = None
    model: str | None = None
    calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    retries: int = 0
    latency_ms: float | None = None


@dataclass
class Turn:
    text: str
    artifacts: list[Artifact] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    # Filled in by the runner from the sandbox trace, not by the adapter.
    queries: list[str] = field(default_factory=list)
    gate_violations: list[str] = field(default_factory=list)

    # Raw payload the adapter returned, kept for debugging/reporting only.
    # Graders must not read implementation-internal keys from it (see
    # module docstring) -- it exists so a human can inspect a failure.
    raw: dict[str, Any] = field(default_factory=dict)


class Session(Protocol):
    """One conversation. `ask` is called once per turn, in order."""

    def ask(self, message: str) -> Turn: ...


class BenchmarkAdapter(Protocol):
    """Factory for sessions. One adapter instance per benchmark run."""

    name: str

    def new_session(self, session_id: str) -> Session: ...
