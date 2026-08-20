"""Provider-neutral result shapes for one reasoning turn.

Moved from eval/benchmark/adapters/base.py (Stage A1 of the Alpha v0.1 build)
byte-for-byte for the four dataclasses (`ToolCall`, `Artifact`, `Usage`,
`Turn`). The `Session`/`BenchmarkAdapter` Protocols from the original module
are benchmark-only concepts (a benchmark run instantiates one adapter per
run and one session per conversation) and stay in
eval/benchmark/adapters/base.py, importing `Turn` from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    duration_ms: float | None = None
    trace: dict[str, Any] = field(default_factory=dict)


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
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
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
    raw: dict[str, Any] = field(default_factory=dict)
